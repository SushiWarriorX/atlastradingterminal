"""The new-listings feed as a service: fetch the calendar, look for independent confirmation, save the raw facts, and recompute every status against today's date when the page is read.

Confirmation of a first trading day needs an independent price history (the same daily-bar source the rest of the app uses): the first bar must fall within ten days after the pricing date.
A company whose price history starts long before its pricing date is a transfer or ticker change, not a new company. SEC verification looks for the final prospectus (424B4).
Everything that cannot be checked stays marked as not confirmed; nothing is assumed.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from . import listings as L

PRICED_WINDOW_DAYS = 30
MAX_CHECKS = 25


def first_bar(candles) -> str | None:
    if not candles:
        return None
    t = min(c.time for c in candles)
    return datetime.fromtimestamp(t, timezone.utc).date().isoformat()


def confirm_from_bars(candles, priced_date: str | None) -> dict:
    """{'first_trade': iso|None, 'earliest_price': iso|None, 'newness': {...}} from daily bars. The first bar must be on or after the pricing date, within ten days."""
    fb = first_bar(candles)
    if fb is None or not priced_date:
        return {"first_trade": None, "earliest_price": fb, "newness": None}
    gap = (date.fromisoformat(fb) - date.fromisoformat(priced_date)).days
    ft = fb if 0 <= gap <= 10 else None
    # newness compares the pricing date (the presumed debut) with the earliest price history: history long before it means a transfer or ticker change
    return {"first_trade": ft, "earliest_price": fb, "newness": L.is_genuinely_new(ft or priced_date, earliest_price_date=fb) if ft or gap < 0 else None}


class ListingsService:
    def __init__(self, db, feed: L.NasdaqIpoFeed, bars=None, edgar=None, demo: bool = False):
        self.db, self.feed, self.bars, self.edgar, self.demo = db, feed, bars, edgar, demo

    async def refresh(self, now: datetime | None = None, call=None) -> dict:
        now = now or datetime.now(timezone.utc)
        today = now.date()
        if self.demo:
            return {"available": False, "reason": "Demo mode: listings are real events, and made-up ones would look real, so none are shown."}
        rows, errors = await self.feed.rows(today, now)
        if call:
            call("public_api", 4)
        recent = [r for r in rows if r["stage"] == "priced" and r["symbol"] and r["exchange"] and r.get("priced_date") and (today - date.fromisoformat(r["priced_date"])).days <= PRICED_WINDOW_DAYS][:MAX_CHECKS]
        confirmations, newness, verifications = {}, {}, {}
        if self.bars is not None and recent:
            try:
                batch = await self.bars.fetch([r["symbol"] for r in recent])
                for r in recent:
                    cf = confirm_from_bars(batch.bars.get(r["symbol"]), r["priced_date"])
                    if cf["first_trade"]:
                        confirmations[r["symbol"].upper()] = cf["first_trade"]
                    if cf["newness"]:
                        newness[r["symbol"].upper()] = cf["newness"]
                if batch.failed:
                    errors.append(f"Price history: {len(batch.failed)} of {len(recent)} symbols could not be checked, so their first trading day is not confirmed.")
            except Exception as e:  # noqa: BLE001  confirmation is best-effort; the deal list still shows, marked unconfirmed
                errors.append(f"Price history could not be read ({type(e).__name__}), so no first trading day is confirmed.")
        elif recent:
            errors.append("No price-history source is available, so no first trading day is confirmed.")
        if self.edgar is not None and getattr(self.edgar, "enabled", False) and recent:
            for r in recent:
                try:
                    hit = await self.edgar.cik(r["symbol"])
                    if hit is None:
                        continue
                    data, _, _ = await self.edgar.all_filings(hit[0])
                    if call:
                        call("sec", 2)
                    verifications[r["symbol"].upper()] = L.verify_with_sec(data["filings"], r["priced_date"])
                except Exception:  # noqa: BLE001  a company too new for the ticker file simply stays unverified
                    continue
        elif recent:
            errors.append("SEC verification is off (ATLAS_SEC_CONTACT is not set): deals are marked unverified.")
        payload = {"rows": rows, "confirmations": confirmations, "newness": newness, "verifications": verifications, "errors": errors, "fetched_at": now.isoformat()}
        self.db.x("INSERT INTO disc_feed_runs(kind,asof,created_at,payload) VALUES('listings',?,?,?) ON CONFLICT(kind,asof) DO UPDATE SET created_at=excluded.created_at, payload=excluded.payload",
                  (today.isoformat(), now.isoformat(), json.dumps(payload)))
        return {"available": True, "rows": len(rows), "confirmed": len(confirmations), "verified": sum(1 for v in verifications.values() if v["verified"]), "errors": errors}

    def read(self, days: int = 30, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        today = now.date()
        r = self.db.q("SELECT payload FROM disc_feed_runs WHERE kind='listings' ORDER BY asof DESC LIMIT 1")
        if not r:
            return {"available": False, "reason": "The listings feed has not been fetched yet. It refreshes daily through the scheduler.", "recent": [], "upcoming": [], "coverage": L.COVERAGE_NOTE, "source": L.SOURCE}
        p = json.loads(r[0]["payload"])
        feed = L.build_feed(p["rows"], today, max(1, min(int(days), 120)), p["confirmations"], p["verifications"], p["errors"])
        for item in feed["recent"]:
            n = (p.get("newness") or {}).get((item.get("symbol") or "").upper())
            if n:
                item["newness"] = n
        age = (now - datetime.fromisoformat(p["fetched_at"])).total_seconds() / 3600
        return {"available": True, "fetched_at": p["fetched_at"], "age_hours": round(age, 1), "stale": age > 36, **feed}
