#!/usr/bin/env python3
# pylint: disable=too-many-lines
"""Tests for customizeBuildroot Makefile, Config.in, and custom-package edits."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import unittest
from collections.abc import Iterable, Iterator
from contextlib import contextmanager, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Self

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
        self.assertIn("LATE_CUSTOM_PACKAGES_LIBS += gcc-standalone-toolchain", late)
        self.assertNotIn("LATE_CUSTOM_PACKAGES += gcc-standalone-toolchain", late)
        self.assertIn("LATE_CUSTOM_PACKAGES += groff", late)
        self.assertIn("LATE_CUSTOM_PACKAGES += hexedit", late)
        self.assertNotIn("LATE_CUSTOM_PACKAGES += uutils-coreutils", late)
        self.assertIn("ifeq ($(BR2_PACKAGE_GCC_STANDALONE_TOOLCHAIN),y)", late)
        self.assertLess(
            late.index("LATE_CUSTOM_PACKAGES_LIBS :="),
            late.index("LATE_CUSTOM_PACKAGES :="),
        )
        self.assertIn(
            "$(eval $(p)-install: $(LATE_CUSTOM_PACKAGES_LIBS))",
            late,
        )
        self.assertNotIn("gcc-standalone-toolchain-install:", late)
        makefile = (self.br / "Makefile").read_text()
        self.assertIn("include package/custom-late.mk", makefile)
        self.assertIn("include package/fetch-hash.mk", makefile)
        self.assertTrue((self.br / "package" / "fetch-hash.mk").is_file())
        self.assertTrue((self.br / "package" / "fetch_hash_helper.py").is_file())
        self.assertEqual(
            cb.kconfig_package_symbol("gcc-standalone-toolchain"),
            "BR2_PACKAGE_GCC_STANDALONE_TOOLCHAIN",
        )
        self.assertEqual(
            cb.kconfig_package_symbol("uutils-coreutils"),
            "BR2_PACKAGE_UUTILS_COREUTILS",
        )
        self.assertEqual(
            cb.kconfig_package_symbol("sudo-rs"),
            "BR2_PACKAGE_SUDO_RS",
        )
        self.assertEqual(
            cb.kconfig_package_symbol("fdfind"),
            "BR2_PACKAGE_FDFIND",
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
        self.assertEqual(once_make.count("include package/fetch-hash.mk"), 1)


class Br2ExternalLayoutTests(unittest.TestCase):
    """The repo custom_package tree is a valid br2-external layout."""

    ROOT = Path(__file__).resolve().parent / "buildrootConf" / "custom_package"

    def test_required_files_exist(self) -> None:
        """external.desc, Config.in, and external.mk are at the tree root."""
        self.assertTrue((self.ROOT / "external.desc").is_file())
        self.assertTrue((self.ROOT / "Config.in").is_file())
        self.assertTrue((self.ROOT / "external.mk").is_file())
        desc = (self.ROOT / "external.desc").read_text()
        self.assertIn("name: OPENWRT_INSTALLER_CUSTOM_PACKAGE", desc)

    def test_config_in_sources_each_package(self) -> None:
        """Root Config.in sources every package Config.in via BR2_EXTERNAL path."""
        text = (self.ROOT / "Config.in").read_text()
        self.assertIn('menu "Custom Packages"', text)
        for name in (
            "brush",
            "dotnet10",
            "fdfind",
            "gcc-standalone-toolchain",
            "groff",
            "hexedit",
            "jaq",
            "pwsh7",
            "python-uv",
            "sharutils",
            "sudo-rs",
            "uutils-coreutils",
        ):
            self.assertIn(
                f'source "$BR2_EXTERNAL_OPENWRT_INSTALLER_CUSTOM_PACKAGE_PATH/{name}/Config.in"',
                text,
            )
            self.assertTrue((self.ROOT / name / "Config.in").is_file())
            self.assertTrue((self.ROOT / name / f"{name}.mk").is_file())

    def test_external_mk_includes_package_makefiles(self) -> None:
        """external.mk includes */*.mk; late install stays in custom-late.mk."""
        text = (self.ROOT / "external.mk").read_text()
        self.assertIn(
            "include $(sort $(wildcard "
            "$(BR2_EXTERNAL_OPENWRT_INSTALLER_CUSTOM_PACKAGE_PATH)/*/*.mk))",
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
        self.assertIn(
            "config BR2_PACKAGE_UUTILS_COREUTILS_INDIVIDUAL_BINARIES", text
        )
        self.assertNotIn("select BR2_PACKAGE_LIBSELINUX", text)
        self.assertNotIn("depends on BR2_PACKAGE_LIBSELINUX", text)
        mk = (self.ROOT / "uutils-coreutils" / "uutils-coreutils.mk").read_text()
        self.assertIn("UUTILS_COREUTILS_CARGO_PROFILE = release", mk)
        self.assertNotIn("release-small", mk)
        self.assertNotIn("FETCH_HASH", mk)
        self.assertIn("ifeq ($(BR2_PACKAGE_LIBSELINUX),y)", mk)
        self.assertIn("UUTILS_COREUTILS_APPLETS += chcon runcon", mk)
        self.assertIn("feat_selinux", mk)
        self.assertIn("usr/bin/[", mk)
        self.assertIn(
            "ifeq ($(BR2_PACKAGE_UUTILS_COREUTILS_INDIVIDUAL_BINARIES),y)", mk
        )
        applets = mk[
            mk.index("UUTILS_COREUTILS_APPLETS =") : mk.index(
                "UUTILS_COREUTILS_CARGO_FEATURES"
            )
        ]
        for missing in (
            "b3sum",
            "hashsum",
            "sha3-224sum",
            "sha3sum",
            "shake128sum",
            "relpath",
        ):
            self.assertNotIn(missing, applets)
        for name in (
            "hexedit",
            "sharutils",
            "gcc-standalone-toolchain",
            "sudo-rs",
            "fdfind",
            "brush",
            "jaq",
            "python-uv",
            "dotnet10",
            "pwsh7",
        ):
            pkg_mk = (self.ROOT / name / f"{name}.mk").read_text()
            self.assertNotIn("FETCH_HASH", pkg_mk)
            self.assertNotIn("_HASH_FILE", pkg_mk)

    def test_sudo_rs_replaces_gnu_sudo(self) -> None:
        """sudo-rs conflicts with GNU sudo, selects PAM, and sets setuid via PERMISSIONS."""
        text = (self.ROOT / "sudo-rs" / "Config.in").read_text()
        self.assertIn("config BR2_PACKAGE_SUDO_RS", text)
        self.assertIn("depends on !BR2_PACKAGE_SUDO", text)
        self.assertIn("select BR2_PACKAGE_LINUX_PAM", text)
        self.assertIn('default "0.2.15"', text)
        mk = (self.ROOT / "sudo-rs" / "sudo-rs.mk").read_text()
        self.assertIn("define SUDO_RS_PERMISSIONS", mk)
        self.assertIn("/usr/bin/sudo f 4755 0 0 - - - - -", mk)
        self.assertIn("/usr/sbin/su f 4755 0 0 - - - - -", mk)
        self.assertIn("/etc/sudoers f 0640 0 0 - - - - -", mk)
        self.assertIn("SUDO_RS_DEPENDENCIES = linux-pam", mk)
        self.assertIn("$(TARGET_DIR)/usr/bin/sudo", mk)
        self.assertIn("$(TARGET_DIR)/usr/sbin/su", mk)
        self.assertIn("$(TARGET_DIR)/etc/pam.d/sudo", mk)
        self.assertNotIn("host-cargo", mk)
        self.assertTrue((self.ROOT / "sudo-rs" / "sudoers").is_file())
        self.assertTrue((self.ROOT / "sudo-rs" / "sudo.pam").is_file())
        self.assertTrue((self.ROOT / "sudo-rs" / "su.pam").is_file())

    def test_fdfind_installs_renamed_binary(self) -> None:
        """fdfind installs the fd crate binary as /usr/bin/fdfind with no fd symlink."""
        text = (self.ROOT / "fdfind" / "Config.in").read_text()
        self.assertIn("config BR2_PACKAGE_FDFIND", text)
        self.assertIn('default "10.5.0"', text)
        mk = (self.ROOT / "fdfind" / "fdfind.mk").read_text()
        self.assertIn("$(TARGET_DIR)/usr/bin/fdfind", mk)
        self.assertNotRegex(mk, r"\$\(TARGET_DIR\)/usr/bin/fd[ \n]")
        self.assertNotIn("ln -s", mk)
        self.assertNotIn("ln -sf", mk)
        self.assertNotIn("host-cargo", mk)
        self.assertIn("$(call github,sharkdp,fd,v$(FDFIND_VERSION))", mk)

    def test_brush_package(self) -> None:
        """brush builds crate brush-shell, installs /usr/bin/brush, and fetches docs."""
        text = (self.ROOT / "brush" / "Config.in").read_text(encoding="utf-8")
        self.assertIn("config BR2_PACKAGE_BRUSH", text)
        self.assertIn("select BR2_PACKAGE_HOST_RUSTC", text)
        self.assertIn('default "0.4.0"', text)
        self.assertIn("config BR2_PACKAGE_BRUSH_DOCS", text)
        self.assertIn("default y", text)
        mk = (self.ROOT / "brush" / "brush.mk").read_text(encoding="utf-8")
        self.assertIn(
            "$(call github,reubeno,brush,brush-shell-v$(BRUSH_VERSION))", mk
        )
        self.assertIn("BRUSH_SOURCE = brush-$(BRUSH_VERSION).tar.gz", mk)
        self.assertIn("--manifest-path brush-shell/Cargo.toml", mk)
        self.assertIn("$(TARGET_DIR)/usr/bin/brush", mk)
        self.assertIn("BRUSH_CARGO_PROFILE = release", mk)
        self.assertNotIn("--features", mk)
        self.assertNotIn("host-cargo", mk)
        self.assertNotIn("FETCH_HASH", mk)
        self.assertIn(
            "releases/download/brush-shell-v$(BRUSH_VERSION)/brush-docs.tar.gz",
            mk,
        )
        self.assertIn("docs-extracted/man/brush.1", mk)
        self.assertIn("$(TARGET_DIR)/usr/share/man/man1/brush.1", mk)
        self.assertIn("docs-extracted/md/brush.md", mk)
        self.assertIn("$(TARGET_DIR)/usr/share/doc/brush/brush.md", mk)
        self.assertIn("ifeq ($(BR2_PACKAGE_BRUSH_DOCS),y)", mk)
        self.assertNotIn("docs-extracted/*.1", mk)
        self.assertEqual(cb.kconfig_package_symbol("brush"), "BR2_PACKAGE_BRUSH")
        self.assertNotIn("brush", cb.LATE_CUSTOM_SKIP_PACKAGES)
        setup = (
            Path(__file__).resolve().parent / "buildrootConf" / "setup.config"
        ).read_text(encoding="utf-8")
        self.assertIn("BR2_PACKAGE_BRUSH=y", setup)
        self.assertIn('BR2_PACKAGE_BRUSH_VERSION="0.4.0"', setup)
        self.assertIn('BR2_SYSTEM_BIN_SH="bash"', setup)


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


_ESPFLASH_DEFMT_4_0_1 = """\
        let table = match Table::parse(elf) {
            Ok(Some(table)) => table,
            Ok(None) => bail!(DefmtError::NoDefmtData),
            Err(e) => return Err(DefmtError::TableParseFailed).with_context(|| e),
        };
"""


_ESPFLASH_CONFIG_2026_08 = """\
config BR2_PACKAGE_ESPFLASH
\tbool "espflash"
\tdepends on BR2_PACKAGE_HOST_RUSTC_TARGET_ARCH_SUPPORTS
\tdepends on BR2_PACKAGE_HAS_UDEV
\tselect BR2_PACKAGE_HOST_RUSTC
\thelp
\t  Serial flasher utilities for Espressif devices.

\t  https://github.com/esp-rs/espflash

comment "espflash needs udev /dev management"
\tdepends on BR2_PACKAGE_HOST_RUSTC_TARGET_ARCH_SUPPORTS
\tdepends on !BR2_PACKAGE_HAS_UDEV
"""

_ESPFLASH_MK_2026_08 = """\
################################################################################
#
# espflash
#
################################################################################

ESPFLASH_VERSION = 4.0.1
ESPFLASH_SITE = $(call github,esp-rs,espflash,v$(ESPFLASH_VERSION))
ESPFLASH_SUBDIR = espflash

$(eval $(cargo-package))
"""


class PatchEspflashTests(unittest.TestCase):
    """Stock package/espflash: bail! patch and optional version override."""

    PATCH_NAME = "0001-esp_defmt-bail-in-statement-position.patch"

    def setUp(self) -> None:
        """Temporary package/espflash directory with the 2026.08 files."""
        self.td = Path(tempfile.mkdtemp())
        self.pkg = self.td / "espflash"
        self.pkg.mkdir()
        self.config_in = self.pkg / "Config.in"
        self.mk = self.pkg / "espflash.mk"
        self.config_in.write_text(_ESPFLASH_CONFIG_2026_08, encoding="utf-8")
        self.mk.write_text(_ESPFLASH_MK_2026_08, encoding="utf-8")

    def tearDown(self) -> None:
        """Remove the temp tree."""
        shutil.rmtree(self.td)

    def test_missing_dir_is_noop(self) -> None:
        """Incomplete trees and unit fixtures without espflash skip."""
        self.assertIsNone(cb.patch_espflash(self.td / "missing"))

    def test_writes_first_patch_into_the_version_dir(self) -> None:
        """Buildroot reads package/espflash/4.0.1/ only while the version is 4.0.1."""
        expected = self.pkg / "4.0.1" / self.PATCH_NAME
        self.assertEqual(cb.patch_espflash(self.pkg), expected)
        text = expected.read_text(encoding="utf-8")
        self.assertIn("-            Ok(None) => bail!(DefmtError::NoDefmtData),", text)
        self.assertIn("+                bail!(DefmtError::NoDefmtData);", text)
        self.assertIn("a/espflash/src/cli/monitor/parser/esp_defmt.rs", text)
        self.assertEqual(list(self.pkg.glob("*.patch")), [])

    def test_numbering_follows_existing_patches(self) -> None:
        """An unrelated 0001 patch in the version dir pushes this one to 0002."""
        (self.pkg / "4.0.1").mkdir()
        (self.pkg / "4.0.1" / "0001-other.patch").write_text("other\n")
        self.assertEqual(
            cb.patch_espflash(self.pkg),
            self.pkg / "4.0.1" / "0002-esp_defmt-bail-in-statement-position.patch",
        )

    def test_idempotent(self) -> None:
        """A second --customize does not add another numbered file."""
        self.assertIsNotNone(cb.patch_espflash(self.pkg))
        self.assertIsNone(cb.patch_espflash(self.pkg))
        self.assertEqual(len(list((self.pkg / "4.0.1").glob("*.patch"))), 1)

    def test_skips_when_hunk_already_present(self) -> None:
        """Do not add a second copy if the tree already ships the same hunk."""
        (self.pkg / "4.0.1").mkdir()
        (self.pkg / "4.0.1" / "0001-upstream.patch").write_text(
            cb.ESPFLASH_BAIL_PATCH, encoding="utf-8"
        )
        self.assertIsNone(cb.patch_espflash(self.pkg))
        self.assertEqual(len(list((self.pkg / "4.0.1").glob("*.patch"))), 1)

    def test_patch_applies_to_the_4_0_1_source(self) -> None:
        """The hunk applies with patch -p1 and leaves bail! as a statement."""
        if shutil.which("patch") is None:
            self.skipTest("patch is not installed")
        src = self.td / "src" / "espflash" / "src" / "cli" / "monitor" / "parser"
        src.mkdir(parents=True)
        target = src / "esp_defmt.rs"
        target.write_text(
            "fn load() {\n" + _ESPFLASH_DEFMT_4_0_1 + "}\n", encoding="utf-8"
        )
        dest = cb.patch_espflash(self.pkg)
        subprocess.run(
            ["patch", "-p1", "-s", "-i", str(dest)],
            cwd=self.td / "src",
            check=True,
        )
        fixed = target.read_text(encoding="utf-8")
        self.assertIn(
            "            Ok(None) => {\n"
            "                bail!(DefmtError::NoDefmtData);\n"
            "            }\n",
            fixed,
        )
        self.assertNotIn("=> bail!(", fixed)

    def test_config_in_adds_the_override_with_the_stock_default(self) -> None:
        """The Kconfig string defaults to 4.0.1 and sits inside if ESPFLASH."""
        cb.patch_espflash_config_in(self.config_in)
        text = self.config_in.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(_ESPFLASH_CONFIG_2026_08))
        block = text[text.index("if BR2_PACKAGE_ESPFLASH\n") :]
        self.assertIn("config BR2_PACKAGE_ESPFLASH_VERSION_OVERRIDE\n", block)
        self.assertIn('\tstring "espflash version override"\n', block)
        self.assertIn('\tdefault "4.0.1"\n', block)
        self.assertTrue(block.endswith("endif\n"))
        cb.patch_espflash_config_in(self.config_in)
        self.assertEqual(self.config_in.read_text(encoding="utf-8"), text)

    def test_mk_honors_the_override_between_version_and_site(self) -> None:
        """espflash.mk keeps ESPFLASH_VERSION and lets the option replace it."""
        cb.patch_espflash_mk(self.mk)
        text = self.mk.read_text(encoding="utf-8")
        stock = text.index("ESPFLASH_VERSION = 4.0.1\n")
        override = text.index(
            "ESPFLASH_VERSION = $(call qstrip,"
            "$(BR2_PACKAGE_ESPFLASH_VERSION_OVERRIDE))"
        )
        self.assertLess(stock, override)
        self.assertLess(override, text.index("ESPFLASH_SITE = "))
        cb.patch_espflash_mk(self.mk)
        self.assertEqual(self.mk.read_text(encoding="utf-8"), text)

    def test_mk_without_a_version_line_is_fatal(self) -> None:
        """A layout change in espflash.mk stops --customize instead of skipping."""
        self.mk.write_text("ESPFLASH_SITE = x\n", encoding="utf-8")
        with self.assertRaises(SystemExit):
            cb.patch_espflash_mk(self.mk)

    def test_override_selects_the_version_under_make(self) -> None:
        """Unset or empty keeps 4.0.1; a quoted Kconfig string replaces it."""
        if shutil.which("make") is None:
            self.skipTest("make is not installed")
        cb.patch_espflash_mk(self.mk)
        stub = self.td / "stub.mk"
        stub.write_text(
            'qstrip = $(strip $(subst ",,$(1)))\n'
            "github = gh:$(1)/$(2)/$(3)\n"
            "cargo-package =\n"
            f"include {self.mk}\n"
            "show:\n"
            "\t@echo $(ESPFLASH_VERSION) $(ESPFLASH_SITE)\n",
            encoding="utf-8",
        )
        cases = [
            (None, "4.0.1 gh:esp-rs/espflash/v4.0.1"),
            ('""', "4.0.1 gh:esp-rs/espflash/v4.0.1"),
            ('"4.0.1"', "4.0.1 gh:esp-rs/espflash/v4.0.1"),
            ('"4.1.0"', "4.1.0 gh:esp-rs/espflash/v4.1.0"),
        ]
        for override, expected in cases:
            with self.subTest(override=override):
                argv = ["make", "-s", "-f", str(stub), "show"]
                if override is not None:
                    argv.append(f"BR2_PACKAGE_ESPFLASH_VERSION_OVERRIDE={override}")
                result = subprocess.run(
                    argv, capture_output=True, text=True, check=False
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), expected)

    def test_customize_applies_both_espflash_patches(self) -> None:
        """customize_buildroot adds the option, the .mk hook, and the bail! patch."""
        br = self.td / "br"
        custom = self.td / "custom"
        br.mkdir()
        (br / "Config.in").write_text('menu "x"\nendmenu\n')
        shutil.copy(SAMPLE, br / "Makefile")
        (br / "package").mkdir()
        (br / "package" / "Config.in").write_text('menu "Target packages"\nendmenu\n')
        groff = custom / "groff"
        groff.mkdir(parents=True)
        (groff / "Config.in").write_text('config BR2_PACKAGE_GROFF\n\tbool "g"\n')
        stock = br / "package" / "espflash"
        shutil.copytree(self.pkg, stock)
        cb.customize_buildroot(br, custom)
        self.assertTrue((stock / "4.0.1" / self.PATCH_NAME).is_file())
        self.assertIn(
            "BR2_PACKAGE_ESPFLASH_VERSION_OVERRIDE",
            (stock / "Config.in").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "$(BR2_PACKAGE_ESPFLASH_VERSION_OVERRIDE)",
            (stock / "espflash.mk").read_text(encoding="utf-8"),
        )


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
        self.assertTrue((self.br / "package" / "fetch-hash.mk").is_file())
        self.assertIn("include package/fetch-hash.mk", (self.br / "Makefile").read_text())

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
        self.assertTrue((self.br / "package" / "fetch-hash.mk").is_file())
        self.assertTrue((self.br / "package" / "fetch_hash_helper.py").is_file())
        self.assertIn(
            "include package/fetch-hash.mk",
            (self.br / "Makefile").read_text(encoding="utf-8"),
        )

    def test_getbuildroot_flag_is_exclusive(self) -> None:
        """getBuildroot.sh documents --update-kernel-support as a lone argument."""
        script = Path(__file__).with_name("getBuildroot.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("--update-kernel-support)", script)
        self.assertIn("--update-rust-version)", script)
        self.assertIn("must be used by itself", script)
        self.assertIn("--update-kernel-support", script)
        self.assertIn("customizeBuildroot/main.py", script)
        self.assertIn('PYTHONPATH="${BUILDER_ROOT_DIR%/}', script)
        self.assertNotIn("RUST_VERSION:=", script)
        self.assertNotIn("RUST_BINDGEN_VERSION:=", script)

    def test_installs_fetch_hash_mk(self) -> None:
        """--update-kernel-support installs package/fetch-hash.mk at Makefile EOF."""
        makefile_path = self.br / "Makefile"
        self._apply()
        dest = self.br / "package" / "fetch-hash.mk"
        helper = self.br / "package" / "fetch_hash_helper.py"
        self.assertTrue(dest.is_file())
        self.assertTrue(helper.is_file())
        text = dest.read_text(encoding="utf-8")
        self.assertNotIn("FETCH_HASH_METHOD_", text)
        self.assertNotIn("cdn.kernel.org", text)
        self.assertIn("$(HOST_DIR)/bin/python3", text)
        self.assertIn("$(HOST_DIR)/etc/ssl/certs/ca-certificates.crt", text)
        self.assertIn("FETCH_HASH_PYTHON ?=", text)
        self.assertNotIn(" python3 \"", text)
        self.assertIn("fetch_hash_helper.py", text)
        self.assertIn("PRE_DOWNLOAD_HOOKS += FETCH_HASH", text)
        self.assertIn("DOWNLOAD_POST_PROCESS", text)
        self.assertIn("$($(PKG)_DL_DIR)", text)
        self.assertIn("support/download/", text)
        for key in (
            "rust",
            "usbutils",
            "linux",
            "linux-headers",
            "gcc-standalone-toolchain",
            "brush-docs.tar.gz",
        ):
            self.assertIn(f"FETCH_HASH_URL.{key} =", text)
        self.assertNotIn("archive/refs/tags/brush-shell-v0.4.0.tar.gz.sha256", text)
        htext = helper.read_text(encoding="utf-8")
        self.assertNotIn("FETCH_HASH_URL", htext)
        self.assertNotIn("kernel.org", htext)
        makefile = makefile_path.read_text(encoding="utf-8")
        self.assertIn("include package/fetch-hash.mk", makefile)
        self.assertEqual(makefile.count("include package/fetch-hash.mk"), 1)
        self.assertGreater(
            makefile.index("include package/fetch-hash.mk"),
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
            makefile_path.read_text(encoding="utf-8").count(
                "include package/fetch-hash.mk"
            ),
            1,
        )
        self.assertEqual(dest.read_text(encoding="utf-8"), text)


_RUST_MK_2026_08 = """\
################################################################################
#
# rust
#
################################################################################

# When updating this version, check whether support/download/cargo-post-process
# still generates the same archives.
RUST_VERSION = 1.97.1
RUST_SOURCE = rustc-$(RUST_VERSION)-src.tar.xz
RUST_SITE = https://static.rust-lang.org/dist

define HOST_RUST_CONFIGURE_CMDS
	echo 'target = ["$(RUSTC_TARGET_NAME)"]'
endef

$(eval $(host-generic-package))
"""

_RUST_BIN_MK_2026_08 = """\
################################################################################
#
# rust-bin
#
################################################################################

# When updating this version, check whether support/download/cargo-post-process
# still generates the same archives.
RUST_BIN_VERSION = 1.97.1
RUST_BIN_SITE = https://static.rust-lang.org/dist
HOST_RUST_BIN_SOURCE = rust-$(RUST_BIN_VERSION)-$(RUSTC_HOST_NAME).tar.xz

$(eval $(host-generic-package))
"""

_RUST_BINDGEN_MK_2026_08 = """\
################################################################################
#
# rust-bindgen
#
################################################################################

RUST_BINDGEN_VERSION = 0.72.1
RUST_BINDGEN_SITE = $(call github,rust-lang,rust-bindgen,refs/tags/v$(RUST_BINDGEN_VERSION))
RUST_BINDGEN_LICENSE = BSD-3-clause

$(eval $(host-cargo-package))
"""


class UpdateRustVersionTests(unittest.TestCase):
    """--update-rust-version patches rust/rust-bin/rust-bindgen from env vars."""

    def setUp(self) -> None:
        """Minimal 2026.08 rust package makefile tree."""
        self.td = Path(tempfile.mkdtemp())
        self.br = self.td / "Buildroot-Builder"
        rust = self.br / "package" / "rust"
        rust_bin = self.br / "package" / "rust-bin"
        bindgen = self.br / "package" / "rust-bindgen"
        rust.mkdir(parents=True)
        rust_bin.mkdir(parents=True)
        bindgen.mkdir(parents=True)
        (self.br / "Config.in").write_text('menu "x"\nendmenu\n', encoding="utf-8")
        shutil.copy(SAMPLE, self.br / "Makefile")
        (self.br / "package" / "Config.in").write_text(
            'menu "Target packages"\nendmenu\n', encoding="utf-8"
        )
        self.rust_mk = rust / "rust.mk"
        self.rust_bin_mk = rust_bin / "rust-bin.mk"
        self.bindgen_mk = bindgen / "rust-bindgen.mk"
        self.rust_mk.write_text(_RUST_MK_2026_08, encoding="utf-8")
        self.rust_bin_mk.write_text(_RUST_BIN_MK_2026_08, encoding="utf-8")
        self.bindgen_mk.write_text(_RUST_BINDGEN_MK_2026_08, encoding="utf-8")

    def tearDown(self) -> None:
        """Remove the temp tree."""
        shutil.rmtree(self.td)

    @contextmanager
    def _env(self, **values: str | None) -> Iterator[None]:
        """Set rust env vars for one test; restore afterward. No defaults."""
        keys = ("RUST_VERSION", "RUST_BINDGEN_VERSION")
        saved = {key: os.environ.get(key) for key in keys}
        for key in keys:
            os.environ.pop(key, None)
        for key, value in values.items():
            if value is not None:
                os.environ[key] = value
        try:
            yield
        finally:
            for key in keys:
                os.environ.pop(key, None)
                previous = saved[key]
                if previous is not None:
                    os.environ[key] = previous

    def test_patches_rust_and_bindgen_from_env(self) -> None:
        """RUST_VERSION updates rust and rust-bin; RUST_BINDGEN_VERSION updates bindgen."""
        with self._env(RUST_VERSION="1.99.0", RUST_BINDGEN_VERSION="0.73.2"):
            cb.update_rust_version(self.br)
        rust_text = self.rust_mk.read_text(encoding="utf-8")
        bin_text = self.rust_bin_mk.read_text(encoding="utf-8")
        bindgen_text = self.bindgen_mk.read_text(encoding="utf-8")
        self.assertIn("RUST_VERSION = 1.99.0\n", rust_text)
        self.assertNotIn("RUST_VERSION = 1.97.1\n", rust_text)
        self.assertIn("RUST_SOURCE = rustc-$(RUST_VERSION)-src.tar.xz\n", rust_text)
        self.assertIn("define HOST_RUST_CONFIGURE_CMDS\n", rust_text)
        self.assertIn("$(eval $(host-generic-package))\n", rust_text)
        self.assertIn("RUST_BIN_VERSION = 1.99.0\n", bin_text)
        self.assertIn("RUST_BINDGEN_VERSION = 0.73.2\n", bindgen_text)
        self.assertIn(
            "RUST_BINDGEN_SITE = $(call github,rust-lang,rust-bindgen,"
            "refs/tags/v$(RUST_BINDGEN_VERSION))\n",
            bindgen_text,
        )
        self.assertTrue((self.br / "package" / "fetch-hash.mk").is_file())
        self.assertTrue((self.br / "package" / "fetch_hash_helper.py").is_file())
        self.assertIn(
            "include package/fetch-hash.mk",
            (self.br / "Makefile").read_text(encoding="utf-8"),
        )
        self.assertFalse((self.br / "package" / "rustc").exists())

    def test_rust_only_leaves_bindgen(self) -> None:
        """A set RUST_VERSION with blank bindgen env patches only rust/rust-bin."""
        with self._env(RUST_VERSION="1.99.0"):
            buf = StringIO()
            with redirect_stdout(buf):
                cb.update_rust_version(self.br)
        self.assertIn("RUST_VERSION = 1.99.0\n", self.rust_mk.read_text(encoding="utf-8"))
        self.assertIn(
            "RUST_BIN_VERSION = 1.99.0\n",
            self.rust_bin_mk.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "RUST_BINDGEN_VERSION = 0.72.1\n",
            self.bindgen_mk.read_text(encoding="utf-8"),
        )
        self.assertIn("Skipping rust-bindgen", buf.getvalue())
        self.assertIn("Declare RUST_BINDGEN_VERSION", buf.getvalue())

    def test_bindgen_only_leaves_rust(self) -> None:
        """A set RUST_BINDGEN_VERSION with blank rust env patches only bindgen."""
        with self._env(RUST_BINDGEN_VERSION="0.73.2"):
            buf = StringIO()
            with redirect_stdout(buf):
                cb.update_rust_version(self.br)
        self.assertIn("RUST_VERSION = 1.97.1\n", self.rust_mk.read_text(encoding="utf-8"))
        self.assertIn(
            "RUST_BIN_VERSION = 1.97.1\n",
            self.rust_bin_mk.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "RUST_BINDGEN_VERSION = 0.73.2\n",
            self.bindgen_mk.read_text(encoding="utf-8"),
        )
        self.assertIn("Skipping rust and rust-bin", buf.getvalue())
        self.assertIn("Declare RUST_VERSION", buf.getvalue())

    def test_blank_env_is_noop(self) -> None:
        """Unset or blank env vars leave the makefiles unchanged."""
        with self._env():
            buf = StringIO()
            with redirect_stdout(buf):
                cb.update_rust_version(self.br)
        self.assertEqual(self.rust_mk.read_text(encoding="utf-8"), _RUST_MK_2026_08)
        self.assertEqual(self.rust_bin_mk.read_text(encoding="utf-8"), _RUST_BIN_MK_2026_08)
        self.assertEqual(
            self.bindgen_mk.read_text(encoding="utf-8"), _RUST_BINDGEN_MK_2026_08
        )
        self.assertFalse((self.br / "package" / "fetch-hash.mk").exists())
        self.assertIn("nothing to patch", buf.getvalue())

        with self._env(RUST_VERSION="", RUST_BINDGEN_VERSION="   "):
            cb.update_rust_version(self.br)
        self.assertEqual(self.rust_mk.read_text(encoding="utf-8"), _RUST_MK_2026_08)

        with self._env(RUST_VERSION="not-a-version"):
            cb.update_rust_version(self.br)
        self.assertEqual(self.rust_mk.read_text(encoding="utf-8"), _RUST_MK_2026_08)

    def test_strips_quotes_from_env_value(self) -> None:
        """Quoted env values still patch as the inner version number."""
        with self._env(RUST_VERSION='"1.99.0"', RUST_BINDGEN_VERSION="'0.73.2'"):
            cb.update_rust_version(self.br)
        self.assertIn("RUST_VERSION = 1.99.0\n", self.rust_mk.read_text(encoding="utf-8"))
        self.assertIn(
            "RUST_BINDGEN_VERSION = 0.73.2\n",
            self.bindgen_mk.read_text(encoding="utf-8"),
        )

    def test_idempotent(self) -> None:
        """A second --update-rust-version leaves already-patched files unchanged."""
        with self._env(RUST_VERSION="1.99.0", RUST_BINDGEN_VERSION="0.73.2"):
            cb.update_rust_version(self.br)
            first_rust = self.rust_mk.read_text(encoding="utf-8")
            first_bin = self.rust_bin_mk.read_text(encoding="utf-8")
            first_bindgen = self.bindgen_mk.read_text(encoding="utf-8")
            cb.update_rust_version(self.br)
        self.assertEqual(self.rust_mk.read_text(encoding="utf-8"), first_rust)
        self.assertEqual(self.rust_bin_mk.read_text(encoding="utf-8"), first_bin)
        self.assertEqual(self.bindgen_mk.read_text(encoding="utf-8"), first_bindgen)
        self.assertEqual(first_rust.count("RUST_VERSION = 1.99.0\n"), 1)

    def test_missing_makefile_errors(self) -> None:
        """A set env var with a missing package makefile is an error."""
        self.rust_mk.unlink()
        with (
            self._env(RUST_VERSION="1.99.0"),
            self.assertRaises(SystemExit) as raised,
        ):
            cb.update_rust_version(self.br)
        self.assertIn("rust.mk", str(raised.exception))

    def test_cli_update_rust_version_skips_customize(self) -> None:
        """python customizeBuildroot/main.py --update-rust-version is rust-only."""
        with self._env(RUST_VERSION="1.99.0", RUST_BINDGEN_VERSION="0.73.2"):
            rc = cb.main(["--br-path", str(self.br), "--update-rust-version"])
        self.assertEqual(rc, 0)
        self.assertIn("RUST_VERSION = 1.99.0\n", self.rust_mk.read_text(encoding="utf-8"))
        self.assertNotIn(
            "config BR2_KEEP_MAN_PAGES_DOCS",
            (self.br / "Config.in").read_text(encoding="utf-8"),
        )
        self.assertFalse((self.br / "package" / "custom-late.mk").exists())
        self.assertTrue((self.br / "package" / "fetch-hash.mk").is_file())
        self.assertTrue((self.br / "package" / "fetch_hash_helper.py").is_file())

    def test_customize_does_not_bump_rust(self) -> None:
        """--customize must not rewrite rust/rust-bin/rust-bindgen versions."""
        custom = self.td / "custom"
        groff = custom / "groff"
        groff.mkdir(parents=True)
        (groff / "Config.in").write_text(
            'config BR2_PACKAGE_GROFF\n\tbool "g"\n', encoding="utf-8"
        )
        with self._env(RUST_VERSION="1.99.0", RUST_BINDGEN_VERSION="0.73.2"):
            cb.customize_buildroot(self.br, custom)
        self.assertEqual(self.rust_mk.read_text(encoding="utf-8"), _RUST_MK_2026_08)
        self.assertEqual(self.rust_bin_mk.read_text(encoding="utf-8"), _RUST_BIN_MK_2026_08)
        self.assertEqual(
            self.bindgen_mk.read_text(encoding="utf-8"), _RUST_BINDGEN_MK_2026_08
        )
        names = cb.customize_buildroot.__code__.co_names
        self.assertNotIn("update_rust_version", names)

    def test_module_has_no_version_fallback(self) -> None:
        """host_rust.py does not bake in a default rust or bindgen version."""
        src = (
            Path(__file__).resolve().parent
            / "customizeBuildroot"
            / "patches"
            / "host_rust.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn('os.environ.get("RUST_VERSION",', src)
        self.assertNotIn("os.environ.get('RUST_VERSION',", src)
        self.assertNotIn('os.environ.get("RUST_BINDGEN_VERSION",', src)
        self.assertNotIn("os.environ.get('RUST_BINDGEN_VERSION',", src)
        self.assertNotIn("1.99.0", src)
        self.assertNotIn("0.73.2", src)
        self.assertNotIn("import configobj", src)


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
        self.assertNotIn("define SYSTEMD_FETCH_HASH", mk)
        self.assertNotIn("SYSTEMD_PRE_DOWNLOAD_HOOKS += SYSTEMD_FETCH_HASH", mk)
        meson_eval = mk.index("$(eval $(meson-package))")
        filter_opts = mk.index("SYSTEMD_CONF_OPTS := $(filter-out")
        self.assertLess(filter_opts, meson_eval)
        self.assertTrue((self.br / "package" / "fetch-hash.mk").is_file())
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
        self.assertNotIn("define LINUX_PAM_FETCH_HASH", mk)
        self.assertNotIn("LINUX_PAM_PRE_DOWNLOAD_HOOKS += LINUX_PAM_FETCH_HASH", mk)
        self.assertIn(
            "LINUX_PAM_SOURCE = Linux-PAM-$(LINUX_PAM_VERSION).tar.xz",
            mk,
        )
        self.assertTrue((self.br / "package" / "fetch-hash.mk").is_file())

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

    def test_replaces_legacy_hash_skip(self) -> None:
        """Re-running --customize drops leftover BR_NO_CHECK_HASH_FOR."""
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
        self.assertNotIn("SYSTEMD_FETCH_HASH", systemd_text)
        self.assertNotIn("LINUX_PAM_FETCH_HASH", pam_text)
        self.assertTrue((self.br / "package" / "fetch-hash.mk").is_file())

    def test_setup_config_selects_override_versions(self) -> None:
        """The installer fragment requests systemd 262 and linux-pam 1.7.3."""
        setup = (
            Path(__file__).resolve().parent
            / "buildrootConf"
            / "setup.config"
        ).read_text(encoding="utf-8")
        self.assertIn('BR2_PACKAGE_SYSTEMD_VERSION_OVERRIDE="262"', setup)
        self.assertIn('BR2_PACKAGE_LINUX_PAM_VERSION_OVERRIDE="1.7.3"', setup)


_RUBY_MK_2026_08 = r"""\
################################################################################
#
# ruby
#
################################################################################

RUBY_VERSION_MAJOR = 4.0
RUBY_VERSION = $(RUBY_VERSION_MAJOR).5
RUBY_VERSION_EXT = 4.0.0
RUBY_SITE = http://cache.ruby-lang.org/pub/ruby/$(RUBY_VERSION_MAJOR)
RUBY_SOURCE = ruby-$(RUBY_VERSION).tar.xz

RUBY_LICENSE = \
	Ruby or BSD-2-Clause, \
	BSD-3-Clause, \
	MIT, \
	others
RUBY_LICENSE_FILES = LEGAL COPYING BSDL

RUBY_CPE_ID_VENDOR = ruby-lang

RUBY_DEPENDENCIES = host-pkgconf host-ruby
HOST_RUBY_DEPENDENCIES = host-libyaml host-pkgconf host-openssl
RUBY_MAKE_ENV = $(TARGET_MAKE_ENV)
RUBY_CONF_OPTS = \
	--disable-install-doc \
	--disable-rpath \
	--disable-rubygems \
	--disable-yjit \
	--disable-zjit
HOST_RUBY_CONF_OPTS = \
	--disable-install-doc \
	--disable-yjit \
	--disable-zjit \
	--with-out-ext=curses,readline \
	--without-gmp

ifeq ($(BR2_TOOLCHAIN_HAS_LIBATOMIC),y)
RUBY_CONF_ENV += LIBS=-latomic
endif

ifeq ($(BR2_TOOLCHAIN_USES_UCLIBC),y)
# On uClibc, finite, isinf and isnan are not directly implemented as
# functions.  Instead math.h #define's these to __finite, __isinf and
# __isnan, confusing the Ruby configure script. Tell it that they
# really are available.
RUBY_CONF_ENV += \
	ac_cv_func_finite=yes \
	ac_cv_func_isinf=yes \
	ac_cv_func_isnan=yes
endif

ifeq ($(BR2_TOOLCHAIN_HAS_SSP),)
RUBY_CONF_ENV += stack_protector=no
endif

# Force optionals to build before we do
ifeq ($(BR2_PACKAGE_BERKELEYDB),y)
RUBY_DEPENDENCIES += berkeleydb
endif
ifeq ($(BR2_PACKAGE_LIBFFI),y)
RUBY_DEPENDENCIES += libffi
else
# Disable fiddle to avoid a build failure with bundled-libffi on MIPS
RUBY_CONF_OPTS += --with-out-ext=fiddle
endif
ifeq ($(BR2_PACKAGE_GDBM),y)
RUBY_DEPENDENCIES += gdbm
endif
ifeq ($(BR2_PACKAGE_LIBYAML),y)
RUBY_DEPENDENCIES += libyaml
endif
ifeq ($(BR2_PACKAGE_NCURSES),y)
RUBY_DEPENDENCIES += ncurses
endif
ifeq ($(BR2_PACKAGE_OPENSSL),y)
RUBY_DEPENDENCIES += openssl
endif
ifeq ($(BR2_PACKAGE_READLINE),y)
RUBY_DEPENDENCIES += readline
endif
ifeq ($(BR2_PACKAGE_ZLIB),y)
RUBY_DEPENDENCIES += zlib
endif
ifeq ($(BR2_PACKAGE_GMP),y)
RUBY_DEPENDENCIES += gmp
RUBY_CONF_OPTS += --with-gmp
else
RUBY_CONF_OPTS += --without-gmp
endif

RUBY_CFLAGS = $(TARGET_CFLAGS)

ifeq ($(BR2_TOOLCHAIN_HAS_GCC_BUG_83143),y)
RUBY_CFLAGS += -freorder-blocks-algorithm=simple
endif

RUBY_CONF_OPTS += CFLAGS="$(RUBY_CFLAGS)"

# Remove rubygems and friends, as they need extensions that aren't
# built and a target compiler.
RUBY_EXTENSIONS_REMOVE = rake* rdoc* rubygems*
define RUBY_REMOVE_RUBYGEMS
	rm -f $(addprefix $(TARGET_DIR)/usr/bin/, gem rdoc ri rake)
	rm -rf $(TARGET_DIR)/usr/lib/ruby/gems
	rm -rf $(addprefix $(TARGET_DIR)/usr/lib/ruby/$(RUBY_VERSION_EXT)/, \
		$(RUBY_EXTENSIONS_REMOVE))
endef
RUBY_POST_INSTALL_TARGET_HOOKS += RUBY_REMOVE_RUBYGEMS

$(eval $(autotools-package))
$(eval $(host-autotools-package))
"""

_RUBY_CONFIG_2026_08 = r"""\
config BR2_PACKAGE_RUBY
	bool "ruby"
	depends on BR2_USE_WCHAR
	depends on BR2_TOOLCHAIN_HAS_THREADS
	depends on !BR2_STATIC_LIBS
	depends on BR2_TOOLCHAIN_GCC_AT_LEAST_4_9
	depends on BR2_HOST_GCC_AT_LEAST_4_9
	help
	  Object Oriented Scripting Language.

	  http://www.ruby-lang.org/

comment "ruby needs a toolchain w/ wchar, threads, dynamic library, gcc >= 4.9, host gcc >= 4.9"
	depends on !BR2_USE_WCHAR || !BR2_TOOLCHAIN_HAS_THREADS || \
		BR2_STATIC_LIBS || !BR2_TOOLCHAIN_GCC_AT_LEAST_4_9 || \
		!BR2_HOST_GCC_AT_LEAST_4_9
"""


class RubyOverrideTests(unittest.TestCase):
    """--customize adds the ruby version override and feature toggles."""

    def setUp(self) -> None:
        """Minimal tree with the stock 2026.08 ruby package files."""
        self.td = Path(tempfile.mkdtemp())
        self.br = self.td / "Buildroot-Builder"
        self.ruby = self.br / "package" / "ruby"
        self.ruby.mkdir(parents=True)
        (self.br / "Config.in").write_text('menu "x"\nendmenu\n')
        shutil.copy(SAMPLE, self.br / "Makefile")
        (self.br / "package" / "Config.in").write_text(
            'menu "Target packages"\nendmenu\n'
        )
        (self.ruby / "Config.in").write_text(_RUBY_CONFIG_2026_08)
        (self.ruby / "ruby.mk").write_text(_RUBY_MK_2026_08)
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

    def test_kconfig_options(self) -> None:
        """Version override defaults to empty; the feature toggles are bools."""
        self._apply()
        cfg = (self.ruby / "Config.in").read_text()
        self.assertIn("config BR2_PACKAGE_RUBY_VERSION_OVERRIDE", cfg)
        self.assertIn('\tstring "ruby version override"\n\tdefault ""\n', cfg)
        for symbol in ("RUBYGEMS", "YJIT", "ZJIT"):
            self.assertIn(f"config BR2_PACKAGE_RUBY_{symbol}\n\tbool ", cfg)
        self.assertIn("if BR2_PACKAGE_RUBY\n", cfg)

    def test_makefile_keeps_stock_version_and_derives_the_series(self) -> None:
        """RUBY_VERSION stays 4.0.5; a set override drives version, series and EXT."""
        self._apply()
        mk = (self.ruby / "ruby.mk").read_text()
        self.assertIn("RUBY_VERSION = $(RUBY_VERSION_MAJOR).5\n", mk)
        self.assertIn("RUBY_VERSION_MAJOR = 4.0\n", mk)
        self.assertIn(
            "ifneq ($(call qstrip,$(BR2_PACKAGE_RUBY_VERSION_OVERRIDE)),)\n"
            "RUBY_VERSION = $(call qstrip,$(BR2_PACKAGE_RUBY_VERSION_OVERRIDE))\n"
            "RUBY_VERSION_MAJOR = $(word 1,$(subst ., ,$(RUBY_VERSION)))."
            "$(word 2,$(subst ., ,$(RUBY_VERSION)))\n"
            "RUBY_VERSION_EXT = $(RUBY_VERSION_MAJOR).0\n"
            "endif\n",
            mk,
        )
        self.assertLess(
            mk.index("RUBY_SOURCE ="), mk.index("BR2_PACKAGE_RUBY_VERSION_OVERRIDE")
        )

    def test_conf_opts_are_conditional(self) -> None:
        """Only --disable-rpath is unconditional; the rest follow the options."""
        self._apply()
        mk = (self.ruby / "ruby.mk").read_text()
        self.assertIn("RUBY_CONF_OPTS = \\\n\t--disable-rpath\n", mk)
        self.assertIn(
            "ifneq ($(BR2_KEEP_MAN_PAGES_DOCS),y)\n"
            "RUBY_CONF_OPTS += --disable-install-doc\n"
            "endif\n",
            mk,
        )
        self.assertIn(
            "ifneq ($(BR2_PACKAGE_RUBY_RUBYGEMS),y)\n"
            "RUBY_CONF_OPTS += --disable-rubygems\n"
            "endif\n",
            mk,
        )
        for jit in ("yjit", "zjit"):
            self.assertIn(
                f"ifeq ($(BR2_PACKAGE_RUBY_{jit.upper()}),y)\n"
                "RUBY_DEPENDENCIES += host-rustc\n"
                f"RUBY_CONF_OPTS += --enable-{jit}\n"
                "else\n"
                f"RUBY_CONF_OPTS += --disable-{jit}\n"
                "endif\n",
                mk,
            )
        host_block = mk[mk.index("HOST_RUBY_CONF_OPTS") :].split("\n\n")[0]
        self.assertIn("--disable-install-doc", host_block)

    def test_rubygems_removal_hook_is_guarded(self) -> None:
        """RUBY_REMOVE_RUBYGEMS is only registered without BR2_PACKAGE_RUBY_RUBYGEMS."""
        self._apply()
        mk = (self.ruby / "ruby.mk").read_text()
        self.assertIn("define RUBY_REMOVE_RUBYGEMS\n", mk)
        self.assertIn(
            "ifneq ($(BR2_PACKAGE_RUBY_RUBYGEMS),y)\n"
            "RUBY_POST_INSTALL_TARGET_HOOKS += RUBY_REMOVE_RUBYGEMS\n"
            "endif\n",
            mk,
        )

    def test_customize_is_idempotent(self) -> None:
        """A second --customize run leaves Config.in and ruby.mk unchanged."""
        self._apply()
        cfg = (self.ruby / "Config.in").read_text()
        mk = (self.ruby / "ruby.mk").read_text()
        self._apply()
        self.assertEqual((self.ruby / "Config.in").read_text(), cfg)
        self.assertEqual((self.ruby / "ruby.mk").read_text(), mk)
        self.assertEqual(cfg.count("config BR2_PACKAGE_RUBY_VERSION_OVERRIDE"), 1)
        self.assertEqual(mk.count("ifneq ($(call qstrip,$(BR2_PACKAGE_RUBY_VERSION"), 1)

    def test_unexpected_conf_opts_block_is_an_error(self) -> None:
        """A ruby.mk whose RUBY_CONF_OPTS block changed upstream stops the run."""
        (self.ruby / "ruby.mk").write_text(
            _RUBY_MK_2026_08.replace("--disable-zjit", "--disable-other")
        )
        with self.assertRaises(SystemExit), redirect_stdout(StringIO()):
            self._apply()

    def test_setup_config_requests_ruby_override(self) -> None:
        """The installer fragment requests ruby 4.0.7."""
        setup = (
            Path(__file__).resolve().parent / "buildrootConf" / "setup.config"
        ).read_text(encoding="utf-8")
        self.assertIn('BR2_PACKAGE_RUBY_VERSION_OVERRIDE="4.0.7"', setup)


PATCHES = Path(__file__).resolve().parent / "customizeBuildroot" / "patches"
HASH_HEADER = ["#", "# Automatically generated file; DO NOT EDIT.", "#"]


def _load_fetch_hash_helper():
    """Load fetch_hash_helper.py by path; it is not a customizeBuildroot import."""
    spec = importlib.util.spec_from_file_location(
        "fetch_hash_helper_test", PATCHES / "fetch_hash_helper.py"
    )
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load fetch_hash_helper.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dead_url() -> str:
    """Return a loopback URL nothing listens on, so any request to it fails."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{sock.getsockname()[1]}"


def _sha256_line(payload: bytes, name: str) -> str:
    """Return the .hash line expected for *payload* stored as *name*."""
    return f"sha256  {hashlib.sha256(payload).hexdigest()}  {name}"


class _Origin:
    """Local HTTP origin serving ``{path: bytes}``; unknown paths are 404.

    Paths listed in *truncated* promise the full Content-Length but send only
    half the body, like a connection dropped mid-download.
    """

    def __init__(
        self, files: dict[str, bytes], truncated: Iterable[str] = ()
    ) -> None:
        """Bind an ephemeral loopback port; serving starts on ``with``."""
        cut = set(truncated)

        class Handler(socketserver.StreamRequestHandler):
            """Answer one HTTP/1.0 GET from *files*, then close."""

            def handle(self) -> None:
                """Read the request line, skip the headers, write the response."""
                path = self.rfile.readline().split()[1].decode("ascii")
                while self.rfile.readline().strip():
                    pass
                body = files.get(path)
                if body is None:
                    self.wfile.write(b"HTTP/1.0 404 Not Found\r\n\r\n")
                    return
                head = f"HTTP/1.0 200 OK\r\nContent-Length: {len(body)}\r\n\r\n"
                sent = body[: len(body) // 2] if path in cut else body
                self.wfile.write(head.encode("ascii") + sent)

        self._server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.base = f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self) -> Self:
        """Start serving in a background thread."""
        threading.Thread(
            target=self._server.serve_forever, args=(0.01,), daemon=True
        ).start()
        return self

    def __exit__(self, *args: object) -> None:
        """Stop serving and release the port."""
        self._server.shutdown()
        self._server.server_close()


class FetchHashHelperTests(unittest.TestCase):
    """fetch_hash_helper.py: sidecar parsing, streaming hash, post-process, append."""

    @classmethod
    def setUpClass(cls) -> None:
        """Load the helper once for this class."""
        cls.helper = _load_fetch_hash_helper()

    def setUp(self) -> None:
        """Point the helper at an empty temp tree."""
        self.td = Path(tempfile.mkdtemp())
        self.hash_file = self.td / "pkg" / "pkg.hash"
        self.dl_dir = self.td / "dl"

    def tearDown(self) -> None:
        """Remove the temp tree."""
        shutil.rmtree(self.td)

    def _main(self, name: str, url: str, *extra: str) -> None:
        """Run the helper CLI for *name*, discarding its progress line."""
        argv = [str(self.hash_file), name, url, "--dl-dir", str(self.dl_dir), *extra]
        with redirect_stdout(StringIO()):
            self.helper.main(argv)

    def _fails(self, name: str, url: str, *extra: str) -> str:
        """Run the helper expecting a clean exit-1 error; return its message."""
        with self.assertRaises(SystemExit) as raised:
            self._main(name, url, *extra)
        self.assertIsInstance(raised.exception.code, str)
        message = str(raised.exception.code)
        self.assertIn("fetch-hash", message)
        return message

    def _lines(self) -> list[str]:
        """Return the hash file's lines."""
        return self.hash_file.read_text(encoding="utf-8").splitlines()

    def _post_process_script(self, body: str) -> Path:
        """Write an executable stand-in for support/download/*-post-process."""
        script = self.td / "fake-post-process"
        script.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        script.chmod(0o755)
        return script

    def test_helper_is_not_imported_by_customize_buildroot(self) -> None:
        """The helper is executed by Make; customizeBuildroot only copies it."""
        root = Path(cb.__file__).resolve().parent
        for rel in ("__init__.py", "main.py", "patches/__init__.py"):
            text = (root / rel).read_text(encoding="utf-8")
            self.assertNotIn("fetch-hash-helper", text)
            self.assertNotIn("fetch_hash_helper", text)
        fetch_hash = (root / "patches" / "fetch_hash.py").read_text(encoding="utf-8")
        for line in fetch_hash.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                self.assertNotIn("fetch-hash-helper", stripped)
                self.assertNotIn("fetch_hash_helper", stripped)

    def test_sidecar_matches_basename_of_ci_path(self) -> None:
        """A CI absolute path in the sidecar still matches the tarball basename."""
        digest = "1070fa3a9470927c0c3d9c5417151f1b8f72317b42bed21f33e5fd4f3dad3332"
        listing = f"{digest}  /home/runner/work/brush/brush/brush-docs.tar.gz\n"
        with _Origin({"/sums": listing.encode()}) as origin:
            self._main("brush-docs.tar.gz", "", "--sidecar", f"{origin.base}/sums")
            self.assertIn(
                f"sha256  {digest}  brush-docs.tar.gz",
                self._lines(),
            )

    def test_sidecar_picks_the_named_entry_from_a_signed_list(self) -> None:
        """PGP armor, other files, and a ``*`` binary marker do not confuse it."""
        xz, gz = "a" * 64, "b" * 64
        listing = (
            "-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA256\n\n"
            f"{'c' * 64}  linux-7.2.8.tar.xz\n"
            f"{xz}  linux-7.2.9.tar.xz\n"
            f"{gz} *linux-7.2.9.tar.gz\n"
            "-----BEGIN PGP SIGNATURE-----\n\nabc\n-----END PGP SIGNATURE-----\n"
        )
        with _Origin({"/sums": listing.encode()}) as origin:
            sums = f"{origin.base}/sums"
            self._main("linux-7.2.9.tar.xz", "", "--sidecar", sums)
            self._main("linux-7.2.9.tar.gz", "", "--sidecar", sums)
        self.assertEqual(
            [line for line in self._lines() if line.startswith("sha256")],
            [f"sha256  {xz}  linux-7.2.9.tar.xz", f"sha256  {gz}  linux-7.2.9.tar.gz"],
        )

    def test_sidecar_with_a_lone_digest_and_uppercase_hex(self) -> None:
        """A bare digest file is accepted; the digest is written lowercase."""
        digest = "ABCDEF0123456789" * 4
        with _Origin({"/one.sha256": f"{digest}\n".encode()}) as origin:
            self._main("x.tar.xz", "", "--sidecar", f"{origin.base}/one.sha256")
        self.assertIn(f"sha256  {digest.lower()}  x.tar.xz", self._lines())

    def test_sidecar_without_the_file_is_fatal(self) -> None:
        """A checksum file that omits the tarball is an error, not a guess."""
        listing = f"{'a' * 64}  other.tar.xz\n{'b' * 64}  another.tar.xz\n"
        with _Origin({"/sums": listing.encode()}) as origin:
            message = self._fails("x.tar.xz", "", "--sidecar", f"{origin.base}/sums")
        self.assertIn("not listed", message)
        self.assertFalse(self.hash_file.exists())

    def test_sidecar_marker_is_written_once(self) -> None:
        """Two files from one sidecar share a single ``# From`` marker."""
        listing = f"{'a' * 64}  one.tar.xz\n{'b' * 64}  two.tar.xz\n"
        with _Origin({"/sums": listing.encode()}) as origin:
            sums = f"{origin.base}/sums"
            self._main("one.tar.xz", "", "--sidecar", sums)
            self._main("two.tar.xz", "", "--sidecar", sums)
            self.assertEqual(self._lines().count(f"# From {sums}"), 1)
        self.assertEqual(len([ln for ln in self._lines() if "sha256" in ln]), 2)

    def test_http_error_is_fatal(self) -> None:
        """A 404 stops the build with the URL and status in the message."""
        with _Origin({}) as origin:
            message = self._fails("x.tar.gz", f"{origin.base}/x.tar.gz")
        self.assertIn("404", message)
        self.assertFalse(self.hash_file.exists())

    def test_no_url_and_no_sidecar_is_fatal(self) -> None:
        """Without a sidecar or a download URL there is nothing to hash."""
        self.assertIn("no URL", self._fails("x.tar.gz", ""))

    def test_streams_tarball_into_dl_dir(self) -> None:
        """Without a sidecar the tarball is hashed while it is saved to DL_DIR."""
        payload = b"tarball-bytes" * 1000
        with _Origin({"/pkg-1.0.tar.gz": payload}) as origin:
            self._main("pkg-1.0.tar.gz", f"{origin.base}/pkg-1.0.tar.gz")
        self.assertEqual(self._lines()[:3], HASH_HEADER)
        self.assertEqual(self._lines()[-1], _sha256_line(payload, "pkg-1.0.tar.gz"))
        self.assertEqual((self.dl_dir / "pkg-1.0.tar.gz").read_bytes(), payload)
        self.assertEqual([p.name for p in self.dl_dir.iterdir()], ["pkg-1.0.tar.gz"])

    def test_truncated_download_is_not_hashed(self) -> None:
        """A body shorter than Content-Length must not produce a hash line."""
        with _Origin({"/p.tar.gz": b"z" * 4000}, truncated=["/p.tar.gz"]) as origin:
            message = self._fails("p.tar.gz", f"{origin.base}/p.tar.gz")
        self.assertIn("truncated", message)
        self.assertFalse(self.hash_file.exists())
        self.assertEqual(list(self.dl_dir.iterdir()), [])

    def test_post_process_hashes_the_rewritten_file(self) -> None:
        """Cargo-style post-process output, not the raw download, is hashed."""
        script = self._post_process_script(
            "while [ $# -gt 0 ]; do\n"
            "  case $1 in -o) out=$2; shift 2 ;; -n) name=$2; shift 2 ;;\n"
            "    *) rest=\"$rest $1\"; shift ;; esac\n"
            "done\n"
            "printf 'vendored:%s:%s' \"$name\" \"$rest\" > \"$out\"\n"
        )
        with _Origin({"/pkg.tar.gz": b"raw-archive"}) as origin:
            self._main(
                "pkg-1.0.tar.gz",
                f"{origin.base}/pkg.tar.gz",
                "--post-process",
                f"{script} -n pkg-1.0 --opt 'two words'",
            )
        vendored = b"vendored:pkg-1.0: --opt two words"
        self.assertEqual((self.dl_dir / "pkg-1.0.tar.gz").read_bytes(), vendored)
        self.assertEqual(self._lines()[-1], _sha256_line(vendored, "pkg-1.0.tar.gz"))
        self.assertEqual([p.name for p in self.dl_dir.iterdir()], ["pkg-1.0.tar.gz"])

    def test_post_process_failure_is_fatal(self) -> None:
        """A failing post-process leaves no hash line and no file behind."""
        script = self._post_process_script("exit 1\n")
        with _Origin({"/pkg.tar.gz": b"raw"}) as origin:
            message = self._fails(
                "pkg-1.0.tar.gz",
                f"{origin.base}/pkg.tar.gz",
                "--post-process",
                str(script),
            )
        self.assertIn("post-process", message)
        self.assertFalse(self.hash_file.exists())
        self.assertEqual(list(self.dl_dir.iterdir()), [])

    def test_append_keeps_existing_lines_and_fixes_a_missing_newline(self) -> None:
        """New lines go after existing ones, even if the file lacks a final \\n."""
        self.hash_file.parent.mkdir(parents=True)
        old = f"sha256  {'a' * 64}  old.tar.gz"
        self.hash_file.write_text(old, encoding="utf-8")
        payload = b"new"
        with _Origin({"/new.tar.gz": payload}) as origin:
            self._main("new.tar.gz", f"{origin.base}/new.tar.gz")
        self.assertEqual(
            self._lines(), [old, _sha256_line(payload, "new.tar.gz")]
        )


class FetchHashMakeTests(unittest.TestCase):
    """package/fetch-hash.mk under GNU make, with the real helper and a local origin.

    The stub makefile stands in for Buildroot: it defines the ``DEMO_*``
    variables a package would, ``qstrip``/``UPPERCASE``, and a ``run`` target
    that expands the package's PRE_DOWNLOAD_HOOKS the way pkg-generic.mk does.
    """

    STUB = """\
TOPDIR = {top}
TAR = tar
HOST_DIR = $(TOPDIR)/host
EXTRA_ENV =
qstrip = $(strip $(subst ",,$(1)))
UPPERCASE = $(shell echo '$(1)' | tr 'a-z-' 'A-Z_')
define sep


endef
PACKAGES_ALL = demo
PKG = DEMO
DEMO_RAWNAME = demo
DEMO_VERSION = 1.2.3
DEMO_SOURCE = demo-1.2.3.tar.gz
DEMO_SITE = {site}
DEMO_PKGDIR = $(TOPDIR)/package/demo
DEMO_HASH_FILES = $(DEMO_PKGDIR)/demo.hash
DEMO_DL_DIR = $(TOPDIR)/dl/demo
include $(TOPDIR)/package/fetch-hash.mk
{extra}
run:
\t$(foreach hook,$($(PKG)_PRE_DOWNLOAD_HOOKS),$(call $(hook))$(sep))
print:
\t@echo '$(FETCH_HASH_URL.$(KEY))'
showpython:
\t@echo '$(FETCH_HASH_PYTHON)'
"""

    def setUp(self) -> None:
        """Install fetch-hash.mk and the helper into a temp package/ dir."""
        if shutil.which("make") is None:
            self.skipTest("make is not installed")
        self.td = Path(tempfile.mkdtemp())
        package = self.td / "package"
        (package / "demo").mkdir(parents=True)
        for name in ("fetch-hash.mk", "fetch_hash_helper.py"):
            shutil.copy(PATCHES / name, package / name)
        self.hash_file = package / "demo" / "demo.hash"
        self.dl_demo = self.td / "dl" / "demo"

    def tearDown(self) -> None:
        """Remove the temp tree."""
        shutil.rmtree(self.td)

    def _make(
        self,
        target: str = "run",
        *,
        site: str = "",
        extra: str = "",
        python: str | None = sys.executable,
        **cmdline: str,
    ) -> subprocess.CompletedProcess[str]:
        """Run ``make <target>`` on the stub makefile and return the result."""
        stub = self.td / "stub.mk"
        stub.write_text(
            self.STUB.format(top=self.td, site=site or _dead_url(), extra=extra),
            encoding="utf-8",
        )
        argv = ["make", "-s", "-f", str(stub), target]
        if python:
            argv.append(f"FETCH_HASH_PYTHON={python}")
        argv += [f"{key}={value}" for key, value in cmdline.items()]
        return subprocess.run(argv, capture_output=True, text=True, check=False)

    def _ok(self, result: subprocess.CompletedProcess[str]) -> None:
        """Assert a make run succeeded, showing stderr if it did not."""
        self.assertEqual(result.returncode, 0, result.stderr)

    def _lines(self) -> list[str]:
        """Return the demo hash file's non-comment lines."""
        text = self.hash_file.read_text(encoding="utf-8")
        return [ln for ln in text.splitlines() if ln.startswith("sha256")]

    def test_sidecar_url_templates(self) -> None:
        """Make expands each FETCH_HASH_URL entry from the package's version."""
        bootlin = (
            "https://toolchains.bootlin.com/downloads/releases/toolchains/"
            "x86-64-v2/tarballs/x86-64-v2--glibc--stable-2026.08-1.sha256"
        )
        cases = [
            (
                "rust",
                "1.99.0",
                "https://static.rust-lang.org/dist/rustc-1.99.0-src.tar.xz.sha256",
            ),
            (
                "usbutils",
                "018",
                "https://www.kernel.org/pub/linux/utils/usb/usbutils/sha256sums.asc",
            ),
            (
                "linux",
                "7.2.9",
                "https://www.kernel.org/pub/linux/kernel/v7.x/sha256sums.asc",
            ),
            (
                "linux-headers",
                "6.17.1",
                "https://www.kernel.org/pub/linux/kernel/v6.x/sha256sums.asc",
            ),
            ("gcc-standalone-toolchain", "2026.08-1", bootlin),
            (
                "brush-docs.tar.gz",
                "v0.4.0",
                (
                    "https://github.com/reubeno/brush/releases/download/"
                    "brush-shell-v0.4.0/brush-docs.tar.gz.sha256"
                ),
            ),
        ]
        for key, version, expected in cases:
            with self.subTest(key=key):
                result = self._make(
                    "print",
                    KEY=key,
                    DEMO_VERSION=version,
                    GCC_STANDALONE_TOOLCHAIN_BOOTLIN_ARCH="x86-64-v2",
                    GCC_STANDALONE_TOOLCHAIN_BOOTLIN_LIBC="glibc",
                )
                self._ok(result)
                self.assertEqual(result.stdout.strip(), expected)

    def test_existing_hash_line_means_no_python(self) -> None:
        """A sha256 line for the tarball ends the hook before any network use."""
        line = f"sha256  {'0' * 64}  demo-1.2.3.tar.gz\n"
        self.hash_file.write_text(line, encoding="utf-8")
        self._ok(self._make())
        self.assertEqual(self.hash_file.read_text(encoding="utf-8"), line)
        self.assertFalse(self.dl_demo.exists())

    def test_only_an_exact_filename_counts_as_present(self) -> None:
        """Another file's line, or a longer name ending the same, is no match."""
        payload = b"demo"
        self.hash_file.write_text(
            f"sha256  {'0' * 64}  demo-1.2.2.tar.gz\n"
            f"sha256  {'1' * 64}  xdemo-1.2.3.tar.gz\n",
            encoding="utf-8",
        )
        with _Origin({"/demo-1.2.3.tar.gz": payload}) as origin:
            self._ok(self._make(site=origin.base))
        self.assertEqual(self._lines()[-1], _sha256_line(payload, "demo-1.2.3.tar.gz"))
        self.assertEqual(len(self._lines()), 3)

    def test_missing_hash_streams_the_tarball(self) -> None:
        """No hash file and no table entry: download once, hash, create the file."""
        payload = b"demo-tarball"
        with _Origin({"/demo-1.2.3.tar.gz": payload}) as origin:
            self._ok(self._make(site=origin.base))
        self.assertEqual(self._lines(), [_sha256_line(payload, "demo-1.2.3.tar.gz")])
        self.assertEqual((self.dl_demo / "demo-1.2.3.tar.gz").read_bytes(), payload)

    def test_table_entry_replaces_the_download(self) -> None:
        """A FETCH_HASH_URL entry supplies the digest; the tarball is not fetched."""
        digest = "d" * 64
        with _Origin({"/sums": f"{digest}  demo-1.2.3.tar.gz\n".encode()}) as origin:
            sums = f"{origin.base}/sums"
            self._ok(self._make(extra=f"FETCH_HASH_URL.demo = {sums}\n"))
            self.assertIn(f"# From {sums}", self.hash_file.read_text(encoding="utf-8"))
        self.assertEqual(self._lines(), [f"sha256  {digest}  demo-1.2.3.tar.gz"])
        self.assertFalse(self.dl_demo.exists())

    def test_extra_downloads_are_hashed_too(self) -> None:
        """EXTRA_DOWNLOADS get a line each; a table entry is keyed by basename."""
        tarball, blob, docs = b"main", b"blob", "e" * 64
        files = {
            "/demo-1.2.3.tar.gz": tarball,
            "/pub/blob.bin": blob,
            "/docs.sha256": f"{docs}  docs.tar.gz\n".encode(),
        }
        with _Origin(files) as origin:
            extra = (
                f"DEMO_EXTRA_DOWNLOADS = docs.tar.gz {origin.base}/pub/blob.bin\n"
                f"FETCH_HASH_URL.docs.tar.gz = {origin.base}/docs.sha256\n"
            )
            self._ok(self._make(site=origin.base, extra=extra))
        self.assertEqual(
            self._lines(),
            [
                _sha256_line(tarball, "demo-1.2.3.tar.gz"),
                f"sha256  {docs}  docs.tar.gz",
                _sha256_line(blob, "blob.bin"),
            ],
        )
        self.assertEqual(
            sorted(p.name for p in self.dl_demo.iterdir()),
            ["blob.bin", "demo-1.2.3.tar.gz"],
        )

    def test_post_process_runs_with_package_settings(self) -> None:
        """DOWNLOAD_POST_PROCESS, its name and opts reach the helper intact."""
        script = self.td / "support" / "download" / "fake-post-process"
        script.parent.mkdir(parents=True)
        script.write_text(
            "#!/bin/sh\n"
            "while [ $# -gt 0 ]; do\n"
            "  case $1 in -o) out=$2; shift 2 ;; -n) name=$2; shift 2 ;;\n"
            "    *) rest=\"$rest $1\"; shift ;; esac\n"
            "done\n"
            "printf 'vendored:%s:%s' \"$name\" \"$rest\" > \"$out\"\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        extra = (
            "DEMO_DOWNLOAD_POST_PROCESS = fake\n"
            "DEMO_DL_SUBDIR = demo\n"
            "DEMO_DOWNLOAD_POST_PROCESS_OPTS = --foo bar\n"
        )
        with _Origin({"/demo-1.2.3.tar.gz": b"raw"}) as origin:
            self._ok(self._make(site=origin.base, extra=extra))
        vendored = b"vendored:demo-1.2.3: --foo bar"
        self.assertEqual(self._lines(), [_sha256_line(vendored, "demo-1.2.3.tar.gz")])
        self.assertEqual((self.dl_demo / "demo-1.2.3.tar.gz").read_bytes(), vendored)

    def test_skips_leave_the_hash_file_alone(self) -> None:
        """VCS sites, local overrides, and BR_NO_CHECK_HASH_FOR names are skipped."""
        for extra in (
            "DEMO_SITE_METHOD = git\n",
            "DEMO_OVERRIDE_SRCDIR = /src/demo\n",
            "BR_NO_CHECK_HASH_FOR = other.tar.gz demo-1.2.3.tar.gz\n",
        ):
            with self.subTest(extra=extra.strip()):
                self._ok(self._make(extra=extra))
                self.assertFalse(self.hash_file.exists())

    def test_python_is_host_only_once_its_ca_bundle_is_installed(self) -> None:
        """Host python3 needs host-ca-certificates too; otherwise the distro one."""
        distro = "/usr/bin/python3"
        self.assertEqual(self._make("showpython", python=None).stdout.strip(), distro)
        host = self.td / "host" / "bin" / "python3"
        host.parent.mkdir(parents=True)
        marker = self.td / "host-python-used"
        host.write_text(
            f'#!/bin/sh\ntouch "{marker}"\nexec "{sys.executable}" "$@"\n',
            encoding="utf-8",
        )
        host.chmod(0o755)
        certs = self.td / "host" / "etc" / "ssl" / "certs"
        certs.mkdir(parents=True)
        for label in ("python3 but an empty certs dir", "python3 and symlinks only"):
            with self.subTest(label):
                (certs / "abcd1234.0").unlink(missing_ok=True)
                if "symlinks" in label:
                    (certs / "abcd1234.0").symlink_to("missing.pem")
                result = self._make("showpython", python=None)
                self.assertEqual(result.stdout.strip(), distro)
        (certs / "abcd1234.0").unlink(missing_ok=True)
        (certs / "ca-certificates.crt").write_text("bundle\n", encoding="utf-8")
        self.assertEqual(
            self._make("showpython", python=None).stdout.strip(), str(host)
        )
        payload = b"demo"
        with _Origin({"/demo-1.2.3.tar.gz": payload}) as origin:
            self._ok(self._make(site=origin.base, python=None))
        self.assertTrue(marker.exists())
        self.assertEqual(self._lines(), [_sha256_line(payload, "demo-1.2.3.tar.gz")])

    def test_ca_bundle_without_host_python_uses_the_distro_one(self) -> None:
        """The bundle alone is not enough; host/bin/python3 must exist as well."""
        certs = self.td / "host" / "etc" / "ssl" / "certs"
        certs.mkdir(parents=True)
        (certs / "ca-certificates.crt").write_text("bundle\n", encoding="utf-8")
        result = self._make("showpython", python=None)
        self.assertEqual(result.stdout.strip(), "/usr/bin/python3")

    def test_ignores_python3_from_the_host_tree(self) -> None:
        """A python3 that EXTRA_ENV puts first on PATH is never the interpreter.

        Buildroot's host python3 has no CA bundle, so TLS downloads fail with
        CERTIFICATE_VERIFY_FAILED; the hook must stay on the distro python.
        """
        trap = self.td / "host" / "bin" / "python3"
        trap.parent.mkdir(parents=True)
        trap.write_text("#!/bin/sh\necho host python used >&2\nexit 97\n")
        trap.chmod(0o755)
        extra = f'EXTRA_ENV = PATH="{trap.parent}:$(PATH)"\n'
        payload = b"demo"
        with _Origin({"/demo-1.2.3.tar.gz": payload}) as origin:
            self._ok(self._make(site=origin.base, extra=extra))
        self.assertEqual(self._lines(), [_sha256_line(payload, "demo-1.2.3.tar.gz")])

    def test_helper_failure_stops_make(self) -> None:
        """A 404 from the origin makes the hook, and so the build, fail."""
        with _Origin({}) as origin:
            result = self._make(site=origin.base)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ERROR: fetch-hash", result.stderr)
        self.assertFalse(self.hash_file.exists())


if __name__ == "__main__":
    unittest.main()
