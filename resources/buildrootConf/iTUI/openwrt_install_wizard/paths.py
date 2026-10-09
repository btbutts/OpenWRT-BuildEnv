"""Filesystem locations shared with the shell side of the installer."""

SETUP_SCRIPT = "/usr/bin/setup.sh"
MEDIA_SH = "/usr/lib/installer/media.sh"
# Written by media.sh (installer_save_identity) from installer-bootlog.service.
ID_FILE = "/run/installer-media-id"
SETUP_LOG = "/var/log/installer-setup.log"
WIZARD_LOG = "/var/log/installer-wizard-py.log"
# Created just before setup.sh is spawned. openwrt-install-wizard.sh must not
# fall back to wizard.sh (a second wipe prompt) once an install has started.
INSTALL_STARTED = "/run/installer-install-started"
PROC_CMDLINE = "/proc/cmdline"
