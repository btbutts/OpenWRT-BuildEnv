#!/bin/bash
set -e

STAGING_DIR="/builder/workspace/output/usb_installer_stage"
BUILDROOT_ASSETS="/builder/workspace/output/buildroot"
OPENWRT_ASSETS="/builder/workspace/output"

echo "--> Initializing custom USB installer staging tree..."
rm -rf "$STAGING_DIR"
mkdir -p "${STAGING_DIR}/EFI/BOOT"
mkdir -p "${STAGING_DIR}/boot"

# Step 1: Copy over your freshly compiled Buildroot installer kernel
echo "--> Staging compiled kernel architecture payload..."
if [ -f "${BUILDROOT_ASSETS}/vmlinuz-installer" ]; then
    cp "${BUILDROOT_ASSETS}/vmlinuz-installer" "${STAGING_DIR}/boot/vmlinuz-installer"
else
    echo "ERROR: vmlinuz-installer asset missing from Buildroot output directory!" >&2
    exit 1
fi

# Step 2: Inject your custom production OpenWRT deployment tarballs into the staging root
echo "--> Staging custom OpenWRT production payloads..."
if [ -f "${OPENWRT_ASSETS}/openwrt-custom-x86-64-boot.tar.gz" ] && [ -f "${OPENWRT_ASSETS}/openwrt-custom-x86-64-rootfs.tar.gz" ]; then
    # Copy and map names directly to match what setup.sh scans for on boot
    cp "${OPENWRT_ASSETS}/openwrt-custom-x86-64-boot.tar.gz" "${STAGING_DIR}/openwrt-boot.tar.gz"
    cp "${OPENWRT_ASSETS}/openwrt-custom-x86-64-rootfs.tar.gz" "${STAGING_DIR}/openwrt-rootfs.tar.gz"
    echo "--> Successfully staged and renamed production OpenWRT dependencies."
else
    echo "WARNING: Production OpenWRT tarballs not found inside ${OPENWRT_ASSETS}." >&2
    echo "         Make sure to execute buildOpenWRTimages.sh before copying this layout to your physical USB drive." >&2
fi

# Step 3: Generate the custom embedded GRUB.cfg steering loop
# This tells the primary binary to look for the real configuration on the drive
echo "--> Creating structural boot configs..."
cat << 'EOF' > "${STAGING_DIR}/EFI/BOOT/grub.cfg"
set default=0
set timeout=5

translation_filter_mode=1
insmod part_gpt
insmod part_msdos
insmod fat
insmod ext2
insmod serial
insmod video
insmod font

menuentry "Execute Bare-Metal OpenWRT Deployment Engine" --class linux {
    echo "Loading customized system installer kernel..."
    search --no-floppy --file --set=root /boot/vmlinuz-installer
    linux /boot/vmlinuz-installer console=tty1 quiet
}

menuentry "Emergency Hardware Maintenance Shell" --class shell {
    echo "Loading kernel in diagnostic maintenance framework mode..."
    search --no-floppy --file --set=root /boot/vmlinuz-installer
    linux /boot/vmlinuz-installer console=tty1 single
}
EOF

# Step 4: Compile the raw universal EFI binary stub
echo "--> Compiling standalone generic x86_64 EFI bootloader payload..."
grub-mkimage -O x86_64-efi \
    -o "${STAGING_DIR}/EFI/BOOT/BOOTX64.EFI" \
    -p "/EFI/BOOT" \
    part_gpt part_msdos fat ext2 exfat normal test configfile linux search normal ls echo

echo "========================================================="
echo "STAGING SUCCESSFUL!"
echo "Your bootable USB deployment layout is sitting in:"
echo "   ${STAGING_DIR}"
echo "========================================================="
exit 0
