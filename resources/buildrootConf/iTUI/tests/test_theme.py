"""Tests for the colour palette, contrast guarantees and style construction."""

from openwrt_install_wizard import theme

LOW_BACKGROUND_SLOTS = 8
ACCENT_ON_PANEL_CEILING = 3


def test_contrast_pairs_meet_minimum() -> None:
    """Every declared foreground/background pair is readable."""
    for fg, bg, minimum in theme.CONTRAST_PAIRS:
        ratio = theme.contrast_ratio(theme.TOKENS[fg].hex, theme.TOKENS[bg].hex)
        assert ratio >= minimum, f"{fg} on {bg}: {ratio:.2f} < {minimum}"


def test_accent_is_unreadable_on_panel_so_it_must_stay_in_the_chip() -> None:
    """The gold accent is only usable inside its dark chip."""
    ratio = theme.contrast_ratio(theme.TOKENS["accent"].hex, theme.TOKENS["panel"].hex)
    assert ratio < ACCENT_ON_PANEL_CEILING


def test_palette_has_16_slots_and_user_colours() -> None:
    """The VT palette carries the four colours chosen by the user."""
    palette = theme.vt_palette()
    assert len(palette) == theme.PALETTE_SIZE
    assert palette[theme.TOKENS["backdrop"].slot] == "13141a"
    assert palette[theme.TOKENS["panel"].slot] == "7f8188"
    assert palette[theme.TOKENS["ink"].slot] == "011b24"
    assert palette[theme.TOKENS["accent"].slot] == "bb8c05"


def test_backgrounds_only_use_low_slots() -> None:
    """Bright backgrounds are unreliable on fbcon, so backgrounds stay in 0-7."""
    for token in ("backdrop", "panel", "ink", "shadow", "button", "danger"):
        assert theme.TOKENS[token].slot < LOW_BACKGROUND_SLOTS


def test_slots_are_unique() -> None:
    """No two tokens share a palette slot."""
    slots = [c.slot for c in theme.TOKENS.values()]
    assert len(slots) == len(set(slots))


def test_style_builds_in_every_mode() -> None:
    """A style sheet can be built for each render mode."""
    for mode in (theme.MODE_VT, theme.MODE_TRUECOLOR, theme.MODE_ANSI):
        assert theme.build_style(mode) is not None


def test_glyphs_ascii_on_linux_console() -> None:
    """The Linux console font gets ASCII markers; other terminals get Unicode."""
    assert theme.glyphs_for(theme.MODE_VT).check == "x"
    assert theme.glyphs_for(theme.MODE_TRUECOLOR).check != "x"
