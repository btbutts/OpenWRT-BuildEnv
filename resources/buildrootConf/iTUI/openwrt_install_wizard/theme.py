"""Colour palette, prompt_toolkit style and glyph sets.

Three render modes:

``vt``
    Linux virtual console (TERM=linux on /dev/ttyN). 16 colours only, so
    console.py reprograms palette slots 0-15 to the hex values below and the
    style refers to those slots by ANSI name. Backgrounds only use slots 0-7
    (bright backgrounds are unreliable on fbcon).
``truecolor``
    xterm-like terminals: the hex values are used directly.
``ansi``
    Any other 16-colour terminal we cannot reprogram (serial TERM=linux,
    vt100...): each token falls back to a stock ANSI colour.

The accent colour is only legal on the ``chip`` background (see CONTRAST_PAIRS):
on the panel colour it is nearly invisible (about 1.3:1).
"""

from __future__ import annotations

from dataclasses import dataclass

from prompt_toolkit.styles import Style

MODE_VT = "vt"
MODE_TRUECOLOR = "truecolor"
MODE_ANSI = "ansi"

# prompt_toolkit ANSI colour name for each of the 16 VT palette slots.
SLOT_NAMES = (
    "ansiblack",
    "ansired",
    "ansigreen",
    "ansiyellow",
    "ansiblue",
    "ansimagenta",
    "ansicyan",
    "ansigray",
    "ansibrightblack",
    "ansibrightred",
    "ansibrightgreen",
    "ansibrightyellow",
    "ansibrightblue",
    "ansibrightmagenta",
    "ansibrightcyan",
    "ansiwhite",
)
PALETTE_SIZE = len(SLOT_NAMES)

# sRGB relative-luminance constants (WCAG 2.x).
_CHANNEL_MAX = 255
_GAMMA_KNEE = 0.03928
_LINEAR_DIVISOR = 12.92
_GAMMA_OFFSET = 0.055
_GAMMA_SCALE = 1.055
_GAMMA_EXPONENT = 2.4
_LUMA_RED = 0.2126
_LUMA_GREEN = 0.7152
_LUMA_BLUE = 0.0722
_FLARE = 0.05
_HEX_DIGITS_PER_CHANNEL = 2


@dataclass(frozen=True)
class Color:
    """One theme colour and where it lives on each kind of terminal."""

    hex: str  # "#rrggbb"
    slot: int  # VT palette slot; slots 0-7 for anything used as a background
    ansi: str  # stock ANSI fallback for terminals we cannot reprogram


TOKENS: dict[str, Color] = {
    "backdrop": Color("#13141a", 0, "ansiblack"),  # behind the window
    "danger": Color("#4a0b0b", 1, "ansired"),  # erase warning title
    "ink": Color("#011b24", 2, "ansiblack"),  # text on the panel
    "shadow": Color("#0b0c10", 3, "ansiblack"),  # window drop shadow
    "panel": Color("#7f8188", 4, "ansigray"),  # window body
    "button": Color("#4a4d55", 5, "ansibrightblack"),  # neutral buttons
    "panel_hi": Color("#a3a5ad", 6, "ansiwhite"),  # scrollbar / highlight
    "light": Color("#d9dae0", 7, "ansiwhite"),  # text on dark fills
    "accent": Color("#bb8c05", 8, "ansiyellow"),  # selected-marker glyph only
}

# Slots that no token claims get a readable value so a stray default colour
# never turns invisible.
_SPARE_HEX = TOKENS["light"].hex


def vt_palette() -> list[str]:
    """Return 16 hex strings (no '#'); the index is the VT palette slot."""
    palette = [_SPARE_HEX.lstrip("#")] * PALETTE_SIZE
    for color in TOKENS.values():
        palette[color.slot] = color.hex.lstrip("#")
    return palette


def resolve(token: str, mode: str) -> str:
    """Return the colour string prompt_toolkit should use for a token in a mode."""
    color = TOKENS[token]
    if mode == MODE_VT:
        return SLOT_NAMES[color.slot]
    if mode == MODE_TRUECOLOR:
        return color.hex
    return color.ansi


def build_style(mode: str) -> Style:
    """Build the prompt_toolkit style sheet for a render mode."""

    def c(token: str) -> str:
        """Resolve a token for this mode."""
        return resolve(token, mode)

    return Style.from_dict(
        {
            "": f"{c('light')} bg:{c('backdrop')}",
            "dialog": f"bg:{c('backdrop')}",
            "dialog.body": f"{c('ink')} bg:{c('panel')}",
            "dialog shadow": f"bg:{c('shadow')}",
            "frame.border": f"{c('ink')}",
            "frame.label": f"{c('ink')} bold",
            # Buttons are neutral on purpose; focus is shown by inversion, not accent.
            "button": f"{c('light')} bg:{c('button')}",
            "button.arrow": f"{c('light')} bg:{c('button')}",
            "button.focused": f"{c('light')} bg:{c('ink')} bold",
            # Choice lists.
            "row": f"{c('ink')} bg:{c('panel')}",
            "row.focus": f"{c('light')} bg:{c('ink')}",
            "row.current": f"{c('ink')} bg:{c('panel')} bold",
            "chip": f"{c('light')} bg:{c('ink')}",
            "chip.on": f"{c('accent')} bg:{c('ink')} bold",
            # Text input and install log: dark inset, like a terminal.
            "text-area": f"{c('light')} bg:{c('ink')}",
            "log": f"{c('light')} bg:{c('ink')}",
            "scrollbar.background": f"bg:{c('ink')}",
            "scrollbar.button": f"bg:{c('panel_hi')}",
            "danger": f"{c('danger')} bold",
            "error": f"{c('danger')} bold",
        }
    )


@dataclass(frozen=True)
class Glyphs:
    """Marker characters for checkbox and radio rows."""

    check: str
    radio: str


# The stock Linux console font has no check mark / bullet glyph.
GLYPHS_ASCII = Glyphs(check="x", radio="*")
GLYPHS_UNICODE = Glyphs(check="✔", radio="●")


def glyphs_for(mode: str) -> Glyphs:
    """Return the glyph set that the console font of a mode can draw."""
    return GLYPHS_ASCII if mode in (MODE_VT, MODE_ANSI) else GLYPHS_UNICODE


# --- contrast helpers (used by the tests) -----------------------------------


def _channel(value: int) -> float:
    """Linearise one sRGB channel (0-255)."""
    scaled = value / _CHANNEL_MAX
    if scaled <= _GAMMA_KNEE:
        return scaled / _LINEAR_DIVISOR
    return ((scaled + _GAMMA_OFFSET) / _GAMMA_SCALE) ** _GAMMA_EXPONENT


def luminance(hex_color: str) -> float:
    """Return the WCAG relative luminance of ``#rrggbb``."""
    digits = hex_color.lstrip("#")
    step = _HEX_DIGITS_PER_CHANNEL
    red, green, blue = (int(digits[i : i + step], 16) for i in (0, step, 2 * step))
    return _LUMA_RED * _channel(red) + _LUMA_GREEN * _channel(green) + _LUMA_BLUE * _channel(blue)


def contrast_ratio(fg: str, bg: str) -> float:
    """Return the WCAG contrast ratio between two ``#rrggbb`` colours."""
    first, second = luminance(fg), luminance(bg)
    return (max(first, second) + _FLARE) / (min(first, second) + _FLARE)


# (foreground token, background token, minimum contrast ratio)
CONTRAST_PAIRS = (
    ("ink", "panel", 4.5),  # titles, questions, unfocused rows
    ("light", "ink", 4.5),  # focused row, inputs, log
    ("accent", "ink", 4.5),  # selected marker inside its dark chip
    ("light", "button", 4.5),  # button labels
    ("light", "backdrop", 4.5),
    ("danger", "panel", 3.0),  # bold warning title (large/bold text)
)
