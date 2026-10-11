#!/bin/bash
# /root/show-fonts.sh
#
# Page through the console fonts under /usr/share/consolefonts (and its
# subdirectories) on a text virtual console. For each font: load it with
# setfont, draw its glyph grid with showconsolefont, then print a sample of
# letters, digits, punctuation and the box-drawing characters the installer
# TUI uses.
#
#   Right / Down / f / Space / Enter   next font
#   Left  / Up   / b                   previous font
#   q                                  quit
#
# Both ends wrap around. setfont only changes the font in the running kernel
# (nothing is written to disk and a reboot clears it), but it stays changed
# after this script ends, so the font in use when the script starts is saved
# first and put back on exit or Ctrl-C. If that copy cannot be made, the
# kernel's boot default font is restored instead.
#
# Where it runs. These are kernel console fonts: setfont only works on a VT
# that is in text mode. That is the case on a getty login, but not inside
# kmscon (which draws the screen itself, in graphics mode, and whose terminal
# is a pty), nor over ssh or a serial line. When the terminal this is started
# from is not a text VT, the script opens one for itself with openvt, switches
# to it, runs the preview there, and switches back to where it was when you
# quit. Keys are then read from the keyboard attached to that VT, so type them
# at the machine's own keyboard, not in the ssh session.
#
# Usage: show-fonts.sh [--partial]
#   --partial   also list partialfonts/ (glyph subsets meant to be merged into
#               a full font; on their own they render mostly blank)
# TTY=/dev/tty2 show-fonts.sh   preview on that VT; it is used as it is and no
#                               spare VT is opened.

FONT_DIR="${FONT_DIR:-/usr/share/consolefonts}"

find_args=(-type f -name '*.gz')
if [ "${1:-}" != "--partial" ]; then
    find_args+=(! -path "${FONT_DIR}/partialfonts/*")
fi

mapfile -t FONTS < <(find "$FONT_DIR" "${find_args[@]}" | sort)
TOTAL=${#FONTS[@]}
if [ "$TOTAL" -eq 0 ]; then
    echo "No fonts found under ${FONT_DIR}." >&2
    exit 1
fi

# Pick the console the font operations go to. A text VT (getty) is used as it
# is. Anything else (kmscon's pty, ssh, a serial line) is re-run on a spare VT.
if [ -z "${TTY:-}" ]; then
    here="$(tty 2>/dev/null)" || here=""
    dev_dir="${SHOW_FONTS_DEV_DIR:-/dev}"   # only the tests change this
    if [[ "$here" =~ ^${dev_dir}/tty[0-9]+$ ]] || { [ -n "${SHOW_FONTS_ON_VT:-}" ] && [ -n "$here" ]; }; then
        TTY="$here"
    else
        if ! command -v openvt > /dev/null 2>&1; then
            {
                echo "show-fonts.sh: this terminal (${here:-none}) is not a text console and"
                echo "openvt is not installed to open one. Log in on a text VT (e.g. Alt+F2)"
                echo "and run it there, or name a VT with TTY=/dev/ttyN."
            } >&2
            exit 1
        fi
        echo "Opening the font preview on a spare text console; it switches back here when you quit."
        SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
        # TERM=linux: the new VT is the kernel console, not kmscon (TERM=kmscon).
        exec openvt -s -w -- env TERM=linux SHOW_FONTS_ON_VT=1 "$SELF" "$@"
    fi
fi

# Save the font (with its unicode map) and console map now in use.
SAVE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/show-fonts.XXXXXX")"
ORIG_FONT="${SAVE_DIR}/orig.psf"
ORIG_MAP="${SAVE_DIR}/orig.map"
SAVED=0
if setfont -O "$ORIG_FONT" -om "$ORIG_MAP" < "$TTY" 2>/dev/null && [ -s "$ORIG_FONT" ]; then
    SAVED=1
fi

restore_font() {
    if [ "$SAVED" = 1 ]; then
        setfont "$ORIG_FONT" -m "$ORIG_MAP" < "$TTY" 2>/dev/null \
            || setfont "$ORIG_FONT" < "$TTY" 2>/dev/null \
            || setfont -R < "$TTY" 2>/dev/null
    else
        setfont -R < "$TTY" 2>/dev/null || setfont < "$TTY" 2>/dev/null
    fi
    rm -rf "$SAVE_DIR"
    printf '\n'
}
trap restore_font EXIT
trap 'exit 130' INT TERM

# Wait for a navigation key; prints next, prev or quit. Other keys are ignored.
read_key() {
    local k rest
    while :; do
        IFS= read -r -s -n 1 k || { echo quit; return; }
        rest=""
        if [ "$k" = $'\e' ]; then
            # Arrow keys arrive as ESC [ C (or ESC O C); a lone Esc has no tail.
            IFS= read -r -s -n 2 -t 0.05 rest
        fi
        case "${k}${rest}" in
            $'\e[C' | $'\e[B' | $'\eOC' | $'\eOB' | f | F | ' ' | '') echo next; return ;;
            $'\e[D' | $'\e[A' | $'\eOD' | $'\eOA' | b | B) echo prev; return ;;
            q | Q) echo quit; return ;;
        esac
    done
}

idx=0
while :; do
    font="${FONTS[idx]}"
    clear

    # .cp.gz codepage files and a few oddballs may be refused by setfont;
    # report that and carry on.
    if ! setfont "$font" < "$TTY"; then
        printf 'setfont could not load %s\n' "$font"
    else
        showconsolefont < "$TTY"
    fi

    read -r rows cols < <(stty size < "$TTY" 2>/dev/null)
    printf '\n[%d/%d] %s   (console grid %sx%s)\n' \
        "$((idx + 1))" "$TOTAL" "${font#"${FONT_DIR}"/}" "${cols:-?}" "${rows:-?}"
    printf '%s\n%s\n%s\n' \
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ" \
        "abcdefghijklmnopqrstuvwxyz" \
        "0123456789"
    printf '%s\n' '!"#$%&'"'"'()*+,-./:;<=>?@[\]^_`{|}~  O0 Il1|'
    printf '%s\n' '┌─┬─┐ │ ├─┼─┤ └─┴─┘ ░▒▓█ ▲▼◄► ✓ ✗ •'
    printf '%s' '<- / b previous   -> / f / Enter next   q quit '

    case "$(read_key)" in
        next) idx=$(((idx + 1) % TOTAL)) ;;
        prev) idx=$(((idx + TOTAL - 1) % TOTAL)) ;;
        quit) break ;;
    esac
done
