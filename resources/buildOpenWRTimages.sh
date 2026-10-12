#!/usr/bin/env bash
set -e

# Script Killer and Error Handler
die() {
    printf 'Error: %s\n' "$1" >&2
    exit 1
}

# Define directories
: "${WORKSPACE_DIR:=/builder/workspace}"
: "${OPENWRT_BUILDER_DIR:=/builder/OpenWRT-ImageBuilder}"

# Optional: ./buildOpenWRTimages.sh --clean|-C
#           ./buildOpenWRTimages.sh --package-only
CLEAN=0
PACKAGE_ONLY=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --clean|-C)
            CLEAN=1
            shift
            ;;
        --package-only)
            PACKAGE_ONLY=1
            shift
            ;;
        -h|--help)
            printf 'Usage: %s [--clean|-C | --package-only]\n' "${0##*/}"
            printf '  --clean, -C       Wipe staging and output directories before building\n'
            printf '  --package-only    Skip Image Builder make; repackage existing artifacts\n'
            exit 0
            ;;
        *)
            die "Unknown argument: $1 (try --help)"
            ;;
    esac
done

if [[ "$CLEAN" -eq 1 && "$PACKAGE_ONLY" -eq 1 ]]; then
    die '--package-only and --clean are incompatible'
fi

# Define your downstream package choices
# Adding kmod-md-raid1, mdadm, and ext4 filesystem drivers
PACKAGES="-wpad-basic-mbedtls kmod-md-raid1 kmod-md-raid0 mdadm \
amd64-microcode amdgpu-firmware radeon-firmware bash vim-fuller \
wget-ssl kmod-bluetooth bluez-libs bluez-utils kmod-crypto-crc32c \
kmod-dnsresolver kmod-drm-amdgpu kmod-drm-radeon kmod-ipt-core \
kmod-tpm kmod-tpm-i2c-atmel kmod-tpm-i2c-infineon kmod-tpm-tis \
kmod-qlcnic kmod-kvm-amd kmod-leds-gpio kmod-gpio-button-hotplug \
kmod-fs-efivarfs kmod-fs-exfat kmod-fs-ext4 kmod-fs-f2fs \
kmod-fs-nfs kmod-gpio-it87 kmod-hwmon-it87 kmod-igc \
kmod-ipt-nat6 kmod-it87-wdt kmod-ledtrig-activity kmod-lib-crc16 \
kmod-macvlan kmod-md-mod kmod-mlx_wdt kmod-mlx4-core \
kmod-mlx5-core kmod-mlxfw kmod-mlxreg kmod-nf-flow kmod-nf-ipt \
kmod-nf-log kmod-nf-log6 kmod-nf-nat kmod-nf-nathelper kmod-nf-reject \
kmod-nf-reject6 kmod-nft-core kmod-nft-core kmod-nft-nat kmod-nls-base \
kmod-nvme kmod-phy-amd kmod-phylink kmod-sfp kmod-thermal kmod-usb-core \
kmod-usb-storage kmod-usb-storage-uas kmod-usb-uhci kmod-usb2 kmod-usb2-pci \
kmod-usb3 block-mount btrfs-progs ca-bundle coreutils curl \
dhcpcd dnsmasq-full e2fsprogs efibootmgr exfat-fsck f2fs-tools f2fsck fdisk \
fstools gdisk grub2-editenv grub2-efi hd-idle hdparm wpa-supplicant \
ipset ipset-dns jsonfilter libblkid libc luci luci-compat luci-lib-ipkg \
luci-ssl mkf2fs nano openssh-sftp-server parted pciutils usbutils \
smartmontools lm-sensors rng-tools kmod-tls"

# List of EFI Firmware modules to be included in partition 1
# (EFI System Partition)
BOOT_EFI_MODS=(
    part_apple part_bsd part_gpt part_msdos help time
    mdraid09 mdraid1x linux btrfs exfat ext2 fat ntfs
    configfile minicmd normal sleep test tr date echo
    ls search search_fs_file search_fs_uuid search_label
    all_video efi_gop efi_uga gfxterm lspci lsefi fshelp
    font date datetime datehook cat boot chain cpuid
    setpci read serial terminfo terminal hello progress
    usb usb_keyboard usbserial_common usbserial_ftdi
    usbserial_pl2303 usbserial_usbdebug usbtest
)

if [[ "$CLEAN" -eq 1 ]]; then
    echo "=== Step 1: Cleaning previous build environments ==="
    rm -rf "${WORKSPACE_DIR%/}/staging" "${WORKSPACE_DIR%/}/output"
else
    echo "=== Step 1: Reusing previous build environments (pass --clean or -C to wipe) ==="
fi

# Isolate the partition workspaces explicitly
mkdir -p "${WORKSPACE_DIR%/}/staging/boot_partition/EFI/BOOT"
mkdir -p "${WORKSPACE_DIR%/}/staging/root_partition"
mkdir -p "${WORKSPACE_DIR%/}/output"

echo "=== Step 2: Executing OpenWrt Image Builder ==="
cd "${OPENWRT_BUILDER_DIR%/}"
if [[ "$PACKAGE_ONLY" -ne 1 ]]; then
    make image PROFILE="generic" PACKAGES="${PACKAGES}" ROOTFS_PARTSIZE=256
fi

# Locate compiled vanilla artifacts
VANILLA_ROOTFS=$(find bin/targets/x86/64/ -name "openwrt-*-rootfs.tar.gz" | head -n 1)
VANILLA_KERNEL=$(find bin/targets/x86/64/ -name "openwrt-*-kernel.bin" | head -n 1)

if [[ -z $VANILLA_ROOTFS || -z $VANILLA_KERNEL ]]; then
    die 'Image builder asset variables are not set!'
elif [[ ! -e $VANILLA_ROOTFS || ! -e $VANILLA_KERNEL ]]; then
    die 'Image builder asset files do not exist!'
else
    printf '%-27s %s\n' 'OpenWRT RootFS Located:' "$VANILLA_ROOTFS"
    printf '%-27s %s\n' 'OpenWRT Kernel Located:' "$VANILLA_KERNEL"
fi

echo "=== Step 3: Splicing OpenWrt RootFS & Injecting Custom Configurations ==="
# Unpack the vanilla root archive to our isolated root staging environment
tar -xzf "${VANILLA_ROOTFS}" -C "${WORKSPACE_DIR%/}/staging/root_partition"

# Ensure target directories exist inside the root filesystem space
mkdir -p "${WORKSPACE_DIR%/}/staging/root_partition/boot/grub/x86_64-efi"

# Explicitly purge anything lingering in boot/efi inside RootFS, leaving it as a clean mount point anchor
rm -rf "${WORKSPACE_DIR%/}/staging/root_partition/boot/efi"
mkdir -p "${WORKSPACE_DIR%/}/staging/root_partition/boot/efi"

# Place the kernel directly into /boot/vmlinuz inside Partition 2
cp "${VANILLA_KERNEL}" "${WORKSPACE_DIR%/}/staging/root_partition/boot/vmlinuz"

# Copy all runtime .mod drivers into Partition 2 (/boot/grub/x86_64-efi/)
cp /usr/lib/grub/x86_64-efi/*.mod "${WORKSPACE_DIR%/}/staging/root_partition/boot/grub/x86_64-efi/"

echo "=== Step 4: Generating the Partition 1 (OpenWRT-BOOT) Early grub.cfg ==="
cat << 'EOF' > "${WORKSPACE_DIR%/}/staging/boot_partition/EFI/BOOT/grub.cfg"
insmod mdraid1x
insmod ext2

# Locate OpenWRT-ROOT md1 madm RAID partition
# (RAID 1 Mirror) via its filesystem label
search --no-floppy --label --set=root OpenWRT-ROOT
set prefix=($root)/boot/grub
configfile $prefix/grub.cfg
EOF

echo "=== Step 5: Generating the Partition 2 (OpenWRT-ROOT) Main System grub.cfg ==="
cat << 'EOF' > "${WORKSPACE_DIR%/}/staging/root_partition/boot/grub/grub.cfg"
set default="0"
set timeout="6"

# Locate the root filesystem by its filesystem label
search --no-floppy --label --set=root OpenWRT-ROOT

menuentry "OpenWRT (RAID 1 Mirror)" {
    insmod mdraid1x
    insmod ext2
    linux /boot/vmlinuz root=LABEL=OpenWRT-ROOT rootwait @MD_ASSEMBLY_TOKEN@ console=tty0 console=ttyS0,115200n8 noinitrd
}
EOF

echo "=== Step 6: Compiling the Monolithic EFI Bootstub ==="
build_efi_bootstub() {
    grub-mkimage \
        -d /usr/lib/grub/x86_64-efi \
        -O x86_64-efi \
        -o "${WORKSPACE_DIR%/}/staging/boot_partition/EFI/BOOT/bootx64.efi" \
        -p "/boot/grub" \
        "${BOOT_EFI_MODS[@]}"
}

if ! build_efi_bootstub; then
    die 'Failed to generate Monolithic EFI Bootstub with grub-mkimage!'
else
    printf '%-27s %s\n' 'Wrote EFI Bootstub:' "${WORKSPACE_DIR%/}/staging/boot_partition/EFI/BOOT/bootx64.efi"
fi

echo "=== Step 7: Packaging Your Final Isolated Deployable Images ==="


# 1. Package the OpenWRT-BOOT archive (contains ONLY EFI/BOOT/)
tar -czf "${WORKSPACE_DIR%/}/output/openwrt-custom-x86-64-boot.tar.gz" -C "${WORKSPACE_DIR%/}/staging/boot_partition" EFI/

# 2. Re-tar the RootFS workspace preserving file permissions, including your newly injected components
tar -czf "${WORKSPACE_DIR%/}/output/openwrt-custom-x86-64-rootfs.tar.gz" -C "${WORKSPACE_DIR%/}/staging/root_partition" .

cat << EOF
=========================================================
BUILD SUCCESSFUL!
Your custom deployment archives are waiting inside your output directory:
${WORKSPACE_DIR%/}/output

‣ openwrt-custom-x86-64-boot.tar.gz
   └── (Contains ONLY: EFI/BOOT/bootx64.efi & early grub.cfg) -> Extract to Partition 1

‣ openwrt-custom-x86-64-rootfs.tar.gz
   └── (Contains: Base OS, mdadm packages, /boot/vmlinuz, full .mod drivers, and main grub.cfg) -> Extract to Partition 2
=========================================================
EOF

exit 0
