"""Optional BR2_PACKAGE_SYSTEMD_VERSION_OVERRIDE for stock systemd."""

from __future__ import annotations

import re
from pathlib import Path

from ..util import (
    drop_br_no_check_hash_for,
    insert_before_meson_eval,
    insert_kconfig_after_if,
    write_if_changed,
)

SYSTEMD_VERSION_OVERRIDE_KCONFIG = (
    "config BR2_PACKAGE_SYSTEMD_VERSION_OVERRIDE\n"
    '\tstring "systemd version override"\n'
    '\tdefault ""\n'
    "\thelp\n"
    "\t  Leave empty to keep Buildroot's packaged systemd (258.7\n"
    "\t  in 2026.08). Set to a release tag without the leading\n"
    '\t  "v", for example 262, to download that version instead.\n'
    "\n"
    "\t  systemd 260+ dropped SysV meson options; 262 also dropped\n"
    "\t  libidn and libiptc. The makefile strips those -D flags\n"
    "\t  when an override is set so meson configure can succeed.\n"
    "\t  Missing tarball sha256 lines are filled by\n"
    "\t  package/fetch-hash.mk.\n"
)

SYSTEMD_VERSION_OVERRIDE_MK = (
    "SYSTEMD_VERSION_STOCK := $(SYSTEMD_VERSION)\n"
    "ifneq ($(call qstrip,$(BR2_PACKAGE_SYSTEMD_VERSION_OVERRIDE)),)\n"
    "SYSTEMD_VERSION = $(call qstrip,$(BR2_PACKAGE_SYSTEMD_VERSION_OVERRIDE))\n"
    "endif\n"
)

# Previous --customize inserted this hash-skip. Strip it on re-run.
SYSTEMD_OVERRIDE_MK_TAIL_LEGACY = (
    "\n"
    "# Override tarball: skip packaged hashes. systemd 260+ dropped SysV\n"
    "# meson options; 262 also dropped libidn and libiptc.\n"
    "ifneq ($(SYSTEMD_VERSION),$(SYSTEMD_VERSION_STOCK))\n"
    "BR_NO_CHECK_HASH_FOR += systemd-$(SYSTEMD_VERSION).tar.gz\n"
    "SYSTEMD_CONF_OPTS := $(filter-out "
    "-Dsysvinit-path= -Dsysvrcnd-path= "
    "-Dlibidn=enabled -Dlibidn=disabled "
    "-Dlibiptc=enabled -Dlibiptc=disabled,"
    "$(SYSTEMD_CONF_OPTS))\n"
    "HOST_SYSTEMD_CONF_OPTS := $(filter-out "
    "-Dsysvinit-path='' -Dsysvinit-path= "
    "-Dlibidn=enabled -Dlibidn=disabled "
    "-Dlibiptc=enabled -Dlibiptc=disabled,"
    "$(HOST_SYSTEMD_CONF_OPTS))\n"
    "endif\n"
)

SYSTEMD_OVERRIDE_MK_TAIL = (
    "\n"
    "# systemd 260+ dropped SysV meson options; 262 also dropped libidn "
    "and libiptc.\n"
    "ifneq ($(SYSTEMD_VERSION),$(SYSTEMD_VERSION_STOCK))\n"
    "SYSTEMD_CONF_OPTS := $(filter-out "
    "-Dsysvinit-path= -Dsysvrcnd-path= "
    "-Dlibidn=enabled -Dlibidn=disabled "
    "-Dlibiptc=enabled -Dlibiptc=disabled,"
    "$(SYSTEMD_CONF_OPTS))\n"
    "HOST_SYSTEMD_CONF_OPTS := $(filter-out "
    "-Dsysvinit-path='' -Dsysvinit-path= "
    "-Dlibidn=enabled -Dlibidn=disabled "
    "-Dlibiptc=enabled -Dlibiptc=disabled,"
    "$(HOST_SYSTEMD_CONF_OPTS))\n"
    "endif\n"
)


def patch_systemd_config_in(path: Path) -> None:
    """Add empty-default ``BR2_PACKAGE_SYSTEMD_VERSION_OVERRIDE`` to systemd Config.in."""
    text = path.read_text()
    original = text
    text = insert_kconfig_after_if(
        text,
        "if BR2_PACKAGE_SYSTEMD",
        "BR2_PACKAGE_SYSTEMD_VERSION_OVERRIDE",
        SYSTEMD_VERSION_OVERRIDE_KCONFIG,
    )
    write_if_changed(
        path,
        original,
        text,
        "Added BR2_PACKAGE_SYSTEMD_VERSION_OVERRIDE",
    )


def patch_systemd_mk(path: Path) -> None:
    """
    Honor ``BR2_PACKAGE_SYSTEMD_VERSION_OVERRIDE`` in systemd.mk.

    Empty override keeps the packaged ``SYSTEMD_VERSION``. A set override
    drops meson ``-D`` flags that systemd 260+ / 262 removed (SysV
    paths, libidn, libiptc). Missing tarball hashes are filled by
    ``package/fetch-hash.mk``.
    """
    text = path.read_text()
    original = text
    if "SYSTEMD_VERSION_STOCK" not in text:
        updated, n = re.subn(
            r"^(SYSTEMD_VERSION = \S+\n)(SYSTEMD_SITE = )",
            r"\1" + SYSTEMD_VERSION_OVERRIDE_MK + r"\2",
            text,
            count=1,
            flags=re.MULTILINE,
        )
        if n != 1:
            raise SystemExit(
                f"Error: SYSTEMD_VERSION / SYSTEMD_SITE block not found in {path}"
            )
        text = updated
    if SYSTEMD_OVERRIDE_MK_TAIL_LEGACY in text:
        text = text.replace(SYSTEMD_OVERRIDE_MK_TAIL_LEGACY, "\n")
    text = drop_br_no_check_hash_for(text, "systemd-$(SYSTEMD_VERSION).tar.gz")
    text = insert_before_meson_eval(
        text,
        SYSTEMD_OVERRIDE_MK_TAIL,
        "SYSTEMD_CONF_OPTS := $(filter-out",
    )
    write_if_changed(
        path,
        original,
        text,
        "Added systemd version override",
    )
