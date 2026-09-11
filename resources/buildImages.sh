#!/usr/bin/env bash
set -e

# Script Killer and Error Handler
die() {
    printf 'Error: %s\n' "$1" >&2
    exit 1
}

# Define directories
WORKSPACE="/builder/workspace"
IMAGE_BUILDER_DIR="/builder/OpenWRT-ImageBuilder"
STAGING_DIR="${WORKSPACE}/staging"
OUTPUT_DIR="${WORKSPACE}/output"

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
    part_gpt part_msdos mdraid1x mdraid09 ext2 part_apple 
    part_bsd fat search search_label search_fs_uuid search_fs_file 
    configfile ntfs usb btrfs exfat
)

echo "=== Step 1: Cleaning previous build environments ==="
rm -rf "${STAGING_DIR}" "${OUTPUT_DIR}"
mkdir -p "${STAGING_DIR}/boot/efi/EFI/BOOT"
mkdir -p "${STAGING_DIR}/boot/grub/x86_64-efi"
mkdir -p "${OUTPUT_DIR}"

echo "=== Step 2: Executing OpenWrt Image Builder ==="
cd "${IMAGE_BUILDER_DIR}"
make image PROFILE="generic" PACKAGES="${PACKAGES}" ROOTFS_PARTSIZE=256

# Find the newly generated rootfs package
# Using a wildcard match to grab the standard tar.gz rootfs
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

echo "=== Step 3: Extracting Kernel and Staging Boot Architecture ==="
# Place the kernel directly where OpenWrt updates expect to find it
cp "${VANILLA_KERNEL}" "${STAGING_DIR}/boot/vmlinuz"

# Copy all runtime .mod dependency drivers from Debian's library directly
cp /usr/lib/grub/x86_64-efi/*.mod "${STAGING_DIR}/boot/grub/x86_64-efi/"

echo "=== Step 4: Generating the Generic Boot-linked grub.cfg ==="
# Fixes the variable partition challenge. We instruct GRUB to search for 
# a partition explicitly labeled 'OpenWRT-ROOT'.
# This bypasses the need for hardcoded UUIDs.
cat << 'EOF' > "${STAGING_DIR}/boot/efi/EFI/BOOT/grub.cfg"
search --no-floppy --label --set=root OpenWRT-ROOT
set prefix=($root)'/boot/grub'
configfile $prefix/grub.cfg
EOF

echo "=== Step 5: Generating the Root OS Partition grub.cfg ==="
# Creates your working runtime configuration inside the storage mapping space
cat << 'EOF' > "${STAGING_DIR}/boot/grub/grub.cfg"
set default="0"
set timeout="2"

# Locate the root filesystem by its filesystem label
search --no-floppy --label --set=root OpenWRT-ROOT

menuentry "OpenWrt (RAID 1 Mirror)" {
    linux /boot/vmlinuz root=/dev/md0 rootwait console=tty0 console=ttyS0,115200n8 noinitrd
}
EOF

echo "=== Step 6: Compiling the Monolithic EFI Bootstub ==="
# Bakes your core storage and disk architecture drivers directly into the initial file.
# The payload maps back to the root boot directory configured above.
build_efi_bootstub() {
    grub-mkimage \
        -d /usr/lib/grub/x86_64-efi \
        -O x86_64-efi \
        -o "${STAGING_DIR}/boot/efi/EFI/BOOT/bootx64.efi" \
        -p "/boot/grub" \
        "${BOOT_EFI_MODS[@]}"
}

if ! build_efi_bootstub; then
    die 'Failed to generate Monolithic EFI Bootstub with grub-mkimage!'
else
    printf '%-27s %s\n' 'Wrote EFI Bootstub:' "${STAGING_DIR}/boot/efi/EFI/BOOT/bootx64.efi"
fi

echo "=== Step 7: Packaging Your Final Deployable Images ==="
# 1. Package the custom boot filesystem map
tar -czf "${OUTPUT_DIR}/openwrt-custom-x86-64-boot.tar.gz" -C "${STAGING_DIR}" boot/

# 2. Package the custom root filesystem map
# We copy OpenWrt's rootfs tarball out to the workspace for clean deployment delivery
cp "${VANILLA_ROOTFS}" "${OUTPUT_DIR}/openwrt-custom-x86-64-rootfs.tar.gz"

cat << EOF
=========================================================
BUILD SUCCESSFUL!
Your custom deployment archives are waiting inside your output directory:
${OUTPUT_DIR}
‣ openwrt-custom-x86-64-boot.tar.gz
   └──(Contains: Custom GRUB2 framework, all .mod files, and kernel)
‣ openwrt-custom-x86-64-rootfs.tar.gz
   └──(Contains: Base OS tree + preconfigured mdadm dependencies)
=========================================================
EOF

exit 0
