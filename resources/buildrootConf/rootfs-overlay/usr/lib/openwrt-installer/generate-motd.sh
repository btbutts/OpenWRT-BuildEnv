#!/bin/bash
# Build /run/motd.dynamic at login for pam_motd.
# NAME comes from /etc/os-release

set -euo pipefail

if [ -r /usr/lib/os-release ]; then
    # shellcheck disable=SC1091
    . /usr/lib/os-release
elif [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
fi
NAME="${NAME:-OpenWRT-Installer GNU/Linux}"

# Name (comm) of process $1, and its parent's pid. /proc/<pid>/stat is
# "pid (comm) state ppid ...", and comm may hold spaces, so cut after the ") ".
proc_name() { cat "/proc/$1/comm" 2>/dev/null || true; }
proc_parent() {
    local stat rest fields
    stat="$(cat "/proc/$1/stat" 2>/dev/null)" || return 0
    rest="${stat##*) }"
    read -r -a fields <<< "${rest}"
    printf '%s\n' "${fields[1]:-0}"
}

# True when a kmscon process exists.
kmscon_running() {
    local comm
    for comm in /proc/[0-9]*/comm; do
        if [ "$(cat "${comm}" 2>/dev/null || true)" = "kmscon" ]; then
            return 0
        fi
    done
    return 1
}

# Which program is in charge of the console this login came from: walk up from
# this script (run by pam_exec, under login or sshd) until kmscon, agetty or
# sshd. Prints kmscon, getty, ssh:kmscon or ssh:getty.
console_owner() {
    local pid="$$" via="" depth=0
    while [ "${pid:-0}" -gt 1 ] && [ "${depth}" -lt 16 ]; do
        case "$(proc_name "${pid}")" in
            kmscon) via="kmscon"; break ;;
            agetty) via="getty"; break ;;
            sshd*) via="ssh"; break ;;
        esac
        pid="$(proc_parent "${pid}")"
        depth=$((depth + 1))
    done
    if [ -z "${via}" ]; then
        # No known ancestor: the terminal type is the next best hint.
        case "${TERM:-}" in
            kmscon*) via="kmscon" ;;
            *) via="getty" ;;
        esac
    fi
    if [ "${via}" = "ssh" ]; then
        if kmscon_running; then via="ssh:kmscon"; else via="ssh:getty"; fi
    fi
    printf '%s\n' "${via}"
}

case "$(console_owner)" in
    kmscon) OWNER="Console owner: KMSCON (kernel mode-setting console)" ;;
    getty) OWNER="Console owner: GETTY (plain Linux virtual terminal)" ;;
    ssh:kmscon) OWNER="Connected over SSH. The local console is owned by KMSCON." ;;
    ssh:getty) OWNER="Connected over SSH. The local console is owned by GETTY." ;;
    *) OWNER="Console owner: unknown" ;;
esac

# ---- last login -----------------------------------------------------------
# The previous login of this boot, from either the console or ssh, is kept in
# LAST_FILE (epoch|how|detail). pam_exec hands us PAM_SERVICE (login or sshd),
# PAM_TTY and PAM_RHOST. The line printed is the one recorded by the login before
# this one; this login is recorded for the next.
LAST_FILE="/run/installer-lastlogin"
LAST_LINE=""
if [ -r "${LAST_FILE}" ]; then
    IFS='|' read -r last_time last_how last_detail < "${LAST_FILE}" || true
    if [ -n "${last_time:-}" ]; then
        last_date="$(date -d "@${last_time}" 2>/dev/null || echo "epoch ${last_time}")"
        case "${last_how:-}" in
            ssh) LAST_LINE="Last login: ${last_date} over SSH from ${last_detail}" ;;
            console) LAST_LINE="Last login: ${last_date} on the console (${last_detail})" ;;
            *) LAST_LINE="Last login: ${last_date}" ;;
        esac
    fi
fi
tty_name="${PAM_TTY:-}"
tty_name="${tty_name#/dev/}"
case "${PAM_SERVICE:-}" in
    sshd) now_how="ssh"; now_detail="${PAM_RHOST:-unknown host} (${tty_name:-no tty})" ;;
    *) now_how="console"; now_detail="${tty_name:-tty}" ;;
esac

umask 022
tmp="/run/motd.dynamic.tmp.$$"
{
    uname -snrvm
    printf '\n'
    cat << EOF
The programs included with the ${NAME} system are free software;
the exact distribution terms for each program are described in the
individual files in /usr/share/doc/*/README,COPYING,AUTHORS.

${NAME} comes with ABSOLUTELY NO WARRANTY, to the extent
permitted by applicable law.

EOF
    printf '%s\n' "${OWNER}"
    if [ -n "${LAST_LINE}" ]; then
        printf '%s\n' "${LAST_LINE}"
    fi
} > "${tmp}"
mv -f "${tmp}" /run/motd.dynamic
chmod 644 /run/motd.dynamic

# Remember this login for the next one.
printf '%s|%s|%s\n' "$(date +%s)" "${now_how}" "${now_detail}" > "${LAST_FILE}.tmp.$$"
mv -f "${LAST_FILE}.tmp.$$" "${LAST_FILE}"
