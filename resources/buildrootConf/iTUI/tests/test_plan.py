"""Tests for plan validation and the setup.sh argument contract."""

import pytest

from openwrt_install_wizard import plan
from openwrt_install_wizard.storage import GIB, Disk


def make_disk(name: str, gib: int) -> Disk:
    """Return a plain disk of ``gib`` GiB."""
    return Disk(name, gib * GIB, "", "", removable=False)


def test_raid_choices() -> None:
    """Four disks are RAID 10 only; two or three pick RAID 1 or 0."""
    assert plan.raid_choices(2) == ("1", "0")
    assert plan.raid_choices(3) == ("1", "0")
    assert plan.raid_choices(4) == ("10",)


def test_max_root_uses_smallest_disk_minus_boot() -> None:
    """The smallest member limits the ROOT partition."""
    assert plan.max_root_gb([make_disk("a", 500), make_disk("b", 100)]) == 98


def test_bitmap_default_threshold() -> None:
    """The bitmap defaults on from 150 GB."""
    assert plan.bitmap_default(150)
    assert not plan.bitmap_default(149)


@pytest.mark.parametrize("text", ["", "abc", "0", "-3", "99", "1.5"])
def test_bad_sizes_rejected(text: str) -> None:
    """Non-numeric, non-positive and oversized sizes are refused."""
    with pytest.raises(plan.PlanError):
        plan.parse_size_gb(text, 98)


def test_good_size() -> None:
    """A valid size is parsed after trimming."""
    assert plan.parse_size_gb(" 20 ", 98) == 20


def test_disk_count_bounds() -> None:
    """Only two to four disks are accepted."""
    for count in (0, 1, 5):
        with pytest.raises(plan.PlanError):
            plan.validate_disk_count(count)
    for count in (2, 3, 4):
        plan.validate_disk_count(count)


def test_setup_argv_contract_max() -> None:
    """MAX size produces an empty PART_END argument."""
    install = plan.InstallPlan(("sda", "sdb"), "1", None, bitmap=False, max_root_gb=98)
    assert install.to_setup_argv() == ["1", "", "none", "sda", "sdb"]


def test_setup_argv_contract_custom() -> None:
    """A custom size produces +<n>G and the bitmap flag maps to 'internal'."""
    install = plan.InstallPlan(("nvme0n1", "nvme1n1"), "0", 20, bitmap=True, max_root_gb=98)
    assert install.to_setup_argv() == ["0", "+20G", "internal", "nvme0n1", "nvme1n1"]


def test_invalid_raid_for_four_disks() -> None:
    """RAID 1 is rejected for four disks."""
    install = plan.InstallPlan(("a", "b", "c", "d"), "1", None, bitmap=False, max_root_gb=10)
    with pytest.raises(plan.PlanError):
        install.validate()
