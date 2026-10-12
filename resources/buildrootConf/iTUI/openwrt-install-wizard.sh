#!/bin/bash
# /usr/bin/openwrt-install-wizard.sh
#
# ExecStart of installer-wizard.service. Starts the prompt_toolkit wizard
# (python3 -m openwrt_install_wizard.main) and falls back to the dialog-based
# /usr/bin/wizard.sh when the Python wizard cannot start or crashes.
#
# Exit 0 on cancel or when the wizard finishes: systemd (OnSuccess=) then
# starts console-getty.service for the root shell. Exiting that shell makes
# /usr/lib/installer/shell-exit.sh start this unit again.
#
# Kernel command line:
#   installer.ui=bash   force the old wizard.sh

WIZARD_SH=/usr/bin/wizard.sh
PKG_LIB_DIR=/usr/lib/installer
PKG_DIR=$PKG_LIB_DIR/openwrt_install_wizard
LOG=/var/log/installer-wizard-launcher.log
INSTALL_STARTED=/run/installer-install-started
CMDLINE_FILE="${INSTALLER_CMDLINE_FILE:-/proc/cmdline}"

log() {
    mkdir -p /var/log 2>/dev/null || true
    printf '%s openwrt-install-wizard: %s\n' \
        "$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || echo '?')" "$*" >> "$LOG" 2>/dev/null || true
}

cmdline_has() {
    case " $(cat "$CMDLINE_FILE" 2>/dev/null) " in
        *" $1 "*) return 0 ;;
    esac
    return 1
}

# Give the console back to a sane state before handing it to wizard.sh.
reset_console() {
    [ "${TERM:-}" = "linux" ] && printf '\033]R' 2>/dev/null
    printf '\033[0m\033[H\033[2J' 2>/dev/null
    stty sane 2>/dev/null || true
}

fallback() {
    log "falling back to $WIZARD_SH: $*"
    reset_console
    exec "$WIZARD_SH"
}

export TERM="${TERM:-linux}"

if cmdline_has installer.ui=bash; then
    log "installer.ui=bash: using $WIZARD_SH"
    exec "$WIZARD_SH"
fi

command -v python3 >/dev/null 2>&1 || fallback "python3 not found"
[ -d "$PKG_DIR" ] || fallback "$PKG_DIR missing"
python3 -c 'import prompt_toolkit, wcwidth' 2>>"$LOG" \
    || fallback "prompt_toolkit/wcwidth not importable"

# A stale marker from an earlier loop iteration must not suppress the fallback.
rm -f "$INSTALL_STARTED"

PYTHONPATH="$PKG_LIB_DIR${PYTHONPATH:+:$PYTHONPATH}" python3 -m openwrt_install_wizard.main
rc=$?

if [ "$rc" -eq 0 ]; then
    exit 0
fi

log "python wizard exited rc=$rc"
if [ -e "$INSTALL_STARTED" ]; then
    # setup.sh already ran (or is still running). Re-asking the wipe questions
    # in wizard.sh would be dangerous; hand over to the root shell instead.
    reset_console
    echo "The installer wizard stopped unexpectedly after the installation started (rc=$rc)."
    echo "See /var/log/installer-setup.log and /var/log/installer-wizard-py.log."
    exit 0
fi
fallback "rc=$rc"
