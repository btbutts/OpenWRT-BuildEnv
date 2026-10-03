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
    """Staged custom packages are copied and sourced under Custom Packages."""

    def setUp(self) -> None:
        """Build a tiny Buildroot tree with two staged custom packages."""
        self.td = Path(tempfile.mkdtemp())
        self.custom = self.td / "custom_package"
        self.br = self.td / "Buildroot-Builder"
        self.br.mkdir()
        shutil.copy(SAMPLE, self.br / "Makefile")
        (self.br / "Config.in").write_text(
            "menu \"Target options\"\nendmenu\n",
            encoding="utf-8",
        )
        (self.br / "package").mkdir(parents=True, exist_ok=True)
        (self.br / "package" / "Config.in").write_text(
            'menu "Target packages"\n'
            'source "package/busybox/Config.in"\n'
            "endmenu\n",
            encoding="utf-8",
        )
        groff = self.custom / "groff"
        groff.mkdir(parents=True)
        (groff / "Config.in").write_text("config BR2_PACKAGE_GROFF\n\tbool \"groff\"\n")
        (groff / "groff.mk").write_text("# groff.mk\n")
        other = self.custom / "gcc-standalone-toolchain"
        other.mkdir()
        (other / "Config.in").write_text(
            "config BR2_PACKAGE_GCC_STANDALONE_TOOLCHAIN\n\tbool \"gcc-standalone-toolchain\"\n"
        )
        (other / "gcc-standalone-toolchain.mk").write_text("# gcc-standalone-toolchain.mk\n")
        hexedit = self.custom / "hexedit"
        hexedit.mkdir()
        (hexedit / "Config.in").write_text("config BR2_PACKAGE_HEXEDIT\n\tbool \"hexedit\"\n")
        (hexedit / "hexedit.mk").write_text("# hexedit.mk\n")
        sharutils = self.custom / "sharutils"
        sharutils.mkdir()
        (sharutils / "Config.in").write_text(
            "config BR2_PACKAGE_SHARUTILS\n\tbool \"sharutils\"\n"
        )
        (sharutils / "sharutils.mk").write_text("# sharutils.mk\n")

    def tearDown(self) -> None:
        """Remove the temp tree."""
        shutil.rmtree(self.td)

    def test_default_custom_package_dir_uses_conf_env(self) -> None:
        """BUILDROOT_CONF_DIR/custom_package is the staged package tree."""
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

    def test_install_copies_and_sources_each_package(self) -> None:
        """Packages land under package/<name>/ and in Target packages → Custom Packages."""
        cb.customize_buildroot(self.br, self.custom)
        groff_dest = self.br / "package" / "groff"
        gcc_dest = self.br / "package" / "gcc-standalone-toolchain"
        hexedit_dest = self.br / "package" / "hexedit"
        sharutils_dest = self.br / "package" / "sharutils"
        self.assertTrue((groff_dest / "Config.in").is_file())
        self.assertTrue((groff_dest / "groff.mk").is_file())
        self.assertTrue((gcc_dest / "Config.in").is_file())
        self.assertTrue((gcc_dest / "gcc-standalone-toolchain.mk").is_file())
        self.assertTrue((hexedit_dest / "Config.in").is_file())
        self.assertTrue((hexedit_dest / "hexedit.mk").is_file())
        self.assertTrue((sharutils_dest / "Config.in").is_file())
        self.assertTrue((sharutils_dest / "sharutils.mk").is_file())
        self.assertEqual((groff_dest / "groff.mk").read_text(), "# groff.mk\n")
        config = (self.br / "Config.in").read_text()
        self.assertIn("config BR2_KEEP_MAN_PAGES_DOCS", config)
        self.assertNotIn('source "package/gcc-standalone-toolchain/Config.in"', config)
        self.assertNotIn('source "package/groff/Config.in"', config)
        self.assertNotIn('source "package/hexedit/Config.in"', config)
        self.assertNotIn('source "package/sharutils/Config.in"', config)
        pkg_config = (self.br / "package" / "Config.in").read_text()
        self.assertIn('menu "Custom Packages"', pkg_config)
        self.assertIn('\tsource "package/gcc-standalone-toolchain/Config.in"', pkg_config)
        self.assertIn('\tsource "package/groff/Config.in"', pkg_config)
        self.assertIn('\tsource "package/hexedit/Config.in"', pkg_config)
        self.assertIn('\tsource "package/sharutils/Config.in"', pkg_config)
        gcc_at = pkg_config.index('source "package/gcc-standalone-toolchain/Config.in"')
        groff_at = pkg_config.index('source "package/groff/Config.in"')
        hexedit_at = pkg_config.index('source "package/hexedit/Config.in"')
        sharutils_at = pkg_config.index('source "package/sharutils/Config.in"')
        self.assertLess(gcc_at, groff_at)
        self.assertLess(groff_at, hexedit_at)
        self.assertLess(hexedit_at, sharutils_at)
        custom_menu = pkg_config.index('menu "Custom Packages"')
        custom_end = pkg_config.index("endmenu", custom_menu)
        target_end = pkg_config.rindex("endmenu")
        self.assertLess(custom_end, target_end)
        late = (self.br / "package" / "custom-late.mk").read_text()
        self.assertIn("LATE_CUSTOM_PACKAGES += gcc-standalone-toolchain", late)
        self.assertIn("LATE_CUSTOM_PACKAGES += groff", late)
        self.assertIn("LATE_CUSTOM_PACKAGES += hexedit", late)
        self.assertIn("LATE_CUSTOM_PACKAGES += sharutils", late)
        self.assertIn("ifeq ($(BR2_PACKAGE_GCC_STANDALONE_TOOLCHAIN),y)", late)
        self.assertIn("ifeq ($(BR2_PACKAGE_HEXEDIT),y)", late)
        self.assertIn("ifeq ($(BR2_PACKAGE_SHARUTILS),y)", late)
        self.assertIn("$(eval $(p)-install:", late)
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

    def test_strips_stale_root_config_sources(self) -> None:
        """Top-level Config.in source lines from older customize runs are removed."""
        (self.br / "Config.in").write_text(
            'menu "Target options"\n'
            'source "package/groff/Config.in"\n'
            "endmenu\n",
            encoding="utf-8",
        )
        cb.customize_buildroot(self.br, self.custom)
        root = (self.br / "Config.in").read_text()
        self.assertNotIn('source "package/groff/Config.in"', root)
        self.assertIn("config BR2_KEEP_MAN_PAGES_DOCS", root)

    def test_install_is_idempotent(self) -> None:
        """Re-running customize does not duplicate the Custom Packages menu."""
        cb.customize_buildroot(self.br, self.custom)
        once = (self.br / "package" / "Config.in").read_text()
        cb.customize_buildroot(self.br, self.custom)
        self.assertEqual(once, (self.br / "package" / "Config.in").read_text())
        self.assertEqual(once.count('menu "Custom Packages"'), 1)
        self.assertEqual(once.count('source "package/groff/Config.in"'), 1)


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


if __name__ == "__main__":
    unittest.main()
