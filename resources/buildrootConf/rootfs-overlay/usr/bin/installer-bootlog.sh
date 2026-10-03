#!/bin/bash
# /usr/bin/installer-bootlog.sh
#
# One-shot: identify the installer boot partition, copy kmsg/dmesg onto it
# when USB capture is on (or --flush), then unmount and exit.
# Never walks target RAID disks. Never loops.

LOG=/run/installer-boot.log
DEST_REL="boot/logs/installer-boot.log"

FORCE_FLUSH=0
for arg in "$@"; do
    case "$arg" in
        --flush) FORCE_FLUSH=1 ;;
    esac
done

WANT_LOG=0
if grep -q -- "installer.log=1" /proc/cmdline 2>/dev/null; then
    WANT_LOG=1
fi

if [ ! -f /usr/lib/installer/media.sh ]; then
    echo "installer-bootlog: missing /usr/lib/installer/media.sh" >&2
    exit 1
fi
# shellcheck source=/usr/lib/installer/media.sh: disable=SC1091
. /usr/lib/installer/media.sh

mkdir -p /run /var/log
echo 1 > /proc/sys/kernel/printk 2>/dev/null || true

if command -v hwclock >/dev/null 2>&1; then
    hwclock --hctosys --utc 2>/dev/null || hwclock --hctosys 2>/dev/null || true
fi

# Always pin installer media so wizard.sh can exclude the boot disk
# without mounting anything else.
if ! installer_discover; then
    echo "installer-bootlog: installer media not found" >&2
    installer_umount "$INSTALLER_MNT"
    [ "$WANT_LOG" = "1" ] || [ "$FORCE_FLUSH" = "1" ] || exit 0
    exit 1
fi

echo "installer-bootlog: media=${INSTALLER_PART} disk=${INSTALLER_DISK} want_log=${WANT_LOG} flush=${FORCE_FLUSH}"

if [ "$WANT_LOG" != "1" ] && [ "$FORCE_FLUSH" != "1" ]; then
    installer_umount "$INSTALLER_MNT"
    exit 0
fi

snapshot_kmsg() {
    {
        echo "===== installer boot log ====="
        date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date 2>/dev/null || true
        if command -v hwclock >/dev/null 2>&1; then
            echo -n "rtc="
            hwclock -r 2>/dev/null || echo unavailable
        fi
        echo "===== /proc/cmdline ====="
        cat /proc/cmdline
        echo "===== installer media ====="
        echo "INSTALLER_PART=${INSTALLER_PART}"
        echo "INSTALLER_DISK=${INSTALLER_DISK}"
        echo "===== dmesg ====="
        dmesg
    } > "$LOG"
}

flush_once() {
    local was_ro=0 opts dest

    snapshot_kmsg
    if ! installer_mount "$INSTALLER_MNT"; then
        return 1
    fi

    opts="$(awk -v m="$INSTALLER_MNT" '$2 == m { print $4; exit }' /proc/mounts)"
    case ",${opts}," in
        *,ro,*) was_ro=1 ;;
    esac
    if [ "$was_ro" = "1" ]; then
        mount -o remount,rw "$INSTALLER_MNT" || return 1
    fi

    mkdir -p "${INSTALLER_MNT}/boot/logs" || return 1
    dest="${INSTALLER_MNT}/${DEST_REL}"
    if [ "$FORCE_FLUSH" = "1" ] && [ -f "$dest" ]; then
        {
            echo "===== installer-bootlog --flush ====="
            date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date 2>/dev/null || true
            echo "===== dmesg ====="
            dmesg
        } >> "$dest" || return 1
    else
        cp -f "$LOG" "$dest" || return 1
    fi
    if [ -f /var/log/installer-setup.log ]; then
        cp -f /var/log/installer-setup.log "${INSTALLER_MNT}/boot/logs/installer-setup.log" || true
    fi
    if [ -s /var/log/installer-bootlog-wrapper.log ]; then
        cp -f /var/log/installer-bootlog-wrapper.log \
            "${INSTALLER_MNT}/boot/logs/installer-bootlog-wrapper.log" || true
    fi
    sync

    if [ "$was_ro" = "1" ]; then
        mount -o remount,ro "$INSTALLER_MNT" 2>/dev/null || true
    fi
    return 0
}

flush_rc=1
for _ in 1 2 3 4 5; do
    if flush_once; then
        flush_rc=0
        break
    fi
    sleep 2
done

installer_umount "$INSTALLER_MNT"
exit "$flush_rc"
