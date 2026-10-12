# Sourced by /etc/profile (login bash), /etc/zshrc (interactive zsh),
# and /root/.bashrc (non-login interactive bash). Do not execute.
# Functions are not inherited by child shells; do not put this in profile.d.
# shellcheck disable=SC2148

# ls -alh with the permission bits as a leading octal mode.
lsnum() {
    # shellcheck disable=SC2016
    local parse_perms='{k=0;for(i=0;i<=8;i++)k+=((substr($1,i+2,1)~/[rwx]/)*2^(8-i));if(k)printf("%0o ",k);print}'

    # Use current directory if no arguments are provided, otherwise use all arguments
    # shellcheck disable=SC2012
    ls -alh "${@:-.}" | awk "$parse_perms"
}

# Change the font or the font size of the kmscon console, and start the console over so that
# the new one is used.
#
#   set-kmscon-font --font-name "DejaVu Sans Mono:style=Bold" --font-size 22
#   set-kmscon-font --font-size 26          (only the size; the name stays)
#   set-kmscon-font --list                  (every font there is; ":spacing=100" marks fixed width)
#   set-kmscon-font                         (what is configured now)
#   set-kmscon-font --font-size 26 --no-restart   (change the file only)
#
# kmscon reads /etc/kmscon/kmscon.conf when it starts and has no way to switch fonts while
# it runs (Ctrl + and Ctrl - only zoom the size, for that session). Its own units are off in
# this image: the console is started by console-getty.service. So the function edits the file
# and ends this shell; shell-exit.sh sees the request (a stamp in /run) and starts the shell
# console again, straight into a new kmscon, instead of going on to the wizard. This shell's
# history and environment are lost. From ssh (or a plain getty) only the file is changed, and
# it is used the next time the console starts.
#
# Font names are fontconfig names: the family, then ":style=" for a face of it. The file
# DejaVuSansMono-Bold.ttf is "DejaVu Sans Mono:style=Bold". "DejaVu Sans Mono Bold" and
# "DejaVuSansMono-Bold" are not family names and select other fonts.
set-kmscon-font() {
    local conf="${KMSCON_CONF:-/etc/kmscon/kmscon.conf}"
    local stamp="${INSTALLER_SHELL_RELOAD:-/run/installer-shell.reload}"
    local name="" size="" restart=1 list=0 pair key val tmp first requested resolved lowered

    while [ $# -gt 0 ]; do
        case "$1" in
            --font-name)
                if [ $# -lt 2 ]; then echo "set-kmscon-font: --font-name needs a value" >&2; return 2; fi
                name="$2"; shift 2 ;;
            --font-name=*) name="${1#--font-name=}"; shift ;;
            --font-size)
                if [ $# -lt 2 ]; then echo "set-kmscon-font: --font-size needs a value" >&2; return 2; fi
                size="$2"; shift 2 ;;
            --font-size=*) size="${1#--font-size=}"; shift ;;
            --no-restart) restart=0; shift ;;
            --list) list=1; shift ;;
            -h|--help)
                sed -n '/^# Change the font or the font size/,/^# "DejaVuSansMono-Bold" are not/p' \
                    /etc/shared-shell.sh | sed 's/^# \{0,1\}//'
                return 0 ;;
            *) echo "set-kmscon-font: unknown argument: $1 (see --help)" >&2; return 2 ;;
        esac
    done

    if [ "$list" -eq 1 ]; then
        if ! command -v fc-list > /dev/null 2>&1; then
            echo "set-kmscon-font: fc-list is not installed" >&2
            return 1
        fi
        # Every family, not only the ones flagged as fixed width: patched fonts such as the
        # Nerd Fonts are often not flagged (no ":spacing=100") but work in a terminal.
        # A comma separates names the same font goes by; either can be used.
        fc-list : family style spacing | sort -u
        return 0
    fi

    if [ -z "$name" ] && [ -z "$size" ]; then
        echo "kmscon font in ${conf}:"
        grep -E '^(font-name|font-size)=' "$conf" 2> /dev/null || echo "  (nothing set: kmscon's defaults)"
        echo "Use --font-name NAME and/or --font-size N; --list shows the names."
        return 0
    fi

    if [ -n "$size" ]; then
        case "$size" in
            ''|*[!0-9]*) echo "set-kmscon-font: --font-size must be a whole number" >&2; return 2 ;;
        esac
        if [ "$size" -lt 8 ] || [ "$size" -gt 150 ]; then
            echo "set-kmscon-font: --font-size must be between 8 and 150 (pixels)" >&2
            return 2
        fi
    fi

    if [ -n "$name" ]; then
        case "$name" in
            *'#'*|*\\*) echo "set-kmscon-font: the name may not contain # or a backslash" >&2; return 2 ;;
        esac
        # fontconfig always answers; it is the family it answers with that tells whether
        # the name was understood.
        if command -v fc-match > /dev/null 2>&1; then
            # A list ("Source Code Pro,DejaVu Sans Mono") is checked by its first family:
            # fontconfig answers with the first of the list that is installed.
            first="${name%%:*}"
            first="${first%%,*}"
            resolved="$(fc-match -f '%{family}' "$name" 2> /dev/null)"
            lowered="$(printf '%s' "$resolved" | tr '[:upper:]' '[:lower:]')"
            requested="$(printf '%s' "$first" | tr '[:upper:]' '[:lower:]')"
            case ",${lowered}," in
                *",${requested},"*) ;;
                *)
                    echo "set-kmscon-font: no font family \"${first}\" (closest: ${resolved:-none})." >&2
                    echo "  Names look like: DejaVu Sans Mono:style=Bold   (see --list)" >&2
                    return 1 ;;
            esac
        fi
    fi

    if [ ! -w "$conf" ] && [ -e "$conf" ]; then
        echo "set-kmscon-font: cannot write ${conf}" >&2
        return 1
    fi

    # Replace the line of each key in place (so the file's comments stay where they are),
    # or add it at the end when the file has none.
    tmp="${conf}.tmp.$$"
    [ -e "$conf" ] || : > "$conf"
    cp "$conf" "$tmp" || return 1
    for pair in "font-name:${name}" "font-size:${size}"; do
        key="${pair%%:*}"
        val="${pair#*:}"
        [ -n "$val" ] || continue
        awk -v k="$key" -v v="$val" '
            index($0, k "=") == 1 { if (!done) { print k "=" v; done = 1 } ; next }
            { print }
            END { if (!done) print k "=" v }' "$tmp" > "${tmp}.new" && mv -f "${tmp}.new" "$tmp"
    done
    mv -f "$tmp" "$conf"
    echo "kmscon.conf now has:"
    grep -E '^(font-name|font-size)=' "$conf" | sed 's/^/  /'

    if [ "$restart" -eq 0 ]; then
        echo "Not restarting (--no-restart): it is used the next time the console starts."
        return 0
    fi
    if [ "${TERM:-}" != "kmscon" ] || [ ! -t 0 ]; then
        echo "This is not the kmscon console, so it is not restarted: the new font is used the"
        echo "next time the console starts (type exit there, or run this on the console)."
        return 0
    fi
    : > "$stamp" || return 1
    echo "Starting the console over with the new font (this shell ends; a new one starts)..."
    sleep 1
    exit 0
}
