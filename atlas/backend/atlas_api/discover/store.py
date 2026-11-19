"""What I have seen, opened, saved, dismissed and researched (and my notes), kept in SQLite.

Rules that keep discovery useful: a company that was dismissed, saved or researched is never offered again as "new to me"; one that was only shown is not repeated inside a cooldown unless the
facts it was shown with have materially changed (a new filed quarter, or a different valuation reading). Everything here is a plain record of my own actions: no scoring, no network.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from ..db import DB

STATES = ("seen", "opened", "saved", "dismissed", "researched")
COOLDOWN_DAYS = 30
NOTE_MAX = 4000


def _now(now: datetime | None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat()


class DiscoveryStore:
    def __init__(self, db: DB):
        self.db = db

    # ---- per-company state --------------------------------------------------------------
    def get(self, symbol: str) -> dict:
        r = self.db.q("SELECT * FROM disc_company_state WHERE symbol=?", (symbol.upper(),))
        return dict(r[0]) if r else {"symbol": symbol.upper(), "first_seen_at": None, "last_shown_at": None, "shown_count": 0, "opened_at": None, "saved_at": None, "dismissed_at": None,
                                      "researched_at": None, "last_material": None, "last_score": None}

    def states(self, symbols: list[str]) -> dict[str, dict]:
        out = {s.upper(): self.get(s) for s in symbols}
        return out

    def mark_shown(self, symbol: str, material: str | None, score: float | None, now: datetime | None = None) -> None:
        t = _now(now)
        prev = self.get(symbol)
        if prev["last_shown_at"] and prev["last_shown_at"][:10] == t[:10]:        # opening the page again the same day is not a second showing
            self.db.x("UPDATE disc_company_state SET last_material=?, last_score=? WHERE symbol=?", (material, score, symbol.upper()))
            return
        self.db.x("INSERT INTO disc_company_state(symbol,first_seen_at,last_shown_at,shown_count,last_material,last_score) VALUES(?,?,?,1,?,?) "
                  "ON CONFLICT(symbol) DO UPDATE SET last_shown_at=excluded.last_shown_at, shown_count=shown_count+1, last_material=excluded.last_material, last_score=excluded.last_score",
                  (symbol.upper(), t, t, material, score))

    def set_state(self, symbol: str, state: str, on: bool = True, now: datetime | None = None) -> dict:
        if state not in STATES:
            raise ValueError(f"state must be one of {', '.join(STATES)}")
        col = {"seen": "first_seen_at", "opened": "opened_at", "saved": "saved_at", "dismissed": "dismissed_at", "researched": "researched_at"}[state]
        t = _now(now)
        self.db.x(f"INSERT INTO disc_company_state(symbol,first_seen_at,{col}) VALUES(?,?,?) ON CONFLICT(symbol) DO UPDATE SET {col}=?", (symbol.upper(), t, t if on else None, t if on else None))
        if state == "saved" and on:                                         # saving cancels an earlier dismissal and the reverse
            self.db.x("UPDATE disc_company_state SET dismissed_at=NULL WHERE symbol=?", (symbol.upper(),))
        if state == "dismissed" and on:
            self.db.x("UPDATE disc_company_state SET saved_at=NULL WHERE symbol=?", (symbol.upper(),))
        return self.get(symbol)

    def eligible(self, symbol: str, material: str | None, now: datetime | None = None, cooldown_days: int = COOLDOWN_DAYS) -> tuple[bool, str]:
        """May this company be offered as 'new to me' now? Returns (yes/no, why)."""
        s = self.get(symbol)
        if s["dismissed_at"]:
            return False, "dismissed"
        if s["saved_at"]:
            return False, "already saved"
        if s["researched_at"]:
            return False, "already researched"
        if s["last_shown_at"] is None:
            return True, "never shown"
        if material is not None and s["last_material"] is not None and material != s["last_material"]:
            return True, "material change since it was last shown"
        age = ((now or datetime.now(timezone.utc)) - datetime.fromisoformat(s["last_shown_at"])).days
        return (True, "cooldown over") if age >= cooldown_days else (False, f"shown {age} days ago (cooldown {cooldown_days} days) with no material change")

    # ---- notes --------------------------------------------------------------------------
    def add_note(self, symbol: str, body: str, now: datetime | None = None) -> dict:
        body = (body or "").strip()
        if not body:
            raise ValueError("a note cannot be empty")
        if len(body) > NOTE_MAX:
            raise ValueError(f"a note can be at most {NOTE_MAX} characters")
        t = _now(now)
        note_id = self.db.x("INSERT INTO research_notes(symbol,body,created_at,updated_at) VALUES(?,?,?,?)", (symbol.upper(), body, t, t))
        return {"id": note_id, "symbol": symbol.upper(), "body": body, "created_at": t}

    def notes(self, symbol: str) -> list[dict]:
        return [dict(r) for r in self.db.q("SELECT id,symbol,body,created_at,updated_at FROM research_notes WHERE symbol=? ORDER BY id DESC", (symbol.upper(),))]

    def delete_note(self, note_id: int) -> bool:
        before = self.db.q("SELECT COUNT(*) FROM research_notes WHERE id=?", (note_id,))[0][0]
        self.db.x("DELETE FROM research_notes WHERE id=?", (note_id,))
        return bool(before)

    # ---- changes since my last review ---------------------------------------------------
    def snapshot(self, research: dict) -> dict:
        """The few figures worth comparing next time (all taken from the research output, none invented)."""
        rev, val, r40 = research.get("revenue") or {}, research.get("valuation") or {}, research.get("rule_of_40") or {}
        fv = val.get("fair_value_range") or {}
        return {"ttm_revenue": (rev.get("ttm") or {}).get("value"), "ttm_period_end": (rev.get("ttm") or {}).get("period_end"), "ttm_growth_pct": rev.get("ttm_growth_pct"),
                "trend": (rev.get("trend") or {}).get("label"), "rule_of_40": ((r40.get("current") or {}).get("score")), "valuation_label": val.get("label_key"),
                "fair_value_base": fv.get("base"), "price": val.get("price"), "evidence": (val.get("evidence") or {}).get("level"),
                "latest_filing_period": (rev.get("latest_period_end"))}

    def record_review(self, symbol: str, research: dict, now: datetime | None = None) -> dict:
        snap = self.snapshot(research)
        self.db.x("INSERT INTO research_reviews(symbol,reviewed_at,snapshot) VALUES(?,?,?)", (symbol.upper(), _now(now), json.dumps(snap)))
        self.set_state(symbol, "researched", True, now)
        return snap

    def last_review(self, symbol: str) -> dict | None:
        r = self.db.q("SELECT reviewed_at,snapshot FROM research_reviews WHERE symbol=? ORDER BY id DESC LIMIT 1", (symbol.upper(),))
        return {"reviewed_at": r[0]["reviewed_at"], "snapshot": json.loads(r[0]["snapshot"])} if r else None

    def changes_since_review(self, symbol: str, research: dict) -> dict:
        last = self.last_review(symbol)
        if last is None:
            return {"has_review": False, "note": "You have not marked this company as reviewed yet, so there is nothing to compare with."}
        now, old = self.snapshot(research), last["snapshot"]
        rows = []
        for key, label, unit in (("ttm_revenue", "Trailing revenue", "$"), ("ttm_growth_pct", "Trailing revenue growth", "%"), ("trend", "Growth trend", ""), ("rule_of_40", "Rule of 40 score", ""),
                                 ("valuation_label", "Valuation reading", ""), ("fair_value_base", "Base-case fair value per share", "$"), ("price", "Price", "$"), ("evidence", "Evidence quality", ""),
                                 ("latest_filing_period", "Latest filed period", "")):
            a, b = old.get(key), now.get(key)
            if a != b:
                rows.append({"key": key, "label": label, "unit": unit, "before": a, "after": b})
        return {"has_review": True, "reviewed_at": last["reviewed_at"], "changed": rows, "unchanged_count": 9 - len(rows)}
