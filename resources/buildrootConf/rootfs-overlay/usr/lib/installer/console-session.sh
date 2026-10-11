#!/bin/bash
# /usr/lib/installer/console-session.sh
#
# Runs the installer wizard or the root login shell on the console: inside
# kmscon when a real display is up, on the plain Linux VT (getty) otherwise.
#
#   console-session.sh wizard   ExecStart of installer-wizard.service
#   console-session.sh shell    ExecStart of console-getty.service
#   console-session.sh --child <wizard|shell>
#                               the program kmscon runs; not called by systemd
#
# kmscon is used when ALL of these hold:
#   * the kernel console is a virtual terminal (not console=ttyS0 and so on)
#   * a DRM card driven by a real display driver (amdgpu, i915, nouveau, a
#     virtual GPU, ...; not the firmware framebuffer: simpledrm and friends)
#     has a connected connector
#   * /usr/bin/kmscon exists and has not failed earlier in this boot
#   * installer.console=getty is not on the kernel command line
# Otherwise the getty path runs exactly what the units ran before kmscon.
#
# The wizard is only ever started by this script, so it cannot start on the VT
# first and then block kmscon: it waits here (bounded) for the display driver.
# A wizard or shell that is already running is never touched.
#
# Seat access, tried in this order (the first that gets the session going):
#   1. kmscon --libseat. The units run under PAMName=installer-console, so
#      pam_systemd gives them a logind session and libseat takes the seat
#      through systemd-logind. Only tried when that session is bound to a seat
#      and a VT (XDG_SESSION_ID, XDG_SEAT and XDG_VTNR are set), and not again
#      this boot once it has failed.
#   2. kmscon on its own: as root it owns the VT and the DRM device directly.
#   3. getty: what the units ran before kmscon.
#
# Fallback. kmscon is started with --oneshot, so it exits when its child does,
# which keeps the wizard <-> shell loop of shell-exit.sh working unchanged.
#   * kmscon never got as far as starting the child (no display usable, crash
#     at start-up, or no child within the start timeout): kmscon is stopped
#     and the next way down the list is used at once.
#   * kmscon dies after the session started (GPU reset, crash): "failed" is
#     recorded; a shell is replaced by a getty shell right away, the wizard is
#     not restarted from here (the unit ends and the usual OnFailure/shell-exit
#     flow follows, which now takes the getty path).
#   * "failed" lasts until reboot (/run is a tmpfs): no crash loop.
#
# Kernel command line:
#   installer.console=getty          never use kmscon
#   installer.console.libseat=0      never use libseat (skip way 1)
#
# Every path and tool can be overridden through INSTALLER_* variables; the
# tests use that to run this script against a fake /sys.

SYSFS="${INSTALLER_SYSFS:-/sys}"
CMDLINE_FILE="${INSTALLER_CMDLINE_FILE:-/proc/cmdline}"
RUN_DIR="${INSTALLER_RUN_DIR:-/run}"
KMSCON="${INSTALLER_KMSCON:-/usr/bin/kmscon}"
AGETTY="${INSTALLER_AGETTY:-/sbin/agetty}"
LOGIN="${INSTALLER_LOGIN:-/bin/login}"
WIZARD="${INSTALLER_WIZARD:-/usr/bin/openwrt-install-wizard.sh}"
UDEVADM="${INSTALLER_UDEVADM:-udevadm}"
# Seconds to let udev finish loading drivers, and then to keep looking for a
# connected display after that.
SETTLE_WAIT="${INSTALLER_CONSOLE_WAIT:-30}"
EXTRA_WAIT="${INSTALLER_CONSOLE_EXTRA_WAIT:-5}"
# Seconds kmscon may take to start the child before it is given up on: with
# libseat (a failure there is usually immediate) and without.
LIBSEAT_TIMEOUT="${INSTALLER_KMSCON_LIBSEAT_TIMEOUT:-10}"
START_TIMEOUT="${INSTALLER_KMSCON_START_TIMEOUT:-20}"
# Seconds between asking kmscon to stop and killing it.
STOP_GRACE="${INSTALLER_KMSCON_STOP_GRACE:-3}"
POLL="${INSTALLER_CONSOLE_POLL:-0.5}"

STAMP="$RUN_DIR/installer-kmscon-session.started"
FAILED="$RUN_DIR/installer-kmscon.failed"
LIBSEAT_FAILED="$RUN_DIR/installer-kmscon-libseat.failed"
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"

# DRM drivers that only scan out the firmware framebuffer. They show the boot
# console but are no reason to move the installer into kmscon: the real GPU
# driver replaces them a moment later.
FIRMWARE_FB_DRIVERS="simple-framebuffer simpledrm efi-framebuffer efidrm \
vesa-framebuffer vesadrm of-display ofdrm offb vkms vgem"
# Modules whose absence from the boot (nomodeset, modprobe.blacklist=) means
# no display driver is coming, so waiting for one would only delay the console.
GPU_MODULES="amdgpu i915 xe nouveau radeon"

log() {
    logger -t installer-console "$*" 2>/dev/null || echo "installer-console: $*" >&2
}

pause() {
    sleep "$POLL" 2>/dev/null || sleep 1
}

cmdline() {
    cat "$CMDLINE_FILE" 2>/dev/null
}

cmdline_has() {
    case " $(cmdline) " in
        *" $1 "*) return 0 ;;
    esac
    return 1
}

# The last console= argument, without its ",115200n8" options.
cmdline_console() {
    local word last=""
    for word in $(cmdline); do
        case "$word" in
            console=*) last="${word#console=}" ;;
        esac
    done
    printf '%s\n' "${last%%,*}"
}

# Print the virtual terminal the console is on (tty1, ...) or fail when the
# console is a serial line or anything else kmscon cannot draw on.
console_vt() {
    local con
    con="$(cmdline_console)"
    case "$con" in
        ""|tty0) printf 'tty1\n' ;;
        tty[0-9]*) printf '%s\n' "$con" ;;
        *) return 1 ;;
    esac
}

# Print the kernel driver name of a /sys/class/drm/cardN entry.
drm_driver() {
    local line
    while IFS= read -r line; do
        case "$line" in
            DRIVER=*)
                printf '%s\n' "${line#DRIVER=}"
                return 0
                ;;
        esac
    done 2>/dev/null < "$1/device/uevent"
    return 1
}

is_firmware_fb() {
    local name
    for name in $FIRMWARE_FB_DRIVERS; do
        [ "$name" = "$1" ] && return 0
    done
    return 1
}

# True when a real display driver has a connected output. Which driver it is
# does not matter: anything that is not the firmware framebuffer counts.
display_ready() {
    local card name driver status
    for card in "$SYSFS"/class/drm/card[0-9]*; do
        [ -e "$card" ] || continue
        name="${card##*/}"
        case "$name" in
            *-*) continue ;;  # a connector (card0-HDMI-A-1), not a card
        esac
        driver="$(drm_driver "$card")" || continue
        is_firmware_fb "$driver" && continue
        for status in "$SYSFS"/class/drm/"$name"-*/status; do
            [ -f "$status" ] || continue
            [ "$(cat "$status" 2>/dev/null)" = "connected" ] && return 0
        done
    done
    return 1
}

# True when the boot options keep the display drivers out.
gpu_disabled_on_cmdline() {
    local word module
    cmdline_has nomodeset && return 0
    for word in $(cmdline); do
        case "$word" in
            modprobe.blacklist=*)
                for module in $GPU_MODULES; do
                    case ",${word#modprobe.blacklist=}," in
                        *",$module,"*) return 0 ;;
                    esac
                done
                ;;
        esac
    done
    return 1
}

# Give the display driver every chance to come up, but never wait for one that
# was switched off or does not exist: udev loads the drivers (and drains its
# queue when they are done), then the outputs are polled for a short while.
wait_for_display() {
    local deadline
    display_ready && return 0
    "$UDEVADM" settle --timeout="$SETTLE_WAIT" 2>/dev/null
    display_ready && return 0
    gpu_disabled_on_cmdline && return 1
    deadline=$((SECONDS + EXTRA_WAIT))
    while [ "$SECONDS" -lt "$deadline" ]; do
        pause
        display_ready && return 0
    done
    return 1
}

# True when this process sits in a logind session that is bound to a seat and
# a VT, which is what libseat needs. pam_systemd exports these three variables.
have_logind_session() {
    [ -n "${XDG_SESSION_ID:-}" ] && [ -n "${XDG_SEAT:-}" ] && [ -n "${XDG_VTNR:-}" ]
}

# ---- what kmscon runs ------------------------------------------------------

if [ "${1:-}" = "--child" ]; then
    : > "$STAMP" 2>/dev/null || true
    case "${2:-}" in
        wizard) exec "$WIZARD" ;;
        shell) exec "$LOGIN" -f root ;;
    esac
    echo "console-session.sh: unknown --child role: ${2:-}" >&2
    exit 2
fi

# ---- the getty path: exactly what the units ran before kmscon -------------

# The terminal agetty serves. The units are pinned to /dev/tty1 (so the logind
# session they run in is bound to VT 1), and "-" means "the tty I was started
# on". When the kernel console is something else (console=ttyS0), name it, so
# the serial login keeps following the kernel console as it always did.
agetty_port() {
    local con
    con="$(cmdline_console)"
    case "$con" in
        ""|tty[0-9]*) printf '%s\n' "-" ;;  # a VT: the unit's own tty1
        *) printf '%s\n' "$con" ;;          # ttyS0, hvc0, ...
    esac
}

direct() {
    case "$ROLE" in
        wizard) exec "$WIZARD" ;;
        shell)
            exec "$AGETTY" --autologin root --noclear --keep-baud "$(agetty_port)" \
                115200,38400,9600 "${TERM:-linux}"
            ;;
    esac
}

# ---- kmscon -----------------------------------------------------------------

# run_kmscon <vt> <timeout> [kmscon option...]
# Start kmscon, give it <timeout> seconds to get its child going (then ask it
# to stop, and kill it if it does not), and return its exit status. Sets
# STARTED=1 when the child ran.
run_kmscon() {
    local vt="$1" timeout="$2" kpid rc deadline
    shift 2
    STARTED=0
    rm -f "$STAMP"
    "$KMSCON" --vt="$vt" --oneshot --no-reset-env "$@" -l -- "$SELF" --child "$ROLE" &
    kpid=$!
    deadline=$((SECONDS + timeout))
    while [ ! -e "$STAMP" ] && kill -0 "$kpid" 2>/dev/null; do
        if [ "$SECONDS" -ge "$deadline" ]; then
            log "kmscon did not start the $ROLE within ${timeout}s; stopping it"
            kill "$kpid" 2>/dev/null
            deadline=$((SECONDS + STOP_GRACE))
            while kill -0 "$kpid" 2>/dev/null && [ "$SECONDS" -lt "$deadline" ]; do
                pause
            done
            kill -9 "$kpid" 2>/dev/null
            break
        fi
        pause
    done
    wait "$kpid"
    rc=$?
    [ -e "$STAMP" ] && STARTED=1
    return "$rc"
}

mark_failed() {
    log "kmscon failed ($1); using getty for the rest of this boot"
    echo "$1" > "$FAILED" 2>/dev/null || true
}

# What happens after a kmscon session that did start (kmscon rc in $1).
finish() {
    if [ "$1" -eq 0 ]; then
        exit 0
    fi
    mark_failed "died during the $ROLE (rc=$1)"
    if [ "$ROLE" = "shell" ]; then
        direct
    fi
    exit "$1"
}

# ---- main -------------------------------------------------------------------

ROLE="${1:-}"
case "$ROLE" in
    wizard|shell) ;;
    *)
        echo "usage: console-session.sh wizard|shell" >&2
        exit 2
        ;;
esac

if cmdline_has installer.console=getty; then
    log "installer.console=getty: using getty for the $ROLE"
    direct
fi

if [ -e "$FAILED" ]; then
    log "kmscon failed earlier ($(cat "$FAILED" 2>/dev/null)); using getty for the $ROLE"
    direct
fi

if [ ! -x "$KMSCON" ]; then
    log "$KMSCON not installed; using getty for the $ROLE"
    direct
fi

if ! VT="$(console_vt)"; then
    log "console is $(cmdline_console), not a virtual terminal; using getty for the $ROLE"
    direct
fi

if ! wait_for_display; then
    log "no display driver with a connected output; using getty for the $ROLE"
    direct
fi

# Way 1: libseat through the unit's logind session.
if have_logind_session && [ ! -e "$LIBSEAT_FAILED" ] \
    && ! cmdline_has installer.console.libseat=0; then
    log "display is up; running the $ROLE in kmscon on $VT (libseat, session $XDG_SESSION_ID)"
    run_kmscon "$VT" "$LIBSEAT_TIMEOUT" --libseat
    rc=$?
    if [ "$STARTED" = "1" ]; then
        finish "$rc"
    fi
    log "kmscon with libseat did not start the $ROLE (rc=$rc); trying without libseat"
    echo "rc=$rc" > "$LIBSEAT_FAILED" 2>/dev/null || true
else
    log "display is up; running the $ROLE in kmscon on $VT (no libseat)"
fi

# Way 2: kmscon owns the VT and the DRM device itself (it runs as root).
run_kmscon "$VT" "$START_TIMEOUT"
rc=$?
if [ "$STARTED" = "1" ]; then
    finish "$rc"
fi

# Way 3: getty.
mark_failed "no $ROLE started (kmscon rc=$rc)"
direct
