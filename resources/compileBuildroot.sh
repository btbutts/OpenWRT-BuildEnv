#!/bin/bash
set -e

BR_PATH="/builder/Buildroot-Builder"
BR_WORKSPACE_OUT="/builder/workspace/output/buildroot"
SCRIPTS_POOL="/builder/buildrootConf"
#OVERLAY_DIR="${BR_PATH}/system/skeleton_overlay"
OVERLAY_DIR="${BR_PATH}/../buildrootConf/rootfs-overlay"
REBUILD_LINUX=0
for arg in "$@"; do
    case "$arg" in
        --rebuild-linux-firmware) REBUILD_LINUX=1 ;;
        --rebuild-linux-firmware-clean) REBUILD_LINUX=2 ;;
        --compiler-cache-clean) DEL_CCACHE=1 ;;
        --copy-only) COPY_ONLY=1 ;;
        *) echo "Unknown argument: $arg" >&2; exit 2 ;;
    esac
done

copy_kconfig() {
    local remove_params=false
    local src_file=""
    local dest_file=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --remove-commented-params)
                remove_params=true
                shift
                ;;
            *)
                if [ -z "$src_file" ]; then
                    src_file="$1"
                elif [ -z "$dest_file" ]; then
                    dest_file="$1"
                fi
                shift
                ;;
        esac
    done

    # Ensure paths are provided
    if [ -z "$src_file" ] || [ -z "$dest_file" ]; then
        printf '%s\n' "Error [copy_kconfig]: Missing source or destination file path." >&2
        return 1
    elif [ "$remove_params" = false ]; then
        cp "$src_file" "$dest_file"
        return $?
    elif [ -f "$dest_file" ] || [ -L "$dest_file" ]; then
        rm -rf "$dest_file"
    fi
    mkdir -p "$(dirname "$dest_file")"
    touch "$dest_file"

    # Match # followed by all-caps letters separated
    # with underscores (e.g., # CONFIG_XYZ or CONFIG_XYZ=n)
    local pattern='^#[[:space:]]*[A-Z0-9]+(_[A-Z0-9]+)+(=n)?$' protected_param='is not set$'

    # Process the source file line-by-line using a clean loop layout
    while IFS= read -r line || [[ -n "$line" ]]; do
        
        # Check if the line is a candidate for removal (starts with #)
        if [[ "$line" =~ ^# ]]; then
            
            # If it matches our explicit protection rule, keep it safely
            if [[ "$line" =~ $protected_param ]]; then
                printf '%s\n' "$line" >> "$dest_file"
                continue
            fi

            # Check against deletion rule 1 (# CONFIG_XYZ)
            if [[ "$line" =~ $pattern ]]; then
                continue
            fi

        fi
        printf '%s\n' "$line" >> "$dest_file"
    done < "$src_file"
}

run_copy_kconfig() {
    copy_kconfig --remove-commented-params "${SCRIPTS_POOL}/setup.config" "${BR_PATH}/configs/installer_defconfig"
    if [ -f "${SCRIPTS_POOL}/kernelOptions.config" ]; then
        copy_kconfig --remove-commented-params "${SCRIPTS_POOL}/kernelOptions.config" "${BR_PATH}/kernelOptions.config"
    fi
}

if [[ "${COPY_ONLY}" -eq 1 ]]; then
     printf '%s%s\n%s\n\t%s\n\t%s\n' "--> compiler script was run with " "$@" \
        "Copying:" \
        "${SCRIPTS_POOL}/setup.config --> ${BR_PATH}/configs/installer_defconfig" \
        "${SCRIPTS_POOL}/kernelOptions.config --> ${BR_PATH}/kernelOptions.config"
    run_copy_kconfig
    exit 0
fi

# 2. Establish layout overlay pipeline trees
mkdir -p "${OVERLAY_DIR}/usr/bin" \
    "${OVERLAY_DIR}/etc/init.d" \
    "${OVERLAY_DIR}/usr/share/vim" \
    "${OVERLAY_DIR}/etc/acpi/events"

# 3. Inject installer user-space assets
declare -A SCRIPTS_MAP=(
    ["${SCRIPTS_POOL}/iTUI/wizard.sh"]="${OVERLAY_DIR}/usr/bin/wizard.sh"
    ["${SCRIPTS_POOL}/automation/setup.sh"]="${OVERLAY_DIR}/usr/bin/setup.sh"
    ["${OVERLAY_DIR}/usr/sbin/installer-bootlog.sh"]=""
    ["${SCRIPTS_POOL}/inittab/append.sh"]=""
)

# Loop through the keys (source paths)
for file in "${!SCRIPTS_MAP[@]}"; do
    dest="${SCRIPTS_MAP[$file]}"
    # Verify source file existance before copy and executable permission
    if [ -f "$file" ]; then
        if [ -n "$dest" ]; then
            cp "$file" "$dest"
            chmod +x "$dest"
            printf '%s\n\t%s%s%s\n' "Copied and set executable permission:" \
                "$file" "-->" "$dest"
        else
            chmod +x "$file"
            printf '%s%s\n' "Set executable permission: --> " "$file"
        fi
    fi
done

# 4. Write standard system daemon initialization script
cat << 'EOF' > "${OVERLAY_DIR}/etc/init.d/S99installer"
#!/bin/bash
case "$1" in
    start)
        # Keep the kmsg ring buffer; stop printk from painting over dialog/tty1.
        # loglevel= on the kernel cmdline still applies during boot.
        dmesg -n 1 2>/dev/null || true
        if [ -w /proc/sys/kernel/printk ]; then
            echo "1 4 1 7" > /proc/sys/kernel/printk
        fi
        # Force script attachment to the primary system video output console terminal
        /usr/bin/wizard.sh < /dev/tty1 > /dev/tty1 2>&1
        ;;
    stop)
        ;;
    *)
        echo "Usage: $0 {start|stop}"
        exit 1
        ;;
esac
exit 0
EOF

cat << 'EOF' > "${OVERLAY_DIR}/etc/init.d/S20installer-bootlog"
#!/bin/bash
# etc/init.d/S20installer-bootlog
case "${1:-start}" in
    start) 
        mkdir -p /var/log
        /usr/sbin/installer-bootlog.sh > /var/log/installer-bootlog-wrapper.log 2>&1 & ;;
    *) exit 0 ;;
esac
EOF

cat << 'EOF' > "${OVERLAY_DIR}/etc/acpi/events/power"
event=button/power
action=/etc/acpi/power.sh
EOF

cat << 'EOF' > "${OVERLAY_DIR}/etc/acpi/power.sh"
#!/bin/sh
sync
umount -a -r 2>/dev/null || true
exec /sbin/poweroff -f
EOF
chmod +x "${OVERLAY_DIR}/etc/acpi/power.sh" \
    "${OVERLAY_DIR}/etc/acpi/events/power" \
    "${OVERLAY_DIR}/etc/init.d/S99installer" \
    "${OVERLAY_DIR}/etc/init.d/S20installer-bootlog"

# 5. Load and evaluate target configurations
cd "$BR_PATH"

if [[ "${DEL_CCACHE}" -eq 1 ]]; then
    printf '%s\n' "'--compiler-cache-clean' called: Cleaning up Buildroot compiler cache..."
    rm -rf "${BR_PATH}/.buildroot-ccache/.*" \
        "${BR_PATH}/.buildroot-ccache/*"
fi

mkdir -p "${BR_PATH}/.buildroot-ccache"
if [ -f "${SCRIPTS_POOL}/setup.config" ]; then
    run_copy_kconfig
    make installer_defconfig > /dev/null 2>&1
    make olddefconfig > /dev/null 2>&1
    printf '%s%s\n' "--> Configuration from ${SCRIPTS_POOL}/setup.config " \
        "applied to ${BR_PATH}/.config"
else
    printf '%s\n' "--> setup.config not detected. Standardizing on basic x86_64 topology..."
    make qemu_x86_64_defconfig
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

# 7. Map final deployment components directly to your shared Host volume
cd "$BR_PATH"
echo "--> Exporting final installer assets out to Host mount..."
cp "${BR_PATH}"/output/images/bzImage \
    "${BR_WORKSPACE_OUT}"/vmlinuz-installer
cp "${BR_PATH}"/output/images/rootfs.cpio.* \
    "${BR_WORKSPACE_OUT}"/initramfs-installer.img

exit 0
