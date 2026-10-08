"""Optional BR2_PACKAGE_RUBY_VERSION_OVERRIDE and feature toggles for ruby."""

from __future__ import annotations

import inspect
import re
from pathlib import Path

from ..util import append_kconfig_if_block, tabbed, write_if_changed

RUBY_KCONFIG = tabbed(inspect.cleandoc("""
    config BR2_PACKAGE_RUBY_VERSION_OVERRIDE
        string "ruby version override"
        default ""
        help
          Leave empty to keep Buildroot's packaged ruby (4.0.5 in
          2026.08). Set to a release such as 4.0.7 or 3.4.11 to
          download that version instead. The major.minor series in
          the download URL (4.0, 3.4) is taken from this value.
          Missing tarball sha256 lines are filled by
          package/fetch-hash.mk.

    config BR2_PACKAGE_RUBY_RUBYGEMS
        bool "rubygems"
        help
          Build ruby with RubyGems and keep gem, rake, rdoc and ri
          on the target. Buildroot disables RubyGems by default and
          removes those files after installation.

    config BR2_PACKAGE_RUBY_YJIT
        bool "yjit"
        depends on BR2_PACKAGE_HOST_RUSTC_TARGET_ARCH_SUPPORTS
        help
          Build ruby with the YJIT compiler. Buildroot disables it
          by default. This builds the host Rust compiler first.

    config BR2_PACKAGE_RUBY_ZJIT
        bool "zjit"
        depends on BR2_PACKAGE_HOST_RUSTC_TARGET_ARCH_SUPPORTS
        help
          Build ruby with the ZJIT compiler. Buildroot disables it
          by default. This builds the host Rust compiler first.
"""))

# Inserted after RUBY_SOURCE. RUBY_VERSION is set to the literal override
# before RUBY_VERSION_MAJOR is redefined from it, so the two never refer to
# each other. RUBY_SITE and RUBY_VERSION_EXT expand lazily and follow.
# RUBY_VERSION_EXT is the lib/ruby/<ext> directory name: major.minor.0.
RUBY_VERSION_OVERRIDE_MK = inspect.cleandoc("""
    ifneq ($(call qstrip,$(BR2_PACKAGE_RUBY_VERSION_OVERRIDE)),)
    RUBY_VERSION = $(call qstrip,$(BR2_PACKAGE_RUBY_VERSION_OVERRIDE))
    RUBY_VERSION_MAJOR = $(word 1,$(subst ., ,$(RUBY_VERSION))).$(word 2,$(subst ., ,$(RUBY_VERSION)))
    RUBY_VERSION_EXT = $(RUBY_VERSION_MAJOR).0
    endif
""") + "\n"

RUBY_CONF_OPTS_OLD = tabbed(inspect.cleandoc(r"""
    RUBY_CONF_OPTS = \
        --disable-install-doc \
        --disable-rpath \
        --disable-rubygems \
        --disable-yjit \
        --disable-zjit
"""))

RUBY_CONF_OPTS_NEW = tabbed(inspect.cleandoc(r"""
    RUBY_CONF_OPTS = \
        --disable-rpath

    ifneq ($(BR2_KEEP_MAN_PAGES_DOCS),y)
    RUBY_CONF_OPTS += --disable-install-doc
    endif

    ifneq ($(BR2_PACKAGE_RUBY_RUBYGEMS),y)
    RUBY_CONF_OPTS += --disable-rubygems
    endif

    ifeq ($(BR2_PACKAGE_RUBY_YJIT),y)
    RUBY_DEPENDENCIES += host-rustc
    RUBY_CONF_OPTS += --enable-yjit
    else
    RUBY_CONF_OPTS += --disable-yjit
    endif

    ifeq ($(BR2_PACKAGE_RUBY_ZJIT),y)
    RUBY_DEPENDENCIES += host-rustc
    RUBY_CONF_OPTS += --enable-zjit
    else
    RUBY_CONF_OPTS += --disable-zjit
    endif
"""))

RUBY_REMOVE_HOOK_OLD = "RUBY_POST_INSTALL_TARGET_HOOKS += RUBY_REMOVE_RUBYGEMS\n"
RUBY_REMOVE_HOOK_NEW = inspect.cleandoc("""
    ifneq ($(BR2_PACKAGE_RUBY_RUBYGEMS),y)
    RUBY_POST_INSTALL_TARGET_HOOKS += RUBY_REMOVE_RUBYGEMS
    endif
""") + "\n"


def patch_ruby_config_in(path: Path) -> None:
    """Add the version override and rubygems/yjit/zjit options to ruby Config.in."""
    text = path.read_text(encoding="utf-8")
    updated = append_kconfig_if_block(
        text,
        "BR2_PACKAGE_RUBY",
        "BR2_PACKAGE_RUBY_VERSION_OVERRIDE",
        RUBY_KCONFIG,
    )
    write_if_changed(path, text, updated, "Added BR2_PACKAGE_RUBY_VERSION_OVERRIDE")


def patch_ruby_mk(path: Path) -> None:
    """
    Honor the ruby version override and feature toggles in ruby.mk.

    An empty override keeps the packaged ``RUBY_VERSION``. A set override
    also moves ``RUBY_VERSION_MAJOR`` (the download series) and
    ``RUBY_VERSION_EXT``. ``--disable-install-doc`` is dropped under
    ``BR2_KEEP_MAN_PAGES_DOCS``; ``--disable-rubygems``/``-yjit``/``-zjit``
    are dropped by their ``BR2_PACKAGE_RUBY_*`` options, and RubyGems is
    only stripped from the target when it is not enabled. Missing tarball
    hashes are filled by ``package/fetch-hash.mk``.
    """
    text = path.read_text(encoding="utf-8")
    original = text
    if "BR2_PACKAGE_RUBY_VERSION_OVERRIDE" not in text:
        text, count = re.subn(
            r"^(RUBY_SOURCE = \S+\n)",
            lambda m: m.group(1) + RUBY_VERSION_OVERRIDE_MK,
            text,
            count=1,
            flags=re.MULTILINE,
        )
        if count != 1:
            raise SystemExit(f"Error: RUBY_SOURCE line not found in {path}")
    if "BR2_PACKAGE_RUBY_YJIT" not in text:
        if RUBY_CONF_OPTS_OLD not in text:
            raise SystemExit(f"Error: RUBY_CONF_OPTS block not found in {path}")
        text = text.replace(RUBY_CONF_OPTS_OLD, RUBY_CONF_OPTS_NEW, 1)
    if RUBY_REMOVE_HOOK_NEW not in text:
        if RUBY_REMOVE_HOOK_OLD not in text:
            raise SystemExit(f"Error: RUBY_REMOVE_RUBYGEMS hook not found in {path}")
        text = text.replace(RUBY_REMOVE_HOOK_OLD, RUBY_REMOVE_HOOK_NEW, 1)
    write_if_changed(path, original, text, "Added ruby version override and toggles")
