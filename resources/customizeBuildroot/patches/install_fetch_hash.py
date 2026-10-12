"""Install package/fetch-hash.mk plus fetch_hash_helper.py, and include the mk."""

from __future__ import annotations

import inspect
from pathlib import Path

FETCH_HASH_MK_NAME = "fetch-hash.mk"
FETCH_HASH_HELPER_NAME = "fetch_hash_helper.py"
FETCH_HASH_INCLUDE_MARKER = f"include package/{FETCH_HASH_MK_NAME}"
FETCH_HASH_INCLUDE_BLOCK = "\n" + inspect.cleandoc(f"""
    # JIT-append sha256 lines for package tarballs missing from .hash files.
    {FETCH_HASH_INCLUDE_MARKER}
""") + "\n"


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

    makefile = br_path / "Makefile"
    text = makefile.read_text(encoding="utf-8")
    if FETCH_HASH_INCLUDE_MARKER in text:
        print(f"--> The \"{FETCH_HASH_INCLUDE_MARKER}\" is already present in {makefile}")
        return
    makefile.write_text(
        text.rstrip("\n") + "\n" + FETCH_HASH_INCLUDE_BLOCK, encoding="utf-8"
    )
    print(f"--> Appended {FETCH_HASH_INCLUDE_MARKER} to {makefile}")
