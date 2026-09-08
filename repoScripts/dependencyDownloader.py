#!/usr/bin/env python3
"""Download a remote file into a script-relative output directory.

Relative output paths are resolved from this script's parent directory
(repoScripts/), not the process cwd. That keeps GitHub Actions and local
runs aligned when invoked as:

    python3 repoScripts/dependencyDownloader.py <url> ../resources/

Both the URL and the output directory are required. The stored filename is
taken from the URL (right-to-left until '/', '=', or an invalid filename
character). An existing file is overwritten only when its SHA-256 differs
from the freshly downloaded copy.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote
from urllib.request import Request, urlopen

SCRIPT_DIR = Path(__file__).resolve().parent

MEMORY_LIMIT_BYTES = 250 * 1024 * 1024  # 250 MiB
CHUNK_SIZE = 8192
HTTP_TIMEOUT_SECONDS = 120

# Characters that terminate the filename scan. Includes path/query
# delimiters plus characters illegal in Windows, macOS, or Linux names.
_INVALID_FILENAME_CHARS = set('<>:"/\\|?*=' + "".join(chr(i) for i in range(32)))

_USER_AGENT = (
    "OpenWRT-BuildEnv-dependencyDownloader/1.0 "
    "(+https://github.com/btbutts/OpenWRT-BuildEnv)"
)


def extract_filename(url: str) -> str:
    """Return the filename at the end of *url*.

    Characters are collected from the right until the first '/', '=', or
    any character that is not legal in a Windows/macOS/Linux filename.
    Percent-encoded sequences are decoded afterwards.
    """
    collected: list[str] = []
    for char in reversed(url.rstrip()):
        if char in _INVALID_FILENAME_CHARS:
            break
        collected.append(char)

    filename = unquote("".join(reversed(collected))).rstrip(" .")
    if not filename or filename in {".", ".."} or "/" in filename or "\\" in filename:
        raise ValueError(
            f"could not extract a valid filename from URL: {url!r}"
        )
    return filename


def resolve_output_dir(output_arg: str) -> Path:
    """Resolve *output_arg* relative to the script directory, then to absolute."""
    return (SCRIPT_DIR / output_arg).resolve()


def format_bytes(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    for unit, size in (("GiB", 1024**3), ("MiB", 1024**2), ("KiB", 1024)):
        if num_bytes >= size:
            return f"{num_bytes / size:.2f} {unit}"
    return f"{num_bytes} B"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def sha256_buffer(buffer: io.BytesIO) -> str:
    digest = hashlib.sha256()
    buffer.seek(0)
    while True:
        chunk = buffer.read(CHUNK_SIZE)
        if not chunk:
            break
        digest.update(chunk)
    buffer.seek(0)
    return digest.hexdigest()


def parse_content_length(headers) -> int | None:
    raw = headers.get("Content-Length")
    if raw is None or raw == "":
        return None
    try:
        length = int(raw)
    except (TypeError, ValueError):
        return None
    if length < 0:
        return None
    return length


def build_request(url: str) -> Request:
    return Request(
        url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept-Encoding": "identity",
        },
        method="GET",
    )


def iter_chunks(response, chunk_size: int = CHUNK_SIZE):
    while True:
        chunk = response.read(chunk_size)
        if not chunk:
            break
        yield chunk


def write_chunks(response, dest: Path) -> None:
    """Stream *response* to *dest* via a sibling .part file, then replace."""
    part_path = dest.with_name(dest.name + ".part")
    try:
        with part_path.open("wb") as handle:
            for chunk in iter_chunks(response):
                handle.write(chunk)
        part_path.replace(dest)
    except Exception:
        if part_path.exists():
            part_path.unlink()
        raise


def write_buffer(buffer: io.BytesIO, dest: Path) -> None:
    part_path = dest.with_name(dest.name + ".part")
    try:
        buffer.seek(0)
        with part_path.open("wb") as handle:
            handle.write(buffer.getbuffer())
        part_path.replace(dest)
    except Exception:
        if part_path.exists():
            part_path.unlink()
        raise


def stream_hash(response) -> str:
    digest = hashlib.sha256()
    for chunk in iter_chunks(response):
        digest.update(chunk)
    return digest.hexdigest()


def log(message: str) -> None:
    print(message, flush=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download a URL into an output directory resolved relative to "
            "this script's parent directory. Overwrites only when SHA-256 differs."
        )
    )
    parser.add_argument(
        "url",
        help="Remote URL. The filename is taken from the end of this URL.",
    )
    parser.add_argument(
        "output",
        nargs="?",
        default=None,
        help="Output directory, relative to this script's parent directory.",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="output_flag",
        default=None,
        metavar="DIR",
        help="Output directory (alternative to the positional argument).",
    )
    args = parser.parse_args(argv)

    output_dir = args.output_flag or args.output
    if not output_dir:
        parser.error(
            "an output directory is required "
            "(positional argument or -o/--output)"
        )
    if args.output_flag and args.output:
        parser.error(
            "provide the output directory as a positional argument "
            "or as -o/--output, not both"
        )
    args.output_dir = output_dir
    return args


def download(url: str, dest: Path) -> str:
    """Download *url* to *dest*.

    Returns one of: 'created', 'updated', 'unchanged'.
    """
    local_exists = dest.is_file()
    log(f"Local file exists : {local_exists}")

    executor: ThreadPoolExecutor | None = None
    local_hash_future: Future[str] | None = None
    if local_exists:
        executor = ThreadPoolExecutor(max_workers=1)
        local_hash_future = executor.submit(sha256_file, dest)

    try:
        request = build_request(url)
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            remote_size = parse_content_length(response.headers)
            if remote_size is None:
                log("Remote size      : unknown (no Content-Length); streaming")
                use_memory = False
            else:
                log(
                    f"Remote size      : {format_bytes(remote_size)} "
                    f"({remote_size} bytes)"
                )
                use_memory = remote_size <= MEMORY_LIMIT_BYTES

            if use_memory:
                log(
                    f"Transfer mode    : in-memory "
                    f"(<= {format_bytes(MEMORY_LIMIT_BYTES)})"
                )
                buffer = io.BytesIO(response.read())
            else:
                log("Transfer mode    : streaming (chunked SHA-256)")
                buffer = None

            if not local_exists:
                if buffer is not None:
                    write_buffer(buffer, dest)
                    buffer.close()
                else:
                    write_chunks(response, dest)
                return "created"

            # Local copy exists: compare SHA-256 before writing.
            if buffer is not None:
                remote_hash = sha256_buffer(buffer)
            else:
                remote_hash = stream_hash(response)

            assert local_hash_future is not None
            local_hash = local_hash_future.result()
            log(f"Remote SHA-256   : {remote_hash}")
            log(f"Local  SHA-256   : {local_hash}")

            if remote_hash == local_hash:
                if buffer is not None:
                    buffer.close()
                return "unchanged"

            if buffer is not None:
                write_buffer(buffer, dest)
                buffer.close()
                return "updated"

        # Streaming path, hashes differed: the first response body was
        # consumed for hashing, so fetch again and write directly.
        log("SHA-256 mismatch : re-downloading to overwrite local copy")
        with urlopen(build_request(url), timeout=HTTP_TIMEOUT_SECONDS) as response:
            write_chunks(response, dest)
        return "updated"
    finally:
        if executor is not None:
            executor.shutdown(wait=False)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        filename = extract_filename(args.url)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    output_dir = resolve_output_dir(args.output_dir)
    dest = output_dir / filename

    log(f"Script directory : {SCRIPT_DIR}")
    log(f"Output directory : {output_dir}")
    log(f"URL              : {args.url}")
    log(f"Filename         : {filename}")
    log(f"Destination      : {dest}")

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"error: cannot create output directory {output_dir}: {exc}", file=sys.stderr)
        return 1

    if dest.exists() and not dest.is_file():
        print(
            f"error: destination exists and is not a regular file: {dest}",
            file=sys.stderr,
        )
        return 1

    try:
        result = download(args.url, dest)
    except HTTPError as exc:
        print(f"error: HTTP {exc.code} for {args.url}: {exc.reason}", file=sys.stderr)
        return 1
    except URLError as exc:
        print(f"error: failed to fetch {args.url}: {exc.reason}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if result == "created":
        log(f"Wrote new file   : {dest}")
    elif result == "updated":
        log(f"Overwrote file   : {dest} (SHA-256 differed)")
    else:
        log(f"Left file intact : {dest} (SHA-256 matched; download discarded)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
