#!/bin/bash
set -e

BR_PATH="/builder/Buildroot-Builder"
SCRIPTS_POOL="/builder/buildrootConf"
#OVERLAY_DIR="${BR_PATH}/system/skeleton_overlay"
OVERLAY_DIR="${BR_PATH}/../buildrootConf/rootfs-overlay"
REBUILD_LINUX=0
for arg in "$@"; do
    case "$arg" in
        --rebuild-linux) REBUILD_LINUX=1 ;;
        --renew-config) ;; # kept as an alias; copy+installer_defconfig already renews BR2
        --rebuild-linux-clean) REBUILD_LINUX=2 ;;
        --compiler-cache-clean) DEL_CCACHE=1 ;;
        *) echo "Unknown argument: $arg" >&2; exit 2 ;;
    esac
done

# 2. Establish layout overlay pipeline trees
mkdir -p "${OVERLAY_DIR}/usr/bin" "${OVERLAY_DIR}/etc/init.d" "${OVERLAY_DIR}/usr/share/vim"

# 3. Inject installer user-space assets
if [ -f "${SCRIPTS_POOL}/iTUI/wizard.sh" ] && [ -f "${SCRIPTS_POOL}/automation/setup.sh" ]; then
    cp "${SCRIPTS_POOL}/iTUI/wizard.sh" "${OVERLAY_DIR}/usr/bin/wizard.sh"
    cp "${SCRIPTS_POOL}/automation/setup.sh" "${OVERLAY_DIR}/usr/bin/setup.sh"
    chmod +x "${OVERLAY_DIR}/usr/bin/wizard.sh" "${OVERLAY_DIR}/usr/bin/setup.sh"
fi

# 4. Write standard system daemon initialization script
cat << 'EOF' > "${OVERLAY_DIR}/etc/init.d/S99installer"
#!/bin/bash
case "$1" in
    start)
        # Force script attachment to the primary system video output console terminal
        /usr/bin/wizard.sh < /dev/tty1 > /dev/tty1 2>&1
        ;;
    stop)
        ;;
    *)
        echo "Usage: $0 {start|stop}"
        exit 1
esac
exit 0
EOF
chmod +x "${OVERLAY_DIR}/etc/init.d/S99installer"

# 5. Load and evaluate target configurations
cd "$BR_PATH"

if [ -f "${SCRIPTS_POOL}/setup.config" ]; then
    cp "${SCRIPTS_POOL}/setup.config" "${BR_PATH}/configs/installer_defconfig"
    
    if [ -f "${SCRIPTS_POOL}/kernelOptions.config" ]; then
        cp "${SCRIPTS_POOL}/kernelOptions.config" "${BR_PATH}/kernelOptions.config"
    fi
    make installer_defconfig
    make olddefconfig
else
    echo "--> setup.config not detected. Standardizing on basic x86_64 topology..."
    make qemu_x86_64_defconfig
fi

if [[ "${DEL_CCACHE}" -eq 1 ]]; then
    printf '%s\n' "'--compiler-cache-clean' called: Cleaning up Buildroot compiler cache..."
    rm -rf /builder/Buildroot-Builder/.buildroot-ccache/.* \
        /builder/Buildroot-Builder/.buildroot-ccache/*.*
fi

if [[ "${REBUILD_LINUX}" -eq 2 ]]; then
    printf '%s\n' "Rebuilding Linux kernel from scratch: Cleaning up previous Linux kernel build artifacts..."
    make linux-dirclean
    make linux-firmware-dirclean
    rm -rf output/target/lib/firmware \
        output/images/amdgpu output/images/radeon output/images/xe \
        output/images/i915 output/images/amd-ucode output/images/intel-ucode \
        output/images/rootfs.cpio.zst output/images/rootfs.cpio \
        output/images/bzImage output/images/rootfs.tar
fi

if [[ "${REBUILD_LINUX}" =~ ^(1|2)$ ]]; then
    printf '%s\n' "Reconfiguring and rebuilding the Linux kernel..."
    make linux-reconfigure
    grep -E 'CONFIG_EXPERT|CONFIG_DRM_AMDGPU|CONFIG_SND_HDA_INTEL|CONFIG_USB_HID|CONFIG_SCSI=' \
        output/build/linux-*/.config || true
    make linux-rebuild
fi

# 6. Fire off specialized multi-threaded build pipeline pass
echo "--> Compiling specialized cross-toolchain and kernel utilities..."
make -j"$(nproc)"

# 7. Map final deployment components directly to your shared Mac volume
cd "$BR_PATH"
echo "--> Exporting final installer assets out to Mac mount..."
cp /builder/Buildroot-Builder/output/images/bzImage \
    /builder/workspace/output/buildroot/vmlinuz-installer
cp /builder/Buildroot-Builder/output/images/rootfs.cpio.* \
    /builder/workspace/output/buildroot/initramfs-installer.img

exit 0
