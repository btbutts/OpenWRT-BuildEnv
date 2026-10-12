"""Tests for the question sequence, driven by a scripted fake UI."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import cast

import pytest

from openwrt_install_wizard import flow
from openwrt_install_wizard.errors import GoBackError, WizardCancelledError
from openwrt_install_wizard.storage import GIB, Disk, InstallerMedia
from openwrt_install_wizard.ui import Prompt, YesNoLabels

MEDIA = InstallerMedia("sdc1", "sdc", "test")


@dataclass
class Shown:
    """One prompt the flow displayed, with the options it was shown with."""

    kind: str
    prompt: Prompt
    extra: dict[str, object] = field(default_factory=dict)


class FakeUI:
    """A scripted ``WizardUI``: answers come from a queue."""

    def __init__(self, answers: list[object]) -> None:
        """Queue the scripted answers (exceptions are raised, not returned)."""
        self.answers = list(answers)
        self.shown: list[Shown] = []

    def _next(self, kind: str, prompt: Prompt, **extra: object) -> object:
        """Record the prompt and return or raise the next scripted answer."""
        self.shown.append(Shown(kind, prompt, extra))
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException) or (
            isinstance(answer, type) and issubclass(answer, BaseException)
        ):
            raise answer
        return answer

    def kinds(self) -> list[str]:
        """Return the kinds of prompt shown so far."""
        return [item.kind for item in self.shown]

    def msgbox(self, prompt: Prompt, ok: str = "OK") -> None:
        """Consume a scripted acknowledgement."""
        self._next("msgbox", prompt, ok=ok)

    def yesno(self, prompt: Prompt, labels: YesNoLabels | None = None) -> bool:
        """Return the next scripted yes/no answer."""
        return bool(self._next("yesno", prompt, labels=labels))

    def menu(
        self,
        prompt: Prompt,
        items: Sequence[tuple[str, str]],
        initial: str | None = None,
    ) -> str:
        """Return the next scripted menu choice."""
        return str(self._next("menu", prompt, items=items, initial=initial))

    def checklist(
        self,
        prompt: Prompt,
        items: Sequence[tuple[str, str]],
        checked: Sequence[str] = (),
        validate: Callable[[list[str]], str | None] | None = None,
    ) -> list[str]:
        """Return the next scripted selection, after running the validator on it."""
        answer = cast("list[str]", self._next("checklist", prompt, items=items, checked=checked))
        problem = validate(answer) if validate else None
        assert problem is None, f"validator rejected {answer}: {problem}"
        return answer

    def inputbox(
        self,
        prompt: Prompt,
        default: str = "",
        validate: Callable[[str], str | None] | None = None,
    ) -> str:
        """Return the next scripted text, after running the validator on it."""
        answer = str(self._next("inputbox", prompt, default=default))
        problem = validate(answer) if validate else None
        assert problem is None, f"validator rejected {answer!r}: {problem}"
        return answer

    def run_command(
        self,
        argv: list[str],
        env: dict[str, str],
        title: str,
    ) -> tuple[int, list[str]]:
        """Pretend the command succeeded; the flow tests never reach the install."""
        self.shown.append(Shown("run_command", Prompt(title), {"argv": argv, "env": env}))
        return 0, []


def make_disks(*names: str, gib: int = 500) -> list[Disk]:
    """Return plain disks of the same size."""
    return [Disk(name, gib * GIB, "", "", removable=False) for name in names]


def test_two_disks_raid1_max_no_bitmap_small() -> None:
    """Small arrays default to no bitmap; MAX leaves PART_END empty."""
    ui = FakeUI([["sda", "sdb"], "1", "MAX", False, True])
    result = flow.collect_plan(ui, make_disks("sda", "sdb", gib=100), MEDIA)
    assert result.to_setup_argv() == ["1", "", "none", "sda", "sdb"]


def test_large_array_passes_threshold_to_bitmap_default() -> None:
    """The estimated ROOT size drives the bitmap prompt."""
    ui = FakeUI([["sda", "sdb"], "1", "MAX", True, True])
    result = flow.collect_plan(ui, make_disks("sda", "sdb", gib=500), MEDIA)
    assert result.bitmap
    assert result.estimated_root_gb == 498


def test_four_disks_force_raid10() -> None:
    """Four disks skip the RAID menu and show the RAID 10 notice."""
    ui = FakeUI([["a", "b", "c", "d"], None, "CUSTOM", "20", False, True])
    result = flow.collect_plan(ui, make_disks("a", "b", "c", "d"), MEDIA)
    assert result.raid_level == "10"
    assert result.to_setup_argv()[:3] == ["10", "+20G", "none"]
    assert ui.kinds()[1] == "msgbox"


def test_back_returns_to_previous_step() -> None:
    """Back at the size step re-asks the RAID level."""
    ui = FakeUI([["sda", "sdb"], "1", GoBackError, "0", "MAX", False, True])
    result = flow.collect_plan(ui, make_disks("sda", "sdb"), MEDIA)
    assert result.raid_level == "0"


def test_cancel_at_erase_confirmation() -> None:
    """Answering No to the erase warning cancels the whole deployment."""
    ui = FakeUI([["sda", "sdb"], "1", "MAX", False, False])
    with pytest.raises(WizardCancelledError):
        flow.collect_plan(ui, make_disks("sda", "sdb"), MEDIA)


def test_no_targets_ends_wizard() -> None:
    """No disks to offer: explain, then end the wizard."""
    ui = FakeUI([None])
    with pytest.raises(WizardCancelledError):
        flow.collect_plan(ui, [], MEDIA)


def test_boot_disk_that_leaks_into_selection_is_refused() -> None:
    """Even if the boot disk reaches the list, selecting it is refused."""
    ui = FakeUI([["sda", "sdc"], None, ["sda", "sdb"], "1", "MAX", False, True])
    result = flow.collect_plan(ui, make_disks("sda", "sdb", "sdc"), MEDIA)
    assert result.disks == ("sda", "sdb")


def test_unidentified_media_fails_closed() -> None:
    """Without an identity the operator must vouch for the disks before continuing."""
    # "Re-select" the first time, then confirm the second selection.
    ui = FakeUI([["sda", "sdb"], False, ["sda", "sdb"], True, "1", "MAX", False, True])
    result = flow.collect_plan(ui, make_disks("sda", "sdb"), None)
    assert result.disks == ("sda", "sdb")
    assert ui.kinds().count("yesno") >= 3


def test_too_small_disks_send_the_user_back_to_reselect() -> None:
    """Disks with no room for ROOT lead back to the disk selection."""
    targets = [
        Disk("sda", 2 * GIB, "", "", removable=False),
        Disk("sdb", 2 * GIB, "", "", removable=False),
        Disk("sdc", 100 * GIB, "", "", removable=False),
        Disk("sdd", 100 * GIB, "", "", removable=False),
    ]
    ui = FakeUI(
        [
            ["sda", "sdb"],
            "1",  # disks, RAID level
            None,  # msgbox: no room for ROOT -> back to the RAID step
            GoBackError,  # RAID step -> back to disk selection
            ["sdc", "sdd"],
            "1",
            "MAX",
            False,
            True,
        ],
    )
    result = flow.collect_plan(ui, targets, InstallerMedia("sde1", "sde", "test"))
    assert result.disks == ("sdc", "sdd")
