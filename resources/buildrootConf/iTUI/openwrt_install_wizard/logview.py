"""Live output pane for the install run (setup.sh as a subprocess)."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING

from prompt_toolkit.application.current import get_app
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import (
    ConditionalContainer,
    Dimension,
    HSplit,
    Layout,
    Window,
)
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import Button, Dialog, TextArea

from .widgets import build_application

if TYPE_CHECKING:
    from collections.abc import Callable

    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import StyleAndTextTuples
    from prompt_toolkit.key_binding import KeyPressEvent
    from prompt_toolkit.styles import BaseStyle

    from .console import AppIo, Console

log = logging.getLogger(__name__)

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
MAX_LINES = 2000
TAIL_LINES = 15
READ_CHUNK = 4096
SPAWN_FAILED = 127
CONTINUE_WIDTH = 14
LOG_WIDTH = Dimension(min=60, preferred=100, max=140)
LOG_HEIGHT = Dimension(min=8, preferred=18)


class LogBuffer:
    """Process output as lines: ANSI stripped, bare CR overwrites the current line."""

    def __init__(self) -> None:
        """Start empty."""
        self.lines: list[str] = []
        self.partial = ""

    def feed(self, chunk: str) -> None:
        """Append a chunk of decoded output."""
        for char in _ANSI.sub("", chunk):
            if char == "\n":
                self.lines.append(self.partial)
                self.partial = ""
            elif char == "\r":
                # dd/tar/mdadm redraw progress with a bare CR: overwrite the line.
                self.partial = ""
            elif char >= " " or char == "\t":
                self.partial += char
        if len(self.lines) > MAX_LINES:
            del self.lines[: len(self.lines) - MAX_LINES]

    def text(self) -> str:
        """Return everything received so far, including the unfinished line."""
        return "\n".join(self.lines + ([self.partial] if self.partial else []))

    def tail(self) -> list[str]:
        """Return the last non-blank lines."""
        return [line for line in self.lines if line.strip()][-TAIL_LINES:]


class InstallProgress:
    """A full-screen log of a running command with a Continue button at the end."""

    def __init__(
        self,
        console: Console,
        style: BaseStyle,
        title: str,
        io: AppIo,
    ) -> None:
        """Remember the console, style, dialog title and prompt_toolkit I/O."""
        self.console = console
        self.style = style
        self.title = title
        self.io = io
        self.buffer = LogBuffer()
        self.rc: int | None = None

    def status(self) -> StyleAndTextTuples:
        """Return the one-line status under the log."""
        if self.rc is None:
            return [("class:dialog.body", "Working - do not power off or remove media...")]
        if self.rc == 0:
            return [("class:dialog.body", "Finished successfully.")]
        return [("class:error", f"FAILED (exit code {self.rc}). See /var/log/installer-setup.log.")]

    def _build(self) -> tuple[Application[object], TextArea, Button]:
        """Create the application, its log area and its Continue button."""
        area = TextArea(
            text="",
            read_only=True,
            scrollbar=True,
            wrap_lines=True,
            focusable=True,
            style="class:log",
            height=LOG_HEIGHT,
        )
        button = Button(
            "Continue", handler=lambda: get_app().exit(result=True), width=CONTINUE_WIDTH
        )
        body = HSplit(
            [
                area,
                Window(FormattedTextControl(self.status), height=1, style="class:dialog.body"),
                ConditionalContainer(button, filter=Condition(lambda: self.rc is not None)),
            ]
        )
        dialog = Dialog(title=self.title, body=body, width=LOG_WIDTH, with_background=True)
        bindings = KeyBindings()

        # An install must not be interrupted by a stray ESC / Ctrl-C.
        @bindings.add("escape", eager=True)
        @bindings.add("c-c")
        def _ignore(_event: KeyPressEvent) -> None:
            """Swallow the key."""

        app = build_application(
            Layout(dialog, focused_element=area),
            bindings,
            self.console,
            self.style,
            self.io,
        )
        return app, area, button

    async def _drive(
        self,
        argv: list[str],
        env: dict[str, str],
        refresh: Callable[[], None],
        on_done: Callable[[], None],
    ) -> None:
        """Run the command, feeding its output to the buffer until it exits."""
        rc = SPAWN_FAILED
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
            stream = proc.stdout
            while stream is not None:
                chunk = await stream.read(READ_CHUNK)
                if not chunk:
                    break
                self.buffer.feed(chunk.decode("utf-8", "replace"))
                refresh()
            rc = await proc.wait()
        except OSError as exc:  # spawn failure: show it instead of crashing the UI
            log.exception("could not run %s", argv[:1])
            self.buffer.feed(f"\n{type(exc).__name__}: {exc}\n")
        finally:
            self.rc = rc
            self.buffer.feed(f"\n--- finished (exit code {rc}) ---\n")
            refresh()
            on_done()

    def run(self, argv: list[str], env: dict[str, str]) -> tuple[int, list[str]]:
        """Run ``argv`` while showing its output. Returns (exit code, tail lines)."""
        self.console.reapply()
        app, area, button = self._build()

        def refresh() -> None:
            """Show the latest output, scrolled to the end."""
            text = self.buffer.text()
            area.buffer.set_document(Document(text, len(text)), bypass_readonly=True)
            app.invalidate()

        def on_done() -> None:
            """Move focus to the Continue button."""
            app.layout.focus(button)

        async def main() -> None:
            """Run the UI and the command side by side."""
            task = asyncio.create_task(self._drive(argv, env, refresh, on_done))
            try:
                await app.run_async()
            finally:
                if not task.done():
                    task.cancel()

        asyncio.run(main())
        return (SPAWN_FAILED if self.rc is None else self.rc), self.buffer.tail()
