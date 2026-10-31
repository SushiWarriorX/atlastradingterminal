from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable, Protocol

from ..db import DB, now as iso_now
from ..scanner import engine as scan_engine
from ..scanner.bars import BarSource
from ..scanner.presets import ALIASES, PRESETS
from ..scanner.rules import ScanSpec
from ..service import MarketService
from .messages import title
from .observe import observe
from .rules import ScanRule, decide, parse_rule

log = logging.getLogger("atlas.alerts")


class Notifier(Protocol):
    """Delivery channel. Only in-app exists today. Email/Telegram/Discord would implement this
    (and read their secrets from backend env); they are intentionally not built yet."""
    name: str

    async def deliver(self, event: dict, rule) -> str: ...


class InAppNotifier:
    name = "in_app"

    async def deliver(self, event: dict, rule) -> str:
        return "in_app:delivered"  # the row itself is the notification; the UI polls and shows it


class AlertManager:
    def __init__(self, db: DB, svc: MarketService, bars: BarSource, universe_loader: Callable[[str], Awaitable[list[str]]],
                 notifiers: list[Notifier] | None = None):
        self.db, self.svc, self.bars, self.load_universe = db, svc, bars, universe_loader
        self.notifiers = notifiers or [InAppNotifier()]
        self._lock = asyncio.Lock()

    # --- CRUD -------------------------------------------------------------
    def _row(self, r) -> dict:
        return {"id": r["id"], "name": r["name"], "kind": r["kind"], "rule": json.loads(r["rule"]), "version": r["version"],
                "enabled": bool(r["enabled"]), "state": json.loads(r["state"]), "created_at": r["created_at"], "updated_at": r["updated_at"]}

    def list(self) -> list[dict]:
        return [self._row(r) for r in self.db.q("SELECT * FROM alerts ORDER BY id")]

    def get(self, aid: int) -> dict | None:
        r = self.db.q("SELECT * FROM alerts WHERE id=?", (aid,))
        return self._row(r[0]) if r else None

    def create(self, rule_data: dict) -> dict:
        rule = parse_rule(rule_data)
        t = now = iso_now()
        aid = self.db.x("INSERT INTO alerts(name,kind,rule,version,enabled,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                        (title(rule), rule.kind, rule.model_dump_json(), 1, 1, "{}", t, now))
        self.db.audit("user", "alert_create", {"id": aid, "kind": rule.kind})
        return self.get(aid)

    def update(self, aid: int, rule_data: dict) -> dict | None:
        if self.get(aid) is None:
            return None
        rule = parse_rule(rule_data)
        self.db.x("UPDATE alerts SET name=?, kind=?, rule=?, version=version+1, state='{}', updated_at=? WHERE id=?",
                  (title(rule), rule.kind, rule.model_dump_json(), iso_now(), aid))   # new version re-baselines
        self.db.audit("user", "alert_update", {"id": aid})
        return self.get(aid)

    def set_enabled(self, aid: int, enabled: bool) -> dict | None:
        if self.get(aid) is None:
            return None
        self.db.x("UPDATE alerts SET enabled=?, state=CASE WHEN ?=1 THEN '{}' ELSE state END, updated_at=? WHERE id=?",
                  (int(enabled), int(enabled), iso_now(), aid))   # re-enabling re-baselines: no stale edge
        return self.get(aid)

    def delete(self, aid: int) -> None:
        self.db.x("DELETE FROM alerts WHERE id=?", (aid,))
        self.db.audit("user", "alert_delete", {"id": aid})

    # --- events -----------------------------------------------------------
    def events(self, limit: int = 100, unread_only: bool = False) -> dict:
        rows = self.db.q(f"SELECT * FROM alert_events {'WHERE read=0' if unread_only else ''} ORDER BY id DESC LIMIT ?", (limit,))
        unread = self.db.q("SELECT COUNT(*) FROM alert_events WHERE read=0 AND delivery NOT LIKE 'suppressed%'")[0][0]
        return {"events": [{**dict(r), "trigger": json.loads(r["trigger"]), "read": bool(r["read"])} for r in rows], "unread": unread}

    def mark_read(self, ids: list[int] | None) -> int:
        if ids is None:
            n = self.db.q("SELECT COUNT(*) FROM alert_events WHERE read=0")[0][0]
            self.db.x("UPDATE alert_events SET read=1 WHERE read=0")
            return n
        n = 0
        for i in ids:
            n += self.db.q("SELECT COUNT(*) FROM alert_events WHERE id=? AND read=0", (i,))[0][0]
            self.db.x("UPDATE alert_events SET read=1 WHERE id=?", (i,))
        return n   # number of events that actually changed from unread to read

    async def _emit(self, a: dict, rule, verdict: str, message: str, trigger: dict, ts: float) -> dict:
        ev = {"alert_id": a["id"], "alert_name": a["name"], "rule_version": a["version"], "kind": rule.kind, "severity": rule.severity,
              "ts": datetime.fromtimestamp(ts, timezone.utc).isoformat(), "message": message, "trigger": trigger}
        if verdict == "fire":
            res = []
            for n in self.notifiers:
                try:
                    res.append(await n.deliver(ev, rule))
                except Exception as e:  # noqa: BLE001  one failing channel must not lose the event
                    res.append(f"{n.name}:failed:{type(e).__name__}")
            ev["delivery"] = ",".join(res)
        else:
            ev["delivery"] = "suppressed_cooldown"
        ev["id"] = self.db.x("INSERT INTO alert_events(alert_id,alert_name,rule_version,kind,severity,ts,message,trigger,delivery) VALUES(?,?,?,?,?,?,?,?,?)",
                             (a["id"], a["name"], a["version"], rule.kind, rule.severity, ev["ts"], message, json.dumps(trigger, default=str), ev["delivery"]))
        return ev

    # --- evaluation -------------------------------------------------------
    async def evaluate_all(self, now_ts: float | None = None) -> list[dict]:
        async with self._lock:
            now_ts = time.time() if now_ts is None else now_ts
            out: list[dict] = []
            for a in [x for x in self.list() if x["enabled"]]:
                st = dict(a["state"])
                try:
                    rule = parse_rule(a["rule"])
                    out += await (self._scan(a, rule, st, now_ts) if isinstance(rule, ScanRule) else self._single(a, rule, st, now_ts))
                    st.pop("error", None)
                except Exception as e:  # noqa: BLE001  isolate: one broken rule must not stop the others
                    log.exception("alert %s failed", a["id"])
                    st["error"] = f"{type(e).__name__}: {e}"[:200]
                self.db.x("UPDATE alerts SET state=? WHERE id=? AND version=?", (json.dumps(st, default=str), a["id"], a["version"]))
            return out

    async def _single(self, a, rule, st, now_ts) -> list[dict]:
        obs = await observe(rule, self.svc, now_ts)
        st.update(last_eval_at=now_ts, last_skip=obs.skip_reason, last_status=obs.prov.status.value if obs.prov else None)
        if obs.cond is None:
            return []   # stale/unavailable/insufficient data: state untouched, nothing fires
        verdict = decide(st.get("prev"), obs.cond, st.get("last_fired_at"), now_ts, rule.cooldown_seconds)
        st.update(prev=obs.cond, last_value=obs.value)
        if verdict not in ("fire", "suppressed"):
            return []
        p = obs.prov
        trig = {"value": obs.value, "detail": obs.detail, "notes": obs.notes,
                "data": {"provider": p.provider, "venue": p.venue, "status": p.status.value, "event_time": p.event_time.isoformat() if p.event_time else None,
                         "ingested_time": p.ingested_time.isoformat()} if p else None, "rule": rule.model_dump()}
        if verdict == "fire":
            st["last_fired_at"], st["fires"] = now_ts, st.get("fires", 0) + 1
        msg = f"{a['name']}: {obs.detail} · {p.status.value} · {p.provider} {('(' + '; '.join(obs.notes) + ')') if obs.notes else ''}".strip()
        return [await self._emit(a, rule, verdict, msg, trig, now_ts)]

    async def _scan(self, a, rule: ScanRule, st, now_ts) -> list[dict]:
        last = st.get("last_eval_at")
        if last is not None and now_ts - last < rule.interval_seconds:
            return []
        if rule.preset:
            pid = ALIASES.get(rule.preset.upper(), rule.preset)
            if pid not in PRESETS:
                raise ValueError(f"unknown preset {rule.preset}")
            spec = PRESETS[pid]["spec"].model_copy(deep=True)
        else:
            spec = ScanSpec.model_validate(rule.spec)
        spec.limit = 500    # need the full match set to detect NEW entrants
        res = await scan_engine.run(spec, self.bars, await self.load_universe(spec.universe))
        meta = res["meta"]
        st.update(last_eval_at=now_ts, last_status=meta["status"], last_skip=None)
        if meta["with_data"] == 0:
            st["last_skip"] = "scan returned no data"
            return []
        rows = {r["symbol"]: r for r in res["results"]}
        prev = st.get("matches")
        st["matches"] = sorted(rows)
        if prev is None:
            return []   # baseline
        fired = st.setdefault("fired", {})
        new = [s for s in rows if s not in set(prev)]
        fresh = [s for s in new if now_ts - fired.get(s, -1e18) >= rule.cooldown_seconds]
        held = [s for s in new if s not in fresh]
        out = []
        for verdict, syms in (("fire", fresh), ("suppressed", held)):
            if not syms:
                continue
            shown = sorted(syms, key=lambda s: -(rows[s].get("score") or 0))[: rule.max_symbols]
            trig = {"symbols": shown, "more": max(0, len(syms) - len(shown)), "scan": meta["spec"]["name"],
                    "rows": [{k: rows[s].get(k) for k in ("symbol", "price", "change_pct", "rvol", "setup", "score")} for s in shown],
                    "data": {"provider": meta["provider"], "status": meta["status"], "latest_bar_date": meta["latest_bar_date"], "coverage_pct": meta["coverage_pct"]},
                    "notes": meta["notes"]}
            if verdict == "fire":
                for s in syms:
                    fired[s] = now_ts
                st["fires"] = st.get("fires", 0) + 1
            word = "new match" + ("es" if len(syms) > 1 else "")
            msg = f"{a['name']}: {len(syms)} {word}: {', '.join(shown)}{' +%d more' % trig['more'] if trig['more'] else ''} · {meta['status']} · {meta['provider']}"
            out.append(await self._emit(a, rule, verdict, msg, trig, now_ts))
        return out

    async def run_loop(self, seconds: float) -> None:
        while True:
            try:
                await self.evaluate_all()
            except Exception:  # noqa: BLE001
                log.exception("alert loop iteration failed")
            await asyncio.sleep(seconds)
