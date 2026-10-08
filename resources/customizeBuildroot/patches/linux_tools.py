"""Patch package/linux-tools for kernel 6.14+ pci_endpoint and grep-install."""

from __future__ import annotations

import inspect
import re
from pathlib import Path

from ..util import tabbed

# Kernel 6.14+ moved pcitest from tools/pci to tools/testing/selftests/pci_endpoint
# (kselftest lib.mk requires INSTALL_PATH). The grep-for-install check then
# treats a missing tools/pci/Makefile as "kernel too old".
PCI_BUILD_CMDS_OLD = tabbed(inspect.cleandoc(r"""
    define PCI_BUILD_CMDS
        $(Q)if ! grep install $(LINUX_DIR)/tools/pci/Makefile >/dev/null 2>&1 ; then \
            echo "Your kernel version is too old and does not have install section in the pci tools." ; \
            echo "At least kernel 4.20 must be used." ; \
            exit 1 ; \
        fi

        $(TARGET_MAKE_ENV) $(MAKE) -C $(LINUX_DIR)/tools/pci \
            $(PCI_MAKE_OPTS)
    endef
"""))

PCI_BUILD_CMDS_NEW = tabbed(inspect.cleandoc(r"""
    define PCI_BUILD_CMDS
        $(Q)if test -f $(LINUX_DIR)/tools/testing/selftests/pci_endpoint/Makefile ; then \
            PCI_SUBDIR=tools/testing/selftests/pci_endpoint \
            TEST_GEN_PROGS="TEST_GEN_PROGS=pci_endpoint_test"; \
        elif test -f $(LINUX_DIR)/tools/pci/Makefile ; then \
            PCI_SUBDIR=tools/pci; \
        else \
            echo "linux-tools pci: no tools/pci or tools/testing/selftests/pci_endpoint Makefile" ; \
            exit 1 ; \
        fi ; \
        $(TARGET_MAKE_ENV) $(MAKE) -C $(LINUX_DIR)/$${PCI_SUBDIR} \
            $(PCI_MAKE_OPTS) $${TEST_GEN_PROGS}
    endef
"""))

PCI_INSTALL_CMDS_OLD = tabbed(inspect.cleandoc(r"""
    define PCI_INSTALL_TARGET_CMDS
        $(TARGET_MAKE_ENV) $(MAKE) -C $(LINUX_DIR)/tools/pci \
            $(PCI_MAKE_OPTS) \
            DESTDIR=$(TARGET_DIR) \
            install
    endef
"""))

PCI_INSTALL_CMDS_NEW = tabbed(inspect.cleandoc(r"""
    define PCI_INSTALL_TARGET_CMDS
        $(Q)if test -f $(LINUX_DIR)/tools/testing/selftests/pci_endpoint/Makefile ; then \
            PCI_INSTALL_OPT="INSTALL_PATH=$(TARGET_DIR)/usr/bin" \
            PCI_SUBDIR=tools/testing/selftests/pci_endpoint \
            TEST_GEN_PROGS="TEST_GEN_PROGS=pci_endpoint_test"; \
        else \
            PCI_INSTALL_OPT="DESTDIR=$(TARGET_DIR)" \
            PCI_SUBDIR=tools/pci; \
        fi ; \
        $(TARGET_MAKE_ENV) $(MAKE) -C $(LINUX_DIR)/$${PCI_SUBDIR} \
            $(PCI_MAKE_OPTS) $${TEST_GEN_PROGS} \
            $${PCI_INSTALL_OPT} \
            install
    endef
"""))

GREP_INSTALL_RE = re.compile(
    r"if ! grep install (\$\(LINUX_DIR\)/\S+/Makefile) >/dev/null 2>&1"
)


def patch_linux_tool_pci_mk_in(text: str) -> str:
    """
    Point PCI_BUILD_CMDS / PCI_INSTALL_TARGET_CMDS at pci_endpoint when
    tools/pci is gone. Also accept a present tools/pci/Makefile without
    grepping for the word ``install``.
    """
    if "tools/testing/selftests/pci_endpoint" in text:
        return text
    if "define PCI_BUILD_CMDS" not in text:
        return text
    updated = re.sub(
        r"define PCI_BUILD_CMDS\n.*?\nendef\n",
        PCI_BUILD_CMDS_NEW,
        text,
        count=1,
        flags=re.DOTALL,
    )
    updated = re.sub(
        r"define PCI_INSTALL_TARGET_CMDS\n.*?\nendef\n",
        PCI_INSTALL_CMDS_NEW,
        updated,
        count=1,
        flags=re.DOTALL,
    )
    return updated


def patch_linux_tools_grep_install(text: str) -> str:
    """
    Replace ``grep install <Makefile>`` guards with ``test -f <Makefile>``.

    Newer kernel Makefiles often pull ``install`` in from lib.mk, so the
    word is absent from the fragment and the old grep false-fails.
    """
    return GREP_INSTALL_RE.sub(r"if ! test -f \1", text)


def patch_linux_tools(linux_tools_dir: Path) -> None:
    """
    Patch ``package/linux-tools/*.mk.in`` in an extracted Buildroot tree.

    PCI is relocated for kernel 6.14+; remaining tools drop the grep-install
    kernel-too-old check. Missing directory is a no-op (unit tests).
    """
    if not linux_tools_dir.is_dir():
        return
    for path in sorted(linux_tools_dir.glob("*.mk.in")):
        original = path.read_text()
        updated = original
        if path.name == "linux-tool-pci.mk.in":
            updated = patch_linux_tool_pci_mk_in(updated)
        updated = patch_linux_tools_grep_install(updated)
        if updated == original:
            continue
        path.write_text(updated)
        print(f"--> Patched linux-tools fragment {path.name}")
