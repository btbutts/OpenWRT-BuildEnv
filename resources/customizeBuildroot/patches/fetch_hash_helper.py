#!/usr/bin/env python3
"""JIT sha256 lines for Buildroot package tarballs.

Executed only by package/fetch-hash.mk (system python3). Not imported by
customizeBuildroot. Sidecar URLs live here as FETCH_HASH_URLS so extra
downloads can have their own hash source under the same package name.

When a sidecar exists, only that small checksum file is fetched. When it
does not, the tarball is hashed in one pass: streamed to DL_DIR, or
written through $(PKG)_DOWNLOAD_POST_PROCESS (cargo vendor, ...) so
dl-wrapper reuses the same bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

USER_AGENT = "Buildroot fetch-hash-helper"

# Outer key is $($(PKG)_RAWNAME). Inner key is the tarball basename;
# "" is the main source tarball only (never used for EXTRA_DOWNLOADS).
# Placeholders: {version} {major} {minor} plus --subst keys.
FETCH_HASH_URLS: dict[str, dict[str, str]] = {
    "rust": {
        "": "https://static.rust-lang.org/dist/rustc-{version}-src.tar.xz.sha256",
    },
    "usbutils": {
        "": "https://www.kernel.org/pub/linux/utils/usb/usbutils/sha256sums.asc",
    },
    "linux": {
        "": "https://www.kernel.org/pub/linux/kernel/v{major}.x/sha256sums.asc",
    },
    "linux-headers": {
        "": "https://www.kernel.org/pub/linux/kernel/v{major}.x/sha256sums.asc",
    },
    "gcc-standalone-toolchain": {
        "": (
            "https://toolchains.bootlin.com/downloads/releases/toolchains/"
            "{bootlin_arch}/tarballs/"
            "{bootlin_arch}--{bootlin_libc}--stable-{major}.{minor}.sha256"
        ),
    },
    "brush": {
        "brush-docs.tar.gz": (
            "https://github.com/reubeno/brush/"
            "releases/download/brush-shell-v{version}/brush-docs.tar.gz.sha256"
        ),
    },
}

_SHA256_HEX = re.compile(r"^[0-9a-fA-F]{64}$")
_CHUNK = 1024 * 1024


def split_version(version: str) -> tuple[str, str, str]:
    """Return (version, major, minor) with a leading v stripped."""
    ver = version.strip()
    if ver.startswith(("v", "V")):
        ver = ver[1:]
    if "." in ver:
        major, minor = ver.split(".", 1)
    else:
        major, minor = ver, ""
    return ver, major, minor


def substitutions(version: str, subst: list[str]) -> dict[str, str]:
    """Build the format mapping from --version and --subst KEY=VALUE."""
    ver, major, minor = split_version(version)
    mapping = {"version": ver, "major": major, "minor": minor}
    for item in subst:
        if "=" not in item:
            raise SystemExit(f"ERROR: fetch-hash: invalid --subst {item!r}")
        key, value = item.split("=", 1)
        mapping[key] = value
    return mapping


def format_url(template: str, mapping: dict[str, str]) -> str:
    """Expand {placeholders} in a sidecar URL template."""
    try:
        return template.format(**mapping)
    except KeyError as exc:
        raise SystemExit(
            f"ERROR: fetch-hash: sidecar URL missing substitution {exc}"
        ) from exc


def lookup_sidecar(
    pkg: str,
    filename: str,
    *,
    is_extra: bool,
    mapping: dict[str, str],
) -> str | None:
    """Return the sidecar URL for *filename*, or None.

    Exact filename keys win. The package default ``""`` applies only to
    the main tarball, never to EXTRA_DOWNLOADS.
    """
    files = FETCH_HASH_URLS.get(pkg)
    if not files:
        return None
    template = files.get(filename)
    if template is None and not is_extra:
        template = files.get("")
    if not template:
        return None
    return format_url(template, mapping)


def parse_sidecar_hash(text: str, filename: str) -> str | None:
    """Return the sha256 for *filename* from a sidecar checksum file.

    Matches the basename of the second field so a CI absolute path such
    as ``.../brush-docs.tar.gz`` still hits. A lone 64-hex line is used
    only when the file has no named entries.
    """
    base = Path(filename).name
    named: str | None = None
    lone: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "-----")):
            continue
        if line.lower().startswith(("hash:", "version:", "comment:")):
            continue
        parts = line.split()
        if not parts:
            continue
        digest = parts[0]
        if not _SHA256_HEX.fullmatch(digest):
            continue
        if len(parts) == 1:
            lone.append(digest)
            continue
        name = parts[1].removeprefix("*")
        if Path(name).name == base or name in {base, f"./{base}"}:
            named = digest
            break
    if named:
        return named
    if len(lone) == 1:
        return lone[0]
    return None


def hash_line_present(hash_file: Path, filename: str) -> bool:
    """True when *hash_file* already has a sha256 line for *filename*."""
    if not hash_file.is_file():
        return False
    for line in hash_file.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "sha256" and parts[-1] == filename:
            return True
    return False


def ensure_hash_file(hash_file: Path, pkg: str) -> None:
    """Create an empty auto-generated hash file, or fail for linux."""
    if hash_file.is_file():
        return
    if pkg in {"linux", "linux-headers"}:
        raise SystemExit(f"ERROR: fetch-hash: missing {hash_file}")
    hash_file.parent.mkdir(parents=True, exist_ok=True)
    hash_file.write_text(
        "#\n# Automatically generated file; DO NOT EDIT.\n#\n",
        encoding="utf-8",
    )


def append_hash(
    hash_file: Path,
    digest: str,
    filename: str,
    source: str | None = None,
) -> None:
    """Append a sha256 line, with an optional ``# From <url>`` marker."""
    hash_file.parent.mkdir(parents=True, exist_ok=True)
    if not hash_file.exists():
        hash_file.write_text(
            "#\n# Automatically generated file; DO NOT EDIT.\n#\n",
            encoding="utf-8",
        )
    text = hash_file.read_text(encoding="utf-8")
    extra = ""
    if source:
        marker = f"# From {source}"
        if marker not in text:
            extra += f"\n{marker}\n"
    extra += f"sha256  {digest}  {filename}\n"
    if extra.startswith("\n") and not text.endswith("\n"):
        extra = "\n" + extra
    with hash_file.open("a", encoding="utf-8") as handle:
        handle.write(extra)
    print(f"--> Appended sha256  {digest}  {filename} to {hash_file}")


def _urlopen(url: str, timeout: int = 120):
    """Open *url* with a fixed User-Agent; SystemExit on HTTP errors."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise SystemExit(
            f"ERROR: fetch-hash: failed to download {url}: HTTP {exc.code}"
        ) from exc
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"ERROR: fetch-hash: failed to download {url}: {exc.reason}"
        ) from exc


def fetch_text(url: str) -> str:
    """Download a small sidecar as text."""
    with _urlopen(url, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def stream_sha256(url: str, dest: Path | None = None) -> str:
    """Hash *url* in one pass. When *dest* is set, write it as *dest*.part."""
    hasher = hashlib.sha256()
    part: Path | None = None
    try:
        with _urlopen(url) as resp:
            if dest is None:
                while True:
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    hasher.update(chunk)
                return hasher.hexdigest()
            dest.parent.mkdir(parents=True, exist_ok=True)
            part = dest.parent / (dest.name + ".part")
            with part.open("wb") as out:
                while True:
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    hasher.update(chunk)
                    out.write(chunk)
            part.replace(dest)
            part = None
    finally:
        if part is not None and part.exists():
            part.unlink()
    return hasher.hexdigest()


def file_sha256(path: Path) -> str:
    """Return the sha256 of an existing file."""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_CHUNK)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def download_post_process(
    url: str,
    dest_name: str,
    dl_dir: Path,
    work_dir: Path,
    post_process_bin: str,
    post_process_name: str,
    post_process_opts: list[str],
) -> str:
    """Download *url*, run the Buildroot post-process, hash, leave in DL_DIR."""
    if not post_process_bin:
        raise SystemExit(
            f"ERROR: fetch-hash: DOWNLOAD_POST_PROCESS set but no helper for {dest_name}"
        )
    work_dir.mkdir(parents=True, exist_ok=True)
    tmpd = Path(tempfile.mkdtemp(prefix=".fetch-hash.", dir=str(work_dir)))
    tmpf = tmpd / "output"
    try:
        stream_sha256(url, dest=tmpf)
        cmd = [
            post_process_bin,
            "-o",
            str(tmpf),
            "-n",
            post_process_name,
            *post_process_opts,
        ]
        try:
            subprocess.run(cmd, cwd=tmpd, check=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise SystemExit(
                f"ERROR: fetch-hash: {Path(post_process_bin).name} "
                f"failed for {dest_name}"
            ) from exc
        digest = file_sha256(tmpf)
        dl_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmpf), str(dl_dir / dest_name))
        return digest
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)


def fetch_one(
    *,
    pkg: str,
    filename: str,
    url: str,
    is_extra: bool,
    hash_file: Path,
    dl_dir: Path,
    work_dir: Path,
    mapping: dict[str, str],
    skip: set[str],
    post_process: str,
    post_process_bin: str,
    post_process_name: str,
    post_process_opts: list[str],
) -> None:
    """Append a sha256 line for one tarball if the hash file lacks it."""
    if not filename or filename in skip:
        return
    if hash_line_present(hash_file, filename):
        return
    sidecar = lookup_sidecar(pkg, filename, is_extra=is_extra, mapping=mapping)
    if sidecar:
        digest = parse_sidecar_hash(fetch_text(sidecar), filename)
        if not digest:
            raise SystemExit(
                f"ERROR: fetch-hash: {filename} not listed at {sidecar}"
            )
        append_hash(hash_file, digest, filename, source=sidecar)
        return
    if not url or url == "/":
        raise SystemExit(f"ERROR: fetch-hash: no URL for {filename}")
    if post_process and not is_extra:
        digest = download_post_process(
            url=url,
            dest_name=filename,
            dl_dir=dl_dir,
            work_dir=work_dir,
            post_process_bin=post_process_bin,
            post_process_name=post_process_name,
            post_process_opts=post_process_opts,
        )
    else:
        digest = stream_sha256(url, dest=dl_dir / filename)
    append_hash(hash_file, digest, filename, source=None)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """CLI used by fetch-hash.mk."""
    parser = argparse.ArgumentParser(
        description="JIT sha256 lines for Buildroot package tarballs."
    )
    parser.add_argument("--pkg", required=True, help="Package raw name")
    parser.add_argument("--version", default="", help="Package version")
    parser.add_argument("--hash-file", required=True, type=Path)
    parser.add_argument("--dl-dir", required=True, type=Path)
    parser.add_argument("--tarball", default="", help="Main source basename")
    parser.add_argument("--tarball-url", default="", help="Main source URL")
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument(
        "--no-check",
        default="",
        help="Space-separated BR_NO_CHECK_HASH_FOR names",
    )
    parser.add_argument("--post-process", default="")
    parser.add_argument("--post-process-bin", default="")
    parser.add_argument("--post-process-name", default="")
    parser.add_argument("--post-process-opts", default="")
    parser.add_argument(
        "--subst",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Extra sidecar placeholder, e.g. bootlin_arch=x86-64-v2",
    )
    parser.add_argument(
        "--extra",
        nargs=2,
        action="append",
        default=[],
        metavar=("NAME", "URL"),
        help="Extra download basename and URL (repeatable)",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> None:
    """Ensure the hash file exists, then hash the main tarball and extras."""
    ensure_hash_file(args.hash_file, args.pkg)
    mapping = substitutions(args.version, args.subst)
    skip = {part for part in args.no_check.split() if part}
    opts = shlex.split(args.post_process_opts) if args.post_process_opts else []
    shared = {
        "pkg": args.pkg,
        "hash_file": args.hash_file,
        "dl_dir": args.dl_dir,
        "work_dir": args.work_dir,
        "mapping": mapping,
        "skip": skip,
        "post_process": args.post_process,
        "post_process_bin": args.post_process_bin,
        "post_process_name": args.post_process_name,
        "post_process_opts": opts,
    }
    fetch_one(
        filename=args.tarball,
        url=args.tarball_url,
        is_extra=False,
        **shared,
    )
    for name, url in args.extra:
        fetch_one(filename=name, url=url, is_extra=True, **shared)


def main(argv: list[str] | None = None) -> int:
    """Entry point for fetch-hash.mk. Returns 0 on success, 1 on error."""
    try:
        run(parse_args(argv))
    except SystemExit as exc:
        if isinstance(exc.code, int):
            return exc.code
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
