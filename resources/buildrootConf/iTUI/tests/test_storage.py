"""Tests for lsblk parsing, boot-media identification and target filtering."""

import json
from pathlib import Path

from openwrt_install_wizard import storage
from openwrt_install_wizard.storage import GIB, MediaSources, UuidWait


def node(name: str, type_: str = "disk", size: int = 100 * GIB, **extra: object) -> dict:
    """Build one lsblk JSON node."""
    raw: dict = {
        "name": name,
        "type": type_,
        "size": size,
        "model": None,
        "tran": None,
        "rm": False,
        "fstype": None,
        "uuid": None,
        "mountpoints": [None],
    }
    raw.update(extra)
    return raw


def devices() -> list[storage.Block]:
    """Return a machine with two SSDs, an NVMe drive, a USB stick and virtual devices."""
    usb = node(
        "sdc",
        rm=True,
        tran="usb",
        model="Flash",
        size=32 * GIB,
        children=[
            node(
                "sdc1",
                "part",
                fstype="vfat",
                uuid="ABCD-1234",
                mountpoints=["/run/installer-media"],
            ),
        ],
    )
    raw = [
        node("sda", model="SSD A", tran="sata"),
        node("sdb", model="SSD B", tran="sata"),
        usb,
        node("nvme0n1", model="NVMe", tran="nvme"),
        node("nbd0", size=0),
        node("loop0", size=10 * GIB),
        node("sr0", size=1 * GIB),
        node("zram0", size=GIB),
    ]
    return storage.parse_lsblk(json.dumps({"blockdevices": raw}))


def no_probe() -> None:
    """Stand in for media.sh probing that finds nothing."""
    return


def sources(tmp_path: Path, **overrides: object) -> MediaSources:
    """Build MediaSources with no id file, no cmdline and no probing by default."""
    base = {
        "read": devices,
        "id_file": str(tmp_path / "missing-id-file"),
        "cmdline": "",
        "payload_check": lambda _mount: False,
        "probe": no_probe,
    }
    base.update(overrides)
    return MediaSources(**base)


def test_parse_handles_old_and_new_mount_keys_and_rm_forms() -> None:
    """Old util-linux spellings (MOUNTPOINT, "1" for RM) parse like the new ones."""
    text = json.dumps(
        {
            "blockdevices": [
                {"name": "sda", "type": "disk", "size": "1000", "rm": "1", "mountpoint": "/mnt"}
            ]
        },
    )
    blk = storage.parse_lsblk(text)[0]
    assert blk.size == 1000
    assert blk.hw.removable
    assert blk.fs.mountpoints == ("/mnt",)


def test_id_file_wins(tmp_path: Path) -> None:
    """The id file written by installer-bootlog.service is used first."""
    id_file = tmp_path / "id"
    id_file.write_text("INSTALLER_PART=sdc1\nINSTALLER_DISK=sdc\n", encoding="utf-8")
    media, _ = storage.find_media(sources(tmp_path, id_file=str(id_file)))
    assert media is not None
    assert (media.disk, media.part, media.source) == ("sdc", "sdc1", "id-file")


def test_stale_id_file_is_ignored(tmp_path: Path) -> None:
    """An id file naming a device that is not present falls through to the UUID."""
    id_file = tmp_path / "id"
    id_file.write_text("INSTALLER_PART=sdz1\nINSTALLER_DISK=sdz\n", encoding="utf-8")
    media, _ = storage.find_media(
        sources(tmp_path, id_file=str(id_file), cmdline="installer.uuid=abcd-1234"),
    )
    assert media is not None
    assert (media.disk, media.source) == ("sdc", "cmdline-uuid")


def test_cmdline_uuid_case_insensitive(tmp_path: Path) -> None:
    """GRUB prints FAT UUIDs in lower case while lsblk reports upper case."""
    media, _ = storage.find_media(
        sources(tmp_path, cmdline="console=tty1 installer.uuid=abcd-1234 loglevel=3"),
    )
    assert media is not None
    assert (media.disk, media.part) == ("sdc", "sdc1")


def test_uuid_appears_late(tmp_path: Path) -> None:
    """A slow USB device is waited for, re-reading lsblk until it shows up."""
    calls = {"reads": 0, "clock": 0.0}

    def read() -> list[storage.Block]:
        calls["reads"] += 1
        if calls["reads"] >= 4:
            return devices()
        return storage.parse_lsblk(json.dumps({"blockdevices": [node("sda"), node("sdb")]}))

    def sleep(seconds: float) -> None:
        calls["clock"] += seconds

    wait = UuidWait(timeout=20, sleep=sleep, now=lambda: calls["clock"])
    media, _ = storage.find_media(
        sources(tmp_path, read=read, cmdline="installer.uuid=ABCD-1234", wait=wait),
    )
    assert media is not None
    assert media.disk == "sdc"
    assert calls["reads"] == 4


def test_uuid_never_appears_then_mounted_payload(tmp_path: Path) -> None:
    """If the UUID never shows up, a mounted payload volume still identifies the stick."""
    clock = {"now": 0.0}

    def sleep(seconds: float) -> None:
        clock["now"] += seconds

    wait = UuidWait(timeout=3, sleep=sleep, now=lambda: clock["now"])
    media, _ = storage.find_media(
        sources(
            tmp_path,
            cmdline="installer.uuid=DEAD-BEEF",
            wait=wait,
            payload_check=lambda mount: mount == "/run/installer-media",
        ),
    )
    assert media is not None
    assert (media.source, media.disk) == ("mounted-payload", "sdc")


def test_media_sh_probe_is_last_resort(tmp_path: Path) -> None:
    """The legacy media.sh probing runs only when everything else failed."""
    media, _ = storage.find_media(sources(tmp_path, probe=lambda: ("sdc1", "sdc")))
    assert media is not None
    assert (media.source, media.disk) == ("media.sh", "sdc")


def test_unidentifiable_returns_none(tmp_path: Path) -> None:
    """With no usable source the media is unknown, so the caller fails closed."""
    media, devs = storage.find_media(sources(tmp_path))
    assert media is None
    assert devs


def test_targets_exclude_boot_virtual_and_zero() -> None:
    """The boot disk, virtual devices and empty devices are never targets."""
    media = storage.InstallerMedia("sdc1", "sdc", "test")
    names = [d.name for d in storage.list_targets(devices(), media)]
    assert names == ["sda", "sdb", "nvme0n1"]


def test_targets_when_media_unknown_keep_everything_real() -> None:
    """Without an identity every real disk stays listed (the flow then fails closed)."""
    names = [d.name for d in storage.list_targets(devices(), None)]
    assert names == ["sda", "sdb", "sdc", "nvme0n1"]


def test_cmdline_uuid_parser() -> None:
    """Only a non-empty installer.uuid= token counts."""
    assert storage.read_cmdline_uuid("a b installer.uuid=1234-ABCD c") == "1234-ABCD"
    assert storage.read_cmdline_uuid("installer.uuid= x") is None
    assert storage.read_cmdline_uuid("quiet") is None


def test_label_formats() -> None:
    """The disk list label shows size, model and the removable flag."""
    disk = storage.Disk("sdc", 32 * GIB, "Flash", "usb", removable=True)
    assert "32.0 GiB" in disk.label()
    assert "(removable)" in disk.label()


def test_describe_devices_lists_uuids_for_the_log() -> None:
    """The wizard log records every disk with its partitions' filesystem and UUID."""
    summary = storage.describe_devices(devices())
    assert "sdc(disk,32GiB){sdc1[vfat:ABCD-1234]}" in summary
    assert storage.describe_devices([]) == "(none)"
