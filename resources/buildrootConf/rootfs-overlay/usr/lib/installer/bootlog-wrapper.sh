#!/bin/bash
# systemd installer-bootlog.service helper.
# Quiet tty1 printk, sync the RTC, then run the one-shot bootlog script.
# stdout/stderr of this wrapper (and of installer-bootlog.sh) land in
# /var/log/installer-bootlog-wrapper.log.

WRAPPER=/var/log/installer-bootlog-wrapper.log

mkdir -p /var/log /run
dmesg -n 1 2>/dev/null || true
if [ -w /proc/sys/kernel/printk ]; then
    echo "1 4 1 7" > /proc/sys/kernel/printk
fi
if command -v hwclock >/dev/null 2>&1; then
    hwclock --hctosys --utc >/dev/null 2>&1 || hwclock --hctosys >/dev/null 2>&1 || true
fi

{
    echo "installer-bootlog.service: start"
    date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date
    if command -v hwclock >/dev/null 2>&1; then
        echo -n "rtc="
        hwclock -r 2>/dev/null || echo unavailable
    fi
    /usr/bin/installer-bootlog.sh
    rc=$?
    echo "installer-bootlog.service: finished rc=$rc"
    exit "$rc"
} > "$WRAPPER" 2>&1
