#!/bin/bash
set -e

# Unpack positional parameters passed from wizard.sh
ROOT_RAID_LEVEL="$1"
ROOT_PART_END="$2"
ROOT_BITMAP_MODE="$3"
shift 3
DISK_ARRAY=("$@")
DISK_COUNT=${#DISK_ARRAY[@]}

SETUP_LOG=/var/log/installer-setup.log
SETUP_LOG_FIFO=/run/installer-setup.fifo
SETUP_TEE_PID=""
SETUP_LOGGING=0

if [ ! -f /usr/lib/installer/media.sh ]; then
    echo "ERROR: installer media helper is missing (/usr/lib/installer/media.sh)." >&2
    exit 1
fi
# shellcheck source=/usr/lib/installer/media.sh: disable=SC1091
. /usr/lib/installer/media.sh

mkdir -p /var/log /run

if command -v hwclock >/dev/null 2>&1; then
    hwclock --hctosys --utc 2>/dev/null || hwclock --hctosys 2>/dev/null || true
fi

log_clock() {
    printf 'system=%s utc=%s' \
        "$(date '+%Y-%m-%dT%H:%M:%S%z' 2>/dev/null || date)" \
        "$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || echo unknown)"
    if command -v hwclock >/dev/null 2>&1; then
        printf ' rtc=%s' "$(hwclock -r 2>/dev/null | head -n1 || echo unavailable)"
    fi
    printf '\n'
}

# Print to the console and to SETUP_LOG. With no arguments, copy stdin
# (so `cmd 2>&1 | write_log` works). After setup_start_console_log,
# stdout/stderr are already teed, so this is a plain print/cat.
write_log() {
    if [ "$SETUP_LOGGING" = "1" ]; then
        if [ "$#" -gt 0 ]; then
            printf '%s\n' "$*"
        else
            cat
        fi
        return 0
    fi
    if [ "$#" -gt 0 ]; then
        printf '%s\n' "$*" | tee -a "$SETUP_LOG"
    else
        tee -a "$SETUP_LOG"
    fi
}

setup_start_console_log() {
    exec 3>&1 4>&2
    rm -f "$SETUP_LOG_FIFO"
    if mkfifo "$SETUP_LOG_FIFO" 2>/dev/null; then
        tee -a "$SETUP_LOG" < "$SETUP_LOG_FIFO" &
        SETUP_TEE_PID=$!
        exec > "$SETUP_LOG_FIFO" 2>&1
    else
        exec > >(tee -a "$SETUP_LOG") 2>&1
    fi
    SETUP_LOGGING=1
}

setup_stop_console_log() {
    [ "$SETUP_LOGGING" = "1" ] || return 0
    SETUP_LOGGING=0
    exec 1>&3 2>&4
    exec 3>&- 4>&-
    if [ -n "$SETUP_TEE_PID" ]; then
        wait "$SETUP_TEE_PID" 2>/dev/null || true
        SETUP_TEE_PID=""
    else
        sleep 1
    fi
    rm -f "$SETUP_LOG_FIFO"
}

copy_setup_log_to_media() {
    local dest_root=""
    if awk -v d="/src" '$2 == d { found=1 } END { exit !found }' /proc/mounts; then
        dest_root=/src
    elif installer_mount /src; then
        dest_root=/src
    fi
    [ -n "$dest_root" ] || return 0
    mkdir -p "${dest_root}/boot/logs" 2>/dev/null || true
    cp -f "$SETUP_LOG" "${dest_root}/boot/logs/installer-setup.log" 2>/dev/null || true
    sync
}

setup_fail() {
    echo "ERROR: setup.sh aborted at line ${1:-?}."
    echo "See ${SETUP_LOG} and dmesg."
    cat /proc/mdstat 2>/dev/null || true
    setup_stop_console_log 2>/dev/null || true
    copy_setup_log_to_media || true
    if [ -x /usr/bin/installer-bootlog.sh ]; then
        /usr/bin/installer-bootlog.sh --flush || true
    fi
    sleep 8
    exit 1
}
trap 'setup_fail $LINENO' ERR

{
    echo "===== setup.sh start ====="
    log_clock
    echo "RAID_LEVEL=$ROOT_RAID_LEVEL ROOT_PART_END=${ROOT_PART_END:-MAX} BITMAP=$ROOT_BITMAP_MODE"
    echo "DISKS=${DISK_ARRAY[*]}"
    echo "DISK_COUNT=$DISK_COUNT"
} >> "$SETUP_LOG"

setup_start_console_log

# Never wipe the volume we booted the installer from.
if installer_load_identity || installer_discover; then
    write_log "--> Installer boot disk is /dev/${INSTALLER_DISK} (excluded from wipe)."
    for DISK in "${DISK_ARRAY[@]}"; do
        if [ "$DISK" = "$INSTALLER_DISK" ]; then
            write_log "ERROR: installer boot disk /dev/$DISK was passed as a RAID target."
            exit 1
        fi
    done
else
    write_log "WARNING: could not identify installer boot disk; proceeding with wizard disk list."
fi

# mdadm wait monitor wrapper
safe_mdadm_wait() {
    local target_array="$1"
    write_log "--> Monitoring synchronization initialization flags on ${target_array}..."

    # Check if array exists and is tracking a recovery/resync op
    if [ -f "/proc/mdstat" ]; then
        # If mdstat contains a recovery, resync, or reshape tag for this array, wait cleanly
        if grep -q "${target_array##*/}.*\(resync\|recovery\|reshape\)" /proc/mdstat; then
            write_log "--> Background rebuild active. Attaching structural tracking wait process..."
            mdadm --wait "$target_array" || true
        else
            write_log "--> No background synchronization loops active or required for ${target_array}. Advancing..."
        fi
    else
        # Fallback to standard wait wrapped inside an error bypass block if proc paths are missing
        mdadm --wait "$target_array" || true
    fi
}

# Bootlog is a one-shot that must already have finished before wizard.
# Stop/umount anyway so this script is the only userspace touching disks.
if command -v systemctl >/dev/null 2>&1; then
    systemctl stop installer-bootlog.service 2>/dev/null || true
fi
pkill -f '/usr/bin/installer-bootlog.sh' 2>/dev/null || true
pkill -f '/usr/lib/installer/bootlog-wrapper.sh' 2>/dev/null || true
installer_umount "$INSTALLER_MNT" 2>/dev/null || true

release_disk() {
    local disk="$1" spec mnt part holders_dir holder
    while read -r spec mnt _; do
        case "$spec" in
            /dev/"${disk}"|/dev/"${disk}"[0-9]*|/dev/"${disk}"p[0-9]*)
                umount "$mnt" 2>/dev/null || umount -l "$mnt" 2>/dev/null || true
                ;;
        esac
    done < /proc/mounts

    holders_dir="/sys/block/${disk}/holders"
    if [ -d "$holders_dir" ]; then
        for holder in "$holders_dir"/*; do
            [ -e "$holder" ] || continue
            mdadm --stop "/dev/$(basename "$holder")" 2>/dev/null || true
        done
    fi
    for part in /sys/block/"${disk}"/"${disk}"*; do
        [ -d "$part" ] || continue
        if [ -d "$part/holders" ]; then
            for holder in "$part"/holders/*; do
                [ -e "$holder" ] || continue
                mdadm --stop "/dev/$(basename "$holder")" 2>/dev/null || true
            done
        fi
    done

    if command -v udevadm >/dev/null 2>&1; then
        udevadm settle --timeout=10 2>/dev/null || true
    fi
}

# Step 1: Identically Partition Disks
write_log "--> Stopping any stale md arrays before wiping target disks..."
mdadm --stop /dev/md0 2>/dev/null || true
mdadm --stop /dev/md1 2>/dev/null || true
mdadm --stop --scan 2>/dev/null || true

for DISK in "${DISK_ARRAY[@]}"; do
    write_log "--> Purging existing volume mappings on /dev/$DISK..."
    release_disk "$DISK"
    dd if=/dev/zero of="/dev/$DISK" bs=512 count=1000
    if ! wipefs -a "/dev/$DISK"; then
        write_log "ERROR: wipefs failed on /dev/$DISK (device busy)."
        write_log "--> Mounts:"
        grep "/dev/${DISK}" /proc/mounts || true
        write_log "--> mdstat:"
        cat /proc/mdstat 2>/dev/null || true
        write_log "--> holders:"
        ls -l /sys/block/"$DISK"/holders 2>/dev/null || true
        exit 1
    fi

    if [ -z "$ROOT_PART_END" ]; then
        printf "label: gpt\n,2G,U\n,\n" | sfdisk "/dev/$DISK"
    else
        printf "label: gpt\n,2G,U\n,%s,L\n" "$ROOT_PART_END" | sfdisk "/dev/$DISK"
    fi
    if command -v partx >/dev/null 2>&1; then
        partx -u "/dev/$DISK" 2>/dev/null || true
    else
        blockdev --rereadpt "/dev/$DISK" 2>/dev/null || true
    fi
done
if command -v udevadm >/dev/null 2>&1; then
    udevadm settle --timeout=10 2>/dev/null || true
fi

# Step 2: Construct Array Component Strings
BOOT_COMPONENTS=()
ROOT_COMPONENTS=()

for DISK in "${DISK_ARRAY[@]}"; do
    if [[ "$DISK" == nvme* ]]; then
        BOOT_COMPONENTS+=("/dev/${DISK}p1")
        ROOT_COMPONENTS+=("/dev/${DISK}p2")
    else
        BOOT_COMPONENTS+=("/dev/${DISK}1")
        ROOT_COMPONENTS+=("/dev/${DISK}2")
    fi
done

# Step 3: Set mdadm metadata constraints
# Clear out any stale md mappings before recreation passes
mdadm --stop /dev/md0 2>/dev/null || true
mdadm --stop /dev/md1 2>/dev/null || true
mdadm --zero-superblock \
    "${BOOT_COMPONENTS[@]}" \
    "${ROOT_COMPONENTS[@]}" \
    2>/dev/null || true

# md0: Always RAID 1, Metadata 1.0 (Superblock at end so motherboard reads raw FAT32)
write_log "--> Assembling OpenWRT-BOOT storage array (/dev/md0)..."
yes | mdadm --create --force --run /dev/md0 \
    --level=1 --metadata=1.0 \
    --bitmap=none \
    --raid-devices="$DISK_COUNT" \
    "${BOOT_COMPONENTS[@]}"

# md1: Chosen RAID level, Metadata 1.2 (Modern standard)
write_log "--> Assembling OpenWRT-ROOT storage array (/dev/md1)..."
write_log "--> Setting OpenWRTroot array write-intent bitmap mode to $ROOT_BITMAP_MODE..."
yes | mdadm --create --force --run /dev/md1 \
    --level="$ROOT_RAID_LEVEL" \
    --metadata=1.2 \
    --bitmap="$ROOT_BITMAP_MODE" \
    --raid-devices="$DISK_COUNT" \
    "${ROOT_COMPONENTS[@]}"
sleep 6s

# Wait for arrays to be initialized cleanly
write_log "--> Waiting for mirror background synchronization loops to complete..."
safe_mdadm_wait /dev/md0
safe_mdadm_wait /dev/md1
sleep 6s

# Step 4: Create Array Filesystems
write_log "--> Creating target filesystems and partition labels..."
mkfs.vfat -F 32 -n "BOOT" /dev/md0
mkfs.ext4 -F -L "OpenWRT-ROOT" /dev/md1

# Step 5: Mount and Unpack OpenWRT FS Tarballs
write_log "--> Mounting target filesystems and preparing for OpenWRT extraction..."
# Create mount points
mkdir -p /target/root
mount /dev/md1 /target/root

mkdir -p /target/root/boot/efi
mount /dev/md0 /target/root/boot/efi

# Mount only the installer partition already identified at boot.
# Target RAID disks stay unmounted.
mkdir -p /src
USB_SOURCE=""
if installer_mount /src; then
    USB_SOURCE="/dev/${INSTALLER_PART}"
    write_log "--> Using installer media $USB_SOURCE at /src"
else
    write_log "ERROR: Could not mount installer media for OpenWRT tarballs."
    exit 1
fi
if [ ! -f /src/openwrt-rootfs.tar.gz ] || [ ! -f /src/openwrt-boot.tar.gz ]; then
    write_log "ERROR: Installer media $USB_SOURCE is missing openwrt-rootfs.tar.gz / openwrt-boot.tar.gz."
    installer_umount /src
    exit 1
fi

# Unpack
write_log "--> Extracting operational target filesystems... Please stand by."
tar --no-same-owner -xzf /src/openwrt-rootfs.tar.gz -C /target/root/
tar --no-same-owner -xzf /src/openwrt-boot.tar.gz -C /target/root/boot/efi/

# Step 6: Inject Master Software RAID Assembly Maps into Target OS ===
write_log "--> Generating persistent mdadm array profiles for OpenWRT cold boot..."

# Ensure target configuration directories exist
mkdir -p /target/root/etc/config
mkdir -p /target/root/boot/grub

# Temp print line then pause 20 seconds
printf "DEVICE %s\n" "${BOOT_COMPONENTS[*]} ${ROOT_COMPONENTS[*]}"
sleep 5s

# Generate persistent mdadm array profiles inside the target rootfs
echo "DEVICE partitions" > /target/root/etc/mdadm.conf
mdadm --examine --scan >> /target/root/etc/mdadm.conf

# Extract the exact dynamic active UUID signatures of your arrays
MD0_UUID=$(mdadm --detail /dev/md0 | grep -i "UUID" | awk '{print $3}')
MD1_UUID=$(mdadm --detail /dev/md1 | grep -i "UUID" | awk '{print $3}')

# Write OpenWRT's specialized configuration model sheet
cat << EOF > /target/root/etc/config/mdadm
config mdadm
	option email root
	option alert_program /usr/sbin/handle-mdadm-events

config array
	option uuid "$MD0_UUID"
	option device /dev/md0
	option name BOOT

config array
	option uuid "$MD1_UUID"
	option device /dev/md1
	option name OpenWRT-ROOT
EOF

# Dynamically set the 'md=' parm string for /md1 array
# Creates grub string like: md=1,/dev/nvme0n1p2,/dev/nvme1n1p2,.../dev/nvmeXn1p2
MD_CMD_STRING="md=1"
for partition in "${ROOT_COMPONENTS[@]}"; do
    MD_CMD_STRING="${MD_CMD_STRING},${partition}"
done

write_log "--> Computed dynamic kernel parameter array signature: $MD_CMD_STRING"

# 4. Replace placeholder token inside the unpacked OpenWRT-ROOT fs grub.cfg
TARGET_GRUB_CFG="/target/root/boot/grub/grub.cfg"
if [ -f "$TARGET_GRUB_CFG" ]; then
    write_log "--> Patching target menu entries configuration layout..."
    sed -i "s|@MD_ASSEMBLY_TOKEN@|${MD_CMD_STRING}|g" "$TARGET_GRUB_CFG"
    write_log "--> Successfully injected runtime storage array mapping rules."
else
    write_log "WARNING: Primary system grub.cfg not found at $TARGET_GRUB_CFG! Patch skipped."
fi

write_log "--> Storage metadata mappings successfully slipstreamed into target filesystem."

# Generate OpenWRT's Unified Storage Automation Profile (fstab)
write_log "--> Generating automated mounting parameters profile (/etc/config/fstab)..."

cat << 'EOF' > /target/root/etc/config/fstab
config global
	option anon_swap '0'
	option anon_mount '0'
	option auto_swap '1'
	option auto_mount '1'
	option delay_root '5'
	option check_fs '1'

config mount
	option target '/'
	option label 'OpenWRT-ROOT'
	option enabled '1'
	option kmod 'kmod-fs-ext4'

config mount
	option target '/boot/efi'
	option label 'BOOT'
	option enabled '1'
	option kmod 'kmod-fs-vfat'
EOF

write_log "--> Production storage automation arrays fully synchronized!"

# Sync caches and finish
sync
write_log "--> Extraction successfully processed. Finalizing mounts..."
umount -R /target/root/

# Log copy must not abort a successful install.
trap - ERR

write_log "===== setup.sh complete ====="
log_clock
write_log "DISKS=${DISK_ARRAY[*]}"
write_log "RAID_LEVEL=$ROOT_RAID_LEVEL BITMAP=$ROOT_BITMAP_MODE"

setup_stop_console_log

# Copy installation logs to the installer media while it is still mounted,
# then let installer-bootlog.sh snapshot remaining kmsg and unmount.
mount -o remount,rw /src 2>/dev/null || true
copy_setup_log_to_media || true
installer_umount /src
if [ -x /usr/bin/installer-bootlog.sh ]; then
    /usr/bin/installer-bootlog.sh --flush || true
fi

# Confirm execution pass
echo "--> Installation successfully completed! Remove your installer media."
if dialog --yesno "Confirm YES to reboot the system immediately, or NO to launch an emergency maintenance shell:" 10 60; then
    echo "System will reboot in 5 seconds..."
    sleep 5
    reboot -f
else
    echo "--> Entering interactive shell as requested by user..."
    clear
    # dialog leaves the VT in cbreak/raw; without ISIG, Ctrl+C is echoed
    # as a literal. Claim a controlling tty so job-control signals work.
    stty sane < /dev/tty1 > /dev/tty1 2>/dev/null || stty sane 2>/dev/null || true
    if [ -x /bin/zsh ]; then
        MAINT_SHELL=/bin/zsh
    else
        MAINT_SHELL=/bin/bash
    fi
    if command -v setsid >/dev/null 2>&1; then
        exec setsid -c "$MAINT_SHELL" -l < /dev/tty1 > /dev/tty1 2>&1
    fi
    exec "$MAINT_SHELL" -l < /dev/tty1 > /dev/tty1 2>&1
fi
