"""Bump 2026.08 latest kernel/headers from 7.1.13 to 7.2.9."""

from __future__ import annotations

import re
from pathlib import Path

from ..util import write_if_changed

# 2026.08 latest kernel/headers stop at 7.1.13. --update-kernel-support
# promotes 7.2.9 the same way Buildroot itself bumps a latest series.
# Kconfig prompts use the series (7.2); VERSION / patch dirs use the full tag.
KERNEL_PREV_FULL = "7.1.13"
KERNEL_LATEST_FULL = "7.2.9"
KERNEL_PREV_SERIES = ".".join(KERNEL_PREV_FULL.split(".")[:2])
KERNEL_LATEST_SERIES = ".".join(KERNEL_LATEST_FULL.split(".")[:2])
KERNEL_HASH_DIR = "from-6.17"
GET_HASH_MK_NAME = "get-hash.mk"
GET_HASH_INCLUDE_MARKER = f"include linux/{KERNEL_HASH_DIR}/{GET_HASH_MK_NAME}"
GET_HASH_INCLUDE_COMMENT = (
    "# JIT-append kernel.org sha256 lines for linux/linux-headers tarballs.\n"
)
GET_HASH_INCLUDE_BLOCK = (
    f"\n{GET_HASH_INCLUDE_COMMENT}{GET_HASH_INCLUDE_MARKER}\n"
)
# Register hooks before package/*.mk and linux/linux.mk so both
# linux-headers and linux see LINUX_*_PRE_DOWNLOAD_HOOKS.
PACKAGE_WILDCARD_INCLUDE = "include $(sort $(wildcard package/*/*.mk))\n"


def patch_kernel_headers_host(path: Path) -> None:
    """
    Add ``BR2_KERNEL_HEADERS_7_2`` as the latest headers series.

    7.1.x stays in the choice without ``BR2_KERNEL_HEADERS_LATEST``.
    The custom-series "or later" option and ``BR2_DEFAULT_KERNEL_HEADERS``
    follow the same 7.2.9 bump.
    """
    text = path.read_text()
    original = text

    text = re.sub(
        r"(?m)^(\tdefault )BR2_KERNEL_HEADERS_7_1$",
        r"\1BR2_KERNEL_HEADERS_7_2",
        text,
        count=1,
    )

    old_headers = (
        "config BR2_KERNEL_HEADERS_7_1\n"
        '\tbool "Linux 7.1.x kernel headers"\n'
        "\tselect BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_1\n"
        "\tselect BR2_KERNEL_HEADERS_LATEST\n"
    )
    new_headers = (
        "config BR2_KERNEL_HEADERS_7_1\n"
        '\tbool "Linux 7.1.x kernel headers"\n'
        "\tselect BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_1\n"
        "\n"
        "config BR2_KERNEL_HEADERS_7_2\n"
        '\tbool "Linux 7.2.x kernel headers"\n'
        "\tselect BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_2\n"
        "\tselect BR2_KERNEL_HEADERS_LATEST\n"
    )
    if "config BR2_KERNEL_HEADERS_7_2\n" not in text:
        if old_headers not in text:
            raise SystemExit(
                f"Error: BR2_KERNEL_HEADERS_7_1 latest block not found in {path}"
            )
        text = text.replace(old_headers, new_headers, 1)

    old_custom = (
        "config BR2_PACKAGE_HOST_LINUX_HEADERS_CUSTOM_7_1\n"
        '\tbool "7.1.x or later"\n'
        "\tselect BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_1\n"
    )
    new_custom = (
        "config BR2_PACKAGE_HOST_LINUX_HEADERS_CUSTOM_7_2\n"
        '\tbool "7.2.x or later"\n'
        "\tselect BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_2\n"
        "\n"
        "config BR2_PACKAGE_HOST_LINUX_HEADERS_CUSTOM_7_1\n"
        '\tbool "7.1.x"\n'
        "\tselect BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_1\n"
    )
    if "config BR2_PACKAGE_HOST_LINUX_HEADERS_CUSTOM_7_2\n" not in text:
        if old_custom not in text:
            raise SystemExit(
                f"Error: BR2_PACKAGE_HOST_LINUX_HEADERS_CUSTOM_7_1 "
                f"'or later' block not found in {path}"
            )
        text = text.replace(old_custom, new_custom, 1)

    latest_default = '\tdefault "7.2.9"\tif BR2_KERNEL_HEADERS_7_2\n'
    prev_default = '\tdefault "7.1.13"\tif BR2_KERNEL_HEADERS_7_1\n'
    if not re.search(
        r'default "7\.2\.\d+"\s+if BR2_KERNEL_HEADERS_7_2',
        text,
    ):
        if prev_default not in text:
            raise SystemExit(
                f"Error: BR2_DEFAULT_KERNEL_HEADERS 7.1.13 default not found in {path}"
            )
        text = text.replace(prev_default, latest_default + prev_default, 1)

    write_if_changed(path, original, text, "Added Linux 7.2.x kernel headers")


def patch_toolchain_headers_at_least(path: Path) -> None:
    """
    Add ``BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_2`` as the latest AT_LEAST symbol.

    7_2 selects 7_1 and ``BR2_TOOLCHAIN_HEADERS_LATEST``; the string
    option prefers ``"7.2"``.
    """
    text = path.read_text()
    original = text

    old_at_least = (
        "config BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_1\n"
        "\tbool\n"
        "\tselect BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_0\n"
        "\tselect BR2_TOOLCHAIN_HEADERS_LATEST\n"
    )
    new_at_least = (
        "config BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_1\n"
        "\tbool\n"
        "\tselect BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_0\n"
        "\n"
        "config BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_2\n"
        "\tbool\n"
        "\tselect BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_1\n"
        "\tselect BR2_TOOLCHAIN_HEADERS_LATEST\n"
    )
    if "config BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_2\n" not in text:
        if old_at_least not in text:
            raise SystemExit(
                f"Error: BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_1 latest block "
                f"not found in {path}"
            )
        text = text.replace(old_at_least, new_at_least, 1)

    old_string = (
        "config BR2_TOOLCHAIN_HEADERS_AT_LEAST\n"
        "\tstring\n"
        '\tdefault "7.1" if BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_1\n'
    )
    new_string = (
        "config BR2_TOOLCHAIN_HEADERS_AT_LEAST\n"
        "\tstring\n"
        '\tdefault "7.2" if BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_2\n'
        '\tdefault "7.1" if BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_1\n'
    )
    if '\tdefault "7.2" if BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_2\n' not in text:
        if old_string not in text:
            raise SystemExit(
                f"Error: BR2_TOOLCHAIN_HEADERS_AT_LEAST 7.1 default not found in {path}"
            )
        text = text.replace(old_string, new_string, 1)

    write_if_changed(path, original, text, "Added toolchain headers at least 7.2")


def patch_linux_latest_version(path: Path) -> None:
    """
    Point ``BR2_LINUX_KERNEL_LATEST_VERSION`` at 7.2.9.

    Also moves the AS_KERNEL ``AT_LEAST`` select to 7_2 so glibc and
    other packages that depend on a headers floor stay enabled.
    """
    text = path.read_text()
    original = text

    text = text.replace(
        f'\tbool "Latest version ({KERNEL_PREV_SERIES})"\n',
        f'\tbool "Latest version ({KERNEL_LATEST_SERIES})"\n',
        1,
    )

    text = re.sub(
        r"(config BR2_LINUX_KERNEL_LATEST_VERSION\n"
        r'\tbool "Latest version \(7\.\d\)"\n'
        r"\tselect BR2_TOOLCHAIN_HEADERS_AT_LEAST_)7_1"
        r"( if BR2_KERNEL_HEADERS_AS_KERNEL)",
        r"\g<1>7_2\2",
        text,
        count=1,
    )

    text = re.sub(
        r'(config BR2_LINUX_KERNEL_VERSION\n'
        r"\tstring\n"
        rf'\tdefault )"{re.escape(KERNEL_PREV_FULL)}"( if BR2_LINUX_KERNEL_LATEST_VERSION)',
        rf'\g<1>"{KERNEL_LATEST_FULL}"\2',
        text,
        count=1,
    )

    if f'bool "Latest version ({KERNEL_LATEST_SERIES})"' not in text:
        raise SystemExit(
            f"Error: BR2_LINUX_KERNEL_LATEST_VERSION {KERNEL_PREV_SERIES} "
            f"prompt not found in {path}"
        )
    if "select BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_2 if BR2_KERNEL_HEADERS_AS_KERNEL" not in text:
        raise SystemExit(
            f"Error: LATEST_VERSION AT_LEAST_7_1 select not found in {path}"
        )
    if not re.search(
        r'default "7\.2\.\d+" if BR2_LINUX_KERNEL_LATEST_VERSION',
        text,
    ):
        raise SystemExit(
            f"Error: BR2_LINUX_KERNEL_VERSION default 7.1.13 not found in {path}"
        )

    write_if_changed(
        path,
        original,
        text,
        "Set BR2_LINUX_KERNEL_LATEST_VERSION to 7.2.9",
    )


def link_kernel_version_patch_dirs(br_path: Path) -> None:
    """
    Point ``linux/7.2.9`` and ``package/linux-headers/7.2.9`` at the
    same patch directory 2026.08 uses for 7.1.13 (``from-6.17``).
    """
    pairs = (
        br_path / "linux" / KERNEL_PREV_FULL,
        br_path / "linux" / KERNEL_LATEST_FULL,
        br_path / "package" / "linux-headers" / KERNEL_PREV_FULL,
        br_path / "package" / "linux-headers" / KERNEL_LATEST_FULL,
    )
    for prev, dest in (pairs[:2], pairs[2:]):
        if dest.exists() or dest.is_symlink():
            continue
        if not (prev.exists() or prev.is_symlink()):
            continue
        if prev.is_symlink():
            dest.symlink_to(prev.readlink())
        else:
            dest.symlink_to(prev.name)
        print(f"--> Linked kernel patch dir {dest} -> {dest.readlink()}")


def write_get_hash_mk(br_path: Path) -> None:
    """
    Install ``linux/from-6.17/get-hash.mk`` and include it from the Makefile.

    The include is inserted before ``package/*/*.mk`` so linux-headers
    and linux both see the PRE_DOWNLOAD_HOOKS. The fragment copies a
    missing ``linux-*.tar.xz`` sha256 from kernel.org ``sha256sums.asc``
    into the existing ``linux.hash`` before Buildroot's hash check.
    """
    dest_dir = br_path / "linux" / KERNEL_HASH_DIR
    if not dest_dir.is_dir():
        raise SystemExit(
            f"Error: {dest_dir} is missing; cannot install {GET_HASH_MK_NAME}"
        )
    src = Path(__file__).with_name(GET_HASH_MK_NAME)
    if not src.is_file():
        raise SystemExit(f"Error: {src} is missing from customizeBuildroot")
    dest = dest_dir / GET_HASH_MK_NAME
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"--> Wrote {dest}")

    makefile = br_path / "Makefile"
    text = makefile.read_text(encoding="utf-8")
    if GET_HASH_INCLUDE_MARKER in text:
        print(f"--> {GET_HASH_INCLUDE_MARKER} already present in {makefile}")
        return
    if PACKAGE_WILDCARD_INCLUDE in text:
        makefile.write_text(
            text.replace(
                PACKAGE_WILDCARD_INCLUDE,
                GET_HASH_INCLUDE_BLOCK + PACKAGE_WILDCARD_INCLUDE,
                1,
            ),
            encoding="utf-8",
        )
        print(
            f"--> Inserted {GET_HASH_INCLUDE_MARKER} before package/*.mk in {makefile}"
        )
        return
    makefile.write_text(
        text.rstrip("\n") + "\n" + GET_HASH_INCLUDE_BLOCK,
        encoding="utf-8",
    )
    print(f"--> Appended {GET_HASH_INCLUDE_MARKER} to {makefile}")


def update_kernel_support(br_path: Path) -> None:
    """
    Patch an extracted 2026.08 tree so latest kernel/headers are 7.2.9.

    Edits ``package/linux-headers/Config.in.host``, ``toolchain/Config.in``,
    and ``linux/Config.in``. Installs ``linux/from-6.17/get-hash.mk``.
    Does not run ``customize_buildroot``.
    """
    headers = br_path / "package" / "linux-headers" / "Config.in.host"
    toolchain = br_path / "toolchain" / "Config.in"
    linux_cfg = br_path / "linux" / "Config.in"
    missing = [p for p in (headers, toolchain, linux_cfg) if not p.is_file()]
    if missing:
        names = ", ".join(str(p) for p in missing)
        raise SystemExit(
            f"Error: --update-kernel-support needs these files: {names}"
        )
    patch_kernel_headers_host(headers)
    patch_toolchain_headers_at_least(toolchain)
    patch_linux_latest_version(linux_cfg)
    link_kernel_version_patch_dirs(br_path)
    write_get_hash_mk(br_path)
    print("--> update-kernel-support completed successfully.")
