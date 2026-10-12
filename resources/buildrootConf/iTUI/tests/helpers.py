"""Shared test doubles."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from prompt_toolkit.output import ColorDepth


class StubConsole:
    """A console with no terminal side effects (satisfies ``console.Console``)."""

    def __init__(self, mode: str = "vt", color_depth: ColorDepth | None = None) -> None:
        """Remember the render mode and colour depth to report."""
        self._mode = mode
        self._color_depth = color_depth

    @property
    def mode(self) -> str:
        """Return the render mode."""
        return self._mode

    @property
    def color_depth(self) -> ColorDepth | None:
        """Return the colour depth to request."""
        return self._color_depth

    def reapply(self) -> None:
        """Do nothing: there is no palette to program."""
