#!/usr/bin/env python3
"""
Patch an extracted Buildroot tree for this installer.

Keeps man/docs when requested and drops small patches into stock
Buildroot package dirs (openvmtools C23, linux-tools PCI, optional
systemd/linux-pam version overrides) during `getBuildroot.sh
--customize`. Writes `package/custom-late.mk` so br2-external
packages under `buildrootConf/custom_package/` install last on a
full image build (gcc-standalone-toolchain last among those;
uutils-coreutils is excluded so it can overlay BusyBox applets at
normal order).

`--customize` also installs `package/fetch-hash.mk` so any package
tarball missing a sha256 line gets one from a published sums URL or
from hashing the downloaded archive. `getBuildroot.sh
--update-kernel-support` is a separate action: it bumps 2026.08
`BR2_LINUX_KERNEL_LATEST_VERSION` from 7.1.13 to 7.2.9 and adds
matching `BR2_KERNEL_HEADERS_7_2` / `BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_2`
Kconfig so glibc stays enabled. It also installs fetch-hash.mk so a
kernel-only bump still hashes `linux-7.2.9.tar.xz`. It is not part of
`--customize`. `getBuildroot.sh --update-rust-version` is likewise
separate: it writes `RUST_VERSION` into rust.mk and rust-bin.mk and
`RUST_BINDGEN_VERSION` into rust-bindgen.mk. Blank env vars skip that
patch. It is not part of `--customize`.

Custom packages are not copied into `package/<name>/`.
`compileBuildroot.sh` exports `BR2_EXTERNAL` so Buildroot sources
the tree via `external.desc` / `Config.in` / `external.mk`.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from customizeBuildroot.patches.custom_late import (
    iter_custom_packages,
    write_custom_late_mk,
)
from customizeBuildroot.patches.fetch_hash import write_fetch_hash_mk
from customizeBuildroot.patches.host_rust import update_rust_version
from customizeBuildroot.patches.kernel_support import update_kernel_support
from customizeBuildroot.patches.linux_pam import (
    patch_linux_pam_config_in,
    patch_linux_pam_mk,
)
from customizeBuildroot.patches.linux_tools import patch_linux_tools
from customizeBuildroot.patches.man_docs import patch_config_in, patch_makefile
from customizeBuildroot.patches.openvmtools import patch_openvmtools
from customizeBuildroot.patches.systemd import (
    patch_systemd_config_in,
    patch_systemd_mk,
)

# Parent of this package: resources/ in the repo, /builder/ in the container.
_RESOURCES_DIR = Path(__file__).resolve().parent.parent


def default_br_path() -> Path:
    """
    Return the extracted Buildroot tree path.

    Uses ``BUILDROOT_BUILDER_DIR`` when that env var is set, otherwise
    ``/builder/Buildroot-Builder``.
    """
    value = os.environ.get("BUILDROOT_BUILDER_DIR") or "/builder/Buildroot-Builder"
    trimmed = value.rstrip("/")
    return Path(trimmed) if trimmed else Path("/builder/Buildroot-Builder")


def default_custom_package_dir() -> Path:
    """
    Return the staged custom-package tree.

    Prefers ``BUILDROOT_CONF_DIR/custom_package``, then a sibling of this
    package (repo / ``/builder/buildrootConf/custom_package``).
    """
    env = os.environ.get("BUILDROOT_CONF_DIR")
    if env:
        return Path(env.rstrip("/")) / "custom_package"
    sibling = _RESOURCES_DIR / "buildrootConf" / "custom_package"
    if sibling.is_dir():
        return sibling
    return Path("/builder/buildrootConf/custom_package")


DEFAULT_BR_PATH = default_br_path()


def patch_package_version_overrides(br_path: Path) -> None:
    """
    Add optional systemd and linux-pam version-override Kconfig/makefile.

    Missing package dirs are a no-op (unit-test fixtures). Empty override
    strings keep Buildroot's packaged versions.
    """
    systemd_cfg = br_path / "package" / "systemd" / "Config.in"
    systemd_mk = br_path / "package" / "systemd" / "systemd.mk"
    if systemd_cfg.is_file() and systemd_mk.is_file():
        patch_systemd_config_in(systemd_cfg)
        patch_systemd_mk(systemd_mk)
    pam_cfg = br_path / "package" / "linux-pam" / "Config.in"
    pam_mk = br_path / "package" / "linux-pam" / "linux-pam.mk"
    if pam_cfg.is_file() and pam_mk.is_file():
        patch_linux_pam_config_in(pam_cfg)
        patch_linux_pam_mk(pam_mk)


def customize_buildroot(
    br_path: Path,
    custom_package_dir: Path | None = None,
) -> None:
    """
    Apply stock-tree patches under the extracted Buildroot *br_path*.

    Requires Config.in, package/Config.in, and Makefile at the tree root.
    Inserts BR2_KEEP_MAN_PAGES_DOCS, wraps the man/doc purge, patches
    linux-tools ``*.mk.in`` so PCI follows kernel 6.14+ pci_endpoint,
    writes the GCC 15 / C23 ul.c fix into stock
    ``package/openvmtools/``, and adds empty-default
    ``BR2_PACKAGE_SYSTEMD_VERSION_OVERRIDE`` /
    ``BR2_PACKAGE_LINUX_PAM_VERSION_OVERRIDE`` so a fragment can pick
    systemd 262 or linux-pam 1.7.3 without changing packaged
    defaults. Scans *custom_package_dir* and writes
    ``package/custom-late.mk`` so those packages install last on a
    full image build (uutils-coreutils skipped; gcc-standalone last
    among the rest). Does not copy package files into ``package/``.
    """
    config_in = br_path / "Config.in"
    makefile = br_path / "Makefile"
    custom_dir = custom_package_dir or default_custom_package_dir()

    if not config_in.is_file():
        raise SystemExit(
            f"Error: Buildroot is not extracted at {br_path} (missing Config.in)."
        )
    if not makefile.is_file():
        raise SystemExit(
            f"Error: Buildroot is not extracted at {br_path} (missing Makefile)."
        )
    pkg_config_in = br_path / "package" / "Config.in"
    if not pkg_config_in.is_file():
        raise SystemExit(
            f"Error: Buildroot is not extracted at {br_path} (missing package/Config.in)."
        )

    packages = iter_custom_packages(custom_dir)
    write_custom_late_mk(br_path, packages)
    write_fetch_hash_mk(br_path)
    patch_config_in(config_in)
    patch_makefile(makefile)
    patch_linux_tools(br_path / "package" / "linux-tools")
    patch_openvmtools(br_path / "package" / "openvmtools")
    patch_package_version_overrides(br_path)
    print("--> customizeBuildroot completed successfully.")


def main(argv: list[str] | None = None) -> int:
    """
    Parse CLI arguments and run customize_buildroot().

    Parameters
    ----------
    argv:
        Argument list without the program name. ``None`` uses ``sys.argv[1:]``.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Patch extracted Buildroot sources for man/docs retention, "
            "stock-package compile fixes, and late custom-package install. "
            "Use --update-kernel-support alone to bump latest kernel/headers "
            "from 7.1.13 to 7.2.9. Use --update-rust-version alone to set "
            "rust/rust-bin from RUST_VERSION and rust-bindgen from "
            "RUST_BINDGEN_VERSION."
        )
    )
    parser.add_argument(
        "--br-path",
        type=Path,
        default=DEFAULT_BR_PATH,
        help=f"Buildroot source root (default: {DEFAULT_BR_PATH})",
    )
    parser.add_argument(
        "--custom-package-dir",
        type=Path,
        default=None,
        help=(
            "br2-external custom_package tree used to generate "
            "package/custom-late.mk (default: BUILDROOT_CONF_DIR/custom_package)"
        ),
    )
    exclusive = parser.add_mutually_exclusive_group()
    exclusive.add_argument(
        "--update-kernel-support",
        action="store_true",
        help=(
            "Patch 2026.08 Kconfig so BR2_LINUX_KERNEL_LATEST_VERSION is "
            "Linux 7.2.9 with matching headers. Does not run with --customize."
        ),
    )
    exclusive.add_argument(
        "--update-rust-version",
        action="store_true",
        help=(
            "Set rust and rust-bin from RUST_VERSION, and rust-bindgen "
            "from RUST_BINDGEN_VERSION. Blank env vars skip that patch. "
            "Does not run with --customize."
        ),
    )
    args = parser.parse_args(argv)
    if args.update_kernel_support:
        update_kernel_support(args.br_path)
        return 0
    if args.update_rust_version:
        update_rust_version(args.br_path)
        return 0
    customize_buildroot(args.br_path, args.custom_package_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
