#!/bin/bash
set -e

# Unpack positional parameters passed from wizard.sh
ROOT_RAID_LEVEL="$1"
ROOT_PART_END="$2"
shift 2
DISK_ARRAY=("$@")
DISK_COUNT=${#DISK_ARRAY[@]}

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
echo "--> Assembling BOOT storage array (/dev/md0)..."
mdadm --create --force /dev/md0 \
    --level=1 --metadata=1.0 \
    --raid-devices="$DISK_COUNT" \
    "${BOOT_COMPONENTS[@]}"

# md1: Chosen RAID level, Metadata 1.2 (Modern standard)
echo "--> Assembling ROOT storage array (/dev/md1)..."
mdadm --create --force /dev/md1 \
    --level="$ROOT_RAID_LEVEL" \
    --metadata=1.2 \
    --raid-devices="$DISK_COUNT" \
    "${ROOT_COMPONENTS[@]}"

# Wait for arrays to be initialized cleanly
echo "--> Waiting for mirror background synchronization loops to complete..."
mdadm --wait /dev/md0
mdadm --wait /dev/md1

# Step 4: Create Array Filesystems
echo "--> Creating target filesystems and partition labels..."
mkfs.vfat -F 32 -n "OpenWRT-BOOT" /dev/md0
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
tar -xzf /src/openwrt-rootfs.tar.gz -C /target/root/
tar -xzf /src/openwrt-boot.tar.gz -C /target/root/boot/efi/

# Sync caches and finish
sync
echo "--> Extraction successfully processed. Finalizing mounts..."
umount -R /target
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
