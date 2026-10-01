#!/usr/bin/env python3
"""Patch an extracted Buildroot tree: keep man/docs and install custom packages."""

from __future__ import annotations

import argparse
import inspect
import os
import shutil
import sys
from pathlib import Path


def default_br_path() -> Path:
    """Return the Buildroot root, honoring the shared container env when set."""
    value = os.environ.get("BUILDROOT_BUILDER_DIR") or "/builder/Buildroot-Builder"
    trimmed = value.rstrip("/")
    return Path(trimmed) if trimmed else Path("/builder/Buildroot-Builder")


def default_custom_package_dir() -> Path:
    """
    Return the staged custom-package tree.

    Prefers ``BUILDROOT_CONF_DIR/custom_package``, then a sibling of this
    script (repo / ``/builder/buildrootConf/custom_package``).
    """
    env = os.environ.get("BUILDROOT_CONF_DIR")
    if env:
        return Path(env.rstrip("/")) / "custom_package"
    sibling = Path(__file__).resolve().parent / "buildrootConf" / "custom_package"
    if sibling.is_dir():
        return sibling
    return Path("/builder/buildrootConf/custom_package")


DEFAULT_BR_PATH = default_br_path()
DEFAULT_CUSTOM_PACKAGE_DIR = default_custom_package_dir()

KEEP_MAN_OPTION_BLOCK = inspect.cleandoc("""
    config BR2_KEEP_MAN_PAGES_DOCS
	    bool "Keep manual pages and documentation on target"
	    default n
	    help
	      By default, Buildroot aggressively purges all man, info,
	      and doc directories during target finalization to save
	      space. Enable this option to retain full documentation.
""")

USR_DOC_TOKEN = "$(TARGET_DIR)/usr/doc"
USR_DOC_COMMENT = "#\trm -rf $(TARGET_DIR)/usr/doc\n"
KEEP_DOCS_IFNEQ = "ifneq ($(BR2_KEEP_MAN_PAGES_DOCS),y)\n"
KEEP_DOCS_ENDIF = "endif\n"


def source_line_for(package_name: str) -> str:
    """Return the Config.in source statement for a custom package."""
    return f'source "package/{package_name}/Config.in"'


def iter_custom_packages(custom_dir: Path) -> list[Path]:
    """
    Return staged custom-package directories under *custom_dir*.

    A package is a subdirectory that contains a ``Config.in``. Names are
    sorted so Config.in source order is stable across runs.
    """
    if not custom_dir.is_dir():
        raise SystemExit(f"Error: custom package directory not found: {custom_dir}")
    packages = [
        path
        for path in custom_dir.iterdir()
        if path.is_dir() and (path / "Config.in").is_file()
    ]
    return sorted(packages, key=lambda p: p.name)


def patch_config_in(path: Path, packages: list[Path] | None = None) -> None:
    """
    Insert BR2_KEEP_MAN_PAGES_DOCS and source custom packages in Config.in.

    Places the keep-docs Kconfig option immediately before the last ``endmenu``
    and appends ``source "package/<name>/Config.in"`` for each staged custom
    package. Skips either edit when the corresponding text is already present.
    """
    text = path.read_text()
    changed = False

    if "config BR2_KEEP_MAN_PAGES_DOCS" not in text:
        lines = text.splitlines(keepends=True)
        last_endmenu = None
        for i, line in enumerate(lines):
            if line.strip() == "endmenu":
                last_endmenu = i
        if last_endmenu is None:
            raise SystemExit(f"Error: no endmenu found in {path}")
        insert = []
        if last_endmenu > 0 and lines[last_endmenu - 1].strip() != "":
            insert.append("\n")
        insert.append(
            KEEP_MAN_OPTION_BLOCK
            if KEEP_MAN_OPTION_BLOCK.endswith("\n")
            else KEEP_MAN_OPTION_BLOCK + "\n"
        )
        insert.append("\n")
        lines[last_endmenu:last_endmenu] = insert
        text = "".join(lines)
        changed = True
        print(f"--> Inserted BR2_KEEP_MAN_PAGES_DOCS before last endmenu in {path}")
    else:
        print(f"--> BR2_KEEP_MAN_PAGES_DOCS already present in {path}")

    for package in packages or []:
        line = source_line_for(package.name)
        if line not in text:
            text = text.rstrip("\n") + "\n\n" + line + "\n"
            changed = True
            print(f"--> Appended {line} to {path}")
        else:
            print(f"--> {line} already present in {path}")

    if changed:
        path.write_text(text)


def wrap_with_keep_docs_guard(block: str) -> str:
    """Wrap a Makefile fragment so it runs only when docs are not kept."""
    return f"{KEEP_DOCS_IFNEQ}{block}{KEEP_DOCS_ENDIF}"


def _recipe_body(line: str) -> str:
    """Return a recipe line without leading tabs or a trailing newline."""
    return line.lstrip("\t").rstrip("\n")


def _ends_with_continuation(line: str) -> bool:
    """True when a Makefile line continues onto the next physical line."""
    return line.rstrip("\n").rstrip().endswith("\\")


def find_target_finalize_span(lines: list[str]) -> tuple[int, int]:
    """
    Return [start, end) line indexes covering the target-finalize rule.

    Starts at ``.PHONY: target-finalize`` and runs until the next ``.PHONY:``
    so later Buildroot edits inside the rule still stay in range.
    """
    start = None
    for i, line in enumerate(lines):
        if line.startswith(".PHONY:") and "target-finalize" in line:
            start = i
            break
    if start is None:
        raise SystemExit("Error: .PHONY: target-finalize not found in Makefile")

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith(".PHONY:"):
            end = i
            break
    return start, end


def collect_continued_command(lines: list[str], start: int, end: int) -> int:
    """
    Return the exclusive end index of a backslash-continued command.

    *start* is the first physical line of the command. Following lines that
    complete a trailing ``\\`` are included. *end* is the search limit.
    """
    i = start
    while i < end:
        i += 1
        if not _ends_with_continuation(lines[i - 1]):
            break
    return i


def _strip_usr_doc_token(line: str) -> str:
    """Remove ``$(TARGET_DIR)/usr/doc`` as a whole path token from *line*."""
    token = USR_DOC_TOKEN
    body = line.rstrip("\n")
    newline = "\n" if line.endswith("\n") else ""
    continued = body.rstrip().endswith("\\")
    core = body.rstrip()
    if continued:
        core = core[:-1].rstrip()
    prefix_len = len(core) - len(core.lstrip("\t"))
    prefix = core[:prefix_len]
    rest = core[prefix_len:]
    parts = rest.split()
    parts = [p for p in parts if p != token]
    rebuilt = prefix + " ".join(parts)
    if continued:
        rebuilt = rebuilt.rstrip() + " \\"
    return rebuilt + newline


def strip_usr_doc_from_first_rm(lines: list[str], start: int, end: int) -> bool:
    """
    Drop usr/doc from the first ``rm -rf`` under target-finalize.

    That command is the first recipe ``rm -rf`` after ``target-finalize:``,
    including backslash-continued lines. The live token is removed wherever
    it sits; ``USR_DOC_COMMENT`` is inserted immediately below the command.
    """
    rule = None
    for i in range(start, end):
        if lines[i].startswith("target-finalize:"):
            rule = i
            break
    if rule is None:
        raise SystemExit("Error: target-finalize: rule header not found in Makefile")

    rm_start = None
    for i in range(rule + 1, end):
        body = _recipe_body(lines[i]).lstrip()
        if body.startswith("rm -rf"):
            rm_start = i
            break
    if rm_start is None:
        raise SystemExit(
            "Error: first rm -rf in target-finalize not found in Makefile"
        )

    rm_end = collect_continued_command(lines, rm_start, end)
    after = lines[rm_end] if rm_end < len(lines) else ""
    joined = "".join(lines[rm_start:rm_end])
    if USR_DOC_TOKEN not in joined:
        if after == USR_DOC_COMMENT:
            print("--> First target-finalize usr/doc purge already disabled")
            return False
        if after.lstrip("#").lstrip() == "rm -rf $(TARGET_DIR)/usr/doc\n":
            lines[rm_end] = USR_DOC_COMMENT
            print("--> Normalized usr/doc comment to use a tab after #")
            return True
        raise SystemExit(
            "Error: first target-finalize rm -rf does not mention "
            f"{USR_DOC_TOKEN} and has no retention comment"
        )

    new_cmd = [_strip_usr_doc_token(lines[i]) for i in range(rm_start, rm_end)]
    new_cmd = [ln for ln in new_cmd if ln.lstrip("\t").rstrip("\\\n ").strip()]
    if new_cmd and _ends_with_continuation(new_cmd[-1]):
        new_cmd[-1] = new_cmd[-1].rstrip("\n").rstrip().removesuffix("\\").rstrip() + "\n"
    replacement = new_cmd + [USR_DOC_COMMENT]
    lines[rm_start:rm_end] = replacement
    print("--> Removed usr/doc from the first target-finalize rm -rf")
    return True


def wrap_man_purge_block(lines: list[str], start: int, end: int) -> bool:
    """
    Guard the man/info/doc purge with BR2_KEEP_MAN_PAGES_DOCS.

    Locates the recipe ``rm -rf`` that names ``usr/man``, then consumes
    following recipe lines through the ``rmdir`` of ``$(TARGET_DIR)/usr/share``.
    Extra rm lines in that span are kept and wrapped.
    """
    man_start = None
    for i in range(start, end):
        body = _recipe_body(lines[i])
        if "usr/man" in body and "usr/share/man" in body and "rm -rf" in body:
            man_start = i
            break
    if man_start is None:
        raise SystemExit(
            "Error: usr/man purge line not found in target-finalize"
        )

    prev = lines[man_start - 1] if man_start > 0 else ""
    if prev == KEEP_DOCS_IFNEQ:
        print("--> Man/doc purge already wrapped with BR2_KEEP_MAN_PAGES_DOCS")
        return False

    rmdir_idx = None
    gtk_found = False
    for i in range(man_start, end):
        body = _recipe_body(lines[i])
        if "gtk-doc" in body:
            gtk_found = True
        if body.lstrip().startswith("rmdir") and "$(TARGET_DIR)/usr/share" in body:
            rmdir_idx = i
            break
        if i > man_start and not lines[i].startswith("\t"):
            break
    if rmdir_idx is None:
        raise SystemExit(
            "Error: rmdir $(TARGET_DIR)/usr/share not found after usr/man purge"
        )
    if not gtk_found:
        raise SystemExit(
            "Error: gtk-doc purge not found between usr/man and usr/share rmdir"
        )

    block = "".join(lines[man_start : rmdir_idx + 1])
    lines[man_start : rmdir_idx + 1] = [wrap_with_keep_docs_guard(block)]
    print("--> Wrapped man/info/doc purge with BR2_KEEP_MAN_PAGES_DOCS")
    return True


def patch_makefile(path: Path) -> None:
    """
    Stop target-finalize from always deleting man, info, and doc trees.

    Finds the target-finalize rule structurally, strips usr/doc from its first
    ``rm -rf``, and wraps the man/info/doc purge in
    ``ifneq ($(BR2_KEEP_MAN_PAGES_DOCS),y)``.
    """
    lines = path.read_text().splitlines(keepends=True)
    start, end = find_target_finalize_span(lines)
    changed = strip_usr_doc_from_first_rm(lines, start, end)
    start, end = find_target_finalize_span(lines)
    changed = wrap_man_purge_block(lines, start, end) or changed
    if changed:
        path.write_text("".join(lines))


def install_custom_packages(br_path: Path, custom_dir: Path) -> list[Path]:
    """
    Copy each staged custom package into ``br_path/package/<name>/``.

    Creates the destination directory. Regular files in the staged package
    are copied (overwriting on re-run so the overlay stays the source of
    truth). Returns the package directories that were installed.
    """
    packages = iter_custom_packages(custom_dir)
    if not packages:
        raise SystemExit(f"Error: no custom packages with Config.in in {custom_dir}")

    dest_root = br_path / "package"
    dest_root.mkdir(parents=True, exist_ok=True)

    for src in packages:
        dest = dest_root / src.name
        dest.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            if not item.is_file():
                continue
            shutil.copy2(item, dest / item.name)
        print(f"--> Installed custom package {src.name} -> {dest}")
    return packages


def customize_buildroot(
    br_path: Path,
    custom_package_dir: Path | None = None,
) -> None:
    """
    Apply all Buildroot source patches under the extracted tree *br_path*.

    Requires Config.in and Makefile at the tree root. Copies every package
    from *custom_package_dir* (default: ``default_custom_package_dir()``)
    into ``package/<name>/`` and sources each Config.in.
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

    packages = install_custom_packages(br_path, custom_dir)
    patch_config_in(config_in, packages)
    patch_makefile(makefile)
    print("--> customizeBuildroot.py completed successfully.")


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
            "Patch extracted Buildroot sources for man/docs retention "
            "and install staged custom packages."
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
            "Staged custom packages (default: BUILDROOT_CONF_DIR/custom_package "
            f"or {DEFAULT_CUSTOM_PACKAGE_DIR})"
        ),
    )
    args = parser.parse_args(argv)
    customize_buildroot(args.br_path, args.custom_package_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
