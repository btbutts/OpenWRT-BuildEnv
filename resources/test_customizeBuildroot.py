#!/usr/bin/env python3
# pylint: disable=too-many-lines
"""Tests for customizeBuildroot Makefile, Config.in, and custom-package edits."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import customizeBuildroot as cb

sys.path.insert(0, str(Path(__file__).resolve().parent))

SAMPLE = Path(__file__).with_name("Buildroot_Sample.Makefile")


class PatchMakefileTests(unittest.TestCase):
    """patch_makefile() must locate blocks by structure, not exact text."""

    def test_default_br_path_uses_container_env_when_available(self) -> None:
        """The shared Buildroot env var should override the default container path."""
        original = os.environ.get("BUILDROOT_BUILDER_DIR")
        try:
            os.environ["BUILDROOT_BUILDER_DIR"] = "/tmp/env-buildroot/"
            self.assertEqual(cb.default_br_path(), Path("/tmp/env-buildroot"))
        finally:
            if original is None:
                os.environ.pop("BUILDROOT_BUILDER_DIR", None)
            else:
                os.environ["BUILDROOT_BUILDER_DIR"] = original

    def setUp(self) -> None:
        """Copy Buildroot_Sample.Makefile into a temp tree."""
        self.td = Path(tempfile.mkdtemp())
        self.mk = self.td / "Makefile"
        shutil.copy(SAMPLE, self.mk)

    def tearDown(self) -> None:
        """Remove the temp tree."""
        shutil.rmtree(self.td)

    def _first_rm_span(self, text: str) -> str:
        """Return the first backslash-continued rm -rf after target-finalize."""
        start = text.index(".PHONY: target-finalize")
        marker = "rm -rf $(TARGET_DIR)/usr/include"
        at = text.index(marker, start)
        line_start = text.rfind("\n", start, at) + 1
        chunk = text[line_start:]
        lines = []
        for line in chunk.splitlines(keepends=True):
            lines.append(line)
            if not line.rstrip("\n").rstrip().endswith("\\"):
                break
        return "".join(lines)

    def test_sample_strips_usr_doc_from_first_rm_and_comments_it(self) -> None:
        """The first target-finalize rm -rf loses usr/doc and comments it."""
        cb.patch_makefile(self.mk)
        text = self.mk.read_text()
        first_rm = self._first_rm_span(text)
        self.assertNotIn("$(TARGET_DIR)/usr/doc", first_rm)
        self.assertIn("$(TARGET_DIR)/usr/lib/rpm", first_rm)
        self.assertIn("#\trm -rf $(TARGET_DIR)/usr/doc\n", text)

    def test_sample_wraps_man_info_doc_purge(self) -> None:
        """The man/info/doc purge is wrapped in BR2_KEEP_MAN_PAGES_DOCS."""
        cb.patch_makefile(self.mk)
        text = self.mk.read_text()
        self.assertIn("ifneq ($(BR2_KEEP_MAN_PAGES_DOCS),y)\n", text)
        guarded = text.split("ifneq ($(BR2_KEEP_MAN_PAGES_DOCS),y)\n", 1)[1]
        body, rest = guarded.split("endif\n", 1)
        self.assertIn("usr/man", body)
        self.assertIn("usr/share/man", body)
        self.assertIn("usr/info", body)
        self.assertIn("gtk-doc", body)
        self.assertIn("rmdir $(TARGET_DIR)/usr/share", body)
        self.assertIn("ifneq ($(BR2_ENABLE_DEBUG)", rest)

    def test_first_rm_survives_extra_path_on_last_line(self) -> None:
        """Extra paths on the first rm -rf stay; only usr/doc is dropped."""
        original = self.mk.read_text()
        mutated = original.replace(
            "$(TARGET_DIR)/usr/lib/rpm $(TARGET_DIR)/usr/doc",
            "$(TARGET_DIR)/usr/lib/rpm $(TARGET_DIR)/usr/share/foo $(TARGET_DIR)/usr/doc",
            1,
        )
        self.assertNotEqual(mutated, original)
        self.mk.write_text(mutated)
        cb.patch_makefile(self.mk)
        text = self.mk.read_text()
        first_rm = self._first_rm_span(text)
        self.assertIn("$(TARGET_DIR)/usr/share/foo", first_rm)
        self.assertNotIn("$(TARGET_DIR)/usr/doc", first_rm)
        self.assertIn("#\trm -rf $(TARGET_DIR)/usr/doc\n", text)

    def test_man_wrap_survives_extra_rm_before_rmdir(self) -> None:
        """Extra rm lines between gtk-doc and rmdir stay inside the guard."""
        original = self.mk.read_text()
        mutated = original.replace(
            "\trm -rf $(TARGET_DIR)/usr/share/gtk-doc\n"
            "\trmdir $(TARGET_DIR)/usr/share 2>/dev/null || true\n",
            "\trm -rf $(TARGET_DIR)/usr/share/gtk-doc\n"
            "\trm -rf $(TARGET_DIR)/usr/share/extra-docs\n"
            "\trmdir $(TARGET_DIR)/usr/share 2>/dev/null || true\n",
            1,
        )
        self.assertNotEqual(mutated, original)
        self.mk.write_text(mutated)
        cb.patch_makefile(self.mk)
        text = self.mk.read_text()
        guarded = text.split("ifneq ($(BR2_KEEP_MAN_PAGES_DOCS),y)\n", 1)[1]
        body = guarded.split("endif\n", 1)[0]
        self.assertIn("usr/share/extra-docs", body)
        self.assertIn("gtk-doc", body)
        self.assertIn("rmdir $(TARGET_DIR)/usr/share", body)

    def test_space_indented_comment_is_normalized_to_tab(self) -> None:
        """A usr/doc comment that used spaces after # is rewritten with a tab."""
        cb.patch_makefile(self.mk)
        spaced = self.mk.read_text().replace(
            "#\trm -rf $(TARGET_DIR)/usr/doc\n",
            "#       rm -rf $(TARGET_DIR)/usr/doc\n",
            1,
        )
        self.mk.write_text(spaced)
        cb.patch_makefile(self.mk)
        text = self.mk.read_text()
        self.assertIn("#\trm -rf $(TARGET_DIR)/usr/doc\n", text)
        self.assertNotIn("#       rm -rf $(TARGET_DIR)/usr/doc\n", text)

    def test_patch_is_idempotent(self) -> None:
        """A second patch_makefile() call leaves the Makefile unchanged."""
        cb.patch_makefile(self.mk)
        once = self.mk.read_text()
        cb.patch_makefile(self.mk)
        self.assertEqual(once, self.mk.read_text())
        self.assertEqual(once.count("ifneq ($(BR2_KEEP_MAN_PAGES_DOCS),y)"), 1)
        self.assertEqual(once.count("#\trm -rf $(TARGET_DIR)/usr/doc\n"), 1)


class CustomPackageInstallTests(unittest.TestCase):
    """Custom packages stay in BR2_EXTERNAL; --customize writes custom-late.mk only."""

    def setUp(self) -> None:
        """Build a tiny Buildroot tree plus staged custom packages that must stay put."""
        self.td = Path(tempfile.mkdtemp())
        self.custom = self.td / "custom_package"
        self.br = self.td / "Buildroot-Builder"
        self.br.mkdir()
        shutil.copy(SAMPLE, self.br / "Makefile")
        (self.br / "Config.in").write_text(
            'menu "Target options"\nendmenu\n',
            encoding="utf-8",
        )
        (self.br / "package").mkdir(parents=True, exist_ok=True)
        (self.br / "package" / "Config.in").write_text(
            'menu "Target packages"\n'
            'source "package/busybox/Config.in"\n'
            "endmenu\n",
            encoding="utf-8",
        )
        for name, symbol in (
            ("groff", "GROFF"),
            ("gcc-standalone-toolchain", "GCC_STANDALONE_TOOLCHAIN"),
            ("hexedit", "HEXEDIT"),
            ("uutils-coreutils", "UUTILS_COREUTILS"),
        ):
            pkg = self.custom / name
            pkg.mkdir(parents=True)
            (pkg / "Config.in").write_text(
                f"config BR2_PACKAGE_{symbol}\n\tbool \"{name}\"\n"
            )
            (pkg / f"{name}.mk").write_text(f"# {name}.mk\n")

    def tearDown(self) -> None:
        """Remove the temp tree."""
        shutil.rmtree(self.td)

    def test_default_custom_package_dir_uses_conf_env(self) -> None:
        """BUILDROOT_CONF_DIR/custom_package is the br2-external tree."""
        original = os.environ.get("BUILDROOT_CONF_DIR")
        try:
            os.environ["BUILDROOT_CONF_DIR"] = "/tmp/conf-dir/"
            self.assertEqual(
                cb.default_custom_package_dir(),
                Path("/tmp/conf-dir/custom_package"),
            )
        finally:
            if original is None:
                os.environ.pop("BUILDROOT_CONF_DIR", None)
            else:
                os.environ["BUILDROOT_CONF_DIR"] = original

    def test_does_not_copy_packages_into_buildroot(self) -> None:
        """--customize leaves package/<name>/ alone; keep-docs and late-mk still land."""
        pkg_config_before = (self.br / "package" / "Config.in").read_text()
        cb.customize_buildroot(self.br, self.custom)
        self.assertFalse((self.br / "package" / "groff").exists())
        self.assertFalse((self.br / "package" / "uutils-coreutils").exists())
        self.assertFalse((self.br / "package" / "hexedit").exists())
        config = (self.br / "Config.in").read_text()
        self.assertIn("config BR2_KEEP_MAN_PAGES_DOCS", config)
        self.assertNotIn('source "package/groff/Config.in"', config)
        pkg_config = (self.br / "package" / "Config.in").read_text()
        self.assertEqual(pkg_config, pkg_config_before)
        self.assertNotIn('menu "Custom Packages"', pkg_config)
        late = (self.br / "package" / "custom-late.mk").read_text()
        self.assertIn("LATE_CUSTOM_PACKAGES += gcc-standalone-toolchain", late)
        self.assertIn("LATE_CUSTOM_PACKAGES += groff", late)
        self.assertIn("LATE_CUSTOM_PACKAGES += hexedit", late)
        self.assertNotIn("LATE_CUSTOM_PACKAGES += uutils-coreutils", late)
        self.assertIn("ifeq ($(BR2_PACKAGE_GCC_STANDALONE_TOOLCHAIN),y)", late)
        self.assertIn(
            "gcc-standalone-toolchain-install: "
            "$(filter-out gcc-standalone-toolchain,$(LATE_CUSTOM_PACKAGES))",
            late,
        )
        self.assertIn("include package/custom-late.mk", (self.br / "Makefile").read_text())
        self.assertEqual(
            cb.kconfig_package_symbol("gcc-standalone-toolchain"),
            "BR2_PACKAGE_GCC_STANDALONE_TOOLCHAIN",
        )
        self.assertEqual(
            cb.kconfig_package_symbol("uutils-coreutils"),
            "BR2_PACKAGE_UUTILS_COREUTILS",
        )
        self.assertIn("uutils-coreutils", cb.LATE_CUSTOM_SKIP_PACKAGES)

    def test_customize_is_idempotent(self) -> None:
        """
        Re-running customize does not duplicate keep-docs, late-mk include, or package/Config.in.
        """
        cb.customize_buildroot(self.br, self.custom)
        once_root = (self.br / "Config.in").read_text()
        once_pkg = (self.br / "package" / "Config.in").read_text()
        once_make = (self.br / "Makefile").read_text()
        once_late = (self.br / "package" / "custom-late.mk").read_text()
        cb.customize_buildroot(self.br, self.custom)
        self.assertEqual(once_root, (self.br / "Config.in").read_text())
        self.assertEqual(once_pkg, (self.br / "package" / "Config.in").read_text())
        self.assertEqual(once_make, (self.br / "Makefile").read_text())
        self.assertEqual(once_late, (self.br / "package" / "custom-late.mk").read_text())
        self.assertEqual(once_root.count("config BR2_KEEP_MAN_PAGES_DOCS"), 1)
        self.assertEqual(once_make.count("include package/custom-late.mk"), 1)


class Br2ExternalLayoutTests(unittest.TestCase):
    """The repo custom_package tree is a valid br2-external layout."""

    ROOT = Path(__file__).resolve().parent / "buildrootConf" / "custom_package"

    def test_required_files_exist(self) -> None:
        """external.desc, Config.in, and external.mk are at the tree root."""
        self.assertTrue((self.ROOT / "external.desc").is_file())
        self.assertTrue((self.ROOT / "Config.in").is_file())
        self.assertTrue((self.ROOT / "external.mk").is_file())
        desc = (self.ROOT / "external.desc").read_text()
        self.assertIn("name: OPENWRT_INSTALLER", desc)

    def test_config_in_sources_each_package(self) -> None:
        """Root Config.in sources every package Config.in via BR2_EXTERNAL path."""
        text = (self.ROOT / "Config.in").read_text()
        self.assertIn('menu "Custom Packages"', text)
        for name in (
            "gcc-standalone-toolchain",
            "groff",
            "hexedit",
            "sharutils",
            "uutils-coreutils",
        ):
            self.assertIn(
                f'source "$BR2_EXTERNAL_OPENWRT_INSTALLER_PATH/{name}/Config.in"',
                text,
            )
            self.assertTrue((self.ROOT / name / "Config.in").is_file())
            self.assertTrue((self.ROOT / name / f"{name}.mk").is_file())

    def test_external_mk_includes_package_makefiles(self) -> None:
        """external.mk includes */*.mk; late install stays in custom-late.mk."""
        text = (self.ROOT / "external.mk").read_text()
        self.assertIn(
            "include $(sort $(wildcard $(BR2_EXTERNAL_OPENWRT_INSTALLER_PATH)/*/*.mk))",
            text,
        )
        self.assertNotIn("gcc-standalone-toolchain-install:", text)
        self.assertNotIn("LATE_CUSTOM_PACKAGES", text)

    def test_uutils_conflicts_with_gnu_coreutils(self) -> None:
        """uutils Kconfig hides when GNU coreutils is enabled, and does not need SHOW_OTHERS."""
        text = (self.ROOT / "uutils-coreutils" / "Config.in").read_text()
        self.assertIn("config BR2_PACKAGE_UUTILS_COREUTILS", text)
        self.assertIn("depends on !BR2_PACKAGE_COREUTILS", text)
        self.assertNotIn("BR2_PACKAGE_BUSYBOX_SHOW_OTHERS", text)
        self.assertIn('default "0.12.0"', text)
        mk = (self.ROOT / "uutils-coreutils" / "uutils-coreutils.mk").read_text()
        self.assertIn("UUTILS_COREUTILS_CARGO_PROFILE = release", mk)
        self.assertNotIn("release-small", mk)


class PatchLinuxToolsTests(unittest.TestCase):
    """linux-tools mk.in fragments: pci_endpoint path and grep-install guards."""

    def test_pci_moves_to_pci_endpoint(self) -> None:
        """Kernel 6.14+ pci tools live under tools/testing/selftests/pci_endpoint."""
        patched = cb.patch_linux_tool_pci_mk_in(cb.PCI_BUILD_CMDS_OLD + cb.PCI_INSTALL_CMDS_OLD)
        self.assertIn("tools/testing/selftests/pci_endpoint", patched)
        self.assertIn("INSTALL_PATH=$(TARGET_DIR)/usr/bin", patched)
        self.assertNotIn("grep install", patched)
        self.assertEqual(cb.patch_linux_tool_pci_mk_in(patched), patched)

    def test_grep_install_becomes_test_f(self) -> None:
        """gpio/iio/usbtools/tmon/rtla: require the Makefile, not the word install."""
        src = (
            "\t$(Q)if ! grep install $(LINUX_DIR)/tools/iio/Makefile "
            ">/dev/null 2>&1 ; then \\\n"
        )
        out = cb.patch_linux_tools_grep_install(src)
        self.assertIn("if ! test -f $(LINUX_DIR)/tools/iio/Makefile", out)
        self.assertNotIn("grep install", out)

    def test_customize_patches_linux_tools_dir(self) -> None:
        """customize_buildroot writes the pci and iio fragment fixes."""
        td = Path(tempfile.mkdtemp())
        try:
            br = td / "br"
            custom = td / "custom"
            br.mkdir()
            (br / "Config.in").write_text("menu \"x\"\nendmenu\n")
            shutil.copy(SAMPLE, br / "Makefile")
            (br / "package").mkdir()
            (br / "package" / "Config.in").write_text(
                'menu "Target packages"\nendmenu\n'
            )
            groff = custom / "groff"
            groff.mkdir(parents=True)
            (groff / "Config.in").write_text("config BR2_PACKAGE_GROFF\n\tbool \"g\"\n")
            tools = br / "package" / "linux-tools"
            tools.mkdir()
            (tools / "linux-tool-pci.mk.in").write_text(
                cb.PCI_BUILD_CMDS_OLD + cb.PCI_INSTALL_CMDS_OLD
            )
            (tools / "linux-tool-iio.mk.in").write_text(
                "define IIO_BUILD_CMDS\n"
                "\t$(Q)if ! grep install $(LINUX_DIR)/tools/iio/Makefile "
                ">/dev/null 2>&1 ; then \\\n"
                "\t\techo too old ; \\\n"
                "\t\texit 1 ; \\\n"
                "\tfi\n"
                "endef\n"
            )
            cb.customize_buildroot(br, custom)
            pci = (tools / "linux-tool-pci.mk.in").read_text()
            iio = (tools / "linux-tool-iio.mk.in").read_text()
            self.assertIn("pci_endpoint", pci)
            self.assertIn("test -f $(LINUX_DIR)/tools/iio/Makefile", iio)
        finally:
            shutil.rmtree(td)


class PatchOpenvmtoolsTests(unittest.TestCase):
    """Stock package/openvmtools C23 patch written at --customize time."""

    def setUp(self) -> None:
        """Temporary package/openvmtools directory."""
        self.td = Path(tempfile.mkdtemp())
        self.pkg = self.td / "openvmtools"
        self.pkg.mkdir()

    def tearDown(self) -> None:
        """Remove the temp tree."""
        shutil.rmtree(self.td)

    def test_missing_dir_is_noop(self) -> None:
        """Incomplete trees and unit fixtures without openvmtools skip."""
        self.assertIsNone(cb.patch_openvmtools(self.td / "missing"))

    def test_writes_next_index_after_stock_patches(self) -> None:
        """2025.08/2026.08 trees end at 0014; this patch becomes 0015."""
        (self.pkg / "0014-CVE-2025-22247-1100-1225-VGAuth-updates.patch").write_text(
            "unrelated\n"
        )
        expected = self.pkg / "0015-c23-MXUserTryAcquireForceFail.patch"
        dest = cb.patch_openvmtools(self.pkg)
        self.assertEqual(dest, expected)
        text = expected.read_text()
        self.assertIn("-" + cb.OPENVMTOOLS_C23_OLD, text)
        self.assertIn("+" + cb.OPENVMTOOLS_C23_NEW, text)
        self.assertIn("diff --git a/lib/lock/ul.c b/lib/lock/ul.c", text)

    def test_idempotent(self) -> None:
        """A second --customize does not add another numbered file."""
        first = cb.patch_openvmtools(self.pkg)
        second = cb.patch_openvmtools(self.pkg)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        patches = list(self.pkg.glob("*.patch"))
        self.assertEqual(len(patches), 1)

    def test_skips_when_hunk_already_present(self) -> None:
        """Do not add 0015 if a later Buildroot already ships the same hunk."""
        (self.pkg / "0015-upstream-c23.patch").write_text(cb.OPENVMTOOLS_C23_PATCH)
        self.assertIsNone(cb.patch_openvmtools(self.pkg))
        self.assertEqual(len(list(self.pkg.glob("*.patch"))), 1)

    def test_customize_writes_openvmtools_patch(self) -> None:
        """customize_buildroot drops the patch into package/openvmtools."""
        br = self.td / "br"
        custom = self.td / "custom"
        br.mkdir()
        (br / "Config.in").write_text('menu "x"\nendmenu\n')
        shutil.copy(SAMPLE, br / "Makefile")
        (br / "package").mkdir()
        (br / "package" / "Config.in").write_text(
            'menu "Target packages"\nendmenu\n'
        )
        groff = custom / "groff"
        groff.mkdir(parents=True)
        (groff / "Config.in").write_text('config BR2_PACKAGE_GROFF\n\tbool "g"\n')
        ovm = br / "package" / "openvmtools"
        ovm.mkdir()
        (ovm / "0014-CVE.patch").write_text("stock\n")
        cb.customize_buildroot(br, custom)
        written = ovm / "0015-c23-MXUserTryAcquireForceFail.patch"
        self.assertTrue(written.is_file())
        self.assertIn(cb.OPENVMTOOLS_C23_NEW, written.read_text())


# 2026.08 snippets: latest kernel/headers stop at 7.1.13.
_KERNEL_HEADERS_HOST_2026_08 = """\
choice
	prompt "Kernel Headers"
	default BR2_KERNEL_HEADERS_AS_KERNEL if BR2_LINUX_KERNEL
	default BR2_KERNEL_HEADERS_7_1
	help
	  Select the kernel version to get headers from.

config BR2_KERNEL_HEADERS_AS_KERNEL
	bool "Same as kernel being built"
	depends on BR2_LINUX_KERNEL
	select BR2_KERNEL_HEADERS_LATEST if BR2_LINUX_KERNEL_LATEST_VERSION

config BR2_KERNEL_HEADERS_7_1
	bool "Linux 7.1.x kernel headers"
	select BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_1
	select BR2_KERNEL_HEADERS_LATEST

config BR2_KERNEL_HEADERS_VERSION
	bool "Manually specified Linux version"
endchoice

config BR2_KERNEL_HEADERS_LATEST
	bool

choice
	bool "Custom kernel headers series"
	default BR2_PACKAGE_HOST_LINUX_HEADERS_CUSTOM_REALLY_OLD

config BR2_PACKAGE_HOST_LINUX_HEADERS_CUSTOM_7_1
	bool "7.1.x or later"
	select BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_1

config BR2_PACKAGE_HOST_LINUX_HEADERS_CUSTOM_7_0
	bool "7.0.x"
	select BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_0

endchoice

config BR2_DEFAULT_KERNEL_HEADERS
	string
	default "7.1.13"	if BR2_KERNEL_HEADERS_7_1
	default BR2_DEFAULT_KERNEL_VERSION if BR2_KERNEL_HEADERS_VERSION
"""

_TOOLCHAIN_CONFIG_2026_08 = """\
config BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_0
	bool
	select BR2_TOOLCHAIN_HEADERS_AT_LEAST_6_19

config BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_1
	bool
	select BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_0
	select BR2_TOOLCHAIN_HEADERS_LATEST

config BR2_TOOLCHAIN_HEADERS_LATEST
	bool

config BR2_TOOLCHAIN_HEADERS_AT_LEAST
	string
	default "7.1" if BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_1
	default "7.0" if BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_0
	default "6.19" if BR2_TOOLCHAIN_HEADERS_AT_LEAST_6_19
"""

_LINUX_CONFIG_2026_08 = """\
choice
	prompt "Kernel version"

config BR2_LINUX_KERNEL_LATEST_VERSION
	bool "Latest version (7.1)"
	select BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_1 if BR2_KERNEL_HEADERS_AS_KERNEL

config BR2_LINUX_KERNEL_CUSTOM_VERSION
	bool "Custom version"

endchoice

config BR2_LINUX_KERNEL_VERSION
	string
	default "7.1.13" if BR2_LINUX_KERNEL_LATEST_VERSION
	default BR2_LINUX_KERNEL_CUSTOM_VERSION_VALUE \\
		if BR2_LINUX_KERNEL_CUSTOM_VERSION
"""


class UpdateKernelSupportTests(unittest.TestCase):
    """--update-kernel-support adds 7.2.9 as Buildroot 2026.08 latest."""

    def setUp(self) -> None:
        """Minimal 2026.08 linux/headers/toolchain Kconfig tree."""
        self.td = Path(tempfile.mkdtemp())
        self.br = self.td / "Buildroot-Builder"
        headers = self.br / "package" / "linux-headers"
        linux = self.br / "linux"
        toolchain = self.br / "toolchain"
        headers.mkdir(parents=True)
        linux.mkdir(parents=True)
        toolchain.mkdir(parents=True)
        (self.br / "Config.in").write_text('menu "x"\nendmenu\n')
        shutil.copy(SAMPLE, self.br / "Makefile")
        (self.br / "package" / "Config.in").write_text(
            'menu "Target packages"\nendmenu\n'
        )
        (headers / "Config.in.host").write_text(_KERNEL_HEADERS_HOST_2026_08)
        (toolchain / "Config.in").write_text(_TOOLCHAIN_CONFIG_2026_08)
        (linux / "Config.in").write_text(_LINUX_CONFIG_2026_08)
        (linux / "from-6.17").mkdir()
        (linux / "7.1.13").symlink_to("from-6.17")
        (headers / "7.1.13").symlink_to("../../linux/from-6.17")

    def tearDown(self) -> None:
        """Remove the temp tree."""
        shutil.rmtree(self.td)

    def _apply(self) -> None:
        """Run the kernel-support updater against the fixture tree."""
        cb.update_kernel_support(self.br)

    def test_headers_7_2_is_latest_and_7_1_is_kept(self) -> None:
        """7.2.x headers take LATEST; 7.1.x remains selectable."""
        self._apply()
        text = (self.br / "package" / "linux-headers" / "Config.in.host").read_text()
        self.assertIn('bool "Linux 7.2.x kernel headers"', text)
        self.assertIn("select BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_2", text)
        self.assertRegex(
            text,
            r"config BR2_KERNEL_HEADERS_7_2\n"
            r'\tbool "Linux 7.2.x kernel headers"\n'
            r"\tselect BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_2\n"
            r"\tselect BR2_KERNEL_HEADERS_LATEST\n",
        )
        self.assertNotRegex(
            text,
            r"config BR2_KERNEL_HEADERS_7_1\n"
            r'\tbool "Linux 7.1.x kernel headers"\n'
            r"\tselect BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_1\n"
            r"\tselect BR2_KERNEL_HEADERS_LATEST\n",
        )
        self.assertIn("\tdefault BR2_KERNEL_HEADERS_7_2\n", text)
        self.assertIn('\tdefault "7.2.9"\tif BR2_KERNEL_HEADERS_7_2\n', text)
        self.assertIn('bool "7.2.x or later"', text)
        self.assertIn('bool "7.1.x"', text)
        self.assertNotIn('bool "7.1.x or later"', text)

    def test_toolchain_at_least_7_2_is_latest(self) -> None:
        """AT_LEAST_7_2 selects 7_1 and LATEST; the string default prefers 7.2."""
        self._apply()
        text = (self.br / "toolchain" / "Config.in").read_text()
        self.assertRegex(
            text,
            r"config BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_2\n"
            r"\tbool\n"
            r"\tselect BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_1\n"
            r"\tselect BR2_TOOLCHAIN_HEADERS_LATEST\n",
        )
        self.assertNotRegex(
            text,
            r"config BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_1\n"
            r"\tbool\n"
            r"\tselect BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_0\n"
            r"\tselect BR2_TOOLCHAIN_HEADERS_LATEST\n",
        )
        self.assertRegex(
            text,
            r"config BR2_TOOLCHAIN_HEADERS_AT_LEAST\n"
            r"\tstring\n"
            r'\tdefault "7.2" if BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_2\n'
            r'\tdefault "7.1" if BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_1\n',
        )

    def test_latest_kernel_version_is_7_2_9(self) -> None:
        """LATEST_VERSION prompt, AT_LEAST select, and VERSION default become 7.2.9."""
        self._apply()
        text = (self.br / "linux" / "Config.in").read_text()
        self.assertIn('bool "Latest version (7.2)"', text)
        self.assertIn(
            "select BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_2 "
            "if BR2_KERNEL_HEADERS_AS_KERNEL",
            text,
        )
        self.assertNotIn('bool "Latest version (7.1)"', text)
        self.assertNotIn(
            "select BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_1 "
            "if BR2_KERNEL_HEADERS_AS_KERNEL",
            text,
        )
        self.assertIn('default "7.2.9" if BR2_LINUX_KERNEL_LATEST_VERSION', text)
        self.assertNotIn('default "7.1.13" if BR2_LINUX_KERNEL_LATEST_VERSION', text)

    def test_version_patch_dirs_follow_7_1_13(self) -> None:
        """7.2.9 reuses the same from-6.17 patch dir as 7.1.13."""
        self._apply()
        linux_link = self.br / "linux" / "7.2.9"
        headers_link = self.br / "package" / "linux-headers" / "7.2.9"
        self.assertTrue(linux_link.is_symlink())
        self.assertEqual(linux_link.readlink().as_posix(), "from-6.17")
        self.assertTrue(headers_link.is_symlink())
        self.assertEqual(
            headers_link.readlink().as_posix(),
            "../../linux/from-6.17",
        )

    def test_idempotent(self) -> None:
        """A second --update-kernel-support leaves the tree unchanged."""
        self._apply()
        first_headers = (
            self.br / "package" / "linux-headers" / "Config.in.host"
        ).read_text()
        first_toolchain = (self.br / "toolchain" / "Config.in").read_text()
        first_linux = (self.br / "linux" / "Config.in").read_text()
        self._apply()
        self.assertEqual(
            (self.br / "package" / "linux-headers" / "Config.in.host").read_text(),
            first_headers,
        )
        self.assertEqual(
            (self.br / "toolchain" / "Config.in").read_text(),
            first_toolchain,
        )
        self.assertEqual((self.br / "linux" / "Config.in").read_text(), first_linux)
        self.assertEqual(first_headers.count("config BR2_KERNEL_HEADERS_7_2"), 1)
        self.assertEqual(
            first_toolchain.count("config BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_2"),
            1,
        )

    def test_customize_does_not_add_7_2(self) -> None:
        """--customize must not bump kernel/header latest to 7.2."""
        custom = self.td / "custom"
        groff = custom / "groff"
        groff.mkdir(parents=True)
        (groff / "Config.in").write_text('config BR2_PACKAGE_GROFF\n\tbool "g"\n')
        cb.customize_buildroot(self.br, custom)
        headers = (self.br / "package" / "linux-headers" / "Config.in.host").read_text()
        linux = (self.br / "linux" / "Config.in").read_text()
        toolchain = (self.br / "toolchain" / "Config.in").read_text()
        self.assertNotIn("BR2_KERNEL_HEADERS_7_2", headers)
        self.assertNotIn("BR2_TOOLCHAIN_HEADERS_AT_LEAST_7_2", toolchain)
        self.assertIn('default "7.1.13" if BR2_LINUX_KERNEL_LATEST_VERSION', linux)
        self.assertIn("config BR2_KEEP_MAN_PAGES_DOCS", (self.br / "Config.in").read_text())
        self.assertFalse((self.br / "linux" / "from-6.17" / "get-hash.mk").exists())
        self.assertNotIn("include linux/from-6.17/get-hash.mk", (self.br / "Makefile").read_text())

    def test_cli_update_kernel_support_skips_customize(self) -> None:
        """python customizeBuildroot/main.py --update-kernel-support is kernel-only."""
        rc = cb.main(
            ["--br-path", str(self.br), "--update-kernel-support"]
        )
        self.assertEqual(rc, 0)
        self.assertIn(
            "config BR2_KERNEL_HEADERS_7_2",
            (self.br / "package" / "linux-headers" / "Config.in.host").read_text(),
        )
        self.assertNotIn(
            "config BR2_KEEP_MAN_PAGES_DOCS",
            (self.br / "Config.in").read_text(),
        )
        self.assertFalse((self.br / "package" / "custom-late.mk").exists())

    def test_getbuildroot_flag_is_exclusive(self) -> None:
        """getBuildroot.sh documents --update-kernel-support as a lone argument."""
        script = Path(__file__).with_name("getBuildroot.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("--update-kernel-support)", script)
        self.assertIn("must be used by itself", script)
        self.assertIn("--update-kernel-support", script)
        self.assertIn("customizeBuildroot/main.py", script)
        self.assertIn('PYTHONPATH="${BUILDER_ROOT_DIR%/}', script)

    def test_installs_get_hash_mk(self) -> None:
        """--update-kernel-support drops get-hash.mk next to linux.hash."""
        self._apply()
        dest = self.br / "linux" / "from-6.17" / "get-hash.mk"
        self.assertTrue(dest.is_file())
        text = dest.read_text(encoding="utf-8")
        self.assertIn("LINUX_HASH_FILE := $(dir $(lastword $(MAKEFILE_LIST)))linux.hash", text)
        self.assertIn("LINUX_PRE_DOWNLOAD_HOOKS += LINUX_GET_HASH", text)
        self.assertIn(
            "LINUX_HEADERS_PRE_DOWNLOAD_HOOKS += LINUX_HEADERS_GET_HASH",
            text,
        )
        self.assertIn(
            "https://cdn.kernel.org/pub/linux/kernel/v$$major.x/sha256sums.asc",
            text,
        )
        self.assertIn(
            "# From https://www.kernel.org/pub/linux/kernel/v$$major.x/sha256sums.asc",
            text,
        )
        makefile = (self.br / "Makefile").read_text(encoding="utf-8")
        self.assertIn("include linux/from-6.17/get-hash.mk", makefile)
        self.assertEqual(makefile.count("include linux/from-6.17/get-hash.mk"), 1)
        self.assertLess(
            makefile.index("include linux/from-6.17/get-hash.mk"),
            makefile.index("include $(sort $(wildcard package/*/*.mk))"),
        )
        in_define = False
        for line in text.splitlines():
            if line.startswith("define "):
                in_define = True
                continue
            if line.startswith("endef"):
                in_define = False
                continue
            if in_define and line.strip():
                self.assertTrue(line.startswith("\t"), line)
        self._apply()
        self.assertEqual(
            (self.br / "Makefile").read_text(encoding="utf-8").count(
                "include linux/from-6.17/get-hash.mk"
            ),
            1,
        )
        self.assertEqual(dest.read_text(encoding="utf-8"), text)

    def test_get_hash_awk_appends_under_matching_series_section(self) -> None:
        """New sha256 lands under the v7.x comment, above v6.x and licenses."""
        hash_file = self.td / "linux.hash"
        hash_file.write_text(
            "# From https://www.kernel.org/pub/linux/kernel/v7.x/sha256sums.asc\n"
            "sha256  614d95fafdcb5cce2b6620e7edc6afbb606bffd4655405586815d84687841ad7"
            "  linux-7.1.13.tar.xz\n"
            "\n"
            "# From https://www.kernel.org/pub/linux/kernel/v6.x/sha256sums.asc\n"
            "sha256  ae826f33111fea6f1d279dde7299d7463c8dfd204aeb75a8fb5432bc60a28191"
            "  linux-6.18.49.tar.xz\n"
            "\n"
            "# Licenses hashes\n"
            "sha256  fb5a425bd3b3cd6071a3a9aff9909a859e7c1158d54d32e07658398cd67eb6a0"
            "  COPYING\n",
            encoding="utf-8",
        )
        section = (
            "# From https://www.kernel.org/pub/linux/kernel/v7.x/sha256sums.asc"
        )
        line = (
            "sha256  b4c5dfbe51a364a6c7f03869200f88c8e1f77403539005f14b7fc6bc91b8d8ba"
            "  linux-7.2.9.tar.xz"
        )
        out = self.td / "linux.hash.out"
        awk = r"""
$0 == section { print; insec = 1; next }
insec && (/^$/ || /^# /) { print line; print; inserted = 1; insec = 0; next }
!inserted && $0 == "# Licenses hashes" {
    print section; print line; print ""; inserted = 1
}
{ print }
END {
    if (insec && !inserted) print line
    if (!inserted) { print ""; print section; print line }
}
"""
        with out.open("w", encoding="utf-8") as stdout:
            subprocess.run(
                [
                    "awk",
                    "-v",
                    f"section={section}",
                    "-v",
                    f"line={line}",
                    awk,
                    str(hash_file),
                ],
                check=True,
                stdout=stdout,
            )
        text = out.read_text(encoding="utf-8")
        v7 = text.index(section)
        new = text.index("linux-7.2.9.tar.xz")
        v6 = text.index("v6.x/sha256sums.asc")
        lic = text.index("# Licenses hashes")
        self.assertLess(v7, new)
        self.assertLess(new, v6)
        self.assertLess(v6, lic)
        self.assertIn("linux-7.1.13.tar.xz", text)
        self.assertIn("linux-6.18.49.tar.xz", text)
        self.assertIn("COPYING", text)


_SYSTEMD_CONFIG_2026_08 = """\
menuconfig BR2_PACKAGE_SYSTEMD
	bool "systemd"

if BR2_PACKAGE_SYSTEMD

config BR2_PACKAGE_PROVIDES_LIBUDEV
	default "systemd"

endif
"""

_SYSTEMD_MK_2026_08 = """\
################################################################################
#
# systemd
#
################################################################################

SYSTEMD_VERSION = 258.7
SYSTEMD_SITE = $(call github,systemd,systemd,v$(SYSTEMD_VERSION))

SYSTEMD_CONF_OPTS += \\
	-Dsysvinit-path= \\
	-Dsysvrcnd-path=

HOST_SYSTEMD_CONF_OPTS = \\
	-Dsysvinit-path='' \\
	-Dlibidn=disabled \\
	-Dlibiptc=disabled

$(eval $(meson-package))
$(eval $(host-meson-package))
"""

_LINUX_PAM_CONFIG_2026_08 = """\
config BR2_PACKAGE_LINUX_PAM
	bool "linux-pam"

if BR2_PACKAGE_LINUX_PAM

config BR2_PACKAGE_LINUX_PAM_LASTLOG
	bool "pam_lastlog.so"

endif
"""

_LINUX_PAM_MK_2026_08 = """\
################################################################################
#
# linux-pam
#
################################################################################

LINUX_PAM_VERSION = 1.7.2
LINUX_PAM_SOURCE = Linux-PAM-$(LINUX_PAM_VERSION).tar.xz
LINUX_PAM_SITE = https://github.com/linux-pam/linux-pam/releases/download/v$(LINUX_PAM_VERSION)

$(eval $(meson-package))
"""


class PackageVersionOverrideTests(unittest.TestCase):
    """--customize adds optional systemd and linux-pam version overrides."""

    def setUp(self) -> None:
        """Minimal 2026.08 systemd and linux-pam package files."""
        self.td = Path(tempfile.mkdtemp())
        self.br = self.td / "Buildroot-Builder"
        systemd = self.br / "package" / "systemd"
        pam = self.br / "package" / "linux-pam"
        systemd.mkdir(parents=True)
        pam.mkdir(parents=True)
        (self.br / "Config.in").write_text('menu "x"\nendmenu\n')
        shutil.copy(SAMPLE, self.br / "Makefile")
        (self.br / "package" / "Config.in").write_text(
            'menu "Target packages"\nendmenu\n'
        )
        (systemd / "Config.in").write_text(_SYSTEMD_CONFIG_2026_08)
        (systemd / "systemd.mk").write_text(_SYSTEMD_MK_2026_08)
        (pam / "Config.in").write_text(_LINUX_PAM_CONFIG_2026_08)
        (pam / "linux-pam.mk").write_text(_LINUX_PAM_MK_2026_08)
        self.custom = self.td / "custom"
        groff = self.custom / "groff"
        groff.mkdir(parents=True)
        (groff / "Config.in").write_text('config BR2_PACKAGE_GROFF\n\tbool "g"\n')

    def tearDown(self) -> None:
        """Remove the temp tree."""
        shutil.rmtree(self.td)

    def _apply(self) -> None:
        """Run --customize against the fixture tree."""
        cb.customize_buildroot(self.br, self.custom)

    def test_systemd_override_is_empty_by_default(self) -> None:
        """Kconfig string exists; packaged SYSTEMD_VERSION stays 258.7."""
        self._apply()
        cfg = (self.br / "package" / "systemd" / "Config.in").read_text()
        mk = (self.br / "package" / "systemd" / "systemd.mk").read_text()
        self.assertIn("config BR2_PACKAGE_SYSTEMD_VERSION_OVERRIDE", cfg)
        self.assertIn('\tdefault ""', cfg)
        self.assertIn("SYSTEMD_VERSION = 258.7", mk)
        self.assertIn("SYSTEMD_VERSION_STOCK := $(SYSTEMD_VERSION)", mk)
        self.assertIn(
            "SYSTEMD_VERSION = $(call qstrip,"
            "$(BR2_PACKAGE_SYSTEMD_VERSION_OVERRIDE))",
            mk,
        )
        self.assertNotIn("BR_NO_CHECK_HASH_FOR", mk)
        self.assertIn("define SYSTEMD_FETCH_HASH", mk)
        self.assertIn("SYSTEMD_PRE_DOWNLOAD_HOOKS += SYSTEMD_FETCH_HASH", mk)
        self.assertIn("HOST_SYSTEMD_PRE_DOWNLOAD_HOOKS += SYSTEMD_FETCH_HASH", mk)
        self.assertIn(
            "SYSTEMD_HASH_FILE := $(dir $(lastword $(MAKEFILE_LIST)))systemd.hash",
            mk,
        )
        self.assertIn('$$1 == "sha256" && $$NF == f', mk)
        self.assertIn("$(SYSTEMD_SITE)/$(SYSTEMD_SOURCE)", mk)
        override_if = mk.index(
            "ifneq ($(call qstrip,$(BR2_PACKAGE_SYSTEMD_VERSION_OVERRIDE)),)"
        )
        fetch_hook = mk.index("SYSTEMD_PRE_DOWNLOAD_HOOKS += SYSTEMD_FETCH_HASH")
        meson_eval = mk.index("$(eval $(meson-package))")
        self.assertLess(override_if, fetch_hook)
        self.assertLess(fetch_hook, meson_eval)
        self.assertIn("-Dsysvinit-path=", mk)
        self.assertIn("-Dlibidn=disabled", mk)
        stock = mk.index("SYSTEMD_VERSION = 258.7")
        override = mk.index("SYSTEMD_VERSION = $(call qstrip")
        self.assertLess(stock, override)

    def test_systemd_override_strips_removed_meson_options(self) -> None:
        """A non-stock version drops SysV/libidn/libiptc meson -D flags."""
        self._apply()
        mk = (self.br / "package" / "systemd" / "systemd.mk").read_text()
        self.assertIn("ifneq ($(SYSTEMD_VERSION),$(SYSTEMD_VERSION_STOCK))", mk)
        self.assertIn("-Dsysvinit-path= -Dsysvrcnd-path=", mk)
        self.assertIn("-Dlibidn=enabled -Dlibidn=disabled", mk)
        self.assertIn("-Dlibiptc=enabled -Dlibiptc=disabled", mk)

    def test_linux_pam_override_is_empty_by_default(self) -> None:
        """Kconfig string exists; packaged LINUX_PAM_VERSION stays 1.7.2."""
        self._apply()
        cfg = (self.br / "package" / "linux-pam" / "Config.in").read_text()
        mk = (self.br / "package" / "linux-pam" / "linux-pam.mk").read_text()
        self.assertIn("config BR2_PACKAGE_LINUX_PAM_VERSION_OVERRIDE", cfg)
        self.assertIn('\tdefault ""', cfg)
        self.assertIn("LINUX_PAM_VERSION = 1.7.2", mk)
        self.assertIn("LINUX_PAM_VERSION_STOCK := $(LINUX_PAM_VERSION)", mk)
        self.assertIn(
            "LINUX_PAM_VERSION = $(call qstrip,"
            "$(BR2_PACKAGE_LINUX_PAM_VERSION_OVERRIDE))",
            mk,
        )
        self.assertNotIn("BR_NO_CHECK_HASH_FOR", mk)
        self.assertIn("define LINUX_PAM_FETCH_HASH", mk)
        self.assertIn("LINUX_PAM_PRE_DOWNLOAD_HOOKS += LINUX_PAM_FETCH_HASH", mk)
        self.assertIn(
            "LINUX_PAM_HASH_FILE := $(dir $(lastword $(MAKEFILE_LIST)))"
            "linux-pam.hash",
            mk,
        )
        self.assertIn("$(LINUX_PAM_SITE)/$(LINUX_PAM_SOURCE)", mk)
        override_if = mk.index(
            "ifneq ($(call qstrip,$(BR2_PACKAGE_LINUX_PAM_VERSION_OVERRIDE)),)"
        )
        fetch_hook = mk.index("LINUX_PAM_PRE_DOWNLOAD_HOOKS += LINUX_PAM_FETCH_HASH")
        meson_eval = mk.index("$(eval $(meson-package))")
        self.assertLess(override_if, fetch_hook)
        self.assertLess(fetch_hook, meson_eval)
        self.assertIn(
            "LINUX_PAM_SOURCE = Linux-PAM-$(LINUX_PAM_VERSION).tar.xz",
            mk,
        )

    def test_idempotent(self) -> None:
        """A second --customize does not duplicate the override blocks."""
        self._apply()
        first_systemd_cfg = (
            self.br / "package" / "systemd" / "Config.in"
        ).read_text()
        first_systemd_mk = (
            self.br / "package" / "systemd" / "systemd.mk"
        ).read_text()
        first_pam_cfg = (
            self.br / "package" / "linux-pam" / "Config.in"
        ).read_text()
        first_pam_mk = (self.br / "package" / "linux-pam" / "linux-pam.mk").read_text()
        self._apply()
        self.assertEqual(
            (self.br / "package" / "systemd" / "Config.in").read_text(),
            first_systemd_cfg,
        )
        self.assertEqual(
            (self.br / "package" / "systemd" / "systemd.mk").read_text(),
            first_systemd_mk,
        )
        self.assertEqual(
            (self.br / "package" / "linux-pam" / "Config.in").read_text(),
            first_pam_cfg,
        )
        self.assertEqual(
            (self.br / "package" / "linux-pam" / "linux-pam.mk").read_text(),
            first_pam_mk,
        )
        self.assertEqual(
            first_systemd_cfg.count("config BR2_PACKAGE_SYSTEMD_VERSION_OVERRIDE"),
            1,
        )
        self.assertEqual(first_systemd_mk.count("SYSTEMD_VERSION_STOCK :="), 1)
        self.assertEqual(
            first_pam_cfg.count("config BR2_PACKAGE_LINUX_PAM_VERSION_OVERRIDE"),
            1,
        )
        self.assertEqual(first_pam_mk.count("LINUX_PAM_VERSION_STOCK :="), 1)

    def test_missing_package_dirs_are_noop(self) -> None:
        """Incomplete trees without systemd/linux-pam skip the override patch."""
        br = self.td / "bare"
        br.mkdir()
        (br / "Config.in").write_text('menu "x"\nendmenu\n')
        shutil.copy(SAMPLE, br / "Makefile")
        (br / "package").mkdir()
        (br / "package" / "Config.in").write_text(
            'menu "Target packages"\nendmenu\n'
        )
        cb.patch_package_version_overrides(br)
        self.assertFalse((br / "package" / "systemd").exists())
        self.assertFalse((br / "package" / "linux-pam").exists())

    def test_update_kernel_support_does_not_add_overrides(self) -> None:
        """--update-kernel-support must not patch systemd or linux-pam."""
        names = cb.update_kernel_support.__code__.co_names
        self.assertNotIn("patch_package_version_overrides", names)
        self.assertNotIn("patch_systemd_config_in", names)
        self.assertNotIn("patch_systemd_mk", names)
        self.assertNotIn("patch_linux_pam_config_in", names)
        self.assertNotIn("patch_linux_pam_mk", names)
        self.assertNotIn("customize_buildroot", names)

    def test_replaces_legacy_hash_skip_with_fetch_hash(self) -> None:
        """Re-running --customize upgrades BR_NO_CHECK_HASH_FOR to FETCH_HASH."""
        systemd_mk = self.br / "package" / "systemd" / "systemd.mk"
        pam_mk = self.br / "package" / "linux-pam" / "linux-pam.mk"
        systemd_mk.write_text(
            _SYSTEMD_MK_2026_08.replace(
                "$(eval $(meson-package))\n",
                "SYSTEMD_VERSION_STOCK := $(SYSTEMD_VERSION)\n"
                "ifneq ($(SYSTEMD_VERSION),$(SYSTEMD_VERSION_STOCK))\n"
                "BR_NO_CHECK_HASH_FOR += systemd-$(SYSTEMD_VERSION).tar.gz\n"
                "endif\n"
                "$(eval $(meson-package))\n",
            )
        )
        pam_mk.write_text(
            _LINUX_PAM_MK_2026_08.replace(
                "$(eval $(meson-package))\n",
                "LINUX_PAM_VERSION_STOCK := $(LINUX_PAM_VERSION)\n"
                "ifneq ($(LINUX_PAM_VERSION),$(LINUX_PAM_VERSION_STOCK))\n"
                "BR_NO_CHECK_HASH_FOR += $(LINUX_PAM_SOURCE)\n"
                "endif\n"
                "$(eval $(meson-package))\n",
            )
        )
        self._apply()
        systemd_text = systemd_mk.read_text()
        pam_text = pam_mk.read_text()
        self.assertNotIn("BR_NO_CHECK_HASH_FOR", systemd_text)
        self.assertNotIn("BR_NO_CHECK_HASH_FOR", pam_text)
        self.assertIn("SYSTEMD_PRE_DOWNLOAD_HOOKS += SYSTEMD_FETCH_HASH", systemd_text)
        self.assertIn(
            "LINUX_PAM_PRE_DOWNLOAD_HOOKS += LINUX_PAM_FETCH_HASH",
            pam_text,
        )
        self.assertEqual(systemd_text.count("define SYSTEMD_FETCH_HASH"), 1)
        self.assertEqual(pam_text.count("define LINUX_PAM_FETCH_HASH"), 1)

    def test_setup_config_selects_override_versions(self) -> None:
        """The installer fragment requests systemd 262 and linux-pam 1.7.3."""
        setup = (
            Path(__file__).resolve().parent
            / "buildrootConf"
            / "setup.config"
        ).read_text(encoding="utf-8")
        self.assertIn('BR2_PACKAGE_SYSTEMD_VERSION_OVERRIDE="262"', setup)
        self.assertIn('BR2_PACKAGE_LINUX_PAM_VERSION_OVERRIDE="1.7.3"', setup)


if __name__ == "__main__":
    unittest.main()
