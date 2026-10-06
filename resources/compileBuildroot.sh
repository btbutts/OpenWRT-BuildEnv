#!/bin/bash
set -e

: "${BUILDER_ROOT_DIR:=/builder}"
: "${BUILDROOT_BUILDER_DIR:=/builder/Buildroot-Builder}"
: "${BUILDROOT_OUTPUT_DIR:=/builder/workspace/output/buildroot}"
: "${BUILDROOT_CONF_DIR:=/builder/buildrootConf}"
: "${WORKSPACE_DIR:=/builder/workspace}"
# br2-external tree. Make variable, not Kconfig. First make writes
# output/.br2-external.mk; still export so a wiped tree's first
# installer_defconfig sees custom packages.
: "${BR2_EXTERNAL:=${BR_CUSTOM_PACKAGE_PATH:-${BUILDROOT_CONF_DIR%/}/custom_package}}"
export BR2_EXTERNAL

BUILDROOT_OVERLAY_DIR="${BUILDROOT_CONF_DIR%/}/rootfs-overlay"
BUILDROOT_CCACHE_DIR="${BUILDROOT_BUILDER_DIR%/}/.buildroot-ccache"
BUILDROOT_OUTPUT_DIR="${BUILDROOT_OUTPUT_DIR%/}"

REBUILD_LINUX=0
while [ $# -gt 0 ]; do
    case "$1" in
        --rebuild-linux-firmware) REBUILD_LINUX=1; shift ;;
        --rebuild-linux-firmware-clean) REBUILD_LINUX=2; shift ;;
        --compiler-cache-clean) DEL_CCACHE=1; shift ;;
        --rebuild-app)
            if [ -n "$2" ] && [ "${2:0:1}" != "-" ]; then
                BR_APP="$2"
                shift 2
            else
                echo "Error: --rebuild-app requires a package name argument." >&2
                exit 1
            fi
            ;;
        --rebuild-linux-toolchain) REBUILD_LX_TOOLCHAIN=1; shift ;;
        --copy-only) COPY_ONLY=1; shift ;;
        --target-finalize-clean) RM_TARGET_FINALIZE=1; shift ;;
        --resume) RESUME=1; shift ;;
        --set-mirrors)
            if [ -n "$2" ] && [ "${2:0:1}" != "-" ]; then
                if [ -n "$ZSH_VERSION" ]; then
                    eval 'emulate bash -c "BR_MIRRORS=\($2\)"'
                else
                    eval "BR_MIRRORS=($2)"
                fi
                shift 2
            else
                printf '%s\n%s\n\t%s%s%s\n\t%s%s\n' \
                    "Error: --set-mirrors requires a single-quoted mirror assignment string!" \
                    "Examples:" \
                    "--set-mirrors" \
                    " 'BR2_GNU_MIRROR=\"https://mirrors.ocf.berkeley.edu/gnu\"" \
                    " BR2_KERNEL_MIRROR=\"https://cdn.kernel.org/pub'\"" \
                    "--set-mirrors" \
                    " 'BR2_GNU_MIRROR=\"https://mirrors.ocf.berkeley.edu/gnu\"'" >&2
                exit 1
            fi
            ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
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
    copy_kconfig --remove-commented-params "${BUILDROOT_CONF_DIR%/}/setup.config" "${BUILDROOT_BUILDER_DIR%/}/configs/installer_defconfig"
    if [ -f "${BUILDROOT_CONF_DIR%/}/kernelOptions.config" ]; then
        copy_kconfig --remove-commented-params "${BUILDROOT_CONF_DIR%/}/kernelOptions.config" "${BUILDROOT_BUILDER_DIR%/}/kernelOptions.config"
    fi
    if [ -f "${BUILDROOT_CONF_DIR%/}/busyboxOptions.config" ]; then
        copy_kconfig --remove-commented-params "${BUILDROOT_CONF_DIR%/}/busyboxOptions.config" "${BUILDROOT_BUILDER_DIR%/}/busyboxOptions.config"
    fi
}

if [[ "${COPY_ONLY}" -eq 1 ]]; then
     printf '%s%s\n%s\n\t%s\n\t%s\n' "--> compiler script was run with " "$@" \
        "Copying:" \
        "${BUILDROOT_CONF_DIR%/}/setup.config --> ${BUILDROOT_BUILDER_DIR%/}/configs/installer_defconfig" \
        "${BUILDROOT_CONF_DIR%/}/kernelOptions.config --> ${BUILDROOT_BUILDER_DIR%/}/kernelOptions.config" \
        "${BUILDROOT_CONF_DIR%/}/busyboxOptions.config --> ${BUILDROOT_BUILDER_DIR%/}/busyboxOptions.config"
    run_copy_kconfig
    # installer_defconfig + olddefconfig write .config and fill any
    # missing symbols (including string defaults such as
    # BR2_PACKAGE_SHARUTILS_VERSION) without prompting. Without this,
    # make busybox-menuconfig runs oldaskconfig and asks (NEW).
    cd "${BUILDROOT_BUILDER_DIR%/}"
    make installer_defconfig
    printf '%s\n' "--> Applied installer_defconfig (Kconfig defaults filled in silently)"
    exit 0
fi

run_compile_now() {
    cd "${BUILDROOT_BUILDER_DIR%/}"
    echo "--> Compiling specialized cross-toolchain and kernel utilities..."
    if [ ${#BR_MIRRORS[@]} -gt 0 ]; then
        local mirror_list
        mirror_list=$(printf "%s " "${BR_MIRRORS[@]}")
        mirror_list="${mirror_list% }"
        printf '%s\n\t%s\n' "--> Using custom mirror overide(s):" "$mirror_list"
        make "${BR_MIRRORS[@]}" -j"$(nproc)"
    else
        make -j"$(nproc)"
    fi
}

run_move_images() {
    echo "--> Exporting final installer assets out to Host mount..."
    cp "${BUILDROOT_BUILDER_DIR%/}"/output/images/bzImage \
        "${BUILDROOT_OUTPUT_DIR%/}"/vmlinuz-installer
    cp "${BUILDROOT_BUILDER_DIR%/}"/output/images/rootfs.cpio.* \
        "${BUILDROOT_OUTPUT_DIR%/}"/initramfs-installer.img
}

prepare_overlay() {
    # Buildroot 2026.08 check-merged requires a merged-/usr overlay: /bin
    # and /usr/sbin must be absent (or relative symlinks). Put every binary
    # under usr/bin; the target skeleton already has /bin -> usr/bin and
    # /usr/sbin -> bin.
    mkdir -p "${BUILDROOT_OVERLAY_DIR}/usr/bin" \
        "${BUILDROOT_OVERLAY_DIR}/usr/lib/installer" \
        "${BUILDROOT_OVERLAY_DIR}/usr/lib/openwrt-installer" \
        "${BUILDROOT_OVERLAY_DIR}/etc/systemd/system/multi-user.target.wants" \
        "${BUILDROOT_OVERLAY_DIR}/etc/systemd/system/getty.target.wants" \
        "${BUILDROOT_OVERLAY_DIR}/etc/systemd/system/console-getty.service.d" \
        "${BUILDROOT_OVERLAY_DIR}/etc/systemd/system/supervisord.service.d" \
        "${BUILDROOT_OVERLAY_DIR}/usr/share/vim" \
        "${BUILDROOT_OVERLAY_DIR}/etc/acpi/events"
    # Older overlay copies kept installer-bootlog.sh under usr/sbin (split
    # /usr). Move it before deleting that directory so a stale container
    # COPY still produces a legal merged-/usr overlay.
    if [ -f "${BUILDROOT_OVERLAY_DIR}/usr/sbin/installer-bootlog.sh" ] && \
       [ ! -e "${BUILDROOT_OVERLAY_DIR}/usr/bin/installer-bootlog.sh" ]; then
        mv "${BUILDROOT_OVERLAY_DIR}/usr/sbin/installer-bootlog.sh" \
            "${BUILDROOT_OVERLAY_DIR}/usr/bin/installer-bootlog.sh"
    fi
    rm -rf "${BUILDROOT_OVERLAY_DIR:?}/bin" \
        "${BUILDROOT_OVERLAY_DIR:?}/sbin" \
        "${BUILDROOT_OVERLAY_DIR:?}/usr/sbin"

    # systemd enablement: a unit is inactive until a wants/requires symlink
    # exists. Recreate these every compile so they survive overlay churn.
    ln -sfn ../installer-bootlog.service \
        "${BUILDROOT_OVERLAY_DIR}/etc/systemd/system/multi-user.target.wants/installer-bootlog.service"
    ln -sfn ../installer-wizard.service \
        "${BUILDROOT_OVERLAY_DIR}/etc/systemd/system/multi-user.target.wants/installer-wizard.service"
    ln -sfn /lib/systemd/system/console-getty.service \
        "${BUILDROOT_OVERLAY_DIR}/etc/systemd/system/getty.target.wants/console-getty.service"
    printf '%s\n\t%s\n\t%s\n\t%s\n' "Ensured systemd enablement links:" \
        "installer-bootlog.service" \
        "installer-wizard.service" \
        "console-getty.service"

    # SysV rcS scripts are unused under BR2_INIT_SYSTEMD.
    rm -f "${BUILDROOT_OVERLAY_DIR}/etc/init.d/S99installer" \
        "${BUILDROOT_OVERLAY_DIR}/etc/init.d/S20installer-bootlog"

    # GNU vim installs /usr/bin/vim. BusyBox CONFIG_VI is off so this
    # overlay name wins. On merged /usr, /bin/vi is the same inode.
    ln -sfn vim "${BUILDROOT_OVERLAY_DIR}/usr/bin/vi"
    printf '%s\n\t%s\n' "Ensured vi -> vim overlay symlink:" \
        "${BUILDROOT_OVERLAY_DIR}/usr/bin/vi -> vim"

    declare -A SCRIPTS_MAP=(
        ["${BUILDROOT_CONF_DIR%/}/iTUI/wizard.sh"]="${BUILDROOT_OVERLAY_DIR}/usr/bin/wizard.sh"
        ["${BUILDROOT_CONF_DIR%/}/automation/setup.sh"]="${BUILDROOT_OVERLAY_DIR}/usr/bin/setup.sh"
        ["${BUILDROOT_OVERLAY_DIR}/usr/bin/installer-bootlog.sh"]=""
        ["${BUILDROOT_OVERLAY_DIR}/usr/lib/installer/media.sh"]=""
        ["${BUILDROOT_OVERLAY_DIR}/usr/lib/installer/bootlog-wrapper.sh"]=""
        ["${BUILDROOT_OVERLAY_DIR}/usr/lib/openwrt-installer/generate-motd.sh"]=""
        ["${BUILDROOT_CONF_DIR%/}/post_build_script/append.sh"]=""
        ["${BUILDROOT_CONF_DIR%/}/post_build_script/set_os_release.sh"]=""
    )

    # Sourced by login shells; the executable bit is unused, but keep them
    # readable. zsh does not read /etc/profile unless zprofile/zshenv do.
    for sourced in \
        "${BUILDROOT_OVERLAY_DIR}/etc/profile" \
        "${BUILDROOT_OVERLAY_DIR}/etc/prompt.sh" \
        "${BUILDROOT_OVERLAY_DIR}/etc/zprofile" \
        "${BUILDROOT_OVERLAY_DIR}/etc/zshenv" \
        "${BUILDROOT_OVERLAY_DIR}/etc/zshrc"
    do
        if [ -f "$sourced" ]; then
            chmod 644 "$sourced"
            printf '%s%s\n' "Set shell-init permissions: --> " "$sourced"
        fi
    done

    for file in "${!SCRIPTS_MAP[@]}"; do
        dest="${SCRIPTS_MAP[$file]}"
        if [ -f "$file" ]; then
            if [ -n "$dest" ]; then
                cp "$file" "$dest"
                chmod +x "$dest"
                printf '%s\n\t%s%s%s\n' "Copied and set executable permission:" \
                    "$file" " --> " "$dest"
            else
                chmod +x "$file"
                printf '%s%s\n' "Set executable permission: --> " "$file"
            fi
        fi
    done

    cat << 'EOF' > "${BUILDROOT_OVERLAY_DIR}/etc/acpi/events/power"
event=button/power
action=/etc/acpi/power.sh
EOF

    cat << 'EOF' > "${BUILDROOT_OVERLAY_DIR}/etc/acpi/power.sh"
#!/bin/sh
sync
umount -a -r 2>/dev/null || true
exec /sbin/poweroff -f
EOF
    chmod +x "${BUILDROOT_OVERLAY_DIR}/etc/acpi/power.sh" \
        "${BUILDROOT_OVERLAY_DIR}/etc/acpi/events/power"
    chmod 644 \
        "${BUILDROOT_OVERLAY_DIR}/etc/systemd/system/installer-bootlog.service" \
        "${BUILDROOT_OVERLAY_DIR}/etc/systemd/system/installer-wizard.service"
}

if [[ "${RESUME}" -eq 1 ]]; then
    printf '%s\n' "--> Resuming compilation via --resume argument:"
    prepare_overlay
    if [[ "${RM_TARGET_FINALIZE}" -eq 1 ]]; then
        printf '\t%s\n' "--> Cleaning up target-finalize artifacts..."
        rm -rf "${BUILDROOT_BUILDER_DIR%/}/output/target" \
            "${BUILDROOT_BUILDER_DIR%/}/output/staging" \
            "${BUILDROOT_BUILDER_DIR%/}/output/images"
    else
        # Overlay is copied at target-finalize. Make skips the cpio when
        # output/images/rootfs.cpio* is already current, so drop those
        # so PAM/getty/wizard overlay edits land in the initramfs.
        rm -f "${BUILDROOT_BUILDER_DIR%/}/output/images/rootfs.cpio" \
            "${BUILDROOT_BUILDER_DIR%/}/output/images/rootfs.cpio.zst"
    fi
    run_compile_now
    run_move_images
    exit 0
fi

# When a dirclean command is requested for a
# specific app, handle it here and then exit
if [ -n "${BR_APP}" ]; then
    if [ -d "${BUILDROOT_BUILDER_DIR%/}/package/${BR_APP}" ] || \
       [ -d "${BR2_EXTERNAL%/}/${BR_APP}" ]; then
        cd "${BUILDROOT_BUILDER_DIR%/}"
        printf '%s%s\n' "Running dirclean and build for package: " "${BR_APP}"
        make "${BR_APP}-dirclean"
        run_copy_kconfig
        if [ "${BR_APP}" == "busybox" ]; then
            # Prompt the user and wait for a single keystroke
            msg_text=$(printf '%s\n\n\t%s\n\t%s\n' \
                "In order for the --rebuild-app operation for '${BR_APP}' to succeed:" \
                "1. You must exit the menuconfig TUI using the 'Exit' button." \
                "2. Choose 'YES' when prompted to save the new configuration.")
            dialog --title "BusyBox Configuration Required" --msgbox "$msg_text" 10 70
            printf '%s\n' "Refreshing and syncing configuration for busybox..."
            make "${BR_APP}-menuconfig"
            printf '%s\n' "Syncing configuration updates back to your source file..."
            make "${BR_APP}-update-config"
        fi
        make "${BR_APP}"
        exit 0
    else
        echo "Error: Package directory validation failed for '${BR_APP}'." >&2
        exit 1
    fi
fi

prepare_overlay

# 5. Load and evaluate target configurations
cd "${BUILDROOT_BUILDER_DIR%/}"

# Executes when --compiler-cache-clean is passed
if [[ "${DEL_CCACHE}" -eq 1 ]]; then
    printf '%s\n' "--> '--compiler-cache-clean' called: Cleaning up Buildroot compiler cache..."
    rm -rf "${BUILDROOT_CCACHE_DIR:?}"/.* \
        "${BUILDROOT_CCACHE_DIR:?}"/*
fi

# Copy latest configuration to buildroot source directory
mkdir -p "${BUILDROOT_CCACHE_DIR:?}"
if [ -f "${BUILDROOT_CONF_DIR%/}/setup.config" ]; then
    run_copy_kconfig
    make installer_defconfig > /dev/null 2>&1
    make olddefconfig > /dev/null 2>&1
    printf '%s%s\n' "--> Configuration from ${BUILDROOT_CONF_DIR%/}/setup.config " \
        "applied to ${BUILDROOT_BUILDER_DIR%/}/.config"
else
    printf '%s\n' "--> setup.config not detected. Standardizing on basic x86_64 topology..."
    make qemu_x86_64_defconfig
fi

# Executes when --rebuild-linux-toolchain is passed
if [[ "${REBUILD_LX_TOOLCHAIN}" -eq 1 ]]; then
    printf '%s\n\t%s\n' "Rebuilding the Linux cross-toolchain from scratch:" \
        "--> Cleaning up previous build artifacts..."
    sleep 0.25s
    make toolchain-dirclean host-gdb-dirclean glibc-dirclean
    printf '\t%s\n' "--> Cleaning up target and rootfs output directories..."
    printf '\t%s\n' "--> Cleaning old linux kernel and firmware..."
    REBUILD_LINUX=2
    RM_TARGET_FINALIZE=1
fi

# Executes when --rm-target-finalize or --rebuild-linux-toolchain are passed
if [[ "${RM_TARGET_FINALIZE}" -eq 1 ]]; then
    printf '\t%s\n' "--> Cleaning up target-finalize artifacts..."
    sleep 0.25s
    rm -rf "${BUILDROOT_BUILDER_DIR%/}/output/target" \
        "${BUILDROOT_BUILDER_DIR%/}/output/staging" \
        "${BUILDROOT_BUILDER_DIR%/}/output/images"
fi

# Executes when --rebuild-linux-firmware-clean
# or --rebuild-linux-toolchain are passed
if [[ "${REBUILD_LINUX}" -eq 2 ]]; then
    printf '%s\n\t%s\n' "Rebuilding Linux kernel from scratch:" \
        "--> Cleaning up previous Linux kernel build artifacts..."
    sleep 0.25s
    make linux-dirclean
    make linux-firmware-dirclean
    rm -rf output/target/lib/firmware \
        output/images/amdgpu output/images/radeon output/images/xe \
        output/images/i915 output/images/amd-ucode output/images/intel-ucode \
        output/images/rootfs.cpio.zst output/images/rootfs.cpio \
        output/images/bzImage output/images/rootfs.tar
fi

# Executes when --rebuild-linux-firmware,
# --rebuild-linux-firmware-clean, or
# --rebuild-toolchain are passed
if [[ "${REBUILD_LINUX}" =~ ^(1|2)$ ]]; then
    printf '\t%s\n' "--> Reconfiguring and rebuilding the Linux kernel..."
    sleep 0.25s
    make linux-reconfigure
    grep -E 'CONFIG_EXPERT|CONFIG_DRM_AMDGPU|CONFIG_SND_HDA_INTEL|CONFIG_USB_HID|CONFIG_SCSI=' \
        output/build/linux-*/.config || true
    make linux-rebuild
fi

# 6. Fire off specialized multi-threaded build pipeline pass
run_compile_now

# 7. Map final deployment components directly to your shared Host volume
cd "${BUILDROOT_BUILDER_DIR%/}"
run_move_images

exit 0
