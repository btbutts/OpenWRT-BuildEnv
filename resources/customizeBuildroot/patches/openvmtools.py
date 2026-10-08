"""Stock openvmtools C23 MXUserTryAcquireForceFail patch (GCC 15)."""

from __future__ import annotations

import inspect
import re
from pathlib import Path

# GCC 15 defaults to C23: empty () is (void). open-vm-tools 11.3.5
# defines MXUserTryAcquireForceFail as Bool (*)() while ulInt.h
# declares Bool (*)(const char *). Upstream PR 751, in 13.0.0.
# Stock package/openvmtools stays in-tree; this file is written into
# that directory at --customize time (not custom_package/).
OPENVMTOOLS_C23_PATCH_STEM = "c23-MXUserTryAcquireForceFail"
OPENVMTOOLS_C23_OLD = "Bool (*MXUserTryAcquireForceFail)() = NULL;"
OPENVMTOOLS_C23_NEW = "Bool (*MXUserTryAcquireForceFail)(const char *) = NULL;"
OPENVMTOOLS_PATCH_INDEX_RE = re.compile(r"^(\d{4})-")
OPENVMTOOLS_C23_PATCH = inspect.cleandoc("""
    lib/lock/ul.c: match MXUserTryAcquireForceFail to its prototype

    GCC 15 defaults to C23, where an empty parameter list is (void).
    The definition in ul.c was Bool (*)(void) while ulInt.h declares
    Bool (*)(const char *).

    Upstream: https://github.com/vmware/open-vm-tools/pull/751
    (incorporated in open-vm-tools 13.0.0)

    ---
     lib/lock/ul.c | 2 +-
     1 file changed, 1 insertion(+), 1 deletion(-)

    diff --git a/lib/lock/ul.c b/lib/lock/ul.c
    --- a/lib/lock/ul.c
    +++ b/lib/lock/ul.c
    @@ -28,7 +28,7 @@
     static Bool mxInPanic = FALSE;  // track when involved in a panic
     static Bool mxUserCollectLockingTree = FALSE;

    -Bool (*MXUserTryAcquireForceFail)() = NULL;
    +Bool (*MXUserTryAcquireForceFail)(const char *) = NULL;

     static MX_Rank (*MXUserMxCheckRank)(void) = NULL;
     static void (*MXUserMxLockLister)(void) = NULL;
""") + "\n"


def openvmtools_c23_patch_present(pkg_dir: Path) -> bool:
    """Return True if a package patch already applies the C23 ul.c fix."""
    if not pkg_dir.is_dir():
        return False
    needle_old = "-" + OPENVMTOOLS_C23_OLD
    needle_new = "+" + OPENVMTOOLS_C23_NEW
    for path in pkg_dir.glob("*.patch"):
        text = path.read_text()
        if needle_old in text and needle_new in text:
            return True
    return False


def next_openvmtools_patch_index(pkg_dir: Path) -> int:
    """Return the next 000N index for a new file in package/openvmtools."""
    highest = 0
    if pkg_dir.is_dir():
        for path in pkg_dir.glob("*.patch"):
            match = OPENVMTOOLS_PATCH_INDEX_RE.match(path.name)
            if match:
                highest = max(highest, int(match.group(1)))
    return highest + 1


def patch_openvmtools(pkg_dir: Path) -> Path | None:
    """
    Write the C23 MXUserTryAcquireForceFail patch into stock openvmtools.

    No-op when the directory is missing (unit tests, incomplete trees) or
    when a patch with the same hunk is already present. Numbering follows
    existing 000N-*.patch files so 2025.08/2026.08 trees (through 0014)
    get 0015-c23-MXUserTryAcquireForceFail.patch.
    """
    if not pkg_dir.is_dir():
        return None
    if openvmtools_c23_patch_present(pkg_dir):
        return None
    dest = pkg_dir / (
        f"{next_openvmtools_patch_index(pkg_dir):04d}-"
        f"{OPENVMTOOLS_C23_PATCH_STEM}.patch"
    )
    dest.write_text(OPENVMTOOLS_C23_PATCH)
    print(f"--> Added openvmtools C23 patch {dest.name}")
    return dest
