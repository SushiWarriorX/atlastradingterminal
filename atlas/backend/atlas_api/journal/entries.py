"""Simple journal entries: the trades a person writes down by hand.

The default entry is a note: a symbol, a date and some words. Size, prices, fees, a planned stop, the thesis, the risk plan, the outcome and a screenshot are all optional.
Realised P&L is never stored. It is calculated here, in exact decimal arithmetic, from the fields that were entered, and only when the entry, the exit and the size
are all there; otherwise the entry says which of them is missing. Imported broker and paper trades keep living in the execution-based journal and are listed next to
these in `log()`, marked as imported and read-only here.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict

from ..db import DB, now as iso_now
from ..trading.money import ZERO, s
from . import stats as jstats
from .store import MAX_SCREENSHOT, SCREENSHOT_RE, JournalError, JournalStore

SYMBOL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-:^=/]{0,23}$")
ASSET_CLASSES = ("crypto", "stock", "etf", "other")
TEXT_LIMITS = {"note": 5000, "thesis": 3000, "risk_plan": 3000, "outcome": 3000}
MONEY = ("size", "entry_price", "exit_price", "planned_stop")
CLEARABLE = ("size", "entry_price", "exit_price", "exit_at", "planned_stop", "note", "thesis", "risk_plan", "outcome", "screenshot")
STATUSES = ("note", "open", "closed")


def _bad(msg: str) -> JournalError:
    return JournalError("INVALID_ENTRY", msg, 422)


def _dec(v, name: str, *, positive: bool = True) -> Decimal | None:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        d = Decimal(str(v).strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        raise _bad(f"{name} must be a number") from None
    if not d.is_finite() or d > Decimal("1e15") or d < 0 or (positive and d == 0):
        raise _bad(f"{name} must be a positive number" if positive else f"{name} cannot be negative")
    return d


def _when(v, name: str) -> datetime:
    t = v if isinstance(v, datetime) else None
    if t is None:
        try:
            t = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
        except ValueError:
            raise _bad(f"{name} must be a date like 2026-11-03, or a date and time") from None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    t = t.astimezone(timezone.utc)
    if not 2000 <= t.year <= 2100:
        raise _bad(f"{name} is out of range")
    return t


class EntryIn(BaseModel):
    """Every field optional on update; on create only `symbol` is required (the date defaults to now)."""
    model_config = ConfigDict(extra="forbid")
    symbol: str | None = None
    asset_class: str | None = None
    direction: str | None = None
    size: str | float | None = None
    entry_price: str | float | None = None
    exit_price: str | float | None = None
    entry_at: str | None = None
    exit_at: str | None = None
    fees: str | float | None = None
    planned_stop: str | float | None = None
    note: str | None = None
    thesis: str | None = None
    risk_plan: str | None = None
    outcome: str | None = None
    screenshot: str | None = None


def clean(data: dict, *, create: bool) -> dict:
    """Validate the fields that were sent and return column values (None clears an optional field)."""
    out: dict = {}
    if "symbol" in data or create:
        sym = (data.get("symbol") or "").strip()
        if not SYMBOL_RE.match(sym):
            raise _bad("symbol is required: letters, digits and . - : ^ = / only, up to 24 characters")
        out["symbol"] = sym.upper()
    if "asset_class" in data and data["asset_class"] is not None:
        if data["asset_class"] not in ASSET_CLASSES:
            raise _bad(f"asset_class must be one of {', '.join(ASSET_CLASSES)}")
        out["asset_class"] = data["asset_class"]
    if "direction" in data and data["direction"] is not None:
        if data["direction"] not in ("long", "short"):
            raise _bad("direction must be long or short")
        out["direction"] = data["direction"]
    for k in MONEY:
        if k in data:
            d = _dec(data[k], k.replace("_", " "))
            out[k] = None if d is None else s(d)
    if "fees" in data:
        d = _dec(data["fees"], "fees", positive=False)
        out["fees"] = s(d if d is not None else ZERO)
    if "entry_at" in data and data["entry_at"] is not None:
        out["entry_at"] = _when(data["entry_at"], "entry date").isoformat()
    elif create:
        out["entry_at"] = datetime.now(timezone.utc).isoformat()
    if "exit_at" in data:
        out["exit_at"] = None if not data["exit_at"] else _when(data["exit_at"], "exit date").isoformat()
    for k, lim in TEXT_LIMITS.items():
        if k in data:
            v = (data[k] or "").strip()
            if len(v) > lim:
                raise _bad(f"{k.replace('_', ' ')} is too long (up to {lim} characters)")
            out[k] = v or None
    if "screenshot" in data:
        v = data["screenshot"]
        if v and (len(v) > MAX_SCREENSHOT or not SCREENSHOT_RE.match(v)):
            raise _bad(f"screenshot must be a PNG, JPEG or WebP image of up to {MAX_SCREENSHOT // 1000} KB")
        out["screenshot"] = v or None
    return out


def calc(r: dict) -> dict:
    """Realised P&L, return, R-multiple and holding time from the entered fields. Anything that cannot be worked out stays None and `pnl_missing` says why."""
    size, ep, xp = (Decimal(r[k]) if r.get(k) else None for k in ("size", "entry_price", "exit_price"))
    fees = Decimal(r.get("fees") or "0")
    stop = Decimal(r["planned_stop"]) if r.get("planned_stop") else None
    out = {"status": "note", "gross_pnl": None, "net_pnl": None, "net_pnl_num": None, "return_pct": None, "r_multiple": None, "holding_seconds": None, "pnl_missing": []}
    if size and ep:
        out["status"] = "closed" if xp else "open"
    if size and ep and xp:
        gross = (xp - ep) * size if r["direction"] == "long" else (ep - xp) * size
        net = gross - fees
        cost = ep * size
        out.update(gross_pnl=s(gross), net_pnl=s(net), net_pnl_num=float(net), return_pct=float(net / cost * 100) if cost > 0 else None)
        if stop:
            risk = abs(ep - stop) * size
            out["r_multiple"] = float(net / risk) if risk > 0 else None
    else:
        out["pnl_missing"] = [n for n, v in (("size", size), ("entry price", ep), ("exit price", xp)) if not v]
    if r.get("exit_at") and r.get("entry_at"):
        out["holding_seconds"] = max(0.0, (datetime.fromisoformat(r["exit_at"]) - datetime.fromisoformat(r["entry_at"])).total_seconds())
    return out


def view(r: dict, *, full: bool = False) -> dict:
    v = {k: r[k] for k in ("symbol", "asset_class", "direction", "size", "entry_price", "exit_price", "entry_at", "exit_at", "fees", "planned_stop", "note", "thesis", "risk_plan", "outcome")}
    v.update(id=f"e:{r['id']}", origin="manual", editable=True, has_screenshot=bool(r["screenshot"]), created_at=r["created_at"], updated_at=r["updated_at"], **calc(r))
    if full:
        v["screenshot"] = r["screenshot"]
    return v


class EntryStore:
    def __init__(self, db: DB):
        self.db = db

    def _row(self, eid: int) -> dict | None:
        rows = self.db.q("SELECT * FROM journal_entries WHERE id=?", (eid,))
        return dict(rows[0]) if rows else None

    @staticmethod
    def _check(r: dict) -> None:
        if r.get("exit_at") and r.get("entry_at") and r["exit_at"] < r["entry_at"]:
            raise _bad("the exit date is before the entry date")

    def create(self, data: dict) -> dict:
        c = clean(data, create=True)
        now = iso_now()
        row = {"asset_class": "other", "direction": "long", "fees": "0", **c}
        self._check(row)
        cols = [*row, "created_at", "updated_at"]
        eid = self.db.x(f"INSERT INTO journal_entries({','.join(cols)}) VALUES({','.join('?' * len(cols))})", (*row.values(), now, now))
        self.db.audit("user", "journal_entry_create", {"id": eid, "symbol": row["symbol"]})
        return view(self._row(eid), full=True)

    def get(self, eid: int) -> dict:
        r = self._row(eid)
        if r is None:
            raise JournalError("NOT_FOUND", "no such journal entry", 404)
        return view(r, full=True)

    def update(self, eid: int, data: dict) -> dict:
        cur = self._row(eid)
        if cur is None:
            raise JournalError("NOT_FOUND", "no such journal entry", 404)
        c = clean(data, create=False)
        for k in ("symbol", "direction", "entry_at", "asset_class"):
            if k in data and data[k] is None:
                raise _bad(f"{k.replace('_', ' ')} cannot be cleared")
        merged = {**cur, **c}
        self._check(merged)
        if c:
            sets = ",".join(f"{k}=?" for k in c)
            self.db.x(f"UPDATE journal_entries SET {sets}, updated_at=? WHERE id=?", (*c.values(), iso_now(), eid))
            self.db.audit("user", "journal_entry_update", {"id": eid, "fields": sorted(c)})
        return view(self._row(eid), full=True)

    def delete(self, eid: int) -> None:
        if self._row(eid) is None:
            raise JournalError("NOT_FOUND", "no such journal entry", 404)
        self.db.x("DELETE FROM journal_entries WHERE id=?", (eid,))
        self.db.audit("user", "journal_entry_delete", {"id": eid})

    def all(self) -> list[dict]:
        return [view(dict(r)) for r in self.db.q("SELECT * FROM journal_entries ORDER BY entry_at DESC, id DESC")]


def imported_view(t: dict) -> dict:
    """A trade derived from imported or paper executions, shaped like a manual entry but read-only."""
    closed = t["status"] == "closed"
    return {"id": f"t:{t['key']}", "origin": "imported", "editable": False, "source": t["source"], "symbol": t["symbol"], "asset_class": t["asset_class"], "direction": t["side"],
            "size": t["qty_max"], "entry_price": t["entry_avg"], "exit_price": t["exit_avg"], "entry_at": t["opened_at"].isoformat(), "exit_at": t["closed_at"].isoformat() if t["closed_at"] else None,
            "fees": t["fees"], "planned_stop": t["planned_stop"], "note": None, "thesis": None, "risk_plan": None, "outcome": None, "has_screenshot": t["has_screenshot"],
            "status": "closed" if closed else "open", "gross_pnl": t["gross_pnl"], "net_pnl": s(t["net_pnl"]), "net_pnl_num": float(t["net_pnl"]), "return_pct": t["return_pct"],
            "r_multiple": t["r_multiple"], "holding_seconds": t["holding_seconds"], "pnl_missing": [], "funding": t["funding"], "has_notes": t["has_notes"]}


def _stat_row(i: dict) -> dict:
    return {"net_pnl": i["net_pnl_num"], "closed_at": datetime.fromisoformat(i["exit_at"]) if i["exit_at"] else datetime.fromisoformat(i["entry_at"]), "holding_seconds": i["holding_seconds"],
            "fees": float(i["fees"] or 0), "funding": float(i.get("funding") or 0), "r_multiple": i["r_multiple"]}


def log(journal: JournalStore, entries: EntryStore, *, status: str | None = None, symbol: str | None = None, direction: str | None = None, origin: str | None = None,
        q: str | None = None, since: str | None = None, until: str | None = None, limit: int = 500) -> dict:
    """Manual entries and imported trades in one list, newest first, plus statistics for the closed ones that match the filters."""
    if status and status not in STATUSES:
        raise _bad(f"status must be one of {', '.join(STATUSES)}")
    if direction and direction not in ("long", "short"):
        raise _bad("direction must be long or short")
    if origin and origin not in ("manual", "imported"):
        raise _bad("origin must be manual or imported")
    items: list[dict] = []
    if origin in (None, "manual"):
        items += entries.all()
    if origin in (None, "imported"):
        journal.sync_paper()
        items += [imported_view(t) for t in journal.trades()["trades"]]
    lo = _when(since, "since").isoformat() if since else None
    hi = _when(until, "until").isoformat() if until else None
    needle = (q or "").strip().lower()
    sym = symbol.strip().upper() if symbol else None

    def keep(i: dict) -> bool:
        if status and i["status"] != status or sym and i["symbol"] != sym or direction and i["direction"] != direction:
            return False
        if lo and i["entry_at"] < lo or hi and i["entry_at"] > hi:
            return False
        return not needle or any(needle in (i.get(k) or "").lower() for k in ("symbol", "note", "thesis", "risk_plan", "outcome"))
    items = sorted((i for i in items if keep(i)), key=lambda i: i["entry_at"], reverse=True)
    closed = [i for i in items if i["status"] == "closed"]
    return {"items": items[: min(max(limit, 1), 2000)], "total": len(items), "stats": jstats.summary([_stat_row(i) for i in closed]),
            "filters": {"status": status, "symbol": sym, "direction": direction, "origin": origin, "q": q, "since": since, "until": until}}


def register(app, ok, journal: JournalStore, entries: EntryStore) -> None:
    """Routes under /api/journal/entries (create, read, edit, delete) and /api/journal/log (everything, with statistics)."""
    @app.post("/api/journal/entries")
    async def entry_create(b: EntryIn):
        return ok(entries.create(b.model_dump(exclude_unset=True)))

    @app.get("/api/journal/entries/{eid}")
    async def entry_get(eid: int):
        return ok(entries.get(eid))

    @app.put("/api/journal/entries/{eid}")
    async def entry_update(eid: int, b: EntryIn):
        return ok(entries.update(eid, b.model_dump(exclude_unset=True)))

    @app.delete("/api/journal/entries/{eid}")
    async def entry_delete(eid: int):
        entries.delete(eid)
        return ok({"deleted": True, "id": f"e:{eid}"})

    @app.get("/api/journal/log")
    async def journal_log(status: str | None = None, symbol: str | None = None, direction: str | None = None, origin: str | None = None,
                          q: str | None = None, since: str | None = None, until: str | None = None, limit: int = 500):
        return ok(log(journal, entries, status=status, symbol=symbol, direction=direction, origin=origin, q=q, since=since, until=until, limit=limit))
