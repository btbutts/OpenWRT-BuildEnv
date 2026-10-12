"""Shared helpers for Buildroot Kconfig and makefile patches."""

from __future__ import annotations

from pathlib import Path

_MESON_PACKAGE_EVAL = "$(eval $(meson-package))\n"


def tabbed(block: str) -> str:
    """
    Turn an ``inspect.cleandoc`` block into text for a tab-indented file.

    Write the block with four spaces per indent level and every run of four
    spaces becomes a real tab, so Kconfig and Makefile fragments need no
    ``\\t`` escapes. ``cleandoc`` drops the trailing newline; it is restored.
    """
    return block.replace("    ", "\t") + "\n"


def kconfig_package_symbol(package_name: str) -> str:
    """
    Return the ``BR2_PACKAGE_*`` symbol for a package directory name.

    Hyphens become underscores and the rest is uppercased, matching
    Buildroot (``gcc-standalone-toolchain`` →
    ``BR2_PACKAGE_GCC_STANDALONE_TOOLCHAIN``).
    """
    return "BR2_PACKAGE_" + package_name.replace("-", "_").upper()


def write_if_changed(path: Path, original: str, updated: str, message: str) -> None:
    """Write *updated* when it differs; otherwise say the hunk is present."""
    if updated == original:
        print(f"--> {message} already present in {path}")
        return
    path.write_text(updated)
    print(f"--> {message} in {path}")


def insert_kconfig_after_if(text: str, if_line: str, symbol: str, block: str) -> str:
    """
    Insert *block* immediately after ``if <pkg>`` when *symbol* is absent.

    Raises SystemExit if *if_line* is missing.
    """
    if f"config {symbol}\n" in text:
        return text
    needle = f"{if_line}\n"
    idx = text.find(needle)
    if idx < 0:
        raise SystemExit(f"Error: {if_line!r} not found")
    at = idx + len(needle)
    return text[:at] + "\n" + block + "\n" + text[at:]


def append_kconfig_if_block(text: str, if_symbol: str, symbol: str, block: str) -> str:
    """Append *block* inside a new ``if <if_symbol>`` when *symbol* is absent."""
    if f"config {symbol}\n" in text:
        return text
    return text.rstrip("\n") + f"\n\nif {if_symbol}\n\n{block}\nendif\n"


def insert_before_meson_eval(text: str, tail: str, already: str) -> str:
    """Insert *tail* before the first meson-package eval unless *already* is present."""
    if already in text:
        return text
    idx = text.find(_MESON_PACKAGE_EVAL)
    if idx < 0:
        raise SystemExit("Error: $(eval $(meson-package)) not found")
    return text[:idx] + tail + "\n" + text[idx:]


def drop_br_no_check_hash_for(text: str, token: str) -> str:
    """Remove ``BR_NO_CHECK_HASH_FOR`` lines that mention *token*."""
    return "".join(
        line
        for line in text.splitlines(keepends=True)
        if not (
            line.lstrip().startswith("BR_NO_CHECK_HASH_FOR") and token in line
        )
    )
