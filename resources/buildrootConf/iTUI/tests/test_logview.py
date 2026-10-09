"""Tests for the live install log: buffer handling and the subprocess runner."""

import sys
import threading
import time

from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from openwrt_install_wizard.console import AppIo
from openwrt_install_wizard.dialogs import Dialogs
from openwrt_install_wizard.logview import SPAWN_FAILED, LogBuffer

from .helpers import StubConsole

PUMP_INTERVAL = 0.2


def run_with_enter_pump(argv: list[str]) -> tuple[int, list[str]]:
    """Run argv in the log view, pressing Enter until the Continue button takes it."""
    with create_pipe_input() as pipe:
        stop = threading.Event()

        def pump() -> None:
            """Press Enter repeatedly until the run is over."""
            while not stop.is_set():
                time.sleep(PUMP_INTERVAL)
                try:
                    pipe.send_text("\r")
                except (OSError, ValueError):
                    return

        thread = threading.Thread(target=pump, daemon=True)
        thread.start()
        try:
            ui = Dialogs(StubConsole(), AppIo(pipe, DummyOutput()))
            return ui.run_command(argv, {}, "Test")
        finally:
            stop.set()


def test_feed_handles_cr_ansi_and_partial_lines() -> None:
    """Bare CR overwrites a line, ANSI is stripped, an unfinished line is kept."""
    buffer = LogBuffer()
    buffer.feed("one\ntwo\rTWO\n\x1b[31mred\x1b[0m\nno-newline")
    assert buffer.lines == ["one", "TWO", "red"]
    assert buffer.text().endswith("no-newline")


def test_run_command_success_and_failure() -> None:
    """The exit code and the tail of the output are reported."""
    for code in (0, 3):
        rc, tail = run_with_enter_pump(
            [sys.executable, "-c", f"print('hello'); import sys; sys.exit({code})"],
        )
        assert rc == code
        assert "hello" in tail


def test_spawn_failure_reports_127() -> None:
    """A command that cannot be started reports the shell's 'not found' code."""
    rc, _ = run_with_enter_pump(["/nonexistent/setup.sh"])
    assert rc == SPAWN_FAILED
