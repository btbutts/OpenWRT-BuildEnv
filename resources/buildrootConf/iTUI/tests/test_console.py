"""Tests for terminal mode detection and palette programming."""

from prompt_toolkit.output import ColorDepth

from openwrt_install_wizard import console, theme


def test_real_vt_is_remapped() -> None:
    """TERM=linux on /dev/ttyN is a reprogrammable Linux VT."""
    assert console.detect_mode({"TERM": "linux"}, "/dev/tty1") == theme.MODE_VT


def test_serial_linux_term_is_not_remapped() -> None:
    """TERM=linux on a serial line or without a tty must not get palette escapes."""
    assert console.detect_mode({"TERM": "linux"}, "/dev/ttyS0") == theme.MODE_ANSI
    assert console.detect_mode({"TERM": "linux"}, "") == theme.MODE_ANSI


def test_truecolor_and_xterm() -> None:
    """COLORTERM and xterm-like TERM values select hex colours."""
    assert (
        console.detect_mode({"TERM": "xterm", "COLORTERM": "truecolor"}, "") == theme.MODE_TRUECOLOR
    )
    assert console.detect_mode({"TERM": "xterm-256color"}, "/dev/pts/1") == theme.MODE_TRUECOLOR


def test_unknown_term_falls_back_to_ansi() -> None:
    """Unknown terminals get the stock 16 colours."""
    assert console.detect_mode({"TERM": "vt100"}, "/dev/ttyS0") == theme.MODE_ANSI


def test_palette_sequence_programs_all_16_slots() -> None:
    """The palette escape sets every slot, with the user's colours in place."""
    sequence = console.palette_set_sequence()
    assert sequence.count("\x1b]P") == theme.PALETTE_SIZE
    assert "\x1b]P013141a" in sequence  # slot 0 = backdrop
    assert "\x1b]P8bb8c05" in sequence  # slot 8 = accent


def test_color_depth_selection() -> None:
    """16-colour modes use 4-bit; 24-bit only when COLORTERM advertises it."""
    assert console.detect_color_depth(theme.MODE_VT, {}) == ColorDepth.DEPTH_4_BIT
    assert console.detect_color_depth(theme.MODE_ANSI, {}) == ColorDepth.DEPTH_4_BIT
    truecolor = console.detect_color_depth(theme.MODE_TRUECOLOR, {"COLORTERM": "truecolor"})
    assert truecolor == ColorDepth.DEPTH_24_BIT
    assert console.detect_color_depth(theme.MODE_TRUECOLOR, {}) is None
