#!/usr/bin/env python3
"""Tests for customizeBuildroot.py Makefile, Config.in, and custom-package edits."""

from __future__ import annotations

import os
import shutil
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


if __name__ == "__main__":
    unittest.main()
