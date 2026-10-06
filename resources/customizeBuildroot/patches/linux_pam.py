"""Optional BR2_PACKAGE_LINUX_PAM_VERSION_OVERRIDE for stock linux-pam."""

from __future__ import annotations

import re
from pathlib import Path

from ..util import (
    drop_br_no_check_hash_for,
    insert_before_meson_eval,
    insert_kconfig_after_if,
    tarball_fetch_hash_fragment,
    write_if_changed,
)

LINUX_PAM_VERSION_OVERRIDE_KCONFIG = (
    "config BR2_PACKAGE_LINUX_PAM_VERSION_OVERRIDE\n"
    '\tstring "linux-pam version override"\n'
    '\tdefault ""\n'
    "\thelp\n"
    "\t  Leave empty to keep Buildroot's packaged linux-pam\n"
    "\t  (1.7.2 in 2026.08). Set to a release such as 1.7.3\n"
    "\t  to download that version instead. When set, a\n"
    "\t  PRE_DOWNLOAD_HOOK appends a sha256 line for that\n"
    "\t  tarball to linux-pam.hash if one is not already\n"
    "\t  present (same JIT hash as hexedit/sharutils).\n"
)

LINUX_PAM_VERSION_OVERRIDE_MK = (
    "LINUX_PAM_VERSION_STOCK := $(LINUX_PAM_VERSION)\n"
    "ifneq ($(call qstrip,$(BR2_PACKAGE_LINUX_PAM_VERSION_OVERRIDE)),)\n"
    "LINUX_PAM_VERSION = $(call qstrip,$(BR2_PACKAGE_LINUX_PAM_VERSION_OVERRIDE))\n"
    "endif\n"
)

# Previous --customize inserted this hash-skip. Strip it on re-run.
LINUX_PAM_OVERRIDE_MK_TAIL_LEGACY = (
    "\n"
    "ifneq ($(LINUX_PAM_VERSION),$(LINUX_PAM_VERSION_STOCK))\n"
    "BR_NO_CHECK_HASH_FOR += $(LINUX_PAM_SOURCE)\n"
    "endif\n"
)

LINUX_PAM_OVERRIDE_MK_TAIL = (
    "\n"
    "ifneq ($(call qstrip,$(BR2_PACKAGE_LINUX_PAM_VERSION_OVERRIDE)),)\n"
    + tarball_fetch_hash_fragment(
        "LINUX_PAM",
        "linux-pam.hash",
        "Buildroot-linux-pam",
        error_label="linux-pam",
    )
    + "endif\n"
)


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

    Empty override keeps the packaged ``LINUX_PAM_VERSION``. A set override
    registers ``LINUX_PAM_FETCH_HASH`` so the tarball sha256 is appended to
    linux-pam.hash when missing.
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
    text = insert_before_meson_eval(
        text,
        LINUX_PAM_OVERRIDE_MK_TAIL,
        "LINUX_PAM_PRE_DOWNLOAD_HOOKS += LINUX_PAM_FETCH_HASH",
    )
    write_if_changed(
        path,
        original,
        text,
        "Added linux-pam version override",
    )
