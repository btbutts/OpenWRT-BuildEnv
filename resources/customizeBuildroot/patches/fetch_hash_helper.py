#!/usr/bin/env python3
"""Append a missing sha256 line to a Buildroot .hash file.

Run by package/fetch-hash.mk (system python3) once per file, and only when
HASH_FILE has no line for NAME yet. The digest comes from, in order:

  --sidecar URL        a checksum file published next to the tarball
  --post-process CMD   the tarball as rewritten by CMD (cargo vendor, ...)
  (neither)            the tarball itself, hashed while it streams to disk

A downloaded tarball is left in --dl-dir, where Buildroot's dl-wrapper finds
it matching the new hash line instead of fetching it a second time.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import io
import re
import shlex
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import BinaryIO

USER_AGENT = "Buildroot fetch-hash"
HEADER = "#\n# Automatically generated file; DO NOT EDIT.\n#\n"
SHA256_HEX = re.compile(r"[0-9a-fA-F]{64}")


def fetch(url: str, out: BinaryIO) -> str:
    """Copy *url* into *out* and return the sha256 of the bytes received."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    digest, size = hashlib.sha256(), 0
    try:
        with urllib.request.urlopen(request, timeout=120) as resp:
            while chunk := resp.read(1 << 20):
                digest.update(chunk)
                out.write(chunk)
                size += len(chunk)
            expected = resp.headers.get("Content-Length")
    except (OSError, http.client.HTTPException) as exc:
        sys.exit(f"ERROR: fetch-hash: failed to download {url}: {exc}")
    # read() returns b"" on a connection dropped early; only Content-Length tells.
    if expected and int(expected) != size:
        sys.exit(f"ERROR: fetch-hash: {url} truncated: {size} of {expected} bytes")
    return digest.hexdigest()


def sidecar_digest(url: str, name: str) -> str:
    """Return the sha256 that the checksum file at *url* lists for *name*."""
    listing = io.BytesIO()
    fetch(url, listing)
    lone = []
    for line in listing.getvalue().decode("utf-8", "replace").splitlines():
        fields = line.split()
        if not fields or not SHA256_HEX.fullmatch(fields[0]):
            continue  # PGP armor, comments, blank lines
        if len(fields) == 1:
            lone.append(fields[0])
        elif fields[1].lstrip("*").rsplit("/", 1)[-1] == name:
            return fields[0].lower()
    if len(lone) == 1:  # a bare "<digest>" file describes its only tarball
        return lone[0].lower()
    sys.exit(f"ERROR: fetch-hash: {name} not listed at {url}")


def tarball_digest(url: str, name: str, dl_dir: Path, post_process: str) -> str:
    """Save *url* as dl_dir/name (through *post_process*, if any); return its sha256."""
    dl_dir.mkdir(parents=True, exist_ok=True)
    # Beside the destination so the final rename never crosses filesystems.
    with tempfile.TemporaryDirectory(prefix=".fetch-hash.", dir=dl_dir) as tmp:
        output = Path(tmp) / "output"
        with output.open("wb") as out:
            digest = fetch(url, out)
        if post_process:
            try:
                subprocess.run(
                    [*shlex.split(post_process), "-o", str(output)], cwd=tmp, check=True
                )
            except (OSError, subprocess.CalledProcessError) as exc:
                sys.exit(f"ERROR: fetch-hash: post-process failed for {name}: {exc}")
            with output.open("rb") as rewritten:
                digest = hashlib.file_digest(rewritten, "sha256").hexdigest()
        output.replace(dl_dir / name)
    return digest


def append_hash(hash_file: Path, digest: str, name: str, source: str = "") -> None:
    """Append a sha256 line, creating *hash_file* with a header if it is new."""
    hash_file.parent.mkdir(parents=True, exist_ok=True)
    with hash_file.open("a+", encoding="utf-8") as handle:
        handle.seek(0)
        text = handle.read()
        if not text:
            handle.write(HEADER)
        elif not text.endswith("\n"):
            handle.write("\n")
        if source and f"# From {source}" not in text:
            handle.write(f"\n# From {source}\n")
        handle.write(f"sha256  {digest}  {name}\n")
    print(f"--> Appended sha256  {digest}  {name} to {hash_file}")


def main(argv: list[str] | None = None) -> None:
    """Parse the command line and append the missing hash line."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n", 1)[0])
    parser.add_argument("hash_file", type=Path)
    parser.add_argument("name", help="tarball name as Buildroot looks it up")
    parser.add_argument("url", help="where to download NAME (unused with --sidecar)")
    parser.add_argument("--dl-dir", type=Path, required=True)
    parser.add_argument("--sidecar", default="", help="URL of a checksum file")
    parser.add_argument("--post-process", default="", help="command run as CMD -o FILE")
    args = parser.parse_args(argv)

    if args.sidecar:
        digest = sidecar_digest(args.sidecar, args.name)
    elif args.url:
        digest = tarball_digest(args.url, args.name, args.dl_dir, args.post_process)
    else:
        sys.exit(f"ERROR: fetch-hash: no URL for {args.name}")
    append_hash(args.hash_file, digest, args.name, args.sidecar)


if __name__ == "__main__":
    main()
