"""Entry point: ``PYTHONPATH=/usr/lib/installer python3 -m openwrt_install_wizard.main``.

Exit codes (see the package ``__init__``): 0 = finished or cancelled; an uncaught
exception is logged and exits non-zero, which makes the launcher fall back to wizard.sh.
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

from . import EXIT_OK, paths
from .console import ConsoleSession
from .dialogs import Dialogs
from .errors import WizardCancelledError
from .flow import collect_plan
from .runner import run_install
from .storage import find_media, list_targets

if TYPE_CHECKING:
    from types import TracebackType

log = logging.getLogger("openwrt_install_wizard")


def _setup_logging() -> None:
    """Log to the wizard log file, or stay quiet when /var/log is not writable."""
    try:
        logging.basicConfig(
            filename=paths.WIZARD_LOG,
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
    except OSError:
        logging.basicConfig(level=logging.CRITICAL)


def run() -> None:
    """Identify the boot media, ask the questions and run the install."""
    with ConsoleSession() as console:
        ui = Dialogs(console)
        media, devices = find_media()
        log.info("installer media: %s", media)
        targets = list_targets(devices, media)
        log.info("target disks: %s", [d.name for d in targets])
        plan = collect_plan(ui, targets, media)
        run_install(ui, plan, media)


def _log_uncaught(
    exc_type: type[BaseException],
    exc: BaseException,
    traceback: TracebackType | None,
) -> None:
    """Record an uncaught exception in the wizard log, then print it as usual."""
    log.critical("wizard crashed", exc_info=(exc_type, exc, traceback))
    sys.__excepthook__(exc_type, exc, traceback)


def main() -> int:
    """Run the wizard; return 0 when it finished or the user cancelled."""
    _setup_logging()
    # ConsoleSession has restored the terminal by the time this hook prints.
    sys.excepthook = _log_uncaught
    try:
        run()
    except (WizardCancelledError, KeyboardInterrupt):
        log.info("cancelled by user")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
