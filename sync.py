"""The sync job. The MEGA folder is the record of what is still to do: what is left in it is
waiting. `cache/history.json` keeps every imported or rejected zip, so the list keeps showing
them after they are deleted from MEGA. This run's results and errors are held in memory."""

from __future__ import annotations

import logging
import shutil
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from . import mega, settings
from .history import History

logger = logging.getLogger("vpinfe.ext.mega_sync_vpinfe")

CACHE = Path(__file__).parent / "cache" / "downloads"
STATUS_TTL = 20.0
ROWS_TTL = 20.0


class Sync:
    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self.lock = threading.Lock()
        self.results: dict[str, str] = {}  # zip name -> "imported" | "rejected"
        self.errors: dict[str, str] = {}  # zip name -> error text, this run only
        self.history = History()
        self._status: tuple[float, dict] | None = None
        self._rows: tuple[float, list[dict]] | None = None

    # --- cached reads for the screens ------------------------------------------------

    def status(self, fresh: bool = False) -> dict:
        held = self._status
        if not fresh and held and time.time() - held[0] < STATUS_TTL:
            return held[1]
        value = mega.status(settings.exe(self.ctx))
        self._status = (time.time(), value)
        return value

    def rows(self) -> list[dict]:
        held = self._rows
        if held and time.time() - held[0] < ROWS_TTL:
            return held[1]
        exe, base = settings.exe(self.ctx), settings.folder(self.ctx)
        found = []
        for state, folder in (("waiting", base), ("imported", f"{base}/imported"),
                              ("rejected", f"{base}/rejected")):
            try:
                found += [{**one, "state": state} for one in mega.list_zips(exe, folder)]
            except mega.MegaError as exc:
                logger.warning("Could not list %s: %s", folder, exc)
        handles = {one["handle"] for one in found}
        names = {one["name"].lower() for one in found}
        for handle, kept in self.history.all().items():
            outcome, name = kept.get("outcome"), kept.get("name", "")
            if outcome not in ("imported", "rejected") or not name:
                continue
            if handle in handles or name.lower() in names:
                continue  # still in MEGA, or the same zip was uploaded again
            names.add(name.lower())
            found.append({"handle": handle, "name": name, "size": kept.get("size") or 0,
                          "date": kept.get("at", ""), "state": outcome, "gone": True})
        self._rows = (time.time(), found)
        return found

    def forget(self) -> None:
        self._rows = None
        self._status = None

    def running(self) -> bool:
        return self.lock.locked()

    # --- the job ---------------------------------------------------------------------

    def start(self):
        if self.lock.locked():
            return None
        return self.ctx.jobs.submit("sync", self.work, stoppable=True, keep_result=True)

    def work(self, job) -> dict:
        if not self.lock.acquire(blocking=False):
            return {"skipped": True}
        try:
            return self._work(job)
        finally:
            self.lock.release()
            self.forget()

    def _work(self, job) -> dict:
        ctx = self.ctx
        exe, base = settings.exe(ctx), settings.folder(ctx)
        state = mega.status(exe)
        if not state["connected"]:
            logger.warning("MEGAcmd is not installed or not logged in; nothing to sync")
            job.problems += 1
            return {"connected": False}
        self.errors.clear()
        try:
            zips = mega.list_zips(exe, base)
        except mega.MegaError as exc:
            logger.warning("Could not list %s: %s", base, exc)
            job.problems += 1
            return {"error": str(exc)}
        existing = {one["folder_name"].lower() for one in ctx.games.existing()}
        todo = []
        for one in zips:
            stem = PurePosixPath(one["name"]).stem
            if ctx.games.folder_name_for(stem).lower() in existing:
                self._move(job, exe, one, f"{base}/rejected", "rejected")
            else:
                todo.append(one)
        done = 0
        for index, one in enumerate(todo):
            if job.halt.is_set():
                job.stopped = True
                break
            job.progress(index, len(todo), one["name"])
            try:
                self._import(job, exe, base, one)
                done += 1
            except Exception as exc:  # one bad zip never stops the next
                logger.warning("Could not import %s: %s", one["name"], exc)
                self.errors[one["name"]] = str(exc) if isinstance(
                    exc, mega.MegaError) else ctx.why(exc)
                self.history.failed(one["handle"], one["name"], self.errors[one["name"]])
                job.problems += 1
        job.progress(len(todo), len(todo), "")
        if done:
            self._refresh_library(job)
        return {"imported": done,
                "rejected": sum(1 for v in self.results.values() if v == "rejected"),
                "failed": len(self.errors)}

    def _refresh_library(self, job) -> None:
        """Core registers a new game's table file only in a library refresh, which an import
        does not start. Ask for one over the local API, where this device needs no sign-in."""
        url = f"http://127.0.0.1:{settings.port(self.ctx)}/api/v1/library/refresh"
        for attempt in range(5):
            try:
                request = urllib.request.Request(url, data=b"", method="POST")
                with urllib.request.urlopen(request, timeout=30):
                    return
            except urllib.error.HTTPError as exc:
                if exc.code != 409:  # 409: a scan is running; try again shortly
                    logger.warning("The library refresh was refused (%s)", exc.code)
                    job.problems += 1
                    return
            except OSError as exc:
                logger.warning("Could not ask VPinFE to refresh the library: %s", exc)
                job.problems += 1
                return
            time.sleep(10)
        logger.warning("The library refresh stayed busy; the tables register at the next one")
        job.problems += 1

    def _move(self, job, exe: str, one: dict, folder: str, outcome: str) -> None:
        """Move a zip once, then once more; a zip that will not move stays where it is."""
        for attempt in range(2):
            try:
                mega.move(exe, one["handle"], one["name"], folder)
                self.results[one["name"]] = outcome
                self.history.done(one["handle"], one["name"], outcome, one.get("size") or 0)
                return
            except mega.MegaError as exc:
                if attempt:
                    logger.warning("Could not move %s to %s: %s", one["name"], folder, exc)
                    self.errors[one["name"]] = str(exc)
                    self.history.failed(one["handle"], one["name"], str(exc))
                    job.problems += 1

    def _import(self, job, exe: str, base: str, one: dict) -> None:
        ctx = self.ctx
        stem = PurePosixPath(one["name"]).stem
        work = CACHE / one["handle"]
        shutil.rmtree(work, ignore_errors=True)
        try:
            mega.download(exe, one["handle"], work)
            zips = [p for p in work.iterdir() if p.suffix.lower() == ".zip"]
            if len(zips) != 1:
                raise mega.MegaError(ctx.t("error.download_missing"))
            path = zips[0]
            if one["size"] and path.stat().st_size != one["size"]:
                raise mega.MegaError(ctx.t("error.size_mismatch"))
            with zipfile.ZipFile(path) as archive:
                if archive.testzip() is not None:
                    raise mega.MegaError(ctx.t("error.corrupt"))
            ctx.files.set_roots([str(CACHE)])
            plan = ctx.uploads.plan(path, allow_new_game=True, new_game_dir_name=stem)
            report = ctx.uploads.execute(
                path, allow_new_game=True, new_game_dir_name=stem,
                selected=[item["index"] for item in plan["items"]])
            self.results[one["name"]] = "imported"
            self._copy_left_out(path, report)
            self._move(job, exe, one, f"{base}/imported", "imported")
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _copy_left_out(self, archive_path: Path, report: dict) -> None:
        """Files core did not claim go into the game folder at their bundle paths, minus the
        zip's top folder. Nothing is overwritten and nothing may land outside the folder."""
        game_dir = report.get("game_dir")
        left = report.get("not_written") or []
        if not game_dir or not left:
            return
        root = Path(game_dir).resolve()
        with zipfile.ZipFile(archive_path) as archive:
            names = set(archive.namelist())
            for member in left:
                if member not in names or member.endswith("/"):
                    continue
                parts = PurePosixPath(member).parts
                if len(parts) < 2:
                    continue
                relative = PurePosixPath(*parts[1:])
                text = str(relative)
                if relative.is_absolute() or ".." in relative.parts or "\\" in text \
                        or ":" in text:
                    continue
                target = (root / Path(*relative.parts)).resolve()
                if root not in target.parents or target.exists():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
