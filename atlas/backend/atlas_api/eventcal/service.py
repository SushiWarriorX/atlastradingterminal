"""One calendar for the things that move markets: company earnings, economic data (CPI, jobs, GDP, PCE...), interest-rate decisions (FOMC), dividends and Treasury auctions.

Each source is fetched, cached and reported on separately: if one fails the others still show, and the response says which failed. Nothing is invented:
a field a source does not give is None. Nasdaq's calendars are unofficial (free, public, delayed) and are labelled so; BLS, BEA, Treasury and the Fed are official.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from .. import fedwatch
from .. import instruments as I
from ..db import DB
from ..scanner.universe import CORE
from . import sources as S

KINDS = ("earnings", "economy", "rates", "dividend", "auction")
SCOPES = ("watchlist", "major", "all")
MAX_DAYS = 21
PER_DAY_CAP = 40
TTL_DAY = 3 * 3600.0         # Nasdaq per-day lists
TTL_SCHEDULE = 12 * 3600.0   # BLS, BEA, Treasury
URLS = {"earn": "https://api.nasdaq.com/api/calendar/earnings?date={d}", "div": "https://api.nasdaq.com/api/calendar/dividends?date={d}",
        "bls": "https://www.bls.gov/schedule/news_release/bls.ics", "bea": "https://www.bea.gov/news/schedule",
        "tsy": "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/upcoming_auctions?page%5Bsize%5D=400&sort=-auction_date"}
IMPORTANCE = {"high": 3, "medium": 2, "low": 1}


class EventCalendar:
    def __init__(self, db: DB, demo: bool = False, client: httpx.AsyncClient | None = None, contact: str | None = None):
        self.db, self.demo, self._client = db, demo, client
        c = (contact if contact is not None else os.environ.get("ATLAS_SEC_CONTACT", "")).strip()
        self.ua_contact = f"ATLAS-Terminal personal research {c}" if "@" in c else "ATLAS-Terminal/0.1 (personal research)"
        self.ua_browserish = "Mozilla/5.0 (compatible; ATLAS-Terminal personal research)"
        self._cache: dict[str, tuple[float, object]] = {}
        self._sem = asyncio.Semaphore(3)

    # ---- fetching ----
    async def _get(self, key: str, url: str, ua: str, ttl: float, as_json: bool):
        hit = self._cache.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        async with self._sem:
            c = self._client or httpx.AsyncClient(timeout=25, follow_redirects=False)
            try:
                r = await c.get(url, headers={"User-Agent": ua, "Accept": "application/json, text/plain, */*"})
            finally:
                if self._client is None:
                    await c.aclose()
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}")
            data = r.json() if as_json else r.text
            await asyncio.sleep(0.1)
        self._cache[key] = (time.monotonic() + ttl, data)
        return data

    @staticmethod
    def _days(start: date, end: date, weekdays_only: bool) -> list[date]:
        d, out = start, []
        while d <= end:
            if not weekdays_only or d.weekday() < 5:
                out.append(d)
            d += timedelta(days=1)
        return out

    async def _source(self, sid: str, name: str, official: bool, coro_factory):
        try:
            items = await coro_factory()
            return items, {"id": sid, "name": name, "official": official, "ok": True, "count": len(items), "error": None}
        except Exception as e:  # noqa: BLE001  one source failing must not hide the others
            msg = str(e)[:80] if isinstance(e, RuntimeError) else f"{type(e).__name__} (source unreachable)"
            return [], {"id": sid, "name": name, "official": official, "ok": False, "count": 0, "error": msg}

    async def _nasdaq(self, kind: str, start: date, end: date) -> list[dict]:
        days = self._days(start, end, weekdays_only=(kind == "earn"))
        pages = await asyncio.gather(*(self._get(f"{kind}:{d}", URLS[kind].format(d=d.isoformat()), self.ua_browserish, TTL_DAY, True) for d in days))
        out: list[dict] = []
        for d, p in zip(days, pages):
            out += (S.parse_nasdaq_earnings(p, d.isoformat()) if kind == "earn" else S.parse_nasdaq_dividends(p, d.isoformat()))
        return out

    # ---- demo ----
    def _demo_events(self, start: date, end: date, now: datetime) -> list[dict]:
        out = []
        for i, sym in enumerate(["AAPL", "MSFT", "NVDA", "AMD", "TSLA", "COIN", "PLTR", "T"]):
            d = start + timedelta(days=(i * 2) % max((end - start).days, 1))
            out.append({"kind": "earnings", "date": d.isoformat(), "at_utc": None, "time_label": "After the market closes" if i % 2 else "Before the market opens", "title": f"{sym} earnings report", "symbol": sym, "name": f"{sym} (synthetic)",
                        "importance": "high" if i < 3 else "medium", "market_cap": 3e11, "details": {"quarter_ending": "Demo", "eps_estimate": 1.0 + i / 10, "analysts": 10, "last_year_eps": 0.9 + i / 10, "last_year_report_date": None},
                        "source": "DEMO: synthetic, not real", "official": False, "link": None})
            if i % 3 == 0:
                out.append({"kind": "dividend", "date": (d + timedelta(days=1)).isoformat(), "at_utc": None, "time_label": "Ex-dividend date", "title": f"{sym} ex-dividend", "symbol": sym, "name": f"{sym} (synthetic)", "importance": "low", "market_cap": None,
                            "details": {"amount": 0.25, "annual_amount": 1.0, "ex_date": (d + timedelta(days=1)).isoformat(), "pay_date": (d + timedelta(days=20)).isoformat(), "record_date": (d + timedelta(days=1)).isoformat(), "announced": None},
                            "source": "DEMO: synthetic, not real", "official": False, "link": None})
        return out

    # ---- main ----
    def _watch_symbols(self, extra: list[str]) -> set[str]:
        rows = self.db.q("SELECT symbol FROM signal_watchlist WHERE asset_type IN ('stock','etf')")
        return {r["symbol"].upper() for r in rows} | {x.upper() for x in extra}

    async def overview(self, start: date | None = None, days: int = 14, kinds: list[str] | None = None, scope: str = "major", symbols: list[str] | None = None, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        start = start or now.date()
        days = max(1, min(days, MAX_DAYS))
        end = start + timedelta(days=days - 1)
        kinds = [k for k in (kinds or KINDS) if k in KINDS] or list(KINDS)
        scope = scope if scope in SCOPES else "major"
        watch = self._watch_symbols(symbols or [])
        notes: list[str] = []
        items: list[dict] = []
        status: list[dict] = []
        if self.demo:
            items += self._demo_events(start, end, now)
            status.append({"id": "demo", "name": "Demo events (synthetic)", "official": False, "ok": True, "count": len(items), "error": None})
            fomc = fedwatch.scheduled_events(now, limit=200)
            items += S.parse_fomc(fomc)
            status.append({"id": "fomc", "name": "Fed FOMC calendar (entered by hand)", "official": True, "ok": True, "count": len(S.parse_fomc(fomc)), "error": None})
            notes.append("Demo mode: company events are synthetic. The Fed dates are real.")
        else:
            jobs = []
            if "earnings" in kinds:
                jobs.append(self._source("nasdaq_earnings", "Nasdaq earnings calendar (unofficial)", False, lambda: self._nasdaq("earn", start, end)))
            if "dividend" in kinds:
                jobs.append(self._source("nasdaq_dividends", "Nasdaq dividend calendar (unofficial)", False, lambda: self._nasdaq("div", start, end)))
            if "economy" in kinds:
                async def bls():
                    return S.parse_bls(await self._get("bls", URLS["bls"], self.ua_contact, TTL_SCHEDULE, False))

                async def bea():
                    return S.parse_bea(await self._get("bea", URLS["bea"], self.ua_browserish, TTL_SCHEDULE, False), now.date())
                jobs.append(self._source("bls", "BLS release calendar (official)", True, bls))
                jobs.append(self._source("bea", "BEA release schedule (official)", True, bea))
            if "auction" in kinds:
                async def tsy():
                    return S.parse_treasury(await self._get("tsy", URLS["tsy"], self.ua_contact, TTL_SCHEDULE, True), now.date())
                jobs.append(self._source("treasury", "US Treasury auction schedule (official)", True, tsy))
            if "rates" in kinds:
                async def fomc():
                    return S.parse_fomc(fedwatch.scheduled_events(now, limit=200))
                jobs.append(self._source("fomc", "Fed FOMC calendar (entered by hand)", True, fomc))
            for got, st in await asyncio.gather(*jobs):
                items += got
                status.append(st)
        if days > 14:
            notes.append("Company earnings and dividends are fetched one day at a time, so long windows take longer the first time.")
        # filters
        items = [e for e in items if start.isoformat() <= e["date"] <= end.isoformat() and e["kind"] in kinds]
        for e in items:
            e["watch"] = bool(e["symbol"] and e["symbol"] in watch)
            inst = I.resolve(e["symbol"]) if e["symbol"] else None
            e["instrument_id"] = inst.id if inst else None               # lets the terminal add it to a watchlist; None when ATLAS does not know the ticker
        major = set(CORE) | watch
        if scope == "watchlist":
            items = [e for e in items if e["symbol"] is None or e["watch"]]
        elif scope == "major":
            items = [e for e in items if e["symbol"] is None or e["watch"] or e["symbol"] in major or (e["kind"] == "earnings" and e["importance"] in ("high", "medium"))]
        # dedupe (same kind, symbol, date)
        seen, uniq = set(), []
        for e in items:
            k = (e["kind"], e["symbol"], e["date"], e["title"] if e["symbol"] is None else "")
            if k not in seen:
                seen.add(k)
                uniq.append(e)
        items = uniq
        # cap per day and kind for company events
        capped = 0
        by: dict[tuple, list] = {}
        for e in items:
            by.setdefault((e["date"], e["kind"]), []).append(e)
        final: list[dict] = []
        for (d, k), lst in by.items():
            if k in ("earnings", "dividend") and len(lst) > PER_DAY_CAP:
                lst.sort(key=lambda x: (not x["watch"], -(x["market_cap"] or 0), x["symbol"] or ""))
                capped += len(lst) - PER_DAY_CAP
                lst = lst[:PER_DAY_CAP]
            final += lst
        if capped:
            notes.append(f"{capped} smaller company events are hidden (showing the {PER_DAY_CAP} biggest per day and type). Pick 'Watchlist' or a single type to narrow it.")
        order = {"time-pre": 0, "Before": 0, "After": 2}
        final.sort(key=lambda e: (e["date"], e["at_utc"] or ("0" if (e["time_label"] or "").startswith("Before") else "9" if (e["time_label"] or "").startswith("After") else "5"), -IMPORTANCE[e["importance"]], -(e["market_cap"] or 0), e["symbol"] or "", e["title"]))
        counts = {k: sum(1 for e in final if e["kind"] == k) for k in KINDS}
        if all(not s["ok"] for s in status if s["id"] != "fomc") and status:
            notes.append("None of the online sources could be reached, so only what is built in is shown. Check your internet connection and try again.")
        return {"as_of": now.isoformat(), "from": start.isoformat(), "to": end.isoformat(), "demo": self.demo, "scope": scope, "kinds": kinds, "items": final, "counts": counts, "sources": status, "notes": notes,
                "importance_note": "Importance: CPI, jobs, GDP, PCE and Fed decisions are high; a company is high at $200B+ market value, medium at $10B+. It is a guide to what usually moves markets, not a prediction.",
                "labels": {"official": "From the agency that publishes it.", "unofficial": "Free public data from Nasdaq: can be late or wrong; confirm with the company."}}
