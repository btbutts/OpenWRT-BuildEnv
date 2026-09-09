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
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote

import requests

SCRIPT_DIR = Path(__file__).resolve().parent

MEMORY_LIMIT_BYTES = 250 * 1024 * 1024  # 250 MiB
CHUNK_SIZE = 8192
HTTP_TIMEOUT_SECONDS = 120

# Characters that terminate the filename scan. Includes path/query
# delimiters plus characters illegal in Windows, macOS, or Linux names.
_INVALID_FILENAME_CHARS = set('<>:"/\\|?*=' + "".join(chr(i) for i in range(32)))

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/152.0.4196.66 Safari/537.36 Edg/152.0.4196.66"
)

_REQUEST_HEADERS = {
    "User-Agent": _USER_AGENT,
    # Identity so Content-Length matches the bytes we hash/write. requests
    # would otherwise advertise gzip and decompress, making the header lie.
    "Accept-Encoding": "identity",
}

_MIB = 1024 * 1024


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
    """Return *num_bytes* as a human-readable size string."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    for unit, size in (("GiB", 1024**3), ("MiB", 1024**2), ("KiB", 1024)):
        if num_bytes >= size:
            return f"{num_bytes / size:.2f} {unit}"
    return f"{num_bytes} B"


def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest for a file at *path*."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def sha256_buffer(buffer: io.BytesIO) -> str:
    """Return the SHA-256 hex digest for the current contents of *buffer*."""
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
    """Return the parsed Content-Length value, or None if unavailable."""
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


class ProgressMeter:
    """Redraw a single stderr line with download / hash progress.

    Uses carriage return (like wget/curl) so the meter occupies one
    terminal row instead of scrolling. In streaming SHA-256 mode the
    total chunk count is ceil(Content-Length / CHUNK_SIZE).
    """

    def __init__(
        self,
        total_bytes: int | None,
        chunk_size: int,
        show_chunks: bool,
    ) -> None:
        self.total_bytes = total_bytes
        self.chunk_size = chunk_size
        self.show_chunks = show_chunks
        self.bytes_done = 0
        self.chunks_done = 0
        if total_bytes is None:
            self.total_chunks: int | None = None
        else:
            self.total_chunks = (total_bytes + chunk_size - 1) // chunk_size
        self._last_draw = 0.0
        self._last_width = 0
        self._drawn = False

    def update(self, nbytes: int) -> None:
        """Account for one received chunk and redraw at ~20 Hz."""
        self.bytes_done += nbytes
        self.chunks_done += 1
        now = time.monotonic()
        if now - self._last_draw < 0.05:
            return
        self._draw()
        self._last_draw = now

    def close(self) -> None:
        """Force a final draw, then advance to the next line."""
        self._draw()
        if self._drawn:
            sys.stderr.write("\n")
            sys.stderr.flush()
            self._drawn = False

    def _render(self) -> str:
        downloaded = self.bytes_done / _MIB
        if self.total_bytes is not None:
            total = self.total_bytes / _MIB
            pct = (
                100.0 * self.bytes_done / self.total_bytes
                if self.total_bytes
                else 100.0
            )
            byte_part = f"{downloaded:8.2f} / {total:8.2f} MiB ({pct:5.1f}%)"
        else:
            byte_part = f"{downloaded:8.2f} MiB"

        if not self.show_chunks:
            return f"Downloading: {byte_part}"

        if self.total_chunks is not None:
            width = max(len(str(self.total_chunks)), 1)
            chunk_part = (
                f"{self.chunks_done:{width}d} chunks hashed / "
                f"{self.total_chunks} total chunks"
            )
        else:
            chunk_part = f"{self.chunks_done} chunks hashed"
        return f"Downloading: {byte_part} | {chunk_part}"

    def _draw(self) -> None:
        line = self._render()
        pad = max(self._last_width - len(line), 0)
        sys.stderr.write("\r" + line + (" " * pad))
        sys.stderr.flush()
        self._last_width = len(line)
        self._drawn = True


def consume_chunks(
    response: requests.Response,
    total_bytes: int | None,
    show_chunks: bool,
    on_chunk,
) -> None:
    """Feed each response body chunk to *on_chunk* while updating progress."""
    meter = ProgressMeter(total_bytes, CHUNK_SIZE, show_chunks)
    try:
        for chunk in iter_chunks(response):
            on_chunk(chunk)
            meter.update(len(chunk))
    finally:
        meter.close()


def new_session() -> requests.Session:
    """Create a preconfigured session for dependency downloads."""
    session = requests.Session()
    session.headers.update(_REQUEST_HEADERS)
    return session


def get_response(session: requests.Session, url: str) -> requests.Response:
    """Fetch a URL as a streamed response and fail fast on HTTP errors."""
    response = session.get(url, stream=True, timeout=HTTP_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response


def iter_chunks(response: requests.Response, chunk_size: int = CHUNK_SIZE):
    """Yield non-empty content chunks from a streamed HTTP response."""
    for chunk in response.iter_content(chunk_size=chunk_size):
        if chunk:  # drop keep-alive padding
            yield chunk


def write_chunks(
    response: requests.Response,
    dest: Path,
    total_bytes: int | None = None,
) -> None:
    """Stream *response* to *dest* via a sibling .part file, then replace."""
    part_path = dest.with_name(dest.name + ".part")
    try:
        with part_path.open("wb") as handle:
            consume_chunks(response, total_bytes, False, handle.write)
        part_path.replace(dest)
    except Exception:
        if part_path.exists():
            part_path.unlink()
        raise


def write_buffer(buffer: io.BytesIO, dest: Path) -> None:
    """
    Write buffer contents to output dir via
    a sibling .part file, then replace.
    """
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


def read_into_buffer(
    response: requests.Response,
    total_bytes: int | None = None,
) -> io.BytesIO:
    """Download a response body into an in-memory buffer with progress."""
    buffer = io.BytesIO()
    consume_chunks(response, total_bytes, False, buffer.write)
    buffer.seek(0)
    return buffer


def stream_hash(
    response: requests.Response,
    total_bytes: int | None = None,
) -> str:
    """Return the SHA-256 hash of a streamed response body."""
    digest = hashlib.sha256()
    consume_chunks(response, total_bytes, True, digest.update)
    return digest.hexdigest()


def log(message: str) -> None:
    """Print a message to stdout."""
    print(message, flush=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the dependency downloader."""
    parser = argparse.ArgumentParser(
        description=(
            "Download a URL into an output directory resolved relative to this "
            "script's parent directory. Overwrites only when sha256sum differs."
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
        with new_session() as session:
            with get_response(session, url) as response:
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
                    buffer = read_into_buffer(response, remote_size)
                else:
                    log("Transfer mode    : streaming (chunked SHA-256)")
                    buffer = None

                if not local_exists:
                    if buffer is not None:
                        write_buffer(buffer, dest)
                        buffer.close()
                    else:
                        write_chunks(response, dest, remote_size)
                    return "created"

                # Local copy exists: compare SHA-256 before writing.
                if buffer is not None:
                    remote_hash = sha256_buffer(buffer)
                else:
                    remote_hash = stream_hash(response, remote_size)

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
            with get_response(session, url) as response:
                remote_size = parse_content_length(response.headers)
                write_chunks(response, dest, remote_size)
            return "updated"
    finally:
        if executor is not None:
            executor.shutdown(wait=False)


def main(argv: list[str] | None = None) -> int:
    """Run the dependency downloader CLI."""
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
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        reason = exc.response.reason if exc.response is not None else exc
        print(f"error: HTTP {status} for {args.url}: {reason}", file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(f"error: failed to fetch {args.url}: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if result == "created":
        log(f"Wrote new file   : {dest}")
    elif result == "updated":
        log(f"Overwrote file   : {dest}\n(SHA-256 differed)")
    else:
        log(f"Left file intact : {dest}\n(SHA-256 matched; download discarded)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
