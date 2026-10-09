"""Disk discovery and installer-boot-media identification.

The installer is a ramdisk; the USB/SD/NVMe stick it booted from is only the
GRUB + payload volume and must never be offered as a RAID member. The stick is
identified, in order, by:

1. ``/run/installer-media-id`` (written by installer-bootlog.service)
2. ``installer.uuid=<fs uuid>`` (passed on the kernel line by GRUB)
3. a mounted volume holding the installer payload files
4. ``media.sh installer_discover`` (the legacy probing, as a last resort)

If none of these succeed ``find_media`` returns None and the flow fails closed
(see ``flow.step_disks``): the user must confirm the selected disks by hand.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from . import paths

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

log = logging.getLogger(__name__)

# Names that look like disks but are never install targets (mirrors media.sh).
VIRTUAL_PREFIXES = ("nbd", "loop", "ram", "zram", "sr", "fd", "md", "dm-", "zd")
ALLOWED_PREFIXES = ("sd", "nvme", "vd", "hd", "mmcblk", "xvd", "ub", "usb")

# Same markers as media.sh installer_media_here().
PAYLOAD_FILES = (
    "boot/vmlinuz-installer",
    "boot/initramfs-installer.img",
    "openwrt-rootfs.tar.gz",
    "openwrt-boot.tar.gz",
    "openwrt-custom-x86-64-rootfs.tar.gz",
    "openwrt-custom-x86-64-boot.tar.gz",
)

GIB = 1024**3
TIB = 1024 * GIB
LSBLK_TIMEOUT = 30
PROBE_TIMEOUT = 60
PROBE_FIELDS = 2  # "<part> <disk>"
UUID_POLL_SECONDS = 1.0
_IGNORED_MOUNTS = ("/", "[SWAP]")


def is_virtual_name(name: str) -> bool:
    """Return whether a block device name is a virtual (never a target) device."""
    return name.startswith(VIRTUAL_PREFIXES)


def is_allowed_name(name: str) -> bool:
    """Return whether a block device name looks like a real SATA/NVMe/USB/... disk."""
    return not is_virtual_name(name) and name.startswith(ALLOWED_PREFIXES)


@dataclass(frozen=True)
class Hardware:
    """Physical facts about a block device."""

    model: str
    tran: str
    removable: bool


@dataclass(frozen=True)
class Filesystem:
    """Filesystem facts about a block device."""

    fstype: str
    uuid: str
    mountpoints: tuple[str, ...]


@dataclass(frozen=True)
class Block:
    """One lsblk node (disk, partition, md, ...) with its children."""

    name: str
    type: str
    size: int
    hw: Hardware
    fs: Filesystem
    children: tuple[Block, ...] = ()

    def walk(self) -> Iterator[Block]:
        """Yield this node and all of its descendants."""
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass(frozen=True)
class Disk:
    """A whole disk that may be offered as a RAID member."""

    name: str
    size_bytes: int
    model: str
    tran: str
    removable: bool

    @property
    def size_gib(self) -> int:
        """Return the size in whole GiB (what the shell scripts call GB)."""
        return self.size_bytes // GIB

    def label(self) -> str:
        """Return the one-line description shown in the disk list."""
        if self.size_bytes >= TIB:
            size = f"{self.size_bytes / TIB:.1f} TiB"
        else:
            size = f"{self.size_bytes / GIB:.1f} GiB"
        parts = [f"{self.name:<9}", f"{size:>10}"]
        extra = " ".join(p for p in (self.model, self.tran) if p)
        if extra:
            parts.append(extra)
        if self.removable:
            parts.append("(removable)")
        return "  ".join(parts)


@dataclass(frozen=True)
class InstallerMedia:
    """The volume the installer booted from."""

    part: str
    disk: str
    source: str  # which identification step succeeded (for the log)


# --- lsblk -------------------------------------------------------------------


def _truthy(value: object) -> bool:
    """Interpret lsblk's boolean spellings (JSON bool, 0/1, "0"/"1")."""
    return value in (True, 1, "1", "true", "True")


def _parse_node(raw: dict) -> Block:
    """Convert one lsblk JSON node (recursively) into a Block."""
    mounts = raw.get("mountpoints")
    if mounts is None:
        mounts = [raw.get("mountpoint")]
    return Block(
        name=raw.get("name") or "",
        type=raw.get("type") or "",
        size=int(raw.get("size") or 0),
        hw=Hardware(
            model=(raw.get("model") or "").strip(),
            tran=(raw.get("tran") or "").strip(),
            removable=_truthy(raw.get("rm")),
        ),
        fs=Filesystem(
            fstype=(raw.get("fstype") or "").strip(),
            uuid=(raw.get("uuid") or "").strip(),
            mountpoints=tuple(m for m in mounts if m),
        ),
        children=tuple(_parse_node(c) for c in raw.get("children") or ()),
    )


def parse_lsblk(text: str) -> list[Block]:
    """Parse ``lsblk -J`` output into top-level Blocks."""
    data = json.loads(text)
    return [_parse_node(n) for n in data.get("blockdevices", [])]


def _lsblk(*, plural_mounts: bool) -> subprocess.CompletedProcess[str]:
    """Run ``lsblk -J -b``; older util-linux only knows MOUNTPOINT (singular)."""
    if plural_mounts:
        return subprocess.run(
            [
                "/usr/bin/lsblk",
                "-J",
                "-b",
                "-o",
                "NAME,TYPE,SIZE,MODEL,TRAN,RM,FSTYPE,UUID,MOUNTPOINTS",
            ],
            capture_output=True,
            text=True,
            timeout=LSBLK_TIMEOUT,
            check=False,
        )
    return subprocess.run(
        ["/usr/bin/lsblk", "-J", "-b", "-o", "NAME,TYPE,SIZE,MODEL,TRAN,RM,FSTYPE,UUID,MOUNTPOINT"],
        capture_output=True,
        text=True,
        timeout=LSBLK_TIMEOUT,
        check=False,
    )


def read_devices() -> list[Block]:
    """Return the block device tree from lsblk (empty list when lsblk fails)."""
    for plural_mounts in (True, False):
        try:
            result = _lsblk(plural_mounts=plural_mounts)
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("lsblk failed: %s", exc)
            return []
        if result.returncode == 0 and result.stdout.strip():
            return parse_lsblk(result.stdout)
    return []


# --- installer media identification -----------------------------------------


def read_cmdline_uuid(cmdline: str | None = None) -> str | None:
    """Return the ``installer.uuid=`` value from the kernel command line, if any."""
    if cmdline is None:
        try:
            cmdline = Path(paths.PROC_CMDLINE).read_text(encoding="utf-8")
        except OSError:
            return None
    for token in cmdline.split():
        if token.startswith("installer.uuid="):
            return token.split("=", 1)[1] or None
    return None


def read_id_file(path: str = paths.ID_FILE) -> tuple[str, str] | None:
    """Return (partition, disk) from the media id file, or None if absent."""
    part = disk = ""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if key == "INSTALLER_PART":
            part = value.strip()
        elif key == "INSTALLER_DISK":
            disk = value.strip()
    return (part, disk or part) if part else None


def has_payload(root: str | Path) -> bool:
    """Return whether a directory holds any installer payload marker file."""
    base = Path(root)
    return any((base / name).exists() for name in PAYLOAD_FILES)


def _top_disk(devices: list[Block], name: str) -> Block | None:
    """Return the top-level disk that contains a node called ``name``."""
    for disk in devices:
        if any(node.name == name for node in disk.walk()):
            return disk
    return None


def probe_with_media_sh() -> tuple[str, str] | None:
    """Run the legacy media.sh probing; its own UUID wait is skipped (done already)."""
    if not Path(paths.MEDIA_SH).exists():
        return None
    env = {**os.environ, "INSTALLER_MEDIA_SH": paths.MEDIA_SH, "INSTALLER_UUID_WAIT": "0"}
    try:
        result = subprocess.run(
            ["/bin/bash", "-c", '. "$INSTALLER_MEDIA_SH"; installer_print_identity'],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT,
            env=env,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    fields = result.stdout.split()
    if result.returncode == 0 and len(fields) == PROBE_FIELDS:
        return fields[0], fields[1]
    return None


@dataclass
class UuidWait:
    """How long, and how, to wait for the ``installer.uuid`` device to appear."""

    timeout: float = 20.0
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], float] = time.monotonic


@dataclass
class MediaSources:
    """Where installer media identification gets its information (injectable)."""

    read: Callable[[], list[Block]] = read_devices
    id_file: str = paths.ID_FILE
    cmdline: str | None = None
    wait: UuidWait = field(default_factory=UuidWait)
    payload_check: Callable[[str], bool] = has_payload
    probe: Callable[[], tuple[str, str] | None] = probe_with_media_sh


class _Finder:
    """Runs the identification steps in order against one MediaSources."""

    def __init__(self, sources: MediaSources) -> None:
        """Read the device tree once; the UUID step may refresh it."""
        self.src = sources
        self.devices = sources.read()

    def by_id_file(self) -> InstallerMedia | None:
        """Use the id file written by installer-bootlog.service."""
        ident = read_id_file(self.src.id_file)
        if ident is None:
            return None
        part, disk = ident
        if _top_disk(self.devices, disk) is not None:
            return InstallerMedia(part, disk, "id-file")
        log.warning("id file names %s but it is not present in lsblk", disk)
        return None

    def _match_uuid(self, uuid: str) -> InstallerMedia | None:
        """Return the node whose filesystem UUID matches, case-insensitively."""
        for disk in self.devices:
            for node in disk.walk():
                if node.fs.uuid and node.fs.uuid.lower() == uuid.lower():
                    return InstallerMedia(node.name, disk.name, "cmdline-uuid")
        return None

    def by_uuid(self) -> InstallerMedia | None:
        """Use ``installer.uuid=`` from GRUB, waiting for slow USB enumeration."""
        uuid = read_cmdline_uuid(self.src.cmdline)
        if not uuid:
            return None
        deadline = self.src.wait.now() + self.src.wait.timeout
        while True:
            media = self._match_uuid(uuid)
            if media is not None:
                return media
            if self.src.wait.now() >= deadline:
                break
            self.src.wait.sleep(UUID_POLL_SECONDS)
            self.devices = self.src.read()
        log.warning("installer.uuid=%s never appeared in lsblk", uuid)
        return None

    def by_mounts(self) -> InstallerMedia | None:
        """Use any mounted volume that holds the installer payload."""
        for disk in self.devices:
            for node in disk.walk():
                for mount in node.fs.mountpoints:
                    if mount not in _IGNORED_MOUNTS and self.src.payload_check(mount):
                        return InstallerMedia(node.name, disk.name, "mounted-payload")
        return None

    def by_probe(self) -> InstallerMedia | None:
        """Fall back to the legacy media.sh probing."""
        found = self.src.probe()
        if found is None:
            return None
        part, disk = found
        self.devices = self.src.read()
        if _top_disk(self.devices, disk) is not None:
            return InstallerMedia(part, disk, "media.sh")
        return None

    def run(self) -> InstallerMedia | None:
        """Return the first identification that succeeds, or None."""
        for step in (self.by_id_file, self.by_uuid, self.by_mounts, self.by_probe):
            media = step()
            if media is not None:
                return media
        return None


def describe_devices(devices: list[Block]) -> str:
    """Return a one-line summary of the device tree for the wizard log."""
    parts = []
    for disk in devices:
        children = ",".join(
            f"{node.name}[{node.fs.fstype or '-'}:{node.fs.uuid or '-'}]"
            for node in disk.walk()
            if node is not disk
        )
        parts.append(f"{disk.name}({disk.type},{disk.size // GIB}GiB){{{children}}}")
    return " ".join(parts) or "(none)"


def find_media(sources: MediaSources | None = None) -> tuple[InstallerMedia | None, list[Block]]:
    """Identify the installer boot media. Returns (media or None, devices)."""
    src = sources or MediaSources()
    log.info("installer.uuid from kernel command line: %s", read_cmdline_uuid(src.cmdline))
    finder = _Finder(src)
    log.info("lsblk at start: %s", describe_devices(finder.devices))
    media = finder.run()
    if media is None:
        log.warning(
            "installer media NOT identified; lsblk now: %s", describe_devices(finder.devices)
        )
    return media, finder.devices


def list_targets(devices: list[Block], media: InstallerMedia | None) -> list[Disk]:
    """Return real, non-zero, writable disks that are not the installer media."""
    targets = []
    for blk in devices:
        if blk.type != "disk" or not is_allowed_name(blk.name) or blk.size <= 0:
            continue
        if media is not None and blk.name == media.disk:
            continue
        targets.append(Disk(blk.name, blk.size, blk.hw.model, blk.hw.tran, blk.hw.removable))
    return targets
