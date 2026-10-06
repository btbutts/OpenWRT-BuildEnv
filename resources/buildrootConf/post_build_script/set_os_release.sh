#!/bin/bash
# set_os_release.sh - Buildroot post-build script
set -euo pipefail

# Buildroot invokes: script TARGET_DIR [POST_SCRIPT_ARGS]
TARGET="$1"

# systemd/os-release: one vendor file at /usr/lib/os-release.
# /etc/os-release is a symlink to it (Buildroot target-finalize does
# the same). Drop /etc/os-release first so a regular file there cannot
# shadow /usr/lib. Then overwrite the vendor file and recreate the link.
OS_RELEASE="${TARGET}/usr/lib/os-release"

BR_RELEASE_NAME="${BR_RELEASE_NAME:-OpenWRT-Installer}"
BR_REPO_URL="${BR_REPO_URL:-https://github.com/btbutts/OpenWRT-BuildEnv/}"

# BR2_VERSION is exported from Buildroot's Makefile. Kernel version is a
# .config string and is not exported into this script's environment;
# BR2_CONFIG (path to .config) is exported.
BR_VERSION="${BR2_VERSION:-2026.08}"
KERNEL_VER="${BR2_LINUX_KERNEL_VERSION:-}"
if [ -z "${KERNEL_VER}" ] && [ -n "${BR2_CONFIG:-}" ] && [ -f "${BR2_CONFIG}" ]; then
    KERNEL_VER=$(sed -n 's/^BR2_LINUX_KERNEL_VERSION="\(.*\)"$/\1/p' "${BR2_CONFIG}")
fi
if [ -z "${KERNEL_VER}" ]; then
    printf '%s\n' "set_os_release.sh: could not read BR2_LINUX_KERNEL_VERSION from BR2_CONFIG=${BR2_CONFIG:-unset}" >&2
    exit 1
fi

NAME="${BR_RELEASE_NAME} GNU/Linux"
ID=$(printf '%s' "${BR_RELEASE_NAME}" | tr '[:upper:]' '[:lower:]')
PRETTY_NAME="${NAME} ${KERNEL_VER}"
BUILD_ID="buildroot-${BR_VERSION}"

REPO_BASE="${BR_REPO_URL%/}"
HOME_URL="${REPO_BASE}/"
BUG_REPORT_URL="${REPO_BASE}/issues"

mkdir -p "$(dirname "${OS_RELEASE}")" "${TARGET}/etc"
rm -f "${TARGET}/etc/os-release"
tmp="${OS_RELEASE}.tmp.$$"
cat > "${tmp}" << EOF
NAME="${NAME}"
VERSION="${KERNEL_VER}"
ID=${ID}
ID_LIKE=buildroot
VERSION_ID="${KERNEL_VER}"
PRETTY_NAME="${PRETTY_NAME}"
BUILD_ID="${BUILD_ID}"
ANSI_COLOR="1;34"
HOME_URL="${HOME_URL}"
BUG_REPORT_URL="${BUG_REPORT_URL}"
EOF
mv -f "${tmp}" "${OS_RELEASE}"
ln -sfn ../usr/lib/os-release "${TARGET}/etc/os-release"

printf '%s\n' "Generated ${OS_RELEASE} for ${NAME} (${KERNEL_VER})"
