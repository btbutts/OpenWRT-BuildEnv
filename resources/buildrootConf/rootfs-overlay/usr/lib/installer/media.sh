#!/bin/bash
# /usr/lib/installer/media.sh
# Shared installer-media identity for wizard.sh, setup.sh, and installer-bootlog.sh.
# Source this file; do not execute it.
#
# The Buildroot installer is a ramdisk. The boot USB/SD/NVMe is only the
# GRUB + payload volume. Identify that volume once, cache it, and never
# mount RAID members, empty nbd nodes, or other target disks to find it.

: "${INSTALLER_ID_FILE:=/run/installer-media-id}"
: "${INSTALLER_MNT:=/run/installer-media}"

INSTALLER_PART="${INSTALLER_PART:-}"
INSTALLER_DISK="${INSTALLER_DISK:-}"

installer_media_here() {
    local root="$1"
    [ -n "$root" ] && [ -d "$root" ] || return 1
    [ -f "${root}/boot/vmlinuz-installer" ] && return 0
    [ -f "${root}/boot/initramfs-installer.img" ] && return 0
    [ -f "${root}/openwrt-rootfs.tar.gz" ] && return 0
    [ -f "${root}/openwrt-boot.tar.gz" ] && return 0
    [ -f "${root}/openwrt-custom-x86-64-rootfs.tar.gz" ] && return 0
    [ -f "${root}/openwrt-custom-x86-64-boot.tar.gz" ] && return 0
    return 1
}

installer_parent_disk() {
    local part="$1" pk
    [ -n "$part" ] || return 1
    pk="$(lsblk -no PKNAME "/dev/${part}" 2>/dev/null | awk 'NF { print $1; exit }')"
    if [ -n "$pk" ]; then
        printf '%s\n' "$pk"
        return 0
    fi
    case "$part" in
        *[0-9]p[0-9]*)
            printf '%s\n' "${part%p*}"
            ;;
        *)
            printf '%s\n' "${part%%[0-9]*}"
            ;;
    esac
}

installer_is_virtual_name() {
    case "$1" in
        nbd*|loop*|ram*|zram*|sr*|fd*|md*|dm-*|dm[0-9]*|zd*)
            return 0
            ;;
    esac
    return 1
}

installer_is_allowed_name() {
    installer_is_virtual_name "$1" && return 1
    case "$1" in
        sd*|nvme*|vd*|hd*|mmcblk*|xvd*|ub*|usb*)
            return 0
            ;;
    esac
    return 1
}

installer_disk_bytes() {
    local bytes
    bytes="$(lsblk -bndo SIZE "/dev/$1" 2>/dev/null | awk 'NF { print $1; exit }')"
    [ -n "$bytes" ] || bytes=0
    printf '%s\n' "$bytes"
}

installer_is_nonzero_disk() {
    local name="$1" dtype bytes
    [ -b "/dev/${name}" ] || return 1
    installer_is_allowed_name "$name" || return 1
    dtype="$(lsblk -dno TYPE "/dev/${name}" 2>/dev/null | awk 'NF { print $1; exit }')"
    [ "$dtype" = "disk" ] || return 1
    bytes="$(installer_disk_bytes "$name")"
    [ "$bytes" -gt 0 ] 2>/dev/null
}

installer_parent_removable() {
    local disk="$1" f
    f="/sys/block/${disk}/removable"
    [ -f "$f" ] && [ "$(cat "$f" 2>/dev/null)" = "1" ]
}

installer_fstype_is_raid_or_lvm() {
    case "$1" in
        linux_raid_member|LVM2_member|crypto_LUKS|swap|zfs_member)
            return 0
            ;;
    esac
    return 1
}

installer_fstype_is_payload() {
    case "$1" in
        vfat|fat|fat32|exfat|iso9660|msdos)
            return 0
            ;;
    esac
    return 1
}

installer_save_identity() {
    mkdir -p "$(dirname "$INSTALLER_ID_FILE")"
    {
        printf 'INSTALLER_PART=%s\n' "$INSTALLER_PART"
        printf 'INSTALLER_DISK=%s\n' "$INSTALLER_DISK"
    } > "$INSTALLER_ID_FILE"
}

installer_load_identity() {
    local key val
    INSTALLER_PART=""
    INSTALLER_DISK=""
    [ -f "$INSTALLER_ID_FILE" ] || return 1
    while IFS='=' read -r key val; do
        case "$key" in
            INSTALLER_PART) INSTALLER_PART="$val" ;;
            INSTALLER_DISK) INSTALLER_DISK="$val" ;;
        esac
    done < "$INSTALLER_ID_FILE"
    [ -n "$INSTALLER_PART" ] || return 1
    [ -b "/dev/${INSTALLER_PART}" ] || return 1
    if [ -z "$INSTALLER_DISK" ]; then
        INSTALLER_DISK="$(installer_parent_disk "$INSTALLER_PART")"
    fi
    [ -n "$INSTALLER_DISK" ] || return 1
    return 0
}

installer_accept_part() {
    local part="$1"
    INSTALLER_PART="$part"
    INSTALLER_DISK="$(installer_parent_disk "$part")"
    installer_save_identity
}

# Mount $part at $mnt, test installer_media_here, then unmount.
# Returns 0 only when this partition is installer media.
installer_probe_part() {
    local part="$1" mnt="$2"

    [ -b "/dev/${part}" ] || return 1
    if awk '{ print $1 }' /proc/mounts | grep -q "^/dev/${part}$"; then
        return 1
    fi

    mkdir -p "$mnt"
    mount -o ro "/dev/${part}" "$mnt" 2>/dev/null || return 1
    if installer_media_here "$mnt"; then
        umount "$mnt" 2>/dev/null || umount -l "$mnt" 2>/dev/null || true
        installer_accept_part "$part"
        return 0
    fi
    umount "$mnt" 2>/dev/null || umount -l "$mnt" 2>/dev/null || true
    return 1
}

installer_scan_mounted() {
    local spec mnt part
    while read -r spec mnt _; do
        [ -n "$mnt" ] || continue
        [ "$mnt" = "/" ] && continue
        if installer_media_here "$mnt"; then
            case "$spec" in
                /dev/*) part="${spec#/dev/}" ;;
                *) part="$(lsblk -no NAME "$spec" 2>/dev/null | awk 'NF { print $1; exit }')" ;;
            esac
            [ -n "$part" ] || continue
            installer_accept_part "$part"
            return 0
        fi
    done < /proc/mounts
    return 1
}

# Walk TYPE=part candidates in increasing risk order. Never mounts nbd/loop
# nodes or linux_raid_member/LVM/swap signatures. FAT on removable media
# is preferred; NVMe/SATA ext4 is never probed.
installer_discover() {
    local part dtype fstype disk
    local -a fat_rm=() fat_any=() empty_rm=() empty_sata=()

    if installer_load_identity; then
        return 0
    fi
    if installer_scan_mounted; then
        return 0
    fi

    if command -v udevadm >/dev/null 2>&1; then
        udevadm settle --timeout=8 2>/dev/null || true
    fi

    while read -r part dtype fstype _; do
        [ "$dtype" = "part" ] || continue
        installer_is_allowed_name "$part" || continue
        installer_fstype_is_raid_or_lvm "$fstype" && continue
        disk="$(installer_parent_disk "$part")"
        if installer_fstype_is_payload "$fstype"; then
            if installer_parent_removable "$disk"; then
                fat_rm+=("$part")
            else
                fat_any+=("$part")
            fi
            continue
        fi
        if [ -z "$fstype" ]; then
            if installer_parent_removable "$disk"; then
                empty_rm+=("$part")
            else
                case "$disk" in
                    nvme*) ;;
                    *) empty_sata+=("$part") ;;
                esac
            fi
        fi
    done < <(lsblk -lno NAME,TYPE,FSTYPE)

    mkdir -p "$INSTALLER_MNT"
    for part in "${fat_rm[@]}" "${fat_any[@]}" "${empty_rm[@]}" "${empty_sata[@]}"; do
        [ -n "$part" ] || continue
        if installer_probe_part "$part" "$INSTALLER_MNT"; then
            return 0
        fi
    done
    return 1
}

installer_mount() {
    local dest="${1:-$INSTALLER_MNT}"
    local already
    installer_load_identity || installer_discover || return 1
    [ -n "$INSTALLER_PART" ] || return 1
    mkdir -p "$dest"
    if awk -v d="$dest" '$2 == d { found=1 } END { exit !found }' /proc/mounts; then
        installer_media_here "$dest"
        return $?
    fi
    already="$(awk -v p="/dev/${INSTALLER_PART}" '$1 == p { print $2; exit }' /proc/mounts)"
    if [ -n "$already" ] && [ "$already" != "$dest" ]; then
        mount --bind "$already" "$dest" 2>/dev/null || return 1
        installer_media_here "$dest"
        return $?
    fi
    mount -o rw "/dev/${INSTALLER_PART}" "$dest" 2>/dev/null \
        || mount -o ro "/dev/${INSTALLER_PART}" "$dest" 2>/dev/null \
        || return 1
    installer_media_here "$dest"
}

installer_umount() {
    local dest="${1:-$INSTALLER_MNT}"
    if awk -v d="$dest" '$2 == d { found=1 } END { exit !found }' /proc/mounts; then
        umount "$dest" 2>/dev/null || umount -l "$dest" 2>/dev/null || true
    fi
    return 0
}

# True when $1 is a real, writable, non-zero disk that is not installer media.
installer_is_target_disk() {
    local name="$1"
    installer_is_nonzero_disk "$name" || return 1
    installer_load_identity || true
    [ -n "$INSTALLER_DISK" ] && [ "$name" = "$INSTALLER_DISK" ] && return 1
    return 0
}
