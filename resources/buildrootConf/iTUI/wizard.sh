#!/bin/bash
set -e

echo "installer shell=$0 bash=${BASH_VERSION:-NOT_BASH} exe=$(readlink -f /proc/self/exe)" > /dev/tty1

# dialog Cancel=1, ESC=255. Those are a normal end: hand tty1 back to getty.
user_quit() {
    clear
    stty sane < /dev/tty1 > /dev/tty1 2>/dev/null || stty sane 2>/dev/null || true
    exit 0
}

# Capture dialog --stdout; Cancel/ESC leaves the wizard without failing the unit.
dlg_capture() {
    local rc=0 out
    out=$(dialog --stdout "$@") || rc=$?
    if [ "$rc" -eq 1 ] || [ "$rc" -eq 255 ]; then
        user_quit
    fi
    if [ "$rc" -ne 0 ]; then
        exit "$rc"
    fi
    printf '%s\n' "$out"
}

if [ ! -f /usr/lib/installer/media.sh ]; then
    dialog --msgbox "Error: installer media helper is missing (/usr/lib/installer/media.sh)." 8 60
    user_quit
fi
# shellcheck source=/usr/lib/installer/media.sh: disable=SC1091
. /usr/lib/installer/media.sh

# --- Tier 1: Identify the installer boot disk (USB/SD/NVMe) ---
# installer-bootlog.service already discovered this and wrote /run/installer-media-id.
# Do not mount target NVMe/SATA partitions here.
installer_load_identity || installer_discover || true

# --- Tier 2: Real, non-zero disks only; never nbd/loop/0B; never boot media ---
DIALOG_ARGS=()
while read -r NAME SIZE TYPE; do
    [ "$TYPE" = "disk" ] || continue
    installer_is_target_disk "$NAME" || continue
    DIALOG_ARGS+=("$NAME" "Disk_Size:_${SIZE}" "off")
done < <(lsblk -dno NAME,SIZE,TYPE)

if [ ${#DIALOG_ARGS[@]} -eq 0 ]; then
    dialog --msgbox "Error: No target disks available for installation.\nAll detected drives are currently in use by the active OS or installer environment." 8 60
    user_quit
fi

# --- Tier 3: Present the Checkbox Interface via Dialog ---
# Fix: Pass individual arguments cleanly without wrapping the array in double quotes!
SELECTED_RAW=$(dlg_capture --checklist "Select 2 to 4 target disks for OpenWRT RAID:" 15 60 5 "${DIALOG_ARGS[@]}")

read -r -a DISK_ARRAY <<< "$SELECTED_RAW"
DISK_COUNT=${#DISK_ARRAY[@]}

if [ "$DISK_COUNT" -lt 2 ] || [ "$DISK_COUNT" -gt 4 ]; then
    dialog --msgbox "Error: You must select between 2 and 4 disks to construct the RAID matrix." 6 60
    user_quit
fi

# Refuse the installer boot disk even if it leaked into the checklist.
for _disk in "${DISK_ARRAY[@]}"; do
    if [ -n "$INSTALLER_DISK" ] && [ "$_disk" = "$INSTALLER_DISK" ]; then
        dialog --msgbox "Error: ${_disk} is the installer boot media and cannot be a RAID target." 8 60
        user_quit
    fi
    if ! installer_is_target_disk "$_disk"; then
        dialog --msgbox "Error: ${_disk} is not a writable installation target." 8 60
        user_quit
    fi
done


# Step 2: Determine RAID Level & Sizing
if [ "$DISK_COUNT" -eq 4 ]; then
    # 4 Disks -> Auto-assign RAID 10
    ROOT_RAID_LEVEL="10"
    dialog --infobox "4 disks selected. ROOT array will automatically configure as RAID 10." 6 50
    sleep 3
else
    # 2 or 3 Disks -> Let them choose RAID 1 or RAID 0
    ROOT_RAID_LEVEL=$(dlg_capture --menu "Select RAID Level for OpenWRT-ROOT (/md1):" 10 50 2 \
        "1" "RAID 1 (Mirroring - Recommended)" \
        "0" "RAID 0 (Striping - No Redundancy)")
fi

# Ask for Size Constraint
SIZE_CHOICE=$(dlg_capture --menu "Configure ROOT Partition Size:" 10 60 2 \
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
    ROOT_SIZE=$(dlg_capture --inputbox "Enter ROOT partition size per disk (in GB):" 8 50 "20")
    ROOT_PART_END="+${ROOT_SIZE}G"
    ESTIMATED_ROOT_GB=$ROOT_SIZE
else
    ROOT_PART_END="" # Consumes remaining space
    ESTIMATED_ROOT_GB=$MAX_AVAILABLE_ROOT_GB
fi

# Ask for Write-Intent Bitmap Config
# >=150GiB defaults to write-intent bitmap enabled


# Ask for write-intent bitmap. Default follows array size; user can still override.
if [ "$ESTIMATED_ROOT_GB" -ge 150 ]; then
    BITMAP_DEFAULT_BUTTON="yes"
    printf -v PROMPT_TEXT "%s\n\n%s%s\n\n%s\n" \
        "Your estimated target ROOT array size (${ESTIMATED_ROOT_GB} GB) is >= 150 GB." \
        "Enabling a write-intent bitmap optimizes array reconstruction speeds after a power failure, " \
        "but adds a minute write latency overhead." \
        "Do you want to ENABLE the internal write-intent bitmap?"
else
    BITMAP_DEFAULT_BUTTON="no"
    printf -v PROMPT_TEXT "%s\n\n%s%s\n\n%s\n" \
        "Your estimated target ROOT array size (${ESTIMATED_ROOT_GB} GB) is less than 150 GB." \
        "Bitmaps are generally discouraged on smaller storage volumes because the write performance " \
        "tax outweighs recovery gains." \
        "Do you want to override defaults and ENABLE the internal write-intent bitmap anyway?"
fi

if dialog \
    --default-button "$BITMAP_DEFAULT_BUTTON" \
    --yes-label "Enable" \
    --no-label "Disable" \
    --yesno "$PROMPT_TEXT" 14 65
then
    ROOT_BITMAP_MODE="internal"
else
    ROOT_BITMAP_MODE="none"
fi

# Confirm execution pass
if ! dialog --yesno "WARNING: This will completely erase all data on: ${DISK_ARRAY[*]}.\n\nDo you want to proceed?" 10 60; then
    echo "--> Deployment canceled by user."
    user_quit
fi

# Record wizard selections before setup.sh takes over the console.
mkdir -p /var/log
{
    echo "===== wizard.sh selections ====="
    date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date
    echo "INSTALLER_DISK=${INSTALLER_DISK:-unknown}"
    echo "DISKS=${DISK_ARRAY[*]}"
    echo "DISK_COUNT=$DISK_COUNT"
    echo "RAID_LEVEL=$ROOT_RAID_LEVEL"
    echo "ROOT_PART_END=${ROOT_PART_END:-MAX}"
    echo "BITMAP=$ROOT_BITMAP_MODE"
} > /var/log/installer-setup.log

# Hand off to setup.sh with wizard arguments
clear
exec /usr/bin/setup.sh "$ROOT_RAID_LEVEL" "$ROOT_PART_END" "$ROOT_BITMAP_MODE" "${DISK_ARRAY[@]}"
