"""Console setup: colour mode detection and Linux VT palette programming.

On a real Linux VT the 16 palette slots are reprogrammed with
``ESC ] P <slot-hex> <rrggbb>`` and restored with ``ESC ] R`` on every exit
path, so the root shell that follows the wizard keeps the stock colours.
"""

from __future__ import annotations

import contextlib
import os
import re
import signal
import sys
import termios
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, Self

from prompt_toolkit.output import ColorDepth

from .theme import MODE_ANSI, MODE_TRUECOLOR, MODE_VT, vt_palette

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from types import FrameType, TracebackType
    from typing import TextIO

    from prompt_toolkit.input import Input
    from prompt_toolkit.output import Output

# What signal.signal() accepts and signal.getsignal() returns.
type SignalHandler = Callable[[int, FrameType | None], object] | int | signal.Handlers | None

_REAL_VT = re.compile(r"^/dev/tty[0-9]+$")
_TRUECOLOR_VALUES = ("truecolor", "24bit")

PALETTE_RESET = "\x1b]R"
# SGR reset, home, clear screen, show cursor.
SCREEN_RESET = "\x1b[0m\x1b[H\x1b[2J\x1b[?25h"


class Console(Protocol):
    """What the dialogs need from a console (ConsoleSession, or a test double)."""

    @property
    def mode(self) -> str:
        """Render mode: one of the theme.MODE_* values."""
        raise NotImplementedError

    @property
    def color_depth(self) -> ColorDepth | None:
        """prompt_toolkit colour depth to request, or None for its default."""
        raise NotImplementedError

    def reapply(self) -> None:
        """Re-program the palette (an fbcon/GPU takeover can reset it)."""


@dataclass(frozen=True)
class AppIo:
    """Optional prompt_toolkit input/output overrides (tests run headless)."""

    input: Input | None = None
    output: Output | None = None


def tty_name(stream: TextIO) -> str:
    """Return the tty device path of a stream, or '' when it is not a tty."""
    try:
        return os.ttyname(stream.fileno())
    except (OSError, ValueError, AttributeError):
        return ""


def detect_mode(env: Mapping[str, str], tty: str) -> str:
    """Pick the render mode (vt, truecolor or ansi) for this terminal."""
    if env.get("COLORTERM", "").lower() in _TRUECOLOR_VALUES:
        return MODE_TRUECOLOR
    term = env.get("TERM", "")
    if term == "linux":
        # TERM=linux on a serial line is not reprogrammable; only /dev/ttyN is.
        return MODE_VT if _REAL_VT.match(tty) else MODE_ANSI
    if "256color" in term or term.startswith("xterm"):
        return MODE_TRUECOLOR
    return MODE_ANSI


def detect_color_depth(mode: str, env: Mapping[str, str]) -> ColorDepth | None:
    """Return 4-bit where the 16 ANSI names are used, 24-bit only if advertised."""
    if mode in (MODE_VT, MODE_ANSI):
        return ColorDepth.DEPTH_4_BIT
    if env.get("COLORTERM", "").lower() in _TRUECOLOR_VALUES:
        return ColorDepth.DEPTH_24_BIT
    return None  # prompt_toolkit default (256 colours)


def palette_set_sequence() -> str:
    """Return the escape sequence that programs all 16 VT palette slots."""
    return "".join(f"\x1b]P{slot:X}{rgb}" for slot, rgb in enumerate(vt_palette()))


def _exit_on_signal(_signum: int, _frame: FrameType | None) -> None:
    """Unwind through ``ConsoleSession.__exit__`` so the palette is restored."""
    raise SystemExit(0)


class ConsoleSession:
    """Context manager owning the terminal for the lifetime of the wizard."""

    def __init__(self, out: TextIO | None = None, env: Mapping[str, str] | None = None) -> None:
        """Detect the render mode of ``out`` (default stdout) from ``env``."""
        self.out = out or sys.stdout
        self.env = os.environ if env is None else env
        self.mode = detect_mode(self.env, tty_name(self.out))
        self.color_depth = detect_color_depth(self.mode, self.env)
        self._saved_termios: list | None = None
        self._old_handlers: dict[signal.Signals, SignalHandler] = {}

    def _write(self, text: str) -> None:
        """Write to the terminal, ignoring a closed stream."""
        with contextlib.suppress(OSError, ValueError):
            self.out.write(text)
            self.out.flush()

    def reapply(self) -> None:
        """Re-program the palette (an fbcon/GPU takeover can reset it)."""
        if self.mode == MODE_VT:
            self._write(palette_set_sequence())

    def __enter__(self) -> Self:
        """Save terminal state, install signal handlers and program the palette."""
        try:
            self._saved_termios = termios.tcgetattr(sys.stdin.fileno())
        except (termios.error, OSError, ValueError):
            self._saved_termios = None
        for sig in (signal.SIGTERM, signal.SIGHUP):
            with contextlib.suppress(ValueError, OSError):
                self._old_handlers[sig] = signal.signal(sig, _exit_on_signal)
        self.reapply()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Restore palette, screen, termios and signal handlers."""
        if self.mode == MODE_VT:
            self._write(PALETTE_RESET)
        self._write(SCREEN_RESET)
        if self._saved_termios is not None:
            with contextlib.suppress(termios.error, OSError, ValueError):
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._saved_termios)
        for sig, handler in self._old_handlers.items():
            with contextlib.suppress(ValueError, OSError, TypeError):
                signal.signal(sig, handler)
