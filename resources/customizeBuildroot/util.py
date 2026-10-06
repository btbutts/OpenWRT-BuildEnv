"""Shared helpers for Buildroot Kconfig and makefile patches."""

from __future__ import annotations

import inspect
from pathlib import Path

_MESON_PACKAGE_EVAL = "$(eval $(meson-package))\n"


def kconfig_package_symbol(package_name: str) -> str:
    """
    Return the ``BR2_PACKAGE_*`` symbol for a package directory name.

    Hyphens become underscores and the rest is uppercased, matching
    Buildroot (``gcc-standalone-toolchain`` →
    ``BR2_PACKAGE_GCC_STANDALONE_TOOLCHAIN``).
    """
    return "BR2_PACKAGE_" + package_name.replace("-", "_").upper()


def write_if_changed(path: Path, original: str, updated: str, message: str) -> None:
    """Write *updated* when it differs; otherwise say the hunk is present."""
    if updated == original:
        print(f"--> {message} already present in {path}")
        return
    path.write_text(updated)
    print(f"--> {message} in {path}")


def insert_kconfig_after_if(text: str, if_line: str, symbol: str, block: str) -> str:
    """
    Insert *block* immediately after ``if <pkg>`` when *symbol* is absent.

    Raises SystemExit if *if_line* is missing.
    """
    if f"config {symbol}\n" in text:
        return text
    needle = f"{if_line}\n"
    idx = text.find(needle)
    if idx < 0:
        raise SystemExit(f"Error: {if_line!r} not found")
    at = idx + len(needle)
    return text[:at] + "\n" + block + "\n" + text[at:]


def insert_before_meson_eval(text: str, tail: str, already: str) -> str:
    """Insert *tail* before the first meson-package eval unless *already* is present."""
    if already in text:
        return text
    idx = text.find(_MESON_PACKAGE_EVAL)
    if idx < 0:
        raise SystemExit("Error: $(eval $(meson-package)) not found")
    return text[:idx] + tail + "\n" + text[idx:]


def tarball_fetch_hash_fragment(
    pkg: str,
    hash_filename: str,
    user_agent: str,
    *,
    error_label: str | None = None,
    host_hooks: bool = False,
) -> str:
    """
    Return a makefile fragment that JIT-appends a sha256 line for a tarball.

    Same pattern as ``hexedit.mk`` / ``sharutils.mk``: if ``$(PKG_HASH_FILE)``
    already has a ``sha256`` line whose last field is ``$(PKG_SOURCE)``, do
    nothing. Otherwise download ``$(PKG_SITE)/$(PKG_SOURCE)`` and append the
    hash. Register with ``PKG_PRE_DOWNLOAD_HOOKS`` immediately before
    ``$(eval $(*-package))``. Callers wrap this in an override ``ifneq``
    when the hook should run only for a version override.
    """
    label = error_label or pkg.lower().replace("_", "-")
    host_line = (
        f"HOST_{pkg}_PRE_DOWNLOAD_HOOKS += {pkg}_FETCH_HASH\n" if host_hooks else ""
    )
    # Note: Every indented line inside the define block below starts with groups of 4 spaces.
    # First, inspect.cleandoc strips out the shared base indentation of the function.
    # Then we swap the relative 4-space blocks for true tabs (\t).
    fetch_hash_fragment = inspect.cleandoc(
        """
        # Immediate assignment: recursive $(MAKEFILE_LIST) at download time is
        # docs/manual/, not this package. Buildroot reads hashes from PKGDIR.
        {pkg}_HASH_FILE := $(dir $(lastword $(MAKEFILE_LIST))){hash_filename}
        define {pkg}_FETCH_HASH
            mkdir -p $(dir $({pkg}_HASH_FILE))
            if [ ! -f $({pkg}_HASH_FILE) ]; then \\
                printf '%s\\n' \\
                    '#' \\
                    '# Automatically generated file; DO NOT EDIT.' \\
                    '#' \\
                    > $({pkg}_HASH_FILE); \\
            fi
            if ! awk -v f="$({pkg}_SOURCE)" \\
                '$$1 == "sha256" && $$NF == f { found = 1 } END { exit !found }' \\
                $({pkg}_HASH_FILE); then \\
                tmp=$$(mktemp); \\
                if ! wget -qO "$$tmp" --header='User-Agent: {user_agent}' \\
                    "$({pkg}_SITE)/$({pkg}_SOURCE)"; then \\
                    rm -f "$$tmp"; \\
                    echo "ERROR: {label}: failed to download $({pkg}_SITE)/$({pkg}_SOURCE)" >&2; \\
                    exit 1; \\
                fi; \\
                sum=$$(sha256sum "$$tmp" | awk '{print $$1}'); \\
                rm -f "$$tmp"; \\
                printf 'sha256  %s  %s\\n' "$$sum" "$({pkg}_SOURCE)" \\
                    >> $({pkg}_HASH_FILE); \\
            fi
        endef
        {pkg}_PRE_DOWNLOAD_HOOKS += {pkg}_FETCH_HASH
        {host_line}
        """
    )
    return (
        fetch_hash_fragment.replace("{pkg}", pkg)
        .replace("{hash_filename}", hash_filename)
        .replace("{user_agent}", user_agent)
        .replace("{label}", label)
        .replace("{host_line}", host_line)
        .replace("    ", "\t")
    )


def drop_br_no_check_hash_for(text: str, token: str) -> str:
    """Remove ``BR_NO_CHECK_HASH_FOR`` lines that mention *token*."""
    return "".join(
        line
        for line in text.splitlines(keepends=True)
        if not (
            line.lstrip().startswith("BR_NO_CHECK_HASH_FOR") and token in line
        )
    )
