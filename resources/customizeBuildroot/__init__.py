# ruff: noqa: N999
"""
Patch an extracted Buildroot tree for this installer.

Public API used by tests (`import customizeBuildroot as cb`) and by
`customizeBuildroot/main.py` when `getBuildroot.sh` runs --customize,
--update-kernel-support, or --update-rust-version.
"""

from .main import (
    DEFAULT_BR_PATH,
    customize_buildroot,
    default_br_path,
    default_custom_package_dir,
    main,
    patch_package_version_overrides,
)
from .patches.custom_late import LATE_CUSTOM_SKIP_PACKAGES
from .patches.espflash import (
    ESPFLASH_BAIL_PATCH,
    ESPFLASH_STOCK_VERSION,
    patch_espflash,
    patch_espflash_config_in,
    patch_espflash_mk,
)
from .patches.host_rust import update_rust_version
from .patches.kernel_support import update_kernel_support
from .patches.linux_tools import (
    PCI_BUILD_CMDS_OLD,
    PCI_INSTALL_CMDS_OLD,
    patch_linux_tool_pci_mk_in,
    patch_linux_tools_grep_install,
)
from .patches.man_docs import patch_makefile
from .patches.openvmtools import (
    OPENVMTOOLS_C23_NEW,
    OPENVMTOOLS_C23_OLD,
    OPENVMTOOLS_C23_PATCH,
    patch_openvmtools,
)
from .patches.ruby import patch_ruby_config_in, patch_ruby_mk
from .util import kconfig_package_symbol

__all__ = [
    "DEFAULT_BR_PATH",
    "ESPFLASH_BAIL_PATCH",
    "ESPFLASH_STOCK_VERSION",
    "LATE_CUSTOM_SKIP_PACKAGES",
    "OPENVMTOOLS_C23_NEW",
    "OPENVMTOOLS_C23_OLD",
    "OPENVMTOOLS_C23_PATCH",
    "PCI_BUILD_CMDS_OLD",
    "PCI_INSTALL_CMDS_OLD",
    "customize_buildroot",
    "default_br_path",
    "default_custom_package_dir",
    "kconfig_package_symbol",
    "main",
    "patch_espflash",
    "patch_espflash_config_in",
    "patch_espflash_mk",
    "patch_linux_tool_pci_mk_in",
    "patch_linux_tools_grep_install",
    "patch_makefile",
    "patch_openvmtools",
    "patch_package_version_overrides",
    "patch_ruby_config_in",
    "patch_ruby_mk",
    "update_kernel_support",
    "update_rust_version",
]
