#!/bin/bash
set -e
TARGET="$1"
INITTAB="${TARGET}/etc/inittab"
PASSWD="${TARGET}/etc/passwd"
SHADOW="${TARGET}/etc/shadow"
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
# USB installer: empty BR2_TARGET_GENERIC_ROOT_PASSWD. Force an empty
# shadow hash so pam_unix nullok accepts root with no password. A '!'
# or '*' here would lock the account even with ENABLE_ROOT_LOGIN.
if [ -f "${SHADOW}" ]; then
    if grep -q '^root:' "${SHADOW}"; then
        sed -i 's|^root:[^:]*:|root::|' "${SHADOW}"
    else
        printf '%s\n' 'root::0:0:99999:7:::' >> "${SHADOW}"
    fi
    chmod 640 "${SHADOW}" || true
fi
# pam_securetty is not in the login stack. Remove a stock securetty
# list if a package drops one so root is not restricted to named ttys.
rm -f "${TARGET}/etc/nologin" "${TARGET}/etc/securetty"
if [ -f "${SHELLS}" ] && ! grep -qx "${ROOT_SHELL}" "${SHELLS}"; then
    printf '%s\n' "${ROOT_SHELL}" >> "${SHELLS}"
fi
