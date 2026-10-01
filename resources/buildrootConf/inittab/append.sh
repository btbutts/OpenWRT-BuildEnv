#!/bin/bash
set -e
TARGET="$1"
INITTAB="${TARGET}/etc/inittab"
PASSWD="${TARGET}/etc/passwd"
SHELLS="${TARGET}/etc/shells"

# BusyBox ships "#::ctrlaltdel:/sbin/reboot" commented out. A grep for
# ctrlaltdel matches that comment and skips installing a live action, so
# SIGINT from the kernel's CAD handler has nothing to run.
if [ -f "${INITTAB}" ]; then
    sed -i '/ctrlaltdel/d' "${INITTAB}"
    printf '\n::ctrlaltdel:/sbin/reboot -f\n' >> "${INITTAB}"
fi

# Root login shell: zsh when present, else bash. /bin/sh is already bash
# via BR2_SYSTEM_BIN_SH; login reads the last passwd field instead.
ROOT_SHELL="/bin/bash"
if [ -x "${TARGET}/bin/zsh" ]; then
    ROOT_SHELL="/bin/zsh"
elif [ -x "${TARGET}/usr/bin/zsh" ]; then
    ROOT_SHELL="/usr/bin/zsh"
fi
if [ -f "${PASSWD}" ]; then
    sed -i "s|^root:[^:]*:[^:]*:[^:]*:[^:]*:[^:]*:.*|root:x:0:0:root:/root:${ROOT_SHELL}|" "${PASSWD}"
fi
if [ -f "${SHELLS}" ] && ! grep -qx "${ROOT_SHELL}" "${SHELLS}"; then
    printf '%s\n' "${ROOT_SHELL}" >> "${SHELLS}"
fi
