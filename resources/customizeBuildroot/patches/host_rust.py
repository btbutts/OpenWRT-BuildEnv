"""Bump rust, rust-bin, and rust-bindgen versions from container env vars."""

from __future__ import annotations

import os
import re
from pathlib import Path

from ..util import write_if_changed
from .fetch_hash import write_fetch_hash_mk

# Env vars are the only version source. No fallbacks; blank means skip.
RUST_VERSION_ENV = "RUST_VERSION"
RUST_BINDGEN_VERSION_ENV = "RUST_BINDGEN_VERSION"

_VERSION_NUMBER = re.compile(r"^[0-9]+(\.[0-9]+)+$")

SKIP_RUST = (
    "--> Skipping rust and rust-bin: RUST_VERSION is unset or has no "
    "version number.\n"
    "    Declare RUST_VERSION in scriptVars.env to patch them."
)
SKIP_BINDGEN = (
    "--> Skipping rust-bindgen: RUST_BINDGEN_VERSION is unset or has no "
    "version number.\n"
    "    Declare RUST_BINDGEN_VERSION in scriptVars.env to patch it."
)


def env_version(name: str) -> str:
    """
    Return the version string in environment variable *name*.

    Unset, blank, quoted-blank, and values with no dotted version number
    all return ``""``. There is no default.
    """
    raw = os.environ.get(name)
    if raw is None:
        return ""
    value = raw.strip().strip('"').strip("'").strip()
    if not value or _VERSION_NUMBER.fullmatch(value) is None:
        return ""
    return value


def assignment_key(line: str) -> str | None:
    """Return the makefile key for a ``KEY = value`` line, else ``None``."""
    stripped = line.lstrip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key = stripped.split("=", 1)[0].rstrip()
    if key.endswith(":"):
        key = key[:-1].rstrip()
    if not key or any(ch.isspace() for ch in key):
        return None
    return key


def set_makefile_assignment(path: Path, key: str, value: str) -> None:
    """
    Replace the first ``KEY = ...`` assignment in *path*.

    ConfigObj cannot parse makefile ``$(eval ...)`` lines, so this is a
    line scan. The rest of the file, including comments and recipes, is
    left unchanged.
    """
    text = path.read_text(encoding="utf-8")
    original = text
    lines = text.splitlines(keepends=True)
    found = False
    updated: list[str] = []
    for line in lines:
        if not found and assignment_key(line) == key:
            indent = line[: len(line) - len(line.lstrip())]
            eol = "\n" if line.endswith("\n") else ""
            updated.append(f"{indent}{key} = {value}{eol}")
            found = True
        else:
            updated.append(line)
    if not found:
        raise SystemExit(f"Error: {key} assignment not found in {path}")
    write_if_changed(
        path, original, "".join(updated), f"{key} = {value}"
    )


def update_rust_version(br_path: Path) -> None:
    """
    Patch rust / rust-bin / rust-bindgen versions from the environment.

    ``RUST_VERSION`` sets both ``package/rust/rust.mk`` (``RUST_VERSION``)
    and ``package/rust-bin/rust-bin.mk`` (``RUST_BIN_VERSION``).
    ``RUST_BINDGEN_VERSION`` sets ``package/rust-bindgen/rust-bindgen.mk``.
    Each pair is independent: a blank variable skips that patch and
    prints how to set it. Both blank is a no-op. Does not run
    ``customize_buildroot``.
    """
    config_in = br_path / "Config.in"
    if not config_in.is_file():
        raise SystemExit(
            f"Error: Buildroot is not extracted at {br_path} (missing Config.in)."
        )

    rust_ver = env_version(RUST_VERSION_ENV)
    bindgen_ver = env_version(RUST_BINDGEN_VERSION_ENV)
    rust_mk = br_path / "package" / "rust" / "rust.mk"
    rust_bin_mk = br_path / "package" / "rust-bin" / "rust-bin.mk"
    bindgen_mk = br_path / "package" / "rust-bindgen" / "rust-bindgen.mk"
    patched = False

    if rust_ver:
        missing = [p for p in (rust_mk, rust_bin_mk) if not p.is_file()]
        if missing:
            names = ", ".join(str(p) for p in missing)
            raise SystemExit(
                f"Error: --update-rust-version needs these files: {names}"
            )
        set_makefile_assignment(rust_mk, "RUST_VERSION", rust_ver)
        set_makefile_assignment(rust_bin_mk, "RUST_BIN_VERSION", rust_ver)
        patched = True
    else:
        print(SKIP_RUST)

    if bindgen_ver:
        if not bindgen_mk.is_file():
            raise SystemExit(
                f"Error: --update-rust-version needs these files: {bindgen_mk}"
            )
        set_makefile_assignment(
            bindgen_mk, "RUST_BINDGEN_VERSION", bindgen_ver
        )
        patched = True
    else:
        print(SKIP_BINDGEN)

    if patched:
        write_fetch_hash_mk(br_path)
        print("--> update-rust-version completed successfully.")
        return
    print("--> --update-rust-version: nothing to patch.")
