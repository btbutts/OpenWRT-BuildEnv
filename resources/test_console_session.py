#!/usr/bin/env python3
"""Tests for usr/lib/installer/console-session.sh, the kmscon/getty launcher.

The script is run for real, against a fake /sys tree and stub kmscon, agetty,
login, wizard and udevadm programs. Each stub appends a line to one log, so a
test can assert exactly which programs ran, in which order and with which
arguments.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parent
    / "buildrootConf"
    / "rootfs-overlay"
    / "usr"
    / "lib"
    / "installer"
    / "console-session.sh"
)

KMSCON_STUB = """#!/bin/bash
echo "kmscon $*" >> "$STUB_LOG"
mode="${STUB_KMSCON:-child}"
case "$mode" in
    fail) exit 1 ;;
    hang) exec sleep 60 ;;
    libseat-fails)
        for a in "$@"; do
            [ "$a" = "--libseat" ] && exit 1
        done
        ;;
esac
i=0
for a in "$@"; do
    i=$((i + 1))
    [ "$a" = "--" ] && break
done
shift "$i"
"$@"
[ "$mode" = crash ] && exit 139
exit 0
"""


def _logger(name: str) -> str:
    """Return a stub body that records its name and arguments."""
    return f'#!/bin/bash\necho "{name} $*" >> "$STUB_LOG"\nexit 0\n'


LOGIND_SESSION = {"XDG_SESSION_ID": "7", "XDG_SEAT": "seat0", "XDG_VTNR": "1"}

UDEVADM_STUB = """#!/bin/bash
echo "udevadm $*" >> "$STUB_LOG"
[ -n "${STUB_UDEVADM_HOOK:-}" ] && eval "$STUB_UDEVADM_HOOK"
exit 0
"""


class ConsoleSessionTests(unittest.TestCase):
    """Behaviour of console-session.sh for the wizard and shell roles."""

    def setUp(self) -> None:
        """Build a fake /sys, /run, command line and set of stub programs."""
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.sysfs = self.root / "sys"
        self.run_dir = self.root / "run"
        self.bin = self.root / "bin"
        self.log = self.root / "calls.log"
        self.cmdline = self.root / "cmdline"
        for path in (self.sysfs / "class" / "drm", self.run_dir, self.bin):
            path.mkdir(parents=True)
        self.cmdline.write_text("console=tty1 fbcon=deferred\n", encoding="utf-8")
        self.log.write_text("", encoding="utf-8")
        self._stub("kmscon", KMSCON_STUB)
        self._stub("agetty", _logger("agetty"))
        self._stub("login", _logger("login"))
        self._stub("wizard", _logger("wizard"))
        self._stub("udevadm", UDEVADM_STUB)

    def _stub(self, name: str, body: str) -> None:
        """Install an executable stub program."""
        path = self.bin / name
        path.write_text(body, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def add_card(self, name: str, driver: str, connectors: dict[str, str]) -> None:
        """Create /sys/class/drm/<name> driven by <driver> with its connectors."""
        device = self.sysfs / "class" / "drm" / name / "device"
        device.mkdir(parents=True)
        (device / "uevent").write_text(f"DRIVER={driver}\nPCI_SLOT_NAME=0000:00:01.0\n")
        for connector, status in connectors.items():
            conn = self.sysfs / "class" / "drm" / f"{name}-{connector}"
            conn.mkdir(parents=True)
            (conn / "status").write_text(f"{status}\n", encoding="utf-8")

    def clear_cards(self) -> None:
        """Remove every fake DRM card and connector."""
        drm = self.sysfs / "class" / "drm"
        shutil.rmtree(drm)
        drm.mkdir(parents=True)

    def set_cmdline(self, text: str) -> None:
        """Replace the kernel command line."""
        self.cmdline.write_text(text + "\n", encoding="utf-8")

    def launch(
        self, *args: str, extra_env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        """Run the script with every external path pointed at the fake tree."""
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "STUB_LOG": str(self.log),
            "INSTALLER_SYSFS": str(self.sysfs),
            "INSTALLER_CMDLINE_FILE": str(self.cmdline),
            "INSTALLER_RUN_DIR": str(self.run_dir),
            "INSTALLER_KMSCON": str(self.bin / "kmscon"),
            "INSTALLER_AGETTY": str(self.bin / "agetty"),
            "INSTALLER_LOGIN": str(self.bin / "login"),
            "INSTALLER_WIZARD": str(self.bin / "wizard"),
            "INSTALLER_UDEVADM": str(self.bin / "udevadm"),
            "INSTALLER_CONSOLE_WAIT": "1",
            "INSTALLER_CONSOLE_EXTRA_WAIT": "1",
            "INSTALLER_CONSOLE_POLL": "0.05",
            "INSTALLER_KMSCON_LIBSEAT_TIMEOUT": "2",
            "INSTALLER_KMSCON_START_TIMEOUT": "2",
            "INSTALLER_KMSCON_STOP_GRACE": "1",
        }
        env.update(extra_env or {})
        return subprocess.run(
            ["/bin/bash", str(SCRIPT), *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def calls(self) -> list[str]:
        """Return the stub log, one entry per program that ran."""
        return self.log.read_text(encoding="utf-8").splitlines()

    def programs(self) -> list[str]:
        """Return only the program names from the stub log, in order."""
        return [line.split()[0] for line in self.calls()]

    def kmscon_lines(self) -> list[str]:
        """Return the argument lines of every kmscon start."""
        return [line for line in self.calls() if line.startswith("kmscon ")]

    # ---- kmscon is used ---------------------------------------------------

    def test_connected_display_runs_the_wizard_in_kmscon(self) -> None:
        """A real driver with a connected output hosts the wizard in kmscon."""
        self.add_card("card0", "amdgpu", {"HDMI-A-1": "connected"})
        result = self.launch("wizard")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.programs(), ["kmscon", "wizard"])
        args = self.kmscon_lines()[0]
        for token in ("--vt=tty1", "--oneshot", "--no-reset-env", "-l", "--child wizard"):
            self.assertIn(token, args)
        self.assertNotIn("--libseat", args)

    def test_shell_logs_in_root_inside_kmscon(self) -> None:
        """The shell role runs the same autologin as agetty did, inside kmscon."""
        self.add_card("card0", "i915", {"eDP-1": "connected"})
        result = self.launch("shell")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.programs(), ["kmscon", "login"])
        self.assertIn("login -f root", self.calls())

    def test_every_real_display_driver_is_accepted(self) -> None:
        """Not only amdgpu: any non-firmware DRM driver with an output counts."""
        drivers = ("amdgpu", "i915", "xe", "nouveau", "radeon", "virtio_gpu", "vmwgfx", "ast")
        for driver in drivers:
            with self.subTest(driver=driver):
                self.log.write_text("", encoding="utf-8")
                self.clear_cards()
                self.add_card("card0", driver, {"Virtual-1": "connected"})
                result = self.launch("wizard")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.programs(), ["kmscon", "wizard"])

    def test_second_card_with_output_is_enough(self) -> None:
        """simpledrm may be card0 and the real GPU card1: card1 decides."""
        self.add_card("card0", "simple-framebuffer", {"Unknown-1": "connected"})
        self.add_card("card1", "amdgpu", {"DP-1": "connected"})
        result = self.launch("wizard")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.programs(), ["kmscon", "wizard"])

    def test_display_that_appears_while_udev_settles(self) -> None:
        """The wizard waits for the driver udev is still loading."""
        hook = (
            f'd="{self.sysfs}/class/drm"; '
            'mkdir -p "$d/card0/device" "$d/card0-DP-1"; '
            'echo DRIVER=amdgpu > "$d/card0/device/uevent"; '
            'echo connected > "$d/card0-DP-1/status"'
        )
        result = self.launch("wizard", extra_env={"STUB_UDEVADM_HOOK": hook})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.programs(), ["udevadm", "kmscon", "wizard"])

    # ---- getty is used ----------------------------------------------------

    def test_firmware_framebuffer_alone_uses_getty(self) -> None:
        """simpledrm and the other firmware drivers are not a real display driver."""
        for driver in ("simple-framebuffer", "efi-framebuffer", "vesa-framebuffer", "of-display"):
            with self.subTest(driver=driver):
                self.log.write_text("", encoding="utf-8")
                self.add_card("card0", driver, {"Unknown-1": "connected"})
                result = self.launch("wizard")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.programs(), ["udevadm", "wizard"])
                self.clear_cards()

    def test_gpu_without_a_connected_output_uses_getty(self) -> None:
        """A GPU with nothing plugged in is not a display."""
        self.add_card("card0", "amdgpu", {"HDMI-A-1": "disconnected", "DP-1": "disconnected"})
        result = self.launch("shell")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.programs(), ["udevadm", "agetty"])
        self.assertIn(
            "agetty --autologin root --noclear --keep-baud - 115200,38400,9600",
            " ".join(self.calls()),
        )

    def test_getty_shell_serves_the_vt_it_was_started_on(self) -> None:
        """On a VT console agetty keeps the "-" port: the unit's own tty1."""
        result = self.launch("shell")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("agetty --autologin root --noclear --keep-baud - 115200", self.calls()[-1])

    def test_getty_shell_names_a_serial_console(self) -> None:
        """The unit is pinned to tty1, so a serial console= is passed explicitly."""
        self.set_cmdline("console=tty1 console=ttyS0,115200n8")
        result = self.launch("shell")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "agetty --autologin root --noclear --keep-baud ttyS0 115200,38400,9600",
            self.calls()[-1],
        )

    def test_no_drm_device_uses_getty(self) -> None:
        """No GPU at all (headless, nomodeset): getty."""
        result = self.launch("wizard")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.programs(), ["udevadm", "wizard"])

    def test_serial_console_uses_getty(self) -> None:
        """When the operator is on a serial line, kmscon on the display is wrong."""
        self.add_card("card0", "amdgpu", {"HDMI-A-1": "connected"})
        self.set_cmdline("console=tty1 console=ttyS0,115200n8")
        result = self.launch("shell")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.programs(), ["agetty"])

    def test_cmdline_switch_forces_getty(self) -> None:
        """installer.console=getty overrides a working display."""
        self.add_card("card0", "amdgpu", {"HDMI-A-1": "connected"})
        self.set_cmdline("console=tty1 installer.console=getty")
        result = self.launch("wizard")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.programs(), ["wizard"])

    def test_missing_kmscon_uses_getty(self) -> None:
        """An image without kmscon behaves exactly as before."""
        self.add_card("card0", "amdgpu", {"HDMI-A-1": "connected"})
        (self.bin / "kmscon").unlink()
        result = self.launch("wizard")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.programs(), ["wizard"])

    def test_gpu_blacklist_does_not_make_the_console_wait(self) -> None:
        """modprobe.blacklist=amdgpu,i915 (the GRUB option) must not add a delay."""
        self.set_cmdline("console=tty1 modprobe.blacklist=amdgpu,i915")
        started = time.monotonic()
        result = self.launch("wizard", extra_env={"INSTALLER_CONSOLE_EXTRA_WAIT": "20"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(self.programs(), ["udevadm", "wizard"])

    def test_missing_display_waits_a_bounded_time(self) -> None:
        """Without any hint the driver may still come: wait, then give up."""
        started = time.monotonic()
        result = self.launch("wizard", extra_env={"INSTALLER_CONSOLE_EXTRA_WAIT": "2"})
        elapsed = time.monotonic() - started
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreaterEqual(elapsed, 0.9)
        self.assertLess(elapsed, 10)
        self.assertEqual(self.programs(), ["udevadm", "wizard"])

    # ---- kmscon fails -----------------------------------------------------

    def test_kmscon_that_never_starts_the_child_falls_back_at_once(self) -> None:
        """No session started: getty runs in the same invocation, and is remembered."""
        self.add_card("card0", "amdgpu", {"HDMI-A-1": "connected"})
        result = self.launch("wizard", extra_env={"STUB_KMSCON": "fail"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.programs(), ["kmscon", "wizard"])
        self.assertTrue((self.run_dir / "installer-kmscon.failed").exists())
        # A later start (the shell, the loop) goes straight to getty.
        self.log.write_text("", encoding="utf-8")
        result = self.launch("shell", extra_env={"STUB_KMSCON": "fail"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.programs(), ["agetty"])

    def test_hung_kmscon_is_stopped_and_getty_runs(self) -> None:
        """A kmscon that sits on a black screen is killed and replaced by getty."""
        self.add_card("card0", "amdgpu", {"HDMI-A-1": "connected"})
        started = time.monotonic()
        result = self.launch(
            "wizard",
            extra_env={
                "STUB_KMSCON": "hang",
                "INSTALLER_KMSCON_START_TIMEOUT": "1",
                "INSTALLER_KMSCON_STOP_GRACE": "1",
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual(self.programs(), ["kmscon", "wizard"])
        self.assertTrue((self.run_dir / "installer-kmscon.failed").exists())

    def test_kmscon_crash_during_the_wizard_does_not_rerun_the_wizard(self) -> None:
        """The wizard may be mid-install: never start a second one from here."""
        self.add_card("card0", "amdgpu", {"HDMI-A-1": "connected"})
        result = self.launch("wizard", extra_env={"STUB_KMSCON": "crash"})
        self.assertEqual(result.returncode, 139, result.stderr)
        self.assertEqual(self.programs(), ["kmscon", "wizard"])
        self.assertEqual(self.programs().count("wizard"), 1)
        self.assertTrue((self.run_dir / "installer-kmscon.failed").exists())

    def test_kmscon_crash_during_the_shell_gives_a_getty_shell(self) -> None:
        """The shell is replaced by an agetty shell right away."""
        self.add_card("card0", "amdgpu", {"HDMI-A-1": "connected"})
        result = self.launch("shell", extra_env={"STUB_KMSCON": "crash"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.programs(), ["kmscon", "login", "agetty"])

    # ---- libseat ----------------------------------------------------------

    def test_libseat_is_used_inside_a_logind_session(self) -> None:
        """A session bound to seat0 and a VT is what --libseat needs."""
        self.add_card("card0", "amdgpu", {"HDMI-A-1": "connected"})
        result = self.launch("wizard", extra_env=LOGIND_SESSION)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.programs(), ["kmscon", "wizard"])
        self.assertIn("--libseat", self.kmscon_lines()[0])

    def test_libseat_needs_seat_and_vt(self) -> None:
        """A session that is not on a seat/VT does not get --libseat."""
        self.add_card("card0", "amdgpu", {"HDMI-A-1": "connected"})
        partial = {"XDG_SESSION_ID": "7"}
        result = self.launch("wizard", extra_env=partial)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("--libseat", self.kmscon_lines()[0])

    def test_libseat_failure_retries_on_the_vt_and_is_remembered(self) -> None:
        """libseat refusing must not cost the user kmscon: retry without it."""
        self.add_card("card0", "amdgpu", {"HDMI-A-1": "connected"})
        env = {**LOGIND_SESSION, "STUB_KMSCON": "libseat-fails"}
        result = self.launch("wizard", extra_env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.programs(), ["kmscon", "kmscon", "wizard"])
        first, second = self.kmscon_lines()
        self.assertIn("--libseat", first)
        self.assertNotIn("--libseat", second)
        self.assertTrue((self.run_dir / "installer-kmscon-libseat.failed").exists())
        # kmscon itself is fine, so it is not marked failed for the boot.
        self.assertFalse((self.run_dir / "installer-kmscon.failed").exists())
        # The next start does not try libseat again.
        self.log.write_text("", encoding="utf-8")
        result = self.launch("shell", extra_env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.kmscon_lines()), 1)
        self.assertNotIn("--libseat", self.kmscon_lines()[0])

    def test_cmdline_can_turn_libseat_off(self) -> None:
        """installer.console.libseat=0 skips way 1."""
        self.add_card("card0", "amdgpu", {"HDMI-A-1": "connected"})
        self.set_cmdline("console=tty1 installer.console.libseat=0")
        result = self.launch("wizard", extra_env=LOGIND_SESSION)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("--libseat", self.kmscon_lines()[0])

    # ---- the pieces systemd and kmscon call --------------------------------

    def test_child_role_marks_the_session_and_runs_the_program(self) -> None:
        """--child is what kmscon execs: stamp first, then the real program."""
        result = self.launch("--child", "shell")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.run_dir / "installer-kmscon-session.started").exists())
        self.assertEqual(self.calls(), ["login -f root"])

    def test_unknown_role_is_a_usage_error(self) -> None:
        """Neither wizard nor shell: exit 2, nothing runs."""
        result = self.launch("bogus")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
