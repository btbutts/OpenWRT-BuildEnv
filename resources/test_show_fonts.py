#!/usr/bin/env python3
"""Tests for rootfs-overlay/root/show-fonts.sh, the console font previewer.

The script is run for real with stub tty, openvt, setfont, showconsolefont,
stty and clear programs. Each stub appends a line to one log, so a test can
assert which programs ran, in which order and with which arguments. Keys are
fed on stdin, like the real script reads them.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parent
    / "buildrootConf"
    / "rootfs-overlay"
    / "root"
    / "show-fonts.sh"
)



def _find_modern_bash() -> str | None:
    """Return a bash >= 4 (the script uses mapfile, as does the target's bash 5)."""
    candidates = (
        os.environ.get("TEST_BASH", ""),
        "/opt/homebrew/bin/bash",
        "/usr/local/bin/bash",
        "/usr/bin/bash",
        "/bin/bash",
    )
    for candidate in candidates:
        if not candidate or not Path(candidate).exists():
            continue
        probe = subprocess.run(
            [candidate, "-c", "echo ${BASH_VERSINFO[0]}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if probe.stdout.strip().isdigit() and int(probe.stdout) >= 4:
            return candidate
    return None


BASH = _find_modern_bash()

TTY_STUB = """#!/bin/bash
[ -n "${STUB_TTY:-}" ] || { echo "not a tty"; exit 1; }
echo "$STUB_TTY"
"""

# Runs the command after "--" the way openvt does, but on a VT: the command
# sees the spare VT as its terminal.
OPENVT_STUB = """#!/bin/bash
echo "openvt $*" >> "$STUB_LOG"
while [ $# -gt 0 ] && [ "$1" != "--" ]; do
    shift
done
shift   # --
shift   # env
assigns=()
while [[ "$1" == *=* ]]; do
    assigns+=("$1")
    shift
done
script="$1"
shift
# The command a real openvt would start, run on the spare VT, with the bash the
# test selected (the shebang would pick /bin/bash, which may be 3.2 on macOS).
env "${assigns[@]}" STUB_TTY="$STUB_SPARE_VT" "$STUB_BASH" "$script" "$@"
"""

SETFONT_STUB = """#!/bin/bash
echo "setfont $*" >> "$STUB_LOG"
if [ "$1" = "-O" ]; then
    echo saved-font > "$2"
fi
exit 0
"""


def _logger(name: str) -> str:
    """Return a stub body that records its name and arguments."""
    return f'#!/bin/bash\necho "{name} $*" >> "$STUB_LOG"\nexit 0\n'


@unittest.skipIf(BASH is None, "needs bash >= 4 (set TEST_BASH); the target has bash 5")
class ShowFontsTests(unittest.TestCase):
    """show-fonts.sh on a text VT, inside kmscon, and in the error cases."""

    def setUp(self) -> None:
        """Build a font directory and the stub programs."""
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.bin = self.root / "bin"
        self.fonts = self.root / "fonts"
        self.log = self.root / "calls.log"
        (self.fonts / "partialfonts").mkdir(parents=True)
        self.bin.mkdir()
        self.log.write_text("", encoding="utf-8")
        # Stand-ins for /dev/ttyN: the script opens them with "< $TTY".
        self.dev = self.root / "dev"
        self.dev.mkdir()
        for number in (1, 2, 3):
            (self.dev / f"tty{number}").write_text("", encoding="utf-8")
        for name in ("a.psf.gz", "b.psf.gz"):
            (self.fonts / name).write_bytes(b"x")
        (self.fonts / "partialfonts" / "c.psf.gz").write_bytes(b"x")
        self._stub("tty", TTY_STUB)
        self._stub("openvt", OPENVT_STUB)
        self._stub("setfont", SETFONT_STUB)
        self._stub("showconsolefont", _logger("showconsolefont"))
        self._stub("stty", '#!/bin/bash\necho "25 80"\n')
        self._stub("clear", "#!/bin/bash\nexit 0\n")

    def _stub(self, name: str, body: str) -> None:
        """Install an executable stub program."""
        path = self.bin / name
        path.write_text(body, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def launch(
        self,
        keys: str,
        *args: str,
        tty: str | None = None,
        extra_env: dict[str, str] | None = None,
        fonts: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run the script with ``keys`` on stdin and the stubs first on PATH."""
        env = {
            "PATH": f"{self.bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "STUB_LOG": str(self.log),
            "FONT_DIR": str(fonts or self.fonts),
            "TMPDIR": str(self.root),
            "SHOW_FONTS_DEV_DIR": str(self.dev),
            "STUB_SPARE_VT": str(self.dev / "tty2"),
            "STUB_BASH": BASH or "bash",
        }
        if tty is not None:
            env["STUB_TTY"] = tty
        env.update(extra_env or {})
        return subprocess.run(
            [BASH or "bash", str(SCRIPT), *args],
            input=keys,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def vt(self, number: int) -> str:
        """Return the path of the fake /dev/tty<number>."""
        return str(self.dev / f"tty{number}")

    def calls(self) -> list[str]:
        """Return the stub log, one entry per program that ran."""
        return self.log.read_text(encoding="utf-8").splitlines()

    def programs(self) -> list[str]:
        """Return only the program names from the stub log, in order."""
        return [line.split()[0] for line in self.calls()]

    def loaded_fonts(self) -> list[str]:
        """Return the font files setfont was asked to load, in order."""
        loaded = []
        for line in self.calls():
            if not line.startswith("setfont "):
                continue
            for word in line.split()[1:]:
                if word.startswith(str(self.fonts)):
                    loaded.append(Path(word).name)
        return loaded

    # ---- on a text VT: unchanged behaviour ---------------------------------

    def test_text_vt_runs_in_place(self) -> None:
        """A getty login on a VT needs no spare console."""
        result = self.launch("q", tty=self.vt(1))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("openvt", self.programs())
        self.assertEqual(self.loaded_fonts(), ["a.psf.gz"])
        self.assertIn("showconsolefont", self.programs())

    def test_font_in_use_is_saved_and_restored(self) -> None:
        """The font that was loaded is put back when the script ends."""
        result = self.launch("q", tty=self.vt(1))
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertTrue(calls[0].startswith("setfont -O "), calls[0])
        self.assertIn("orig.psf", calls[-1])
        self.assertNotIn("-O", calls[-1].split())

    def test_other_vt_is_used_as_it_is(self) -> None:
        """Run from tty3 it previews on tty3: no hop, no spare VT."""
        result = self.launch("q", tty=self.vt(3))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("openvt", self.programs())

    def test_next_and_previous_wrap(self) -> None:
        """f goes forward, b goes back, both wrap around."""
        result = self.launch("fbq", tty=self.vt(1))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.loaded_fonts(), ["a.psf.gz", "b.psf.gz", "a.psf.gz"])
        self.launch("bq", tty=self.vt(1))
        self.assertEqual(self.loaded_fonts()[-1], "b.psf.gz")

    def test_partial_fonts_only_with_the_flag(self) -> None:
        """partialfonts/ is skipped unless --partial is given."""
        self.launch("fq", tty=self.vt(1))
        self.assertNotIn("c.psf.gz", self.loaded_fonts())
        self.log.write_text("", encoding="utf-8")
        self.launch("ffq", "--partial", tty=self.vt(1))
        self.assertIn("c.psf.gz", self.loaded_fonts())

    # ---- not a text VT: kmscon, ssh, serial --------------------------------

    def test_kmscon_pty_hops_to_a_spare_vt(self) -> None:
        """Inside kmscon (a pty) the preview runs on a VT opened with openvt."""
        result = self.launch("q", tty="/dev/pts/3", extra_env={"TERM": "kmscon"})
        self.assertEqual(result.returncode, 0, result.stderr)
        first = self.calls()[0]
        self.assertTrue(first.startswith("openvt -s -w -- "), first)
        self.assertIn("TERM=linux", first)
        self.assertIn("SHOW_FONTS_ON_VT=1", first)
        # The command openvt started then did the real work.
        self.assertEqual(self.loaded_fonts(), ["a.psf.gz"])
        self.assertIn("showconsolefont", self.programs())
        self.assertIn("switches back here", result.stdout)

    def test_hop_does_not_loop(self) -> None:
        """The re-run on the spare VT must not try to hop again."""
        self.launch("q", tty="/dev/pts/3")
        self.assertEqual(self.programs().count("openvt"), 1)

    def test_serial_line_hops_too(self) -> None:
        """A serial or ssh terminal cannot change the console font either."""
        self.launch("q", tty="/dev/ttyS0")
        self.assertEqual(self.programs().count("openvt"), 1)

    def test_explicit_tty_is_never_hopped(self) -> None:
        """TTY=/dev/ttyN is honoured exactly, whatever stdin is."""
        result = self.launch("q", tty="/dev/pts/3", extra_env={"TTY": self.vt(2)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("openvt", self.programs())
        self.assertEqual(self.loaded_fonts(), ["a.psf.gz"])

    def test_missing_openvt_is_a_clear_error(self) -> None:
        """No openvt and no text VT: say what to do, change nothing."""
        (self.bin / "openvt").unlink()
        # A PATH with the stubs and only the few real tools the script needs, so
        # a real openvt installed on this machine cannot be found.
        tools = self.root / "tools"
        tools.mkdir()
        for tool in ("find", "sort", "mktemp", "rm", "dirname", "basename", "cat", "env"):
            found = subprocess.run(
                ["/usr/bin/which", tool], capture_output=True, text=True, check=False
            ).stdout.strip()
            if found:
                (tools / tool).symlink_to(found)
        result = self.launch(
            "q",
            tty="/dev/pts/3",
            extra_env={"PATH": f"{self.bin}:{tools}"},
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("not a text console", result.stderr)
        self.assertNotIn("setfont", self.programs())

    # ---- errors that must happen before anything changes -------------------

    def test_no_fonts_is_reported_before_any_hop(self) -> None:
        """An empty font directory fails in the user's own terminal."""
        empty = self.root / "empty"
        empty.mkdir()
        result = self.launch("q", tty="/dev/pts/3", fonts=empty)
        self.assertEqual(result.returncode, 1)
        self.assertIn("No fonts found", result.stderr)
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
