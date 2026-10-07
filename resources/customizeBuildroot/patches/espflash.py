"""Stock espflash: bail! warning patch and optional version override."""

from __future__ import annotations

import re
from pathlib import Path

from ..util import append_kconfig_if_block, write_if_changed

# The version Buildroot 2026.08 packages. It is the Kconfig default of
# BR2_PACKAGE_ESPFLASH_VERSION_OVERRIDE and the only version the bail!
# patch is written for.
ESPFLASH_STOCK_VERSION = "4.0.1"

ESPFLASH_VERSION_OVERRIDE_KCONFIG = (
    "config BR2_PACKAGE_ESPFLASH_VERSION_OVERRIDE\n"
    '\tstring "espflash version override"\n'
    f'\tdefault "{ESPFLASH_STOCK_VERSION}"\n'
    "\thelp\n"
    f"\t  Buildroot's packaged espflash is {ESPFLASH_STOCK_VERSION} (2026.08).\n"
    '\t  Set to a release tag without the leading "v", for example\n'
    "\t  4.1.0, to download that version instead. Missing tarball\n"
    "\t  sha256 lines are filled by package/fetch-hash.mk.\n"
    "\n"
    "\t  The esp_defmt.rs bail! patch added by --customize applies\n"
    f"\t  to {ESPFLASH_STOCK_VERSION} only.\n"
)

ESPFLASH_VERSION_OVERRIDE_MK = (
    "ifneq ($(call qstrip,$(BR2_PACKAGE_ESPFLASH_VERSION_OVERRIDE)),)\n"
    "ESPFLASH_VERSION = $(call qstrip,$(BR2_PACKAGE_ESPFLASH_VERSION_OVERRIDE))\n"
    "endif\n"
)

# espflash 4.0.1 writes `Ok(None) => bail!(DefmtError::NoDefmtData),` in
# esp_defmt.rs. miette's bail! expands to `return Err(..);`, and rustc 1.99
# warns about that trailing semicolon in expression position
# (semicolon_in_expressions_from_non_local_macros, rust-lang/rust#79813,
# "will become a hard error"). It is reported twice because espflash builds
# as both a lib and a bin. Braces make it a statement, like the `bail!`
# a few lines above. Buildroot reads package/espflash/<VERSION>/ in place
# of package/espflash/ when that directory exists, so the patch lives in
# 4.0.1/ and a version override never sees it.
ESPFLASH_PATCH_STEM = "esp_defmt-bail-in-statement-position"
ESPFLASH_OLD = "Ok(None) => bail!(DefmtError::NoDefmtData),"
ESPFLASH_NEW = "bail!(DefmtError::NoDefmtData);"
ESPFLASH_PATCH_INDEX_RE = re.compile(r"^(\d{4})-")
ESPFLASH_BAIL_PATCH = """\
esp_defmt: call bail! in statement position

rustc 1.99 warns that the trailing semicolon in miette's bail! is
phased out in expression position
(semicolon_in_expressions_from_non_local_macros, rust-lang/rust#79813).
Wrap the match arm in a block so bail! is a statement.

---
 espflash/src/cli/monitor/parser/esp_defmt.rs | 4 +++-
 1 file changed, 3 insertions(+), 1 deletion(-)

diff --git a/espflash/src/cli/monitor/parser/esp_defmt.rs b/espflash/src/cli/monitor/parser/esp_defmt.rs
--- a/espflash/src/cli/monitor/parser/esp_defmt.rs
+++ b/espflash/src/cli/monitor/parser/esp_defmt.rs
@@ -130,5 +130,7 @@
         let table = match Table::parse(elf) {
             Ok(Some(table)) => table,
-            Ok(None) => bail!(DefmtError::NoDefmtData),
+            Ok(None) => {
+                bail!(DefmtError::NoDefmtData);
+            }
             Err(e) => return Err(DefmtError::TableParseFailed).with_context(|| e),
         };
"""


def espflash_bail_patch_present(patch_dir: Path) -> bool:
    """Return True if a patch in *patch_dir* already applies the bail! fix."""
    needle_old = "-" + " " * 12 + ESPFLASH_OLD
    needle_new = "+" + " " * 16 + ESPFLASH_NEW
    for path in patch_dir.glob("*.patch"):
        text = path.read_text(encoding="utf-8")
        if needle_old in text and needle_new in text:
            return True
    return False


def next_espflash_patch_index(patch_dir: Path) -> int:
    """Return the next 000N index for a new file in *patch_dir*."""
    indexes = [
        int(match.group(1))
        for path in patch_dir.glob("*.patch")
        if (match := ESPFLASH_PATCH_INDEX_RE.match(path.name))
    ]
    return max(indexes, default=0) + 1


def patch_espflash(pkg_dir: Path) -> Path | None:
    """
    Write the esp_defmt.rs bail! patch into ``package/espflash/4.0.1/``.

    No-op when the directory is missing (unit tests, incomplete trees) or
    when a patch with the same hunk is already there.
    """
    if not pkg_dir.is_dir():
        return None
    patch_dir = pkg_dir / ESPFLASH_STOCK_VERSION
    if patch_dir.is_dir() and espflash_bail_patch_present(patch_dir):
        return None
    patch_dir.mkdir(exist_ok=True)
    dest = patch_dir / (
        f"{next_espflash_patch_index(patch_dir):04d}-{ESPFLASH_PATCH_STEM}.patch"
    )
    dest.write_text(ESPFLASH_BAIL_PATCH, encoding="utf-8")
    print(f"--> Added espflash bail! patch {dest.relative_to(pkg_dir.parent)}")
    return dest


def patch_espflash_config_in(path: Path) -> None:
    """Add ``BR2_PACKAGE_ESPFLASH_VERSION_OVERRIDE`` (default 4.0.1)."""
    text = path.read_text(encoding="utf-8")
    updated = append_kconfig_if_block(
        text,
        "BR2_PACKAGE_ESPFLASH",
        "BR2_PACKAGE_ESPFLASH_VERSION_OVERRIDE",
        ESPFLASH_VERSION_OVERRIDE_KCONFIG,
    )
    write_if_changed(
        path, text, updated, "Added BR2_PACKAGE_ESPFLASH_VERSION_OVERRIDE"
    )


def patch_espflash_mk(path: Path) -> None:
    """
    Honor ``BR2_PACKAGE_ESPFLASH_VERSION_OVERRIDE`` in espflash.mk.

    An empty override keeps the packaged ``ESPFLASH_VERSION``. Missing
    tarball hashes are filled by ``package/fetch-hash.mk``.
    """
    text = path.read_text(encoding="utf-8")
    updated = text
    if "BR2_PACKAGE_ESPFLASH_VERSION_OVERRIDE" not in text:
        updated, count = re.subn(
            r"^(ESPFLASH_VERSION = \S+\n)(ESPFLASH_SITE = )",
            r"\1" + ESPFLASH_VERSION_OVERRIDE_MK + r"\2",
            text,
            count=1,
            flags=re.MULTILINE,
        )
        if count != 1:
            raise SystemExit(
                f"Error: ESPFLASH_VERSION / ESPFLASH_SITE block not found in {path}"
            )
    write_if_changed(path, text, updated, "Added espflash version override")
