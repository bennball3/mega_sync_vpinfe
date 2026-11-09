"""What the person sees: the Sync Now action, the MEGA Sync list and the Needs You rows."""

from __future__ import annotations

from . import mega, settings


def _size(count: int) -> str:
    return f"{count / (1024 * 1024):.1f} MB"


def _masked(email: str) -> str:
    """The account shown without its full address: the first letter, then the domain."""
    name, _, domain = email.partition("@")
    if not name or not domain:
        return email
    return f"{name[0]}***@{domain}"


def install(ctx, sync) -> None:
    def status_rows(fresh: bool = False) -> list[list[str]]:
        state = sync.status(fresh)
        return [
            [ctx.t("status.installed"), ctx.t("yes" if state["installed"] else "no")],
            [ctx.t("status.version"), state["version"] or "-"],
            [ctx.t("status.connected"), ctx.t("yes" if state["connected"] else "no")],
            [ctx.t("status.account"), _masked(state["account"]) or "-"],
        ]

    class SyncNow:
        def ask(self, step):
            state = sync.status(True)
            answer = {"help": ctx.t("action.sync.help"), "summary": status_rows(),
                      "confirm": ctx.t("action.sync.confirm")}
            if not state["connected"]:
                answer["ready"] = False
                answer["reason"] = ctx.t("status.cannot_sync")
            return answer

        def check(self, values):
            return self.ask("")

        def run(self, values):
            job = sync.start()
            if job is None:
                return ctx.t("action.sync.already")
            return {"job_id": job.id}

    ctx.ui.action("sync", SyncNow())

    def known_games() -> dict[str, dict]:
        return {one["folder_name"].lower(): one for one in ctx.games.existing()}

    def rows():
        known = known_games()
        out = []
        for one in sync.rows():
            stem = one["name"][:-4]
            game = known.get(ctx.games.folder_name_for(stem).lower()) or {}
            vps = game.get("vps_id")
            state = one["state"]
            if state == "waiting" and sync.results.get(one["name"]):
                state = sync.results[one["name"]]
            kept = sync.history.get(one["handle"])
            out.append({
                "id": one["handle"], "name": stem, "size": _size(one["size"]), "date": kept.get("at") or one.get("date", ""),
                "state": state,
                "matched": (ctx.t("yes") if vps else ctx.t("no")) if state == "imported"
                else "",
                "game": game.get("game_id", ""),
                "error": sync.errors.get(one["name"]) or kept.get("error", ""),
            })
        return out

    def status():
        state = sync.status()
        if not state["installed"]:
            return ctx.t("status.line.not_installed")
        if not state["connected"]:
            return ctx.t("status.line.not_connected", version=state["version"])
        return ctx.t("status.line.ok", version=state["version"], account=_masked(state["account"]))

    ctx.ui.list(
        "tables", rows, area="library", icon="cloud", status=status, add="sync",
        columns=[
            {"field": "name", "header": "", "kind": "text", "identifier": True,
             "under": ["error"]},
            {"field": "size", "header": "", "kind": "text"},
            {"field": "date", "header": "", "kind": "date"},
            {"field": "state", "header": "", "kind": "state",
             "states": {"waiting": {"tier": "warn"}, "imported": {"tier": "on"},
                        "rejected": {"tier": "off"}}},
            {"field": "matched", "header": "", "kind": "text"},
            {"field": "game", "header": "", "kind": "game", "keys": "vpinfe",
             "name_from": "name"},
            {"field": "error", "header": "", "kind": "text"},
        ])

    def needs():
        state = sync.status()
        if not state["installed"]:
            return [{"kind": "not_installed", "ids": ["mega"]}]
        if not state["connected"]:
            return [{"kind": "not_connected", "ids": ["mega"]}]
        return []

    ctx.ui.needs({"not_installed": {"action": "sync", "tone": "danger"},
                  "not_connected": {"action": "sync"}}, needs)
