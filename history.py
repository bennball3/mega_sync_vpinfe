"""What this extension has done to each zip, kept in `cache/history.json` beside the code.

It is a record for display only (when a zip was imported or rejected, and the last error). The
MEGA folders stay the source of truth for what is still to do, so losing this file loses
nothing but those times.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("vpinfe.ext.mega_sync_vpinfe")

PATH = Path(__file__).parent / "cache" / "history.json"


class History:
    def __init__(self, path: Path = PATH) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._rows: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            logger.warning("Could not read %s; starting without history", self._path.name)
            return {}
        return {str(k): v for k, v in data.items() if isinstance(v, dict)} \
            if isinstance(data, dict) else {}

    def get(self, handle: str) -> dict:
        with self._lock:
            return dict(self._rows.get(handle, {}))

    def done(self, handle: str, name: str, outcome: str) -> None:
        """The zip was imported or rejected: record when, and clear any earlier error."""
        self._put(handle, {"name": name, "outcome": outcome, "at": _now(), "error": ""})

    def failed(self, handle: str, name: str, error: str) -> None:
        """The zip failed this run. An earlier import time is kept."""
        with self._lock:
            before = self._rows.get(handle, {})
        self._put(handle, {"name": name, "outcome": before.get("outcome", ""),
                           "at": before.get("at", ""), "error": error,
                           "failed_at": _now()})

    def _put(self, handle: str, row: dict) -> None:
        with self._lock:
            self._rows[handle] = row
            self._write()

    def _write(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temp = self._path.with_suffix(".tmp")
            temp.write_text(json.dumps(self._rows, indent=2), encoding="utf-8")
            os.replace(temp, self._path)
        except OSError:
            logger.warning("Could not write %s", self._path.name, exc_info=True)


def _now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")
