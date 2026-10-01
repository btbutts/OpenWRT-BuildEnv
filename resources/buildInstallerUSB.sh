#!/bin/bash
set -e

: "${WORKSPACE_DIR:=/builder/workspace}"
: "${BUILDROOT_OUTPUT_DIR:=/builder/workspace/output/buildroot}"
: "${OPENWRT_OUTPUT_DIR:=/builder/workspace/output}"
: "${USB_INSTALLER_STAGE_DIR:=/builder/workspace/output/usb_installer_stage}"
: "${BUILDROOT_CONF_DIR:=/builder/buildrootConf}"

echo "--> Initializing custom USB installer staging tree..."
rm -rf "${USB_INSTALLER_STAGE_DIR%/}"
mkdir -p "${USB_INSTALLER_STAGE_DIR%/}/EFI/BOOT"
mkdir -p "${USB_INSTALLER_STAGE_DIR%/}/boot"

# Step 1: Copy over your freshly compiled Buildroot installer kernel and initramfs
echo "--> Staging compiled kernel architecture payload..."
if [ -f "${BUILDROOT_OUTPUT_DIR%/}/vmlinuz-installer" ]; then
    cp "${BUILDROOT_OUTPUT_DIR%/}/vmlinuz-installer" "${USB_INSTALLER_STAGE_DIR%/}/boot/vmlinuz-installer"
else
    echo "ERROR: vmlinuz-installer asset missing from Buildroot output directory!" >&2
    exit 1
fi

echo "--> Staging compiled initramfs payload..."
if [ -f "${BUILDROOT_OUTPUT_DIR%/}/initramfs-installer.img" ]; then
    cp "${BUILDROOT_OUTPUT_DIR%/}/initramfs-installer.img" "${USB_INSTALLER_STAGE_DIR%/}/boot/initramfs-installer.img"
else
    echo "ERROR: initramfs-installer.img asset missing from Buildroot output directory!" >&2
    exit 1
fi

# Step 2: Inject your custom production OpenWRT deployment tarballs into the staging root
echo "--> Staging custom OpenWRT production payloads..."
if [ -f "${OPENWRT_OUTPUT_DIR%/}/openwrt-custom-x86-64-boot.tar.gz" ] && [ -f "${OPENWRT_OUTPUT_DIR%/}/openwrt-custom-x86-64-rootfs.tar.gz" ]; then
    # Copy and map names directly to match what setup.sh scans for on boot
    cp "${OPENWRT_OUTPUT_DIR%/}/openwrt-custom-x86-64-boot.tar.gz" "${USB_INSTALLER_STAGE_DIR%/}/openwrt-boot.tar.gz"
    cp "${OPENWRT_OUTPUT_DIR%/}/openwrt-custom-x86-64-rootfs.tar.gz" "${USB_INSTALLER_STAGE_DIR%/}/openwrt-rootfs.tar.gz"
    echo "--> Successfully staged and renamed production OpenWRT dependencies."
else
    echo "WARNING: Production OpenWRT tarballs not found inside ${OPENWRT_OUTPUT_DIR%/}." >&2
    echo "         Make sure to execute buildOpenWRTimages.sh before copying this layout to your physical USB drive." >&2
fi

# Step 3: Generate the custom embedded GRUB.cfg steering loop
# This tells the primary binary to look for the real configuration on the drive
echo "--> Copying structural boot configs..."
cp "${BUILDROOT_CONF_DIR%/}/grub/buildroot.grub.cfg" "${USB_INSTALLER_STAGE_DIR%/}/EFI/BOOT/grub.cfg"

# Step 4: Compile the raw universal EFI binary stub
echo "--> Compiling standalone generic x86_64 EFI bootloader payload..."
grub_mods=(
    part_gpt part_msdos exfat ext2 fat linux help time
    configfile minicmd normal sleep test tr date echo
    ls search search_fs_file search_fs_uuid search_label
    all_video efi_gop efi_uga gfxterm lspci lsefi fshelp
    font date datetime datehook cat boot chain cpuid
    setpci read serial terminfo terminal hello progress
    usb usb_keyboard usbserial_common usbserial_ftdi
    usbserial_pl2303 usbserial_usbdebug usbtest
)
grub-mkimage \
    -d /usr/lib/grub/x86_64-efi \
    -O x86_64-efi \
    -o "${USB_INSTALLER_STAGE_DIR%/}/EFI/BOOT/BOOTX64.EFI" \
    -p "/EFI/BOOT" \
    "${grub_mods[@]}"

echo "========================================================="
echo "STAGING SUCCESSFUL!"
echo "Your bootable USB deployment layout is sitting in:"
echo "   ${USB_INSTALLER_STAGE_DIR%/}"
echo "========================================================="
exit 0
