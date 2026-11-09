"""MEGA Table Sync: installs table bundles (zips) found in a MEGA folder.

At startup the extension lists the zips in the MEGA folder, hands each new one to VPinFE's own
import (which matches it and fetches artwork), and moves it to `imported` or `rejected` in MEGA.
The MEGA folder is the only record of what has been done.
"""

import logging
import sys
import threading

from . import screens, settings
from .sync import Sync

START_DELAY = 15.0

logger = logging.getLogger("vpinfe.ext.mega_sync_vpinfe")


def register(ctx):
    ctx.ui.settings(settings.fields(), check=settings.make_check(ctx))
    sync = Sync(ctx)
    screens.install(ctx, sync)

    if "--check-extension" in sys.argv:
        return

    def start():
        try:
            if settings.on_start(ctx):
                sync.start()
        except Exception:
            logger.exception("The startup sync could not start")

    timer = threading.Timer(START_DELAY, start)
    timer.daemon = True
    timer.start()
