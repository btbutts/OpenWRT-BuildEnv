"""Keep man/info/doc trees when BR2_KEEP_MAN_PAGES_DOCS is enabled."""

from __future__ import annotations

import inspect
from pathlib import Path

from ..util import tabbed

KEEP_MAN_OPTION_BLOCK = tabbed(inspect.cleandoc("""
    config BR2_KEEP_MAN_PAGES_DOCS
        bool "Keep manual pages and documentation on target"
        default n
        help
          By default, Buildroot aggressively purges all man, info,
          and doc directories during target finalization to save
          space. Enable this option to retain full documentation.
"""))

USR_DOC_TOKEN = "$(TARGET_DIR)/usr/doc"
USR_DOC_COMMENT = "#\trm -rf $(TARGET_DIR)/usr/doc\n"
KEEP_DOCS_IFNEQ = "ifneq ($(BR2_KEEP_MAN_PAGES_DOCS),y)\n"
KEEP_DOCS_ENDIF = "endif\n"


def find_last_endmenu(lines: list[str]) -> int:
    """
    Return the index of the last ``endmenu`` line in *lines*.

    Raises SystemExit if the file has no ``endmenu``.
    """
    last = None
    for i, line in enumerate(lines):
        if line.strip() == "endmenu":
            last = i
    if last is None:
        raise SystemExit("Error: no endmenu found")
    return last


def patch_config_in(path: Path) -> None:
    """
    Insert BR2_KEEP_MAN_PAGES_DOCS in the top-level Config.in.

    Places the keep-docs option immediately before the last ``endmenu``.
    Custom packages are sourced from the br2-external tree, not from
    this file.
    """
    text = path.read_text()
    if "config BR2_KEEP_MAN_PAGES_DOCS" in text:
        print(f"--> BR2_KEEP_MAN_PAGES_DOCS already present in {path}")
        return

    lines = text.splitlines(keepends=True)
    last_endmenu = find_last_endmenu(lines)
    insert = []
    if last_endmenu > 0 and lines[last_endmenu - 1].strip() != "":
        insert.append("\n")
    insert.append(KEEP_MAN_OPTION_BLOCK)
    insert.append("\n")
    lines[last_endmenu:last_endmenu] = insert
    path.write_text("".join(lines))
    print(f"--> Inserted BR2_KEEP_MAN_PAGES_DOCS before last endmenu in {path}")


def wrap_with_keep_docs_guard(block: str) -> str:
    """
    Wrap a Makefile fragment in ``ifneq ($(BR2_KEEP_MAN_PAGES_DOCS),y)``.

    Used around the target-finalize man/info/doc purge so enabling
    BR2_KEEP_MAN_PAGES_DOCS leaves those trees in the rootfs.
    """
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
