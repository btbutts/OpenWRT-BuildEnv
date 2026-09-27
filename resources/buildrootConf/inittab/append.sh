#!/bin/bash
set -e
TARGET="$1"
INITTAB="${TARGET}/etc/inittab"

if [ -f "${INITTAB}" ] && ! grep -q 'ctrlaltdel' "${INITTAB}"; then
    printf '\n::ctrlaltdel:/sbin/reboot -f\n' >> "${INITTAB}"
fi
