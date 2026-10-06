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
} > "${tmp}"
mv -f "${tmp}" /run/motd.dynamic
chmod 644 /run/motd.dynamic
