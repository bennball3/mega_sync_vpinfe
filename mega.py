"""A stateless wrapper over MEGAcmd's `MEGAclient`. Every call is a short-lived process."""

from __future__ import annotations

import re
import subprocess
import time
from datetime import datetime
from pathlib import Path, PurePosixPath

CREATE_NO_WINDOW = 0x08000000
SHORT = 60
LONG = 4 * 3600
NOISE = ("MEGAcmd Server not running", "Initiating in the background")
NOT_FOUND = 53

_LS = re.compile(r"^\S+\s+\S+\s+(\d+|-)\s+(\d{2}\w{3}\d{4}\s+\d\d:\d\d:\d\d)\s+H:(\S+)\s+(.+?)\s*$")


class MegaError(Exception):
    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


def _when(text: str) -> str:
    """MEGA's `09Nov2026 11:58:08` as ISO text, or "" where it does not read."""
    try:
        return datetime.strptime(text, "%d%b%Y %H:%M:%S").isoformat(sep=" ")
    except ValueError:
        return ""


def _run(exe: str, args: list[str], timeout: float = SHORT) -> tuple[int, str]:
    try:
        done = subprocess.run([exe, *args], capture_output=True, stdin=subprocess.DEVNULL,
                              timeout=timeout, creationflags=CREATE_NO_WINDOW,
                              text=True, encoding="utf-8", errors="replace")
    except FileNotFoundError as exc:
        raise MegaError(f"MEGAcmd not found at {exe}") from exc
    except OSError as exc:
        raise MegaError(str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise MegaError("MEGAcmd timed out") from exc
    text = "\n".join(line for line in (done.stdout + "\n" + done.stderr).splitlines()
                     if line.strip() and not any(one in line for one in NOISE))
    return done.returncode, text


def is_megacmd(exe: str) -> bool:
    if not exe or not Path(exe).is_file():
        return False
    try:
        code, text = _run(exe, ["version"], 30)
    except MegaError:
        return False
    return code == 0 and "MEGAcmd version" in text


def status(exe: str) -> dict:
    """installed, version, connected, account."""
    out = {"installed": False, "version": "", "connected": False, "account": ""}
    try:
        code, text = _run(exe, ["version"], 30)
    except MegaError:
        return out
    match = re.search(r"MEGAcmd version:\s*(\S+)", text)
    if code != 0 or not match:
        return out
    out["installed"], out["version"] = True, match.group(1)
    for attempt in range(3):
        try:
            _, text = _run(exe, ["whoami"], 30)
        except MegaError:
            break
        match = re.search(r"Account e-mail:\s*(\S+)", text)
        if match:
            out["connected"], out["account"] = True, match.group(1)
            break
        if attempt < 2:
            time.sleep(3)
    return out


def list_zips(exe: str, folder: str) -> list[dict]:
    """The zips directly in `folder`: name, handle, size. Empty where the folder is missing."""
    code, text = _run(exe, ["ls", "-l", "--show-handles", folder])
    if code == NOT_FOUND:
        return []
    if code != 0:
        raise MegaError(text.strip() or f"ls failed ({code})", code)
    found = []
    for line in text.splitlines():
        match = _LS.match(line)
        if match and match.group(4).lower().endswith(".zip") and match.group(1) != "-":
            found.append({"name": match.group(4), "handle": match.group(3),
                          "size": int(match.group(1)), "date": _when(match.group(2))})
    return found


def download(exe: str, handle: str, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    code, text = _run(exe, ["get", "--ignore-quota-warn", f"H:{handle}", str(dest) + "\\"], LONG)
    if code != 0:
        raise MegaError(text.strip() or f"get failed ({code})", code)


def move(exe: str, handle: str, name: str, folder: str) -> str:
    """Move a file into `folder`, never over a file of the same name. Answers the new name."""
    # MEGAcmd exits non-zero with "Folder already exists" even for `mkdir -p`; the move
    # below is what decides whether the folder is usable.
    _run(exe, ["mkdir", "-p", folder])
    try:
        taken = {one["name"].lower() for one in list_zips(exe, folder)}
    except MegaError:
        taken = set()
    target = name
    if name.lower() in taken:
        stem = PurePosixPath(name).stem
        target = f"{stem} {datetime.now():%Y-%m-%d %H%M%S}.zip"
    dest = f"{folder}/" if target == name else f"{folder}/{target}"
    code, text = _run(exe, ["mv", f"H:{handle}", dest])
    if code != 0:
        raise MegaError(text.strip() or f"mv failed ({code})", code)
    return target
