#!/bin/bash
set -e

# Unpack positional parameters passed from wizard.sh
ROOT_RAID_LEVEL="$1"
ROOT_PART_END="$2"
ROOT_BITMAP_MODE="$3"
shift 3
DISK_ARRAY=("$@")
DISK_COUNT=${#DISK_ARRAY[@]}

# mdadm wait monitor wrapper
safe_mdadm_wait() {
    local target_array="$1"
    echo "--> Monitoring synchronization initialization flags on ${target_array}..."
    
    # Check if array exists and is tracking a recovery/resync op
    if [ -f "/proc/mdstat" ]; then
        # If mdstat contains a recovery, resync, or reshape tag for this array, wait cleanly
        if grep -q "${target_array##*/}.*\(resync\|recovery\|reshape\)" /proc/mdstat; then
            echo "--> Background rebuild active. Attaching structural tracking wait process..."
            mdadm --wait "$target_array" || true
        else
            echo "--> No background synchronization loops active or required for ${target_array}. Advancing..."
        fi
    else
        # Fallback to standard wait wrapped inside an error bypass block if proc paths are missing
        mdadm --wait "$target_array" || true
    fi
}

# Step 1: Identicaly Partition Disks
for DISK in "${DISK_ARRAY[@]}"; do
    # Clear existing partition table
    echo "--> Purging existing volume mappings on /dev/$DISK..."
    dd if=/dev/zero of="/dev/$DISK" bs=512 count=1000
    wipefs -a "/dev/$DISK"
    
    # Create Partition 1 (2GB for EFI/BOOT) and Partition 2 (ROOT)
    if [ -z "$ROOT_PART_END" ]; then
        # Use remaining space
        printf "label: gpt\n,2G,U\n,\n" | sfdisk "/dev/$DISK"
    else
        # Use exact custom size
        printf "label: gpt\n,2G,U\n,%s,L\n" "$ROOT_PART_END" | sfdisk "/dev/$DISK"
    fi
done



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
echo "--> Assembling OpenWRT-BOOT storage array (/dev/md0)..."
yes | mdadm --create --force --run /dev/md0 \
    --level=1 --metadata=1.0 \
    --bitmap=none \
    --raid-devices="$DISK_COUNT" \
    "${BOOT_COMPONENTS[@]}"

# md1: Chosen RAID level, Metadata 1.2 (Modern standard)
echo "--> Assembling OpenWRT-ROOT storage array (/dev/md1)..."
echo "--> Setting OpenWRTroot array write-intent bitmap mode to $ROOT_BITMAP_MODE..."
yes | mdadm --create --force --run /dev/md1 \
    --level="$ROOT_RAID_LEVEL" \
    --metadata=1.2 \
    --bitmap="$ROOT_BITMAP_MODE" \
    --raid-devices="$DISK_COUNT" \
    "${ROOT_COMPONENTS[@]}"
sleep 6s

# Wait for arrays to be initialized cleanly
echo "--> Waiting for mirror background synchronization loops to complete..."
safe_mdadm_wait /dev/md0
safe_mdadm_wait /dev/md1
sleep 6s

# Step 4: Create Array Filesystems
echo "--> Creating target filesystems and partition labels..."
mkfs.vfat -F 32 -n "BOOT" /dev/md0
mkfs.ext4 -F -L "OpenWRT-ROOT" /dev/md1



# Step 5: Mount and Unpack OpenWRT FS Tarballs
echo "--> Mounting target filesystems and preparing for OpenWRT extraction..."
# Create mount points
mkdir -p /target/root
mount /dev/md1 /target/root

mkdir -p /target/root/boot/efi
mount /dev/md0 /target/root/boot/efi

# Mount the USB holding your production tarballs
mkdir -p /src
USB_SOURCE=""
for PART in $(lsblk -lno NAME | grep -E 'sd|nvme'); do
    if mount -o ro "/dev/$PART" /src 2>/dev/null; then
        if [ -f /src/openwrt-rootfs.tar.gz ] && [ -f /src/openwrt-boot.tar.gz ]; then
            USB_SOURCE="/dev/$PART"
            echo "--> Successfully located distribution deployment USB on $USB_SOURCE"
            break
        fi
        umount /src
    fi
done
if [ -z "$USB_SOURCE" ]; then
    echo "ERROR: Could not locate distribution deployment USB with required tarballs."
    exit 1
fi
echo "--> Using distribution deployment USB at $USB_SOURCE"

# Unpack
echo "--> Extracting operational target filesystems... Please stand by."
tar --no-same-owner -xzf /src/openwrt-rootfs.tar.gz -C /target/root/
tar --no-same-owner -xzf /src/openwrt-boot.tar.gz -C /target/root/boot/efi/

# Step 6: Inject Master Software RAID Assembly Maps into Target OS ===
echo "--> Generating persistent mdadm array profiles for OpenWRT cold boot..."

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

echo "--> Computed dynamic kernel parameter array signature: $MD_CMD_STRING"

# 4. Replace placeholder token inside the unpacked OpenWRT-ROOT fs grub.cfg
TARGET_GRUB_CFG="/target/root/boot/grub/grub.cfg"
if [ -f "$TARGET_GRUB_CFG" ]; then
    echo "--> Patching target menu entries configuration layout..."
    sed -i "s|@MD_ASSEMBLY_TOKEN@|${MD_CMD_STRING}|g" "$TARGET_GRUB_CFG"
    echo "--> Successfully injected runtime storage array mapping rules."
else
    echo "WARNING: Primary system grub.cfg not found at $TARGET_GRUB_CFG! Patch skipped." >&2
fi

echo "--> Storage metadata mappings successfully slipstreamed into target filesystem."

# Generate OpenWRT's Unified Storage Automation Profile (fstab)
echo "--> Generating automated mounting parameters profile (/etc/config/fstab)..."

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

echo "--> Production storage automation arrays fully synchronized!"

# Sync caches and finish
sync
echo "--> Extraction successfully processed. Finalizing mounts..."
umount -R /target/root/
umount /src

# Confirm execution pass
echo "--> Installation successfully completed! Remove your installer media."
if dialog --yesno "Confirm YES to reboot the system immediately, or NO to launch an emergency maintenance shell:" 10 60; then
    echo "System will reboot in 5 seconds..."
    sleep 5
    reboot -f
else
    echo "--> Entering interactive shell as requested by user..."
    clear
    # Safe check if custom compiled zsh exists; if not, fallback to standard bash
    if [ -x /bin/zsh ]; then
        exec /bin/zsh
    else
        exec /bin/bash
    fi
fi
