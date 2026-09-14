#!/bin/bash
set -e
# Disable job control and certain shell options
# for compatibility with non-interactive shells
set +m 2>/dev/null || true
unsetopt MONITOR NOTIFY 2>/dev/null || true

BOLD=$'\033[1m'
RESET=$'\033[0m'

print_dots() {
    dots=""
    while kill -0 "$task_pid" 2>/dev/null; do
        case "$dots" in
            "")  dots="." ;;
            ".") dots=".." ;;
            *)   dots="..." ;;
        esac
        printf '\r%-50s' "--> Running: ${label}${dots}"
        sleep 0.5
    done

    task_status=0
    wait "$task_pid" || task_status=$?

    printf '\r%-50s' "--> Running: ${label}..."
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

#    "/builder/compileBuildroot.sh|Compile Installer Media Platform"
STARTUP_SEQUENCE=(
    "/builder/extractImageBuilder.sh|Setup OpenWRT Image Builder"
    "/builder/getBuildroot.sh|Setup Buildroot Environment"
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
    printf '%-50s' "--> Running: $label"
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
