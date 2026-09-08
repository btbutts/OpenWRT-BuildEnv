#!/bin/bash
set -e

# Ensure runtime privilege separation directory
# exists with correct permissions
sudo mkdir -p /run/sshd
sudo chmod 0755 /run/sshd

# Gen SSH Keys
sudo ssh-keygen -A

# Clear stale PID from prior runs
sudo rm -f /var/run/sshd.pid

# Start the SSH service
sudo /usr/sbin/sshd

# Pass PID 1
exec "$@"
