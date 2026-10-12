"""The interface between the wizard flow and whatever draws the prompts.

``flow`` and ``runner`` are written against ``WizardUI``; ``dialogs.Dialogs`` is the
prompt_toolkit implementation and the tests supply a scripted one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from prompt_toolkit.formatted_text import AnyFormattedText


@dataclass(frozen=True)
class Prompt:
    """The fields every dialog shares."""

    text: str
    title: AnyFormattedText = ""
    allow_back: bool = False


@dataclass(frozen=True)
class YesNoLabels:
    """Button captions of a yes/no prompt and which one has focus first."""

    yes: str = "Yes"
    no: str = "No"
    default_yes: bool = True


class WizardUI(Protocol):
    """Every prompt returns its answer or raises WizardCancelledError / GoBackError."""

    def msgbox(self, prompt: Prompt, ok: str = "OK") -> None:
        """Show a message and wait for OK (or Back)."""
        raise NotImplementedError

    def yesno(self, prompt: Prompt, labels: YesNoLabels | None = None) -> bool:
        """Ask a yes/no question. No is an answer, not a cancel."""
        raise NotImplementedError

    def menu(
        self,
        prompt: Prompt,
        items: Sequence[tuple[str, str]],
        initial: str | None = None,
    ) -> str:
        """Pick one of ``items`` (value, label)."""
        raise NotImplementedError

    def checklist(
        self,
        prompt: Prompt,
        items: Sequence[tuple[str, str]],
        checked: Sequence[str] = (),
        validate: Callable[[list[str]], str | None] | None = None,
    ) -> list[str]:
        """Tick any of ``items``; ``validate`` may veto the selection inline."""
        raise NotImplementedError

    def inputbox(
        self,
        prompt: Prompt,
        default: str = "",
        validate: Callable[[str], str | None] | None = None,
    ) -> str:
        """Ask for one line of text; ``validate`` may reject it inline."""
        raise NotImplementedError

    def run_command(
        self,
        argv: list[str],
        env: dict[str, str],
        title: str,
    ) -> tuple[int, list[str]]:
        """Run ``argv`` with a live log. Returns (exit code, last output lines)."""
        raise NotImplementedError
