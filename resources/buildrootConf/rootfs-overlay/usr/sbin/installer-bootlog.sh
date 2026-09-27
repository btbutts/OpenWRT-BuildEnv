#!/bin/bash
# /usr/sbin/installer-bootlog.sh

# Runs only when GRUB passed installer.log=1 on the kernel command line
# Writes boot/logs/installer-boot.log on the installer partition, then
# releases that mount so wizard.sh / setup.sh can mount it themselves

LOG=/run/installer-boot.log
MNT=/run/installer-media
DEST_REL="boot/logs/installer-boot.log"

FOUND_OWNED=0

grep -q -- "installer.log=1" /proc/cmdline || exit 0

mkdir -p /run

# Quiet the console after the early flood has already been printed
# This does not drop messages from the ring buffer or from dmesg
echo 1 > /proc/sys/kernel/printk 2>/dev/null || true

write_log() {
    {
        echo "===== installer boot log ====="
        date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date 2>/dev/null || true
        echo "===== /proc/cmdline ====="
        cat /proc/cmdline
        echo "===== dmesg ====="
        dmesg
    } > "$LOG"
}

# True if this directory is the installer stick (kernel and/or payload).
installer_media_here() {
    local root="$1"
    [ -f "${root}/boot/vmlinuz-installer" ] && return 0
    [ -f "${root}/openwrt-custom-x86-64-rootfs.tar.gz" ] && return 0
    [ -f "${root}/openwrt-custom-x86-64-boot.tar.gz" ] && return 0
    [ -f "${root}/openwrt-rootfs.tar.gz" ] && return 0
    [ -f "${root}/openwrt-boot.tar.gz" ] && return 0
    return 1
}

# Print the mountpoint of the installer partition
find_installer_part() {
    local part mnt

    FOUND_OWNED=0

    # When wizard.sh or setup.sh holds the partition, write through it
    while read -r mnt _; do
        [ -n "$mnt" ] || continue
        [ "$mnt" = "/" ] && continue
        if installer_media_here "$mnt"; then
            printf '%s\n' "$mnt"
            return 0
        fi
    done < /proc/mounts

    mkdir -p "$MNT"
    while read -r part devtype _; do
        [ "$devtype" = "part" ] || continue
        case "$part" in
            sd*|nvme*|vd*|hd*) ;;
            *) continue ;;
        esac
        [[ "$part" == loop* || "$part" == dm-* ]] && continue

        # A second mount of a device wizard already has open breaks setup.sh
        if awk '{print $1}' /proc/mounts | grep -q "^/dev/${part}$"; then
            continue
        fi

        mount -o rw "/dev/${part}" "$MNT" 2>/dev/null || continue
        if installer_media_here "$MNT"; then
            FOUND_OWNED=1
            printf '%s\n' "$MNT"
            return 0
        fi
        umount "$MNT" 2>/dev/null || true
    done < <(lsblk -lno NAME,TYPE)
    return 1
}

flush_installer_log() {
    local target owned was_ro opts

    write_log
    target="$(find_installer_part)" || return 1
    owned=$FOUND_OWNED
    was_ro=0

    opts="$(awk -v m="$target" '$2 == m { print $4; exit }' /proc/mounts)"
    case ",${opts}," in
        *,ro,*) was_ro=1 ;;
    esac

    if [ "$was_ro" = 1 ]; then
        mount -o remount,rw "$target" || return 1
    fi

    mkdir -p "${target}/boot/logs" || return 1
    cp -f "$LOG" "${target}/${DEST_REL}" || return 1
    sync

    if [ "$owned" = 1 ]; then
        umount "$target" 2>/dev/null || true
    elif [ "$was_ro" = 1 ]; then
        mount -o remount,ro "$target" 2>/dev/null || true
    fi
    return 0
}

# Attempt write of installer log 10 times without 
# holding the FAT32 mount between copies.
for _ in 1 2 3 4 5 6 7 8 9 10; do
    flush_installer_log && break
    sleep 2
done

while true; do
    sleep 10
    flush_installer_log || true
done

exit 0
