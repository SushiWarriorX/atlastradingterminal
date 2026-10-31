"""Journal persistence and trade assembly. Executions are the source of truth; trades are re-derived on every read."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from ..db import DB, now as iso_now
from ..trading.money import ZERO, D, s
from .matching import Exec, Flow, Trade, build_trades
from .importers import ParseResult

MAX_TEXT = 5000
MAX_SCREENSHOT = 700_000
NOTE_TEXT = ["setup", "thesis", "catalyst", "timeframe", "notes", "lessons"]
SCREENSHOT_RE = re.compile(r"^data:image/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+$")


class JournalError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _dt(x: str) -> datetime:
    d = datetime.fromisoformat(x)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


class JournalStore:
    def __init__(self, db: DB):
        self.db = db
        self.last_fee_updates = 0

    # --- writes -----------------------------------------------------------
    def batch(self, source: str, kind: str, filename: str | None, res: ParseResult, inserted: int, duplicates: int) -> int:
        return self.db.x("INSERT INTO import_batches(source,kind,filename,rows_total,inserted,duplicates,skipped,mapping,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                         (source, kind, filename, res.rows_total, inserted, duplicates, sum(res.skipped.values()) + len(res.errors),
                          json.dumps({"mapping": res.mapping, "options": res.options}), iso_now()))

    def insert_executions(self, execs: list[Exec], batch_id: int | None = None) -> tuple[int, int]:
        """Idempotent by (source, ext_id). Returns (inserted, duplicates). A known execution whose STORED fee is 0 gets a later non-zero fee
        filled in (brokers such as IBKR report commissions after the fill); a non-zero stored fee is never overwritten."""
        ins = 0
        self.last_fee_updates = 0
        with self.db.tx() as c:
            for e in execs:
                cur = c.execute("INSERT OR IGNORE INTO executions(source,ext_id,ts,symbol,instrument_id,asset_class,side,qty,price,fee,kind,currency,multiplier,batch_id,created_at) "
                                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                (e.source, e.ext_id, e.ts.isoformat(), e.symbol, e.instrument_id, e.asset_class, e.side, s(e.qty), s(e.price), s(e.fee), e.kind, e.currency,
                                 s(e.multiplier), batch_id, iso_now()))
                ins += cur.rowcount
                if cur.rowcount == 0 and e.fee > 0:
                    upd = c.execute("UPDATE executions SET fee=? WHERE source=? AND ext_id=? AND CAST(fee AS REAL)=0", (s(e.fee), e.source, e.ext_id))
                    self.last_fee_updates += upd.rowcount
        return ins, len(execs) - ins

    def insert_flows(self, flows: list[Flow], batch_id: int | None = None) -> tuple[int, int]:
        ins = 0
        with self.db.tx() as c:
            for f in flows:
                cur = c.execute("INSERT OR IGNORE INTO cashflows(source,ext_id,ts,symbol,kind,amount,currency,batch_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                                (f.source, f.ext_id, f.ts.isoformat(), f.symbol, f.kind, s(f.amount), f.currency, batch_id, iso_now()))
                ins += cur.rowcount
        return ins, len(flows) - ins

    def delete_source(self, source: str) -> dict:
        n_e = self.db.q("SELECT COUNT(*) FROM executions WHERE source=?", (source,))[0][0]
        n_f = self.db.q("SELECT COUNT(*) FROM cashflows WHERE source=?", (source,))[0][0]
        with self.db.tx() as c:
            c.execute("DELETE FROM executions WHERE source=?", (source,))
            c.execute("DELETE FROM cashflows WHERE source=?", (source,))
            c.execute("DELETE FROM journal_notes WHERE trade_key LIKE ? ESCAPE '\\'", (source.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "|%",))
        self.db.audit("user", "journal_delete_source", {"source": source, "executions": n_e})
        return {"source": source, "executions_deleted": n_e, "cashflows_deleted": n_f}

    def save_mapping(self, source: str, mapping: dict) -> None:
        self.db.x("INSERT INTO csv_mappings(source,mapping,updated_at) VALUES(?,?,?) ON CONFLICT(source) DO UPDATE SET mapping=excluded.mapping, updated_at=excluded.updated_at",
                  (source, json.dumps(mapping), iso_now()))

    def get_mapping(self, source: str) -> dict | None:
        r = self.db.q("SELECT mapping FROM csv_mappings WHERE source=?", (source,))
        return json.loads(r[0][0]) if r else None

    # --- paper engine fills -> executions (idempotent) ---------------------
    def sync_paper(self) -> dict:
        added = 0
        for p in self.db.q("SELECT id FROM portfolios WHERE kind='paper' AND venue='sim'"):
            src = f"paper:{p['id']}"
            rows = self.db.q("SELECT f.*, o.planned_stop FROM fills f JOIN orders o ON o.id=f.order_id WHERE f.portfolio_id=? ORDER BY f.id", (p["id"],))
            execs = []
            for f in rows:
                inst_class = "crypto" if f["instrument_id"].startswith("CRYPTO:") else "stock"
                execs.append(Exec(source=src, ext_id=f"fill-{f['id']}", ts=_dt(f["ts"]), symbol=f["symbol"], asset_class=inst_class, side=f["side"], qty=D(f["qty"]),
                                  price=D(f["price"]), fee=D(f["fee"]), instrument_id=f["instrument_id"]))
            ins, _ = self.insert_executions(execs)
            added += ins
        return {"paper_executions_added": added}

    def paper_stop_for(self, ext_id: str, source: str) -> str | None:
        m = re.match(r"paper:(\d+)", source)
        if not m or not ext_id.startswith("fill-"):
            return None
        r = self.db.q("SELECT o.planned_stop FROM fills f JOIN orders o ON o.id=f.order_id WHERE f.id=? AND f.portfolio_id=?", (int(ext_id[5:]), int(m.group(1))))
        return r[0][0] if r and r[0][0] else None

    # --- reads ---------------------------------------------------------------
    def sources(self) -> list[dict]:
        out = []
        for r in self.db.q("SELECT source, COUNT(*) n, MIN(ts) first, MAX(ts) last, COUNT(DISTINCT symbol) symbols FROM executions GROUP BY source ORDER BY source"):
            fl = self.db.q("SELECT COUNT(*) FROM cashflows WHERE source=?", (r["source"],))[0][0]
            out.append({"source": r["source"], "executions": r["n"], "cashflows": fl, "first": r["first"], "last": r["last"], "symbols": r["symbols"]})
        for r in self.db.q("SELECT source, COUNT(*) n FROM cashflows WHERE source NOT IN (SELECT DISTINCT source FROM executions) GROUP BY source"):
            out.append({"source": r["source"], "executions": 0, "cashflows": r["n"], "first": None, "last": None, "symbols": 0})
        return out

    def batches(self, limit: int = 20) -> list[dict]:
        return [dict(r) for r in self.db.q("SELECT id,source,kind,filename,rows_total,inserted,duplicates,skipped,created_at FROM import_batches ORDER BY id DESC LIMIT ?", (limit,))]

    def load(self, source: str | None = None) -> tuple[list[Exec], list[Flow]]:
        w, a = ("WHERE source=?", (source,)) if source else ("", ())
        ex = [Exec(source=r["source"], ext_id=r["ext_id"], ts=_dt(r["ts"]), symbol=r["symbol"], asset_class=r["asset_class"], side=r["side"], qty=D(r["qty"]), price=D(r["price"]),
                   fee=D(r["fee"]), kind=r["kind"], currency=r["currency"], multiplier=D(r["multiplier"]), instrument_id=r["instrument_id"])
              for r in self.db.q(f"SELECT * FROM executions {w} ORDER BY ts, id", a)]
        fl = [Flow(source=r["source"], ext_id=r["ext_id"], ts=_dt(r["ts"]), symbol=r["symbol"], kind=r["kind"], amount=D(r["amount"]), currency=r["currency"])
              for r in self.db.q(f"SELECT * FROM cashflows {w} ORDER BY ts, id", a)]
        return ex, fl

    # --- notes ---------------------------------------------------------------
    def get_note(self, key: str) -> dict | None:
        r = self.db.q("SELECT * FROM journal_notes WHERE trade_key=?", (key,))
        return self._note_view(dict(r[0])) if r else None

    @staticmethod
    def _note_view(r: dict) -> dict:
        for k in ("targets", "mistakes", "tags"):
            r[k] = json.loads(r[k]) if r.get(k) else []
        return r

    def upsert_note(self, key: str, data: dict) -> dict:
        allowed = set(NOTE_TEXT) | {"planned_stop", "targets", "mistakes", "tags", "screenshot"}
        extra = set(data) - allowed
        if extra:
            raise JournalError("INVALID_NOTE", f"unknown field(s): {', '.join(sorted(extra))}", 422)
        row: dict = {}
        for k in NOTE_TEXT:
            if k in data:
                v = data[k]
                if v is not None and (not isinstance(v, str) or len(v) > MAX_TEXT):
                    raise JournalError("INVALID_NOTE", f"{k} must be text up to {MAX_TEXT} characters", 422)
                row[k] = v or None
        if "planned_stop" in data:
            v = data["planned_stop"]
            if v in (None, ""):
                row["planned_stop"] = None
            else:
                try:
                    if D(v) <= 0:
                        raise ValueError
                except (InvalidOperation, ValueError):
                    raise JournalError("INVALID_NOTE", "planned_stop must be a positive number", 422)
                row["planned_stop"] = s(D(v))
        for k in ("targets", "mistakes", "tags"):
            if k in data:
                v = data[k] or []
                if not isinstance(v, list) or len(v) > 30:
                    raise JournalError("INVALID_NOTE", f"{k} must be a list of at most 30 items", 422)
                if k == "targets":
                    try:
                        v = [s(D(x)) for x in v]
                    except (InvalidOperation, ValueError):
                        raise JournalError("INVALID_NOTE", "targets must be numbers", 422)
                else:
                    if any(not isinstance(x, str) or not x.strip() or len(x) > 60 for x in v):
                        raise JournalError("INVALID_NOTE", f"each {k[:-1]} must be 1-60 characters", 422)
                    v = sorted({x.strip() for x in v})
                row[k] = json.dumps(v)
        if "screenshot" in data:
            v = data["screenshot"]
            if v:
                if len(v) > MAX_SCREENSHOT or not SCREENSHOT_RE.match(v):
                    raise JournalError("INVALID_NOTE", f"screenshot must be a base64 PNG/JPEG/WebP data URL up to {MAX_SCREENSHOT // 1000} KB", 422)
            row["screenshot"] = v or None
        now = iso_now()
        cols = list(row)
        if self.db.q("SELECT 1 FROM journal_notes WHERE trade_key=?", (key,)):
            if cols:
                self.db.x(f"UPDATE journal_notes SET {', '.join(c + '=?' for c in cols)}, updated_at=? WHERE trade_key=?", (*[row[c] for c in cols], now, key))
        else:
            self.db.x(f"INSERT INTO journal_notes(trade_key{''.join(',' + c for c in cols)},created_at,updated_at) VALUES(?{',?' * len(cols)},?,?)", (key, *[row[c] for c in cols], now, now))
        self.db.audit("user", "journal_note", {"key": key, "fields": cols})
        return self.get_note(key)

    # --- trade assembly -------------------------------------------------------
    def trades(self, source: str | None = None, status: str | None = None, symbol: str | None = None) -> dict:
        ex, fl = self.load(source)
        trades, leftover = build_trades(ex, fl)
        notes = {r["trade_key"]: self._note_view(dict(r)) for r in self.db.q("SELECT * FROM journal_notes")}
        out = []
        for t in trades:
            if (status and t.status != status) or (symbol and t.symbol != symbol.upper()):
                continue
            out.append(self._view(t, notes.get(t.key)))
        out.sort(key=lambda x: x["opened_at"], reverse=True)
        return {"trades": out, "unattributed_cashflows": [{"source": f.source, "ts": f.ts.isoformat(), "symbol": f.symbol, "kind": f.kind, "amount": s(f.amount)} for f in leftover]}

    def _view(self, t: Trade, note: dict | None) -> dict:
        stop = (note or {}).get("planned_stop") or self.paper_stop_for(t.exec_ids[0], t.source)
        r = None
        if stop and t.entry_avg and t.qty_max:
            risk = t.qty_max * abs(t.entry_avg - D(stop)) * t.multiplier
            r = float(t.net_pnl / risk) if risk > 0 else None
        notional = (t.entry_avg or ZERO) * t.qty_max * t.multiplier
        tags = list((note or {}).get("tags") or []) + [f"mistake: {m}" for m in (note or {}).get("mistakes") or []]
        return {
            "key": t.key, "source": t.source, "symbol": t.symbol, "asset_class": t.asset_class, "side": t.side, "status": t.status, "currency": t.currency,
            "opened_at": t.opened_at, "closed_at": t.closed_at, "qty_max": s(t.qty_max), "qty_open": s(t.qty_open), "entry_avg": s(t.entry_avg) if t.entry_avg is not None else None,
            "exit_avg": s(t.exit_avg) if t.exit_avg is not None else None, "gross_pnl": s(t.gross_pnl), "fees": s(t.fees), "funding": s(t.funding), "net_pnl": t.net_pnl,
            "return_pct": float(t.net_pnl / notional * 100) if notional > 0 else None, "holding_seconds": t.holding_seconds, "liquidated": t.liquidated, "n_execs": len(t.exec_ids),
            "planned_stop": stop, "r_multiple": r, "setup": (note or {}).get("setup"), "tags": tags, "has_notes": bool(note), "has_screenshot": bool((note or {}).get("screenshot")),
            "exec_ids": t.exec_ids}
