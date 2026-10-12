#!/bin/bash
set -e
# Disable job control and certain shell options
# for compatibility with non-interactive shells
set +m 2>/dev/null || true
unsetopt MONITOR NOTIFY 2>/dev/null || true

: "${BUILDER_ROOT_DIR:=/builder}"
: "${OPENWRT_BUILDER_DIR:=/builder/OpenWRT-ImageBuilder}"
: "${WORKSPACE_DIR:=/builder/workspace}"

BOLD=$'\033[1m'
RESET=$'\033[0m'
CLEAR_TO_EOL=$'\033[K'
COL_WIDTH=62

print_dots() {
    dots=""
    while kill -0 "$task_pid" 2>/dev/null; do
        case "$dots" in
            "")  dots="." ;;
            ".") dots=".." ;;
            *)   dots="..." ;;
        esac
        #printf '\r%-62s' "--> Running: ${label}${dots}"
        printf '\r%s%-*s' "${CLEAR_TO_EOL}" "$COL_WIDTH" "--> Running: ${label}${dots}"
        sleep 0.5
    done

    task_status=0
    wait "$task_pid" || task_status=$?

    printf '\r%s%-*s' "${CLEAR_TO_EOL}" "$COL_WIDTH" "--> Running: ${label}..."
}

prepare_sshd() {
    # Runtime privilege-separation dir + host keys
    sudo mkdir -p /run/sshd
    sudo chmod 0755 /run/sshd
    sudo ssh-keygen -A
}

start_sshd() {
    # Start the SSH service
    sudo rm -f /var/run/sshd.pid
    sudo /usr/sbin/sshd
}

build_openwrt_fs() {
    local vanilla_rootfs vanilla_kernel
    vanilla_rootfs=$(find "${OPENWRT_BUILDER_DIR%/}/bin/targets/x86/64/" -name "openwrt-*-rootfs.tar.gz" | head -n 1)
    vanilla_kernel=$(find "${OPENWRT_BUILDER_DIR%/}/bin/targets/x86/64/" -name "openwrt-*-kernel.bin" | head -n 1)

    if [ -f "$vanilla_kernel" ] && [ -f "$vanilla_rootfs" ]; then
        printf '%s\n%s\n%s\n' \
            "Found vanilla kernel: $vanilla_kernel" \
            "Found vanilla rootfs: $vanilla_rootfs" \
            "Repackaging only with \"--package-only\" option"
        ./buildOpenWRTimages.sh --package-only
        return 0
    else
        printf '%s\n%s\n' \
            "Either the vanilla kernel or rootfs were not found!" \
            "Building OpenWRT images from existing sources"
        ./buildOpenWRTimages.sh
    fi
}

copy_ssh_keys() {
    local SSHD_KEYS_DIR="/etc/ssh" ssh_keys=() \
        key_file filename dest_file
    
    # Create the destination directory if it doesn't exist
    mkdir -p "${WORKSPACE_DIR%/}/.ssh_keys"

    # Find all keys securely and populate an array
    if [ -d "$SSHD_KEYS_DIR" ]; then
        while IFS= read -r -d '' key_file; do
            ssh_keys+=("$key_file")
        done < <(find "$SSHD_KEYS_DIR" -maxdepth 1 -name "*ssh_host_*_key*" -print0)
    fi

    # Copy discovered keys to host bind mount
    for key_file in "${ssh_keys[@]}"; do
        if [ -f "$key_file" ]; then

            filename=$(basename "$key_file")
            dest_file="${WORKSPACE_DIR%/}/.ssh_keys/$filename"
            printf '\t%s%s%s\n' \
                "--> Copying SSH host key: " "$filename" " to staging"
            sudo cp -p "$key_file" "$dest_file"
            if [[ "$filename" == *.pub ]]; then
                sudo chmod 644 "$dest_file"
            else
                sudo chmod 600 "$dest_file"
            fi

        fi
    done
}


#    "/builder/compileBuildroot.sh|Compile Installer Media Platform"
STARTUP_SEQUENCE=(
    "${BUILDER_ROOT_DIR%/}/extractImageBuilder.sh|Setup OpenWRT Image Builder"
    "${BUILDER_ROOT_DIR%/}/getBuildroot.sh|Setup Buildroot Environment"
    "build_openwrt_fs|Verifying or Preparing OpenWRT Filesystem"
    "copy_ssh_keys|Backing up SSH Keys if available"
    "prepare_sshd|Preparing to start OpenSSH Daemon"
    "start_sshd|Starting OpenSSH Daemon"
)

# Perform pre-startup tasks
echo "Running pre-startup tasks..."

for tasks in "${STARTUP_SEQUENCE[@]}"; do
    task="${tasks%%|*}"
    label="${tasks#*|}"

    # Generate log file for script tasks
    if [ -f "$task" ]; then
        filename="$(basename -- "$task")"
        log_file="/var/log/${filename%.*}.log"
        sudo install -m 644 -o builder -g builder /dev/null "$log_file"
    else
        log_file="/dev/null"
    fi

    # Output entrypoint step to console
    printf '%-*s\r' "$COL_WIDTH" "--> Running: $label"
    "$task" >"$log_file" 2>&1 &
    task_pid=$!
    print_dots
    if [ "$task_status" -eq 0 ]; then
        printf '%s%s%s\n' "$BOLD" 'DONE!' "$RESET"
    else
        printf '%s%s%s\n' "$BOLD" 'FAIL!' "$RESET"
        # We print log_file only for script tasks
        cat "$log_file"
    fi
done

# Pass PID 1
exec "$@"
