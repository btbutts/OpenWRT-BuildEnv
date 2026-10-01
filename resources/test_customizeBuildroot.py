#!/usr/bin/env python3
"""Tests for structural Makefile patching in customizeBuildroot.py."""

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
        self.td = Path(tempfile.mkdtemp())
        self.mk = self.td / "Makefile"
        shutil.copy(SAMPLE, self.mk)

    def tearDown(self) -> None:
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

    # pylint: disable-next=C0116
    def test_sample_strips_usr_doc_from_first_rm_and_comments_it(self) -> None:
        cb.patch_makefile(self.mk)
        text = self.mk.read_text()
        first_rm = self._first_rm_span(text)
        self.assertNotIn("$(TARGET_DIR)/usr/doc", first_rm)
        self.assertIn("$(TARGET_DIR)/usr/lib/rpm", first_rm)
        self.assertIn("#\trm -rf $(TARGET_DIR)/usr/doc\n", text)

    # pylint: disable-next=C0116
    def test_sample_wraps_man_info_doc_purge(self) -> None:
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

    # pylint: disable-next=C0116
    def test_first_rm_survives_extra_path_on_last_line(self) -> None:
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

    # pylint: disable-next=C0116
    def test_man_wrap_survives_extra_rm_before_rmdir(self) -> None:
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

    # pylint: disable-next=C0116
    def test_space_indented_comment_is_normalized_to_tab(self) -> None:
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

    # pylint: disable-next=C0116
    def test_patch_is_idempotent(self) -> None:
        cb.patch_makefile(self.mk)
        once = self.mk.read_text()
        cb.patch_makefile(self.mk)
        self.assertEqual(once, self.mk.read_text())
        self.assertEqual(once.count("ifneq ($(BR2_KEEP_MAN_PAGES_DOCS),y)"), 1)
        self.assertEqual(once.count("#\trm -rf $(TARGET_DIR)/usr/doc\n"), 1)


class CustomPackageInstallTests(unittest.TestCase):
    """Staged custom packages are copied and sourced into Config.in."""

    def setUp(self) -> None:
        self.td = Path(tempfile.mkdtemp())
        self.custom = self.td / "custom_package"
        self.br = self.td / "Buildroot-Builder"
        self.br.mkdir()
        shutil.copy(SAMPLE, self.br / "Makefile")
        (self.br / "Config.in").write_text(
            "menu \"Target options\"\nendmenu\n",
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

    def tearDown(self) -> None:
        shutil.rmtree(self.td)

    def test_default_custom_package_dir_uses_conf_env(self) -> None:
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
        cb.customize_buildroot(self.br, self.custom)
        groff_dest = self.br / "package" / "groff"
        gcc_dest = self.br / "package" / "gcc-standalone-toolchain"
        self.assertTrue((groff_dest / "Config.in").is_file())
        self.assertTrue((groff_dest / "groff.mk").is_file())
        self.assertTrue((gcc_dest / "Config.in").is_file())
        self.assertTrue((gcc_dest / "gcc-standalone-toolchain.mk").is_file())
        self.assertEqual((groff_dest / "groff.mk").read_text(), "# groff.mk\n")
        config = (self.br / "Config.in").read_text()
        self.assertIn("config BR2_KEEP_MAN_PAGES_DOCS", config)
        self.assertIn('source "package/gcc-standalone-toolchain/Config.in"', config)
        self.assertIn('source "package/groff/Config.in"', config)
        gcc_at = config.index('source "package/gcc-standalone-toolchain/Config.in"')
        groff_at = config.index('source "package/groff/Config.in"')
        self.assertLess(gcc_at, groff_at)

    def test_install_is_idempotent(self) -> None:
        cb.customize_buildroot(self.br, self.custom)
        once = (self.br / "Config.in").read_text()
        cb.customize_buildroot(self.br, self.custom)
        self.assertEqual(once, (self.br / "Config.in").read_text())
        self.assertEqual(once.count('source "package/groff/Config.in"'), 1)


if __name__ == "__main__":
    unittest.main()
