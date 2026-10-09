"""OpenWRT bare-metal installer wizard (prompt_toolkit TUI).

Collects the disk / RAID / size / bitmap answers that wizard.sh collects with
``dialog``, then runs /usr/bin/setup.sh as a subprocess with the same argument
contract. Launched by /usr/bin/openwrt-install-wizard.sh as
``python3 -m openwrt_install_wizard.main`` with PYTHONPATH=/usr/lib/installer.
"""

__version__ = "1.0.0"

# Exit code seen by openwrt-install-wizard.sh.
# 0        : finished or cancelled; systemd then starts the root shell.
# non-zero : the wizard crashed (an uncaught exception exits with 1); the
#            launcher falls back to wizard.sh.
EXIT_OK = 0
