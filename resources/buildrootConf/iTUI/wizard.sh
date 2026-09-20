#!/bin/bash
set -e

# --- Tier 1: Identify the Installer USB / Deployment Source Media ---
INSTALLER_DISK=""

# Scan every available block device partition on the system to locate the payload archives
for PART in $(lsblk -lno NAME | grep -E 'sd|nvme|vd|hd'); do
    # Skip loop devices and device-mapper components
    [[ "$PART" == loop* || "$PART" == dm-* ]] && continue
    
    # Try mounting the partition read-only to inspect its contents
    TMP_MNT="/tmp/check_${PART}"
    mkdir -p "$TMP_MNT"
    if mount -o ro "/dev/$PART" "$TMP_MNT" 2>/dev/null; then
        # Check if this partition houses your deployment assets
        if [ -f "${TMP_MNT}/openwrt-custom-x86-64-rootfs.tar.gz" ] || [ -f "${TMP_MNT}/openwrt-custom-x86-64-boot.tar.gz" ]; then
            # Find the parent disk name (e.g., converts 'nvme0n1p1' to 'nvme0n1', 'sda1' to 'sda')
            INSTALLER_DISK=$(lsblk -no PKNAME "/dev/$PART" 2>/dev/null | head -n1)
            # Fallback if PKNAME is empty (some environments don't populate it for raw devices)
            [ -z "$INSTALLER_DISK" ] && INSTALLER_DISK=$(echo "$PART" | sed -E 's/p?[0-9]+$//')
            umount "$TMP_MNT"
            rmdir "$TMP_MNT"
            break
        fi
        umount "$TMP_MNT"
    fi
    rmdir "$TMP_MNT" 2>/dev/null || true
done

# If content validation failed, fall back to checking if the OS is currently running an active LVM layout (VM context)
if [ -z "$INSTALLER_DISK" ]; then
    ROOT_DEV=$(findmnt -n -o SOURCE /)
    if [[ "$ROOT_DEV" == *mapper* || "$ROOT_DEV" == *dm-* ]]; then
        # Use dmsetup to resolve LVM arrays down to their underlying physical device components
        DM_NAME=$(basename "$ROOT_DEV")
        SLAVE_DEV=$(find "/sys/block/${DM_NAME}/slaves/" -maxdepth 1 -type l -printf "%f\n" 2>/dev/null | head -n1)
        if [ ! -z "$SLAVE_DEV" ]; then
            INSTALLER_DISK=$(lsblk -no PKNAME "/dev/$SLAVE_DEV" 2>/dev/null | head -n1)
            [ -z "$INSTALLER_DISK" ] && INSTALLER_DISK=$(echo "$SLAVE_DEV" | sed -E 's/p?[0-9]+$//')
        fi
    fi
fi

# Final absolute fallback if no source environment drive could be determined
[ -z "$INSTALLER_DISK" ] && INSTALLER_DISK="NOT_FOUND_FALLBACK"

# --- Tier 2: Extract Target Disks for Selection ---
# Gathers SCSI/SATA drives (sd*), NVMe drives (nvme*n*), and Virtual/VirtIO drives (vd*) common in VMs
RAW_DRIVES=$(lsblk -dno NAME,SIZE,TYPE | grep -E 'disk' | grep -vE 'loop|ram')

DIALOG_ARGS=()
while read -r NAME SIZE _; do
    # Strictly exclude the installer source disk from being displayed as an option
    [ "$NAME" = "$INSTALLER_DISK" ] && continue
    
    # Format choice list for the dialog box menu array
    DIALOG_ARGS+=("$NAME" "Disk_Size:_${SIZE}" "off")
done <<< "$RAW_DRIVES"

if [ ${#DIALOG_ARGS[@]} -eq 0 ]; then
    dialog --msgbox "Error: No target disks available for installation.\nAll detected drives are currently in use by the active OS or installer environment." 8 60
    exit 1
fi

# --- Tier 3: Present the Checkbox Interface via Dialog ---
# Fix: Pass individual arguments cleanly without wrapping the array in double quotes!
SELECTED_RAW=$(dialog --stdout --checklist "Select 2 to 4 target disks for OpenWRT RAID:" 15 60 5 "${DIALOG_ARGS[@]}")

# Convert selection into an array
# shellcheck disable=SC2206
DISK_ARRAY=($SELECTED_RAW)
DISK_COUNT=${#DISK_ARRAY[@]}

if [ "$DISK_COUNT" -lt 2 ] || [ "$DISK_COUNT" -gt 4 ]; then
    dialog --msgbox "Error: You must select between 2 and 4 disks to construct the RAID matrix." 6 60
    return 1
fi


# Step 2: Determine RAID Level & Sizing
if [ "$DISK_COUNT" -eq 4 ]; then
    # 4 Disks -> Auto-assign RAID 10
    ROOT_RAID_LEVEL="10"
    dialog --infobox "4 disks selected. ROOT array will automatically configure as RAID 10." 6 50
    sleep 3
else
    # 2 or 3 Disks -> Let them choose RAID 1 or RAID 0
    ROOT_RAID_LEVEL=$(dialog --stdout --menu "Select RAID Level for OpenWRT-ROOT (/md1):" 10 50 2 \
        "1" "RAID 1 (Mirroring - Recommended)" \
        "0" "RAID 0 (Striping - No Redundancy)")
fi

# Ask for Size Constraint
SIZE_CHOICE=$(dialog --stdout --menu "Configure ROOT Partition Size:" 10 60 2 \
    "MAX" "Use all remaining disk space" \
    "CUSTOM" "Specify custom size in Gigabytes")

# Extract the base device tracking identifier
# for capacity calculations (e.g., sdb, nvme0n1)
FIRST_DISK="${DISK_ARRAY[0]}"

# Fetch total disk size in GiB
DISK_BYTES=$(lsblk -bndo SIZE "/dev/$FIRST_DISK" | head -n1)
TOTAL_DISK_GB=$(( DISK_BYTES / 1024 / 1024 / 1024 ))
# Calculate max OpenWRT-ROOT partition size
MAX_AVAILABLE_ROOT_GB=$(( TOTAL_DISK_GB - 2 ))

if [[ "$SIZE_CHOICE" == "CUSTOM" ]]; then
    ROOT_SIZE=$(dialog --stdout --inputbox "Enter ROOT partition size per disk (in GB):" 8 50 "20")
    ROOT_PART_END="+${ROOT_SIZE}G"
    ESTIMATED_ROOT_GB=$ROOT_SIZE
else
    ROOT_PART_END="" # Consumes remaining space
    ESTIMATED_ROOT_GB=$MAX_AVAILABLE_ROOT_GB
fi

# Ask for Write-Intent Bitmap Config
# >=150GiB defaults to write-intent bitmap enabled


if [ "$ESTIMATED_ROOT_GB" -ge 150 ]; then
    # Default selection state mapping targeting the YES button
    printf -v PROMPT_TEXT "%s\n\n%s%s\n\n%s\n" \
        "Your estimated target ROOT array size (${ESTIMATED_ROOT_GB} GB) is >= 150 GB." \
        "Enabling a write-intent bitmap optimizes array reconstruction speeds after a power failure, " \
        "but adds a minute write latency overhead." \
        "Do you want to ENABLE the internal write-intent bitmap?"
    
    if dialog --defaultyes --yes-label "Enable" --no-label "Disable" --yesno "$PROMPT_TEXT" 12 65; then
        ROOT_BITMAP_MODE="internal"
    else
        ROOT_BITMAP_MODE="none"
    fi
else
    printf -v PROMPT_TEXT "%s\n\n%s%s\n\n%s\n" \
        "Your estimated target ROOT array size (${ESTIMATED_ROOT_GB} GB) is less than 150 GB." \
        "Bitmaps are generally discouraged on smaller storage volumes because the write performance " \
        "tax outweighs recovery gains." \
        "Do you want to override defaults and ENABLE the internal write-intent bitmap anyway?"
    
    if dialog --defaultno --yes-label "Enable" --no-label "Disable" --yesno "$PROMPT_TEXT" 12 65; then
        ROOT_BITMAP_MODE="internal"
    else
        ROOT_BITMAP_MODE="none"
    fi
fi

# Confirm execution pass
if ! dialog --yesno "WARNING: This will completely erase all data on: ${DISK_ARRAY[*]}.\n\nDo you want to proceed?" 10 60; then
    clear
    echo "--> Deployment canceled by user."
    exit 1
fi

# Hand off to setup.sh with wizard arguments
clear
exec /usr/bin/setup.sh "$ROOT_RAID_LEVEL" "$ROOT_PART_END" "$ROOT_BITMAP_MODE" "${DISK_ARRAY[@]}"
