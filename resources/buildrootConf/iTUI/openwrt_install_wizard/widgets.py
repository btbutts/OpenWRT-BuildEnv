"""Small prompt_toolkit building blocks: wrapped text, choice list, inline error."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from prompt_toolkit.application import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.data_structures import Point
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import (
    ConditionalContainer,
    Dimension,
    FormattedTextControl,
    Layout,
    Window,
)
from wcwidth import wcswidth

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from prompt_toolkit.formatted_text import AnyFormattedText, StyleAndTextTuples
    from prompt_toolkit.key_binding import KeyPressEvent
    from prompt_toolkit.styles import BaseStyle

    from .console import AppIo, Console
    from .theme import Glyphs

PAGE_STEP = 8
EDGE_STEP = sys.maxsize  # clamped by ChoiceModel.move
MIN_LIST_ROWS = 3
MAX_LIST_ROWS = 12
ESC_TIMEOUT = 0.05


def text_block(text: AnyFormattedText) -> Window:
    """Return a word-wrapped, auto-height text window. ``text`` may be a callable."""
    return Window(
        FormattedTextControl(text),
        wrap_lines=True,
        dont_extend_height=True,
    )


@dataclass
class InlineError:
    """Validation message shown under a field while ``text`` is non-empty."""

    text: str = ""

    def container(self) -> ConditionalContainer:
        """Return the container that shows the message only while it is set."""
        return ConditionalContainer(
            text_block(lambda: [("class:error", self.text)]),
            filter=Condition(lambda: bool(self.text)),
        )


@dataclass
class ChoiceModel:
    """State of a choice list: items, cursor and (for checkboxes) checked values."""

    items: list[tuple[str, str]]
    multi: bool
    checked: set[str] = field(default_factory=set)
    index: int = 0

    @classmethod
    def create(
        cls,
        items: Sequence[tuple[str, str]],
        *,
        multi: bool,
        checked: Sequence[str] = (),
        initial: str | None = None,
    ) -> ChoiceModel:
        """Build a model; ``initial`` places the cursor, ``checked`` pre-ticks rows."""
        model = cls(list(items), multi=multi, checked={v for v, _ in items if v in set(checked)})
        for i, (value, _) in enumerate(model.items):
            if value == initial:
                model.index = i
        return model

    @property
    def value(self) -> str:
        """Return the value under the cursor."""
        return self.items[self.index][0]

    def values(self) -> list[str]:
        """Return the checked values in list order."""
        return [v for v, _ in self.items if v in self.checked]

    def move(self, delta: int) -> None:
        """Move the cursor by ``delta`` rows, clamped to the list."""
        if self.items:
            self.index = max(0, min(len(self.items) - 1, self.index + delta))

    def toggle(self) -> None:
        """Tick or untick the row under the cursor (checkbox lists only)."""
        if self.multi and self.items:
            self.checked.symmetric_difference_update({self.value})


class ChoiceList:
    """Vertical list of rows drawn from a ChoiceModel.

    Checkbox rows toggle with Space. Radio rows follow the cursor. The accent
    colour appears only on the marker glyph, which sits in a dark "chip" so it
    stays readable on the grey panel.
    """

    def __init__(self, model: ChoiceModel, glyphs: Glyphs) -> None:
        """Create the focusable control for ``model``."""
        self.model = model
        self.glyphs = glyphs
        self.on_accept: Callable[[], None] | None = None
        self.on_change: Callable[[], None] | None = None
        self._width = max((wcswidth(label) for _, label in model.items), default=0)
        self.control = FormattedTextControl(
            self.render,
            focusable=True,
            show_cursor=False,
            key_bindings=self._bindings(),
            get_cursor_position=lambda: Point(0, self.model.index),
        )
        count = len(model.items)
        self.window = Window(
            self.control,
            height=Dimension(min=min(count, MIN_LIST_ROWS), preferred=count, max=MAX_LIST_ROWS),
            dont_extend_height=True,
        )

    def value(self) -> str:
        """Return the value under the cursor (radio lists)."""
        return self.model.value

    def values(self) -> list[str]:
        """Return the checked values in list order (checkbox lists)."""
        return self.model.values()

    def render(self) -> StyleAndTextTuples:
        """Return the styled fragments for every row."""
        focused = get_app().layout.has_focus(self.window)
        out: StyleAndTextTuples = []
        last = len(self.model.items) - 1
        for i, (value, label) in enumerate(self.model.items):
            current = i == self.model.index
            if self.model.multi:
                marked, left, right = value in self.model.checked, "[", "]"
                glyph = self.glyphs.check
            else:
                marked, left, right, glyph = current, "(", ")", self.glyphs.radio
            row = self._row_style(current=current, focused=focused)
            pad = " " * max(0, self._width - wcswidth(label))
            out.append((row, " "))
            out.append(("class:chip", left))
            out.append(("class:chip.on" if marked else "class:chip", glyph if marked else " "))
            out.append(("class:chip", right))
            out.append((row, f" {label}{pad} "))
            if i < last:
                out.append(("", "\n"))
        return out

    # --- keys ----------------------------------------------------------------

    def _changed(self) -> None:
        """Tell the owner that the cursor or the ticks changed."""
        if self.on_change:
            self.on_change()

    def _mover(self, delta: int) -> Callable[[KeyPressEvent], None]:
        """Return a key handler that moves the cursor by ``delta``."""

        def handler(_event: KeyPressEvent) -> None:
            """Move the cursor."""
            self.model.move(delta)
            self._changed()

        return handler

    def _on_space(self, _event: KeyPressEvent) -> None:
        """Toggle the current row."""
        self.model.toggle()
        self._changed()

    def _on_enter(self, _event: KeyPressEvent) -> None:
        """Accept the list (same as pressing OK)."""
        if self.on_accept:
            self.on_accept()

    def _bindings(self) -> KeyBindings:
        """Return the key bindings of the list."""
        bindings = KeyBindings()
        moves = (
            (("up", "k"), -1),
            (("down", "j"), 1),
            (("pageup",), -PAGE_STEP),
            (("pagedown",), PAGE_STEP),
            (("home",), -EDGE_STEP),
            (("end",), EDGE_STEP),
        )
        for keys, delta in moves:
            handler = self._mover(delta)
            for key in keys:  # alternatives, not a key sequence
                bindings.add(key)(handler)
        bindings.add("space")(self._on_space)
        bindings.add("enter")(self._on_enter)
        return bindings

    # --- drawing -------------------------------------------------------------

    def _row_style(self, *, current: bool, focused: bool) -> str:
        """Return the style class of a row."""
        if not current:
            return "class:row"
        return "class:row.focus" if focused else "class:row.current"


def build_application(
    layout: Layout,
    bindings: KeyBindings,
    console: Console,
    style: BaseStyle,
    io: AppIo,
) -> Application[object]:
    """Create the full-screen application every prompt and the log view run in."""
    app: Application[object] = Application(
        layout=layout,
        key_bindings=bindings,
        style=style,
        color_depth=console.color_depth,
        full_screen=True,
        input=io.input,
        output=io.output,
    )
    app.ttimeoutlen = ESC_TIMEOUT
    return app
