"""Run setup.sh for a confirmed plan and handle what happens afterwards."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

from . import paths
from .ui import Prompt, YesNoLabels

if TYPE_CHECKING:
    from .plan import InstallPlan
    from .storage import InstallerMedia
    from .ui import WizardUI

TITLE = "Installing OpenWRT"


def write_selection_log(
    plan: InstallPlan,
    media: InstallerMedia | None,
    path: str = paths.SETUP_LOG,
) -> None:
    """Write the same selections header wizard.sh writes; setup.sh appends to it."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "===== openwrt_install_wizard selections =====",
        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        f"INSTALLER_DISK={media.disk if media else 'unknown'}",
        f"DISKS={' '.join(plan.disks)}",
        f"DISK_COUNT={len(plan.disks)}",
        f"RAID_LEVEL={plan.raid_level}",
        f"ROOT_PART_END={plan.root_part_end or 'MAX'}",
        f"BITMAP={plan.bitmap_mode}",
    ]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def setup_env() -> dict[str, str]:
    """Return the environment for setup.sh: it must not ask its own questions."""
    env = dict(os.environ)
    # setup.sh skips its own dialog prompt and exits; the reboot-or-shell
    # question is asked here so it matches the wizard's look.
    env["INSTALLER_NONINTERACTIVE"] = "1"
    return env


def run_install(ui: WizardUI, plan: InstallPlan, media: InstallerMedia | None) -> None:
    """Run setup.sh with a live log, then offer reboot or a shell."""
    plan.validate()
    write_selection_log(plan, media)
    # From here on a crash must not fall back to wizard.sh (see the launcher).
    marker = Path(paths.INSTALL_STARTED)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()

    rc, tail = ui.run_command([paths.SETUP_SCRIPT, *plan.to_setup_argv()], setup_env(), TITLE)

    if rc != 0:
        ui.msgbox(
            Prompt(
                f"The installation FAILED (exit code {rc}).\n\n"
                + "\n".join(tail)
                + f"\n\nFull log: {paths.SETUP_LOG}\n"
                "A root shell opens when you close this message.",
                "Installation failed",
            ),
        )
        return

    reboot = ui.yesno(
        Prompt(
            "Installation successfully completed!\n"
            "Remove your installer media.\n\n"
            "Reboot the system now, or open an emergency maintenance shell?",
            "Done",
        ),
        YesNoLabels(yes="Reboot", no="Shell"),
    )
    if reboot:
        subprocess.run(["/sbin/reboot", "-f"], check=False)
