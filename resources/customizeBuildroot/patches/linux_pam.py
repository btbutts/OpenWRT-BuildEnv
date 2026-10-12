"""Optional BR2_PACKAGE_LINUX_PAM_VERSION_OVERRIDE for stock linux-pam."""

from __future__ import annotations

import inspect
import re
from pathlib import Path

from ..util import (
    drop_br_no_check_hash_for,
    insert_kconfig_after_if,
    tabbed,
    write_if_changed,
)

LINUX_PAM_VERSION_OVERRIDE_KCONFIG = tabbed(inspect.cleandoc("""
    config BR2_PACKAGE_LINUX_PAM_VERSION_OVERRIDE
        string "linux-pam version override"
        default ""
        help
          Leave empty to keep Buildroot's packaged linux-pam
          (1.7.2 in 2026.08). Set to a release such as 1.7.3
          to download that version instead. Missing tarball
          sha256 lines are filled by package/fetch-hash.mk.
"""))

LINUX_PAM_VERSION_OVERRIDE_MK = inspect.cleandoc("""
    LINUX_PAM_VERSION_STOCK := $(LINUX_PAM_VERSION)
    ifneq ($(call qstrip,$(BR2_PACKAGE_LINUX_PAM_VERSION_OVERRIDE)),)
    LINUX_PAM_VERSION = $(call qstrip,$(BR2_PACKAGE_LINUX_PAM_VERSION_OVERRIDE))
    endif
""") + "\n"

# Previous --customize inserted this hash-skip. Strip it on re-run.
LINUX_PAM_OVERRIDE_MK_TAIL_LEGACY = "\n" + inspect.cleandoc("""
    ifneq ($(LINUX_PAM_VERSION),$(LINUX_PAM_VERSION_STOCK))
    BR_NO_CHECK_HASH_FOR += $(LINUX_PAM_SOURCE)
    endif
""") + "\n"


def patch_linux_pam_config_in(path: Path) -> None:
    """Add empty-default ``BR2_PACKAGE_LINUX_PAM_VERSION_OVERRIDE``."""
    text = path.read_text()
    original = text
    text = insert_kconfig_after_if(
        text,
        "if BR2_PACKAGE_LINUX_PAM",
        "BR2_PACKAGE_LINUX_PAM_VERSION_OVERRIDE",
        LINUX_PAM_VERSION_OVERRIDE_KCONFIG,
    )
    write_if_changed(
        path,
        original,
        text,
        "Added BR2_PACKAGE_LINUX_PAM_VERSION_OVERRIDE",
    )


def patch_linux_pam_mk(path: Path) -> None:
    """
    Honor ``BR2_PACKAGE_LINUX_PAM_VERSION_OVERRIDE`` in linux-pam.mk.

    Empty override keeps the packaged ``LINUX_PAM_VERSION``. Missing
    tarball hashes are filled by ``package/fetch-hash.mk``.
    """
    text = path.read_text()
    original = text
    if "LINUX_PAM_VERSION_STOCK" not in text:
        updated, n = re.subn(
            r"^(LINUX_PAM_VERSION = \S+\n)(LINUX_PAM_SOURCE = )",
            r"\1" + LINUX_PAM_VERSION_OVERRIDE_MK + r"\2",
            text,
            count=1,
            flags=re.MULTILINE,
        )
        if n != 1:
            raise SystemExit(
                f"Error: LINUX_PAM_VERSION / LINUX_PAM_SOURCE block not found in {path}"
            )
        text = updated
    if LINUX_PAM_OVERRIDE_MK_TAIL_LEGACY in text:
        text = text.replace(LINUX_PAM_OVERRIDE_MK_TAIL_LEGACY, "\n")
    text = drop_br_no_check_hash_for(text, "$(LINUX_PAM_SOURCE)")
    write_if_changed(
        path,
        original,
        text,
        "Added linux-pam version override",
    )
