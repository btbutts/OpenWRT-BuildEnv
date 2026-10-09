"""The question sequence, mirroring wizard.sh.

disks -> RAID level -> ROOT size -> write-intent bitmap -> erase confirmation

Every step after the first offers Back. ``ui`` is a ``ui.WizardUI`` (``dialogs.Dialogs``
or a scripted double), so the flow is testable without a terminal.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from . import plan as planmod
from .errors import GoBackError, WizardCancelledError
from .plan import BOOT_PART_GB, InstallPlan, PlanError
from .ui import Prompt, YesNoLabels

if TYPE_CHECKING:
    from collections.abc import Callable

    from .storage import Disk, InstallerMedia
    from .ui import WizardUI

log = logging.getLogger(__name__)

TITLE = "OpenWRT RAID Deployment"
DEFAULT_CUSTOM_GB = 20


@dataclass
class State:
    """Answers collected so far."""

    targets: list[Disk]
    media: InstallerMedia | None
    disks: list[str] = field(default_factory=list)
    raid_level: str = ""
    root_size_gb: int | None = None
    bitmap: bool = False

    def selected(self) -> list[Disk]:
        """Return the Disk objects of the chosen names."""
        return [d for d in self.targets if d.name in self.disks]

    def max_root_gb(self) -> int:
        """Return the largest ROOT size the chosen disks allow."""
        return planmod.max_root_gb(self.selected())

    def to_plan(self) -> InstallPlan:
        """Freeze the answers into an InstallPlan."""
        return InstallPlan(
            disks=tuple(self.disks),
            raid_level=self.raid_level,
            root_size_gb=self.root_size_gb,
            bitmap=self.bitmap,
            max_root_gb=self.max_root_gb(),
        )


def _validate_count(values: list[str]) -> str | None:
    """Return the problem with a disk selection, or None when it is fine."""
    try:
        planmod.validate_disk_count(len(values))
    except PlanError as exc:
        return str(exc)
    return None


def _disk_prompt(media: InstallerMedia | None) -> Prompt:
    """Build the disk-selection prompt, with a warning when the boot media is unknown."""
    text = (
        f"Select {planmod.MIN_DISKS} to {planmod.MAX_DISKS} target disks for the OpenWRT RAID.\n"
        "Space toggles a disk, Enter confirms."
    )
    if media is None:
        text += (
            "\n\nWARNING: the installer boot media could not be identified. "
            "Do NOT select the USB/SD/NVMe device you booted from."
        )
    return Prompt(text, TITLE)


def _confirm_unidentified(ui: WizardUI, chosen: list[str]) -> bool:
    """Fail closed: make the operator vouch that none of the disks is the boot media."""
    return ui.yesno(
        Prompt(
            "The installer boot media could not be identified.\n\n"
            "Confirm that NONE of these is the USB/SD/NVMe device you booted from:\n"
            f"  {' '.join(chosen)}",
            TITLE,
        ),
        YesNoLabels(yes="None of them", no="Re-select", default_yes=False),
    )


def step_disks(ui: WizardUI, st: State) -> None:
    """Ask which 2-4 disks to use."""
    prompt = _disk_prompt(st.media)
    items = [(d.name, d.label()) for d in st.targets]
    preselected = st.disks
    while True:
        chosen = ui.checklist(prompt, items, checked=preselected, validate=_validate_count)
        # Never trust the list alone: refuse the boot disk even if it leaked in.
        if st.media is not None and st.media.disk in chosen:
            ui.msgbox(
                Prompt(
                    f"{st.media.disk} is the installer boot media and cannot be a RAID target.",
                    TITLE,
                ),
            )
            continue
        if st.media is None and not _confirm_unidentified(ui, chosen):
            preselected = chosen
            continue
        st.disks = chosen
        return


def step_raid(ui: WizardUI, st: State) -> None:
    """Ask for the RAID level (forced to RAID 10 with four disks)."""
    if planmod.raid_choices(len(st.disks)) == ("10",):
        ui.msgbox(
            Prompt(
                "4 disks selected. The ROOT array will be configured as RAID 10 automatically.",
                TITLE,
                allow_back=True,
            ),
        )
        st.raid_level = "10"
        return
    st.raid_level = ui.menu(
        Prompt("Select the RAID level for OpenWRT-ROOT (/dev/md1):", TITLE, allow_back=True),
        [("1", "RAID 1 (mirroring - recommended)"), ("0", "RAID 0 (striping - no redundancy)")],
        initial=st.raid_level or "1",
    )


def step_size(ui: WizardUI, st: State) -> None:
    """Ask whether ROOT uses all remaining space or a custom size."""
    max_gb = st.max_root_gb()
    if max_gb < 1:
        ui.msgbox(
            Prompt(
                f"The smallest selected disk is too small: {BOOT_PART_GB} GB is reserved for "
                "BOOT and nothing is left for ROOT. Go back and choose larger disks.",
                TITLE,
                allow_back=True,
            ),
        )
        raise GoBackError
    mode = ui.menu(
        Prompt("Configure the ROOT partition size (per disk):", TITLE, allow_back=True),
        [
            ("MAX", f"Use all remaining disk space (about {max_gb} GB)"),
            ("CUSTOM", "Specify a custom size in gigabytes"),
        ],
        initial="CUSTOM" if st.root_size_gb else "MAX",
    )
    if mode == "MAX":
        st.root_size_gb = None
        return

    def check(value: str) -> str | None:
        """Return the problem with a typed size, or None when it is fine."""
        try:
            planmod.parse_size_gb(value, max_gb)
        except PlanError as exc:
            return str(exc)
        return None

    answer = ui.inputbox(
        Prompt(
            f"Enter the ROOT partition size per disk, in GB (1 - {max_gb}):",
            TITLE,
            allow_back=True,
        ),
        default=str(st.root_size_gb or min(DEFAULT_CUSTOM_GB, max_gb)),
        validate=check,
    )
    st.root_size_gb = planmod.parse_size_gb(answer, max_gb)


def _bitmap_text(estimated_gb: int, *, enabled_by_default: bool) -> str:
    """Explain the write-intent bitmap trade-off for this array size."""
    threshold = planmod.BITMAP_THRESHOLD_GB
    if enabled_by_default:
        return (
            f"Your estimated target ROOT array size ({estimated_gb} GB) is >= {threshold} GB.\n\n"
            "A write-intent bitmap speeds up array reconstruction after a power failure, "
            "at the cost of slightly higher write latency.\n\n"
            "Enable the internal write-intent bitmap?"
        )
    return (
        f"Your estimated target ROOT array size ({estimated_gb} GB) "
        f"is less than {threshold} GB.\n\n"
        "Bitmaps are generally discouraged on smaller volumes: the write-performance cost "
        "outweighs the recovery gain.\n\n"
        "Override the default and enable the internal write-intent bitmap anyway?"
    )


def step_bitmap(ui: WizardUI, st: State) -> None:
    """Ask whether to enable the write-intent bitmap."""
    estimated = st.to_plan().estimated_root_gb
    by_default = planmod.bitmap_default(estimated)
    st.bitmap = ui.yesno(
        Prompt(_bitmap_text(estimated, enabled_by_default=by_default), TITLE, allow_back=True),
        YesNoLabels(yes="Enable", no="Disable", default_yes=by_default),
    )


def step_confirm(ui: WizardUI, st: State) -> None:
    """Ask for the final erase confirmation; No cancels the deployment."""
    confirmed = ui.yesno(
        Prompt(
            f"This will completely ERASE all data on: {' '.join(st.disks)}\n\n"
            "Do you want to proceed?",
            [("class:danger", " WARNING ")],
            allow_back=True,
        ),
        YesNoLabels(yes="Erase and install", no="Cancel", default_yes=False),
    )
    if not confirmed:
        raise WizardCancelledError


STEPS: tuple[Callable[[WizardUI, State], None], ...] = (
    step_disks,
    step_raid,
    step_size,
    step_bitmap,
    step_confirm,
)


def collect_plan(ui: WizardUI, targets: list[Disk], media: InstallerMedia | None) -> InstallPlan:
    """Walk the steps (with Back) and return a validated plan."""
    if not targets:
        ui.msgbox(
            Prompt(
                "No target disks are available for installation.\n\n"
                "All detected drives are in use by the active OS or the installer media.",
                TITLE,
            ),
        )
        raise WizardCancelledError
    state = State(targets=targets, media=media)
    index = 0
    while index < len(STEPS):
        try:
            STEPS[index](ui, state)
            index += 1
        except GoBackError:
            index = max(0, index - 1)
    plan = state.to_plan()
    plan.validate()
    log.info("plan: %s", plan)
    return plan
