"""The user's answers, their validation, and the setup.sh argument contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .storage import Disk

MIN_DISKS = 2
MAX_DISKS = 4
RAID10_DISKS = 4
BOOT_PART_GB = 2  # setup.sh creates a 2G BOOT partition per disk
BITMAP_THRESHOLD_GB = 150  # write-intent bitmap defaults on at/above this


class PlanError(ValueError):
    """An answer that setup.sh would reject."""


def raid_choices(disk_count: int) -> tuple[str, ...]:
    """Return the RAID levels offered: 4 disks are always RAID 10, else 1 or 0."""
    return ("10",) if disk_count == RAID10_DISKS else ("1", "0")


def max_root_gb(disks: list[Disk]) -> int:
    """Return the largest ROOT partition every selected disk can hold."""
    return min(d.size_gib for d in disks) - BOOT_PART_GB


def bitmap_default(estimated_root_gb: int) -> bool:
    """Return whether the write-intent bitmap is on by default for this size."""
    return estimated_root_gb >= BITMAP_THRESHOLD_GB


def parse_size_gb(text: str, max_gb: int) -> int:
    """Parse a per-disk ROOT size in GB, raising PlanError when unusable."""
    try:
        value = int(text.strip())
    except ValueError:
        msg = "Enter a whole number of gigabytes."
        raise PlanError(msg) from None
    if value < 1:
        msg = "The size must be at least 1 GB."
        raise PlanError(msg)
    if value > max_gb:
        msg = f"The smallest selected disk fits at most {max_gb} GB."
        raise PlanError(msg)
    return value


def validate_disk_count(count: int) -> None:
    """Raise PlanError unless 2-4 disks are selected."""
    if not MIN_DISKS <= count <= MAX_DISKS:
        msg = f"Select between {MIN_DISKS} and {MAX_DISKS} disks ({count} selected)."
        raise PlanError(msg)


@dataclass(frozen=True)
class InstallPlan:
    """Everything setup.sh needs, as confirmed by the user."""

    disks: tuple[str, ...]
    raid_level: str
    root_size_gb: int | None  # None = use all remaining space
    bitmap: bool
    max_root_gb: int

    @property
    def root_part_end(self) -> str:
        """Return the sfdisk size field: '' for all space, else '+<n>G'."""
        return "" if self.root_size_gb is None else f"+{self.root_size_gb}G"

    @property
    def bitmap_mode(self) -> str:
        """Return the mdadm --bitmap value."""
        return "internal" if self.bitmap else "none"

    @property
    def estimated_root_gb(self) -> int:
        """Return the per-disk ROOT size this plan will produce, in GB."""
        return self.max_root_gb if self.root_size_gb is None else self.root_size_gb

    def validate(self) -> None:
        """Raise PlanError if setup.sh would reject this plan."""
        validate_disk_count(len(self.disks))
        if self.raid_level not in raid_choices(len(self.disks)):
            msg = f"RAID {self.raid_level} is not valid for {len(self.disks)} disks."
            raise PlanError(msg)
        if self.root_size_gb is not None:
            parse_size_gb(str(self.root_size_gb), self.max_root_gb)

    def to_setup_argv(self) -> list[str]:
        """Return the setup.sh argument contract: LEVEL PART_END BITMAP disk..."""
        return [self.raid_level, self.root_part_end, self.bitmap_mode, *self.disks]
