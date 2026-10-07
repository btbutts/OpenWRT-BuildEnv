"""Install package/fetch-hash.mk plus fetch_hash_helper.py, and include the mk."""

from __future__ import annotations

from pathlib import Path

FETCH_HASH_MK_NAME = "fetch-hash.mk"
FETCH_HASH_HELPER_NAME = "fetch_hash_helper.py"
FETCH_HASH_INCLUDE_MARKER = f"include package/{FETCH_HASH_MK_NAME}"
FETCH_HASH_INCLUDE_BLOCK = (
    "\n# JIT-append sha256 lines for package tarballs missing from .hash files.\n"
    f"{FETCH_HASH_INCLUDE_MARKER}\n"
)
LEGACY_LINUX_GET_HASH_INCLUDE = "include linux/from-6.17/get-hash.mk"
LEGACY_LINUX_GET_HASH_COMMENT = (
    "# JIT-append kernel.org sha256 lines for linux/linux-headers tarballs."
)


def _drop_legacy_linux_get_hash_include(text: str) -> str:
    """Remove a leftover linux/from-6.17/get-hash.mk include from the Makefile."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    skip_blank_after = False
    for line in lines:
        stripped = line.strip()
        if stripped == LEGACY_LINUX_GET_HASH_INCLUDE:
            skip_blank_after = True
            continue
        if stripped == LEGACY_LINUX_GET_HASH_COMMENT:
            continue
        if skip_blank_after and stripped == "":
            skip_blank_after = False
            continue
        skip_blank_after = False
        out.append(line)
    return "".join(out)


def write_fetch_hash_mk(br_path: Path) -> None:
    """
    Install ``package/fetch-hash.mk`` and ``package/fetch_hash_helper.py``.

    The makefile include is appended once, after all ``package/*/*.mk``
    files and ``BR2_EXTERNAL`` trees have been read, so ``$(PACKAGES_ALL)``
    is complete when ``FETCH_HASH`` is registered on every package. The
    helper is executed by the makefile; it is not imported here.
    """
    dest_dir = br_path / "package"
    if not dest_dir.is_dir():
        raise SystemExit(
            f"Error: {dest_dir} is missing; cannot install {FETCH_HASH_MK_NAME}"
        )
    for name in (FETCH_HASH_MK_NAME, FETCH_HASH_HELPER_NAME):
        src = Path(__file__).with_name(name)
        if not src.is_file():
            raise SystemExit(f"Error: {src} is missing from customizeBuildroot")
        dest = dest_dir / name
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"--> Wrote {dest}")

    leftover = br_path / "linux" / "from-6.17" / "get-hash.mk"
    if leftover.is_file() or leftover.is_symlink():
        leftover.unlink()
        print(f"--> Removed leftover {leftover}")

    makefile = br_path / "Makefile"
    text = makefile.read_text(encoding="utf-8")
    stripped = _drop_legacy_linux_get_hash_include(text)
    if FETCH_HASH_INCLUDE_MARKER not in stripped:
        stripped = stripped.rstrip("\n") + "\n" + FETCH_HASH_INCLUDE_BLOCK
        print(f"--> Appended {FETCH_HASH_INCLUDE_MARKER} to {makefile}")
    elif stripped == text:
        print(f"--> {FETCH_HASH_INCLUDE_MARKER} already present in {makefile}")
    else:
        print(f"--> Dropped leftover {LEGACY_LINUX_GET_HASH_INCLUDE} from {makefile}")
    if stripped != text:
        makefile.write_text(stripped, encoding="utf-8")
