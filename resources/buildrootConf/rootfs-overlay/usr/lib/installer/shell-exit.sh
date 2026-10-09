#!/bin/bash
# /usr/lib/installer/shell-exit.sh
#
# Decides what follows the root login shell on the installer console.
#
#   shell-exit.sh stamp   ExecStartPre of console-getty.service: record start time.
#   shell-exit.sh         ExecStopPost of console-getty.service: choose the next unit.
#
# Loop:  installer-wizard -> (cancel) -> console-getty/zsh -> (exit) -> installer-wizard
#
# Environment from systemd in ExecStopPost: SERVICE_RESULT, EXIT_CODE, EXIT_STATUS.

CMDLINE_FILE="${INSTALLER_CMDLINE_FILE:-/proc/cmdline}"
STAMP="${INSTALLER_SHELL_STAMP:-/run/installer-shell.started}"
MIN_LIFETIME=3
WIZARD_UNIT=installer-wizard.service
GETTY_UNIT=console-getty.service

log() {
    logger -t installer-shell-exit "$*" 2>/dev/null || echo "installer-shell-exit: $*" >&2
}

cmdline_has() {
    case " $(cat "$CMDLINE_FILE" 2>/dev/null) " in
        *" $1 "*) return 0 ;;
    esac
    return 1
}

if [ "${1:-}" = "stamp" ]; then
    date +%s > "$STAMP" 2>/dev/null || true
    exit 0
fi

# The wizard unit stopped this getty through Conflicts=: it is starting (or has
# a queued start job waiting for this stop), so do nothing and avoid a fight.
state="$(systemctl is-active "$WIZARD_UNIT" 2>/dev/null)"
case "$state" in
    active|activating|reloading)
        log "wizard is $state; leaving getty stopped"
        exit 0
        ;;
esac
if systemctl list-jobs --no-legend 2>/dev/null | grep -q "$WIZARD_UNIT.*start"; then
    log "wizard start job pending; leaving getty stopped"
    exit 0
fi

start_getty() {
    log "restarting $GETTY_UNIT ($1)"
    # Rate-limit: StartLimitIntervalSec=0 is set on the units, so a getty that
    # cannot start at all would otherwise spin.
    sleep 1
    systemctl start --no-block "$GETTY_UNIT"
    exit 0
}

# Maintenance entries never run the wizard: keep today's behaviour.
if cmdline_has installer.mode=shell; then
    start_getty "installer.mode=shell"
fi

# Not a clean exit (SIGHUP from a VT hangup / GPU console takeover): the user
# did not type `exit`, so just bring the shell back.
if [ "${SERVICE_RESULT:-success}" != "success" ]; then
    start_getty "SERVICE_RESULT=${SERVICE_RESULT}"
fi

# A shell that died within seconds was not an operator exiting either.
started="$(cat "$STAMP" 2>/dev/null || echo 0)"
now="$(date +%s)"
if [ "$started" -gt 0 ] 2>/dev/null && [ $((now - started)) -lt "$MIN_LIFETIME" ]; then
    start_getty "shell lived $((now - started))s"
fi

log "root shell exited; restarting $WIZARD_UNIT"
systemctl start --no-block "$WIZARD_UNIT"
exit 0
