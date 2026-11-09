"""The extension's settings and how they are read."""

from __future__ import annotations

import os
from pathlib import Path

from . import mega

DEFAULT_FOLDER = "/tables"
DEFAULT_PORT = 8001


def default_exe() -> str:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return str(Path(base) / "MEGAcmd" / "MEGAclient.exe")


def fields() -> list[dict]:
    return [
        {"key": "mega_exe", "type": "path", "wants": "exe", "default": default_exe()},
        {"key": "mega_folder", "type": "string", "default": DEFAULT_FOLDER},
        {"key": "sync_on_start", "type": "switch", "default": True},
        {"key": "vpinfe_port", "type": "number", "default": DEFAULT_PORT, "min": 1,
         "max": 65535},
    ]


def make_check(ctx):
    def check(values: dict) -> None:
        exe = str(values.get("mega_exe") or "").strip()
        if not exe:
            raise ValueError(ctx.t("error.no_exe"))
        if not mega.is_megacmd(exe):
            raise ValueError(ctx.t("error.not_megacmd"))
    return check


def exe(ctx) -> str:
    return str(ctx.config.get("mega_exe") or default_exe()).strip()


def folder(ctx) -> str:
    text = str(ctx.config.get("mega_folder") or DEFAULT_FOLDER).strip().rstrip("/")
    if not text.startswith("/"):
        text = "/" + text
    return text or DEFAULT_FOLDER


def on_start(ctx) -> bool:
    return str(ctx.config.get("sync_on_start")).strip().lower() not in ("false", "0", "off", "no", "")


def port(ctx) -> int:
    try:
        return int(str(ctx.config.get("vpinfe_port") or DEFAULT_PORT).strip())
    except ValueError:
        return DEFAULT_PORT
