#!/bin/bash
# /usr/lib/installer/quiet-console.sh
#
# Keep the console clean for the installer TUI and the login shell that
# follows it. Boot shows the normal systemd status list and whatever kernel
# output the GRUB loglevel= asks for; this runs once the wizard or the
# getty is about to take over tty1, where either would be drawn on top of
# the dialogs. Run from ExecStartPre of installer-wizard.service and
# console-getty.service. Idempotent, and always exits 0.
#
# 1. Kernel messages: console_loglevel = 1, so only KERN_EMERG (panic/oops)
#    reaches the console; 1 is the lowest value the kernel accepts. This
#    changes console output only. The kernel ring buffer still records
#    everything, so `dmesg` and the USB boot-log capture are complete.
#    Re-asserting it here also undoes a raise made from the root shell
#    (`dmesg -n 7`) when the wizard restarts.
# 2. systemd status ("Starting X...", "Started X."): SIGRTMIN+21 to PID 1
#    disables it (SIGRTMIN+20 enables it again, see systemd(1)). The
#    override stays until it is changed, so it covers the root shell too.

dmesg -n 1 2>/dev/null || { echo 1 > /proc/sys/kernel/printk; } 2>/dev/null
kill -s RTMIN+21 1 2>/dev/null
exit 0
