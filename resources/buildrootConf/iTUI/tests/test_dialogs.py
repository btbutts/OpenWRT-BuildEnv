"""Headless rendering: real prompt_toolkit apps driven by a pipe input."""

import io
import re
from collections.abc import Callable, Iterator
from contextlib import ExitStack

import pytest
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import ColorDepth, DummyOutput
from prompt_toolkit.output.vt100 import Vt100_Output

from openwrt_install_wizard.console import AppIo
from openwrt_install_wizard.dialogs import Dialogs
from openwrt_install_wizard.errors import GoBackError, WizardCancelledError
from openwrt_install_wizard.ui import Prompt, YesNoLabels

from .helpers import StubConsole

ITEMS = [("a", "Alpha"), ("b", "Bravo"), ("c", "Charlie")]
BRIGHT_BG_FIRST, BRIGHT_BG_LAST = 100, 107
EXTENDED_COLOUR_INTRODUCERS = (38, 48)
ROWS, COLUMNS = 28, 90

KEY_DOWN = "\x1b[B"
KEY_ENTER = "\r"
KEY_TAB = "\t"
KEY_ESC = "\x1b"
KEY_CTRL_C = "\x03"


@pytest.fixture(name="make_ui")
def make_ui_fixture() -> Iterator[Callable[[str], Dialogs]]:
    """Yield a factory of Dialogs whose input is the given key string."""
    with ExitStack() as stack:

        def make(keys: str) -> Dialogs:
            """Queue ``keys`` on a pipe input and return Dialogs reading from it."""
            pipe = stack.enter_context(create_pipe_input())
            pipe.send_text(keys)
            return Dialogs(StubConsole(), AppIo(pipe, DummyOutput()))

        yield make


def test_msgbox_enter(make_ui: Callable[[str], Dialogs]) -> None:
    """Enter acknowledges a message box."""
    assert make_ui(KEY_ENTER).msgbox(Prompt("hello", "T")) is None


def test_yesno_default_and_switch(make_ui: Callable[[str], Dialogs]) -> None:
    """Enter takes the focused answer; Tab moves focus to the other one."""
    assert make_ui(KEY_ENTER).yesno(Prompt("q?", "T")) is True
    assert make_ui(KEY_ENTER).yesno(Prompt("q?", "T"), YesNoLabels(default_yes=False)) is False
    assert make_ui(KEY_TAB + KEY_ENTER).yesno(Prompt("q?", "T")) is False


def test_menu_down_enter(make_ui: Callable[[str], Dialogs]) -> None:
    """Down then Enter picks the second row."""
    assert make_ui(KEY_DOWN + KEY_ENTER).menu(Prompt("pick", "T"), ITEMS) == "b"


def test_menu_initial(make_ui: Callable[[str], Dialogs]) -> None:
    """The initial value places the cursor."""
    assert make_ui(KEY_ENTER).menu(Prompt("pick", "T"), ITEMS, initial="c") == "c"


def test_checklist_space_toggles(make_ui: Callable[[str], Dialogs]) -> None:
    """Space ticks the row under the cursor."""
    keys = " " + KEY_DOWN + KEY_DOWN + " " + KEY_ENTER  # tick Alpha, move to Charlie, tick
    assert make_ui(keys).checklist(Prompt("pick", "T"), ITEMS) == ["a", "c"]


def test_checklist_validation_blocks_then_accepts(make_ui: Callable[[str], Dialogs]) -> None:
    """A vetoed selection stays open; fixing it lets Enter through."""

    def need_two(values: list[str]) -> str | None:
        """Require at least two ticked rows."""
        return "pick two" if len(values) < 2 else None

    keys = " " + KEY_ENTER + KEY_DOWN + " " + KEY_ENTER
    assert make_ui(keys).checklist(Prompt("pick", "T"), ITEMS, validate=need_two) == ["a", "b"]


def test_checklist_preselected(make_ui: Callable[[str], Dialogs]) -> None:
    """Pre-ticked rows are returned when nothing is changed."""
    assert make_ui(KEY_ENTER).checklist(Prompt("pick", "T"), ITEMS, checked=["b"]) == ["b"]


def test_inputbox_typing_and_validation(make_ui: Callable[[str], Dialogs]) -> None:
    """An invalid value is rejected inline; a corrected one is returned."""

    def digits_only(value: str) -> str | None:
        """Accept only digits."""
        return None if value.isdigit() else "digits only"

    # Enter on "x" is rejected; backspace it away, type 42, Enter.
    keys = KEY_ENTER + "\x7f" * 5 + "42" + KEY_ENTER
    result = make_ui(keys).inputbox(Prompt("size", "T"), default="x", validate=digits_only)
    assert result == "42"


def test_back_and_cancel_buttons(make_ui: Callable[[str], Dialogs]) -> None:
    """Tab order is list, OK, Back, Cancel."""
    prompt = Prompt("pick", "T", allow_back=True)
    with pytest.raises(GoBackError):
        make_ui(KEY_TAB * 2 + KEY_ENTER).menu(prompt, ITEMS)
    with pytest.raises(WizardCancelledError):
        make_ui(KEY_TAB * 3 + KEY_ENTER).menu(prompt, ITEMS)


def test_escape_cancels(make_ui: Callable[[str], Dialogs]) -> None:
    """ESC cancels the wizard."""
    with pytest.raises(WizardCancelledError):
        make_ui(KEY_ESC).msgbox(Prompt("x", "T"))


def test_ctrl_c_cancels(make_ui: Callable[[str], Dialogs]) -> None:
    """Ctrl-C cancels the wizard."""
    with pytest.raises(WizardCancelledError):
        make_ui(KEY_CTRL_C).menu(Prompt("pick", "T"), ITEMS)


def test_vt_mode_emits_only_16_colour_sgr_with_dark_backgrounds() -> None:
    """What reaches /dev/tty1 is 4-bit SGR with no bright backgrounds."""
    sink = io.StringIO()
    out = Vt100_Output(
        sink,
        lambda: Size(rows=ROWS, columns=COLUMNS),
        term="linux",
        default_color_depth=ColorDepth.DEPTH_4_BIT,
    )
    with create_pipe_input() as pipe:
        pipe.send_text(KEY_ENTER)
        ui = Dialogs(StubConsole(color_depth=ColorDepth.DEPTH_4_BIT), AppIo(pipe, out))
        ui.checklist(Prompt("pick", "T", allow_back=True), ITEMS, checked=["a"])
    codes = [
        int(code)
        for match in re.findall(r"\x1b\[([0-9;]*)m", sink.getvalue())
        for code in match.split(";")
        if code
    ]
    assert codes, "no SGR output captured"
    for code in codes:
        assert not BRIGHT_BG_FIRST <= code <= BRIGHT_BG_LAST, f"bright background {code}"
        assert code not in EXTENDED_COLOUR_INTRODUCERS
