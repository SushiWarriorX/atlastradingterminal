"""SEC EDGAR (official, free): ticker -> CIK, annual financials from XBRL company facts, and recent filings.

SEC fair access: every request carries a User-Agent that names a contact (ATLAS_SEC_CONTACT) and requests are kept well under 10 per second.
Without a contact the client is disabled and says so; it never sends a made-up one. Responses are condensed and cached in SQLite.
Parsing is pure and tolerant: a company that reports a figure under a different tag, or not at all, simply has that figure missing (None), never guessed.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from ..db import DB
from ..models import ProviderUnavailable

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
TTL = {"tickers": timedelta(days=7), "facts": timedelta(hours=24), "subs": timedelta(hours=6)}
YEARS = 6
CONTACT_RX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# metric -> (kind, ordered concept fallbacks). kind: flow = a full fiscal-year period; instant = balance at fiscal year end.
CONCEPTS = {
    "revenue": ("flow", ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax"]),
    "gross_profit": ("flow", ["GrossProfit"]),
    "operating_income": ("flow", ["OperatingIncomeLoss"]),
    "net_income": ("flow", ["NetIncomeLoss", "ProfitLoss"]),
    "eps_diluted": ("flow", ["EarningsPerShareDiluted"]),
    "operating_cash_flow": ("flow", ["NetCashProvidedByUsedInOperatingActivities"]),
    "capex": ("flow", ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"]),
    "cash": ("instant", ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"]),
    "debt": ("instant", ["LongTermDebt", "LongTermDebtNoncurrent"]),
    "equity": ("instant", ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]),
    "assets": ("instant", ["Assets"]),
    "liabilities": ("instant", ["Liabilities"]),
}
EIGHT_K = {"1.01": "Entered a material agreement", "1.03": "Bankruptcy or receivership", "2.01": "Completed an acquisition or disposal", "2.02": "Results of operations (earnings release)",
           "2.05": "Exit or restructuring costs", "3.01": "Listing notice or delisting risk", "4.02": "Prior financial statements should no longer be relied on",
           "5.02": "Director or executive officer change", "5.07": "Shareholder vote results", "7.01": "Regulation FD disclosure", "8.01": "Other events"}


def _d(s: str) -> date:
    return date.fromisoformat(s)


def annual_series(facts: dict, kind: str, concepts: list[str]) -> dict[str, float]:
    """end-date -> value for fiscal years. Earlier concepts win; later ones only fill years the earlier ones lack (companies change tags over time)."""
    out: dict[str, float] = {}
    gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    for c in concepts:
        units = (gaap.get(c) or {}).get("units") or {}
        rows = units.get("USD") or units.get("USD/shares") or []
        best: dict[str, dict] = {}
        for r in rows:
            if not str(r.get("form", "")).startswith("10-K") or "end" not in r or not isinstance(r.get("val"), (int, float)):
                continue
            if kind == "flow":
                if "start" not in r:
                    continue
                try:
                    days = (_d(r["end"]) - _d(r["start"])).days
                except ValueError:
                    continue
                if not 350 <= days <= 380:
                    continue
            elif "start" in r:
                continue
            cur = best.get(r["end"])
            if cur is None or r.get("filed", "") > cur.get("filed", ""):
                best[r["end"]] = r
        for end, r in best.items():
            out.setdefault(end, float(r["val"]))
    return out


def condense_facts(facts: dict) -> dict:
    """Company facts -> {'name', 'years': [{'end', metric...}]} for the last YEARS fiscal years. Years are anchored on revenue, or net income if revenue is absent."""
    series = {m: annual_series(facts, k, cs) for m, (k, cs) in CONCEPTS.items()}
    anchor = series["revenue"] or series["net_income"]
    ends = sorted(anchor)[-YEARS:]
    years = [{"end": e, **{m: series[m].get(e) for m in CONCEPTS}} for e in ends]
    used = sorted({c for m, (k, cs) in CONCEPTS.items() for c in cs if c in ((facts.get("facts") or {}).get("us-gaap") or {})})
    return {"name": facts.get("entityName"), "cik": facts.get("cik"), "years": years, "concepts_present": used[:40]}


def condense_subs(subs: dict, limit: int = 12) -> dict:
    rec = (subs.get("filings") or {}).get("recent") or {}
    cik = int(subs.get("cik") or 0)
    rows = []
    for i, form in enumerate(rec.get("form") or []):
        if form not in ("10-K", "10-Q", "8-K", "10-K/A"):
            continue
        acc, doc = (rec.get("accessionNumber") or [])[i], (rec.get("primaryDocument") or [])[i]
        items = [x for x in str((rec.get("items") or [""] * (i + 1))[i] or "").split(",") if x]
        rows.append({"form": form, "filed": (rec.get("filingDate") or [])[i], "report_date": (rec.get("reportDate") or [""] * (i + 1))[i] or None,
                     "items": [{"item": x, "meaning": EIGHT_K.get(x, "Other")} for x in items][:6],
                     "link": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}" if acc and doc and re.fullmatch(r"[\w.\-]+", doc) else None})
        if len(rows) >= limit:
            break
    return {"name": subs.get("name"), "sic": subs.get("sic"), "sic_description": subs.get("sicDescription"), "fiscal_year_end": subs.get("fiscalYearEnd"),
            "exchanges": subs.get("exchanges"), "filings": rows}


class EdgarClient:
    def __init__(self, db: DB, contact: str | None = None, client: httpx.AsyncClient | None = None):
        c = (contact if contact is not None else os.environ.get("ATLAS_SEC_CONTACT", "")).strip()
        self.contact = c if CONTACT_RX.match(c) else None
        self.db = db
        self._client = client
        self._lock = asyncio.Lock()
        self._last = 0.0

    @property
    def enabled(self) -> bool:
        return self.contact is not None

    def _cached(self, key: str, ttl: timedelta):
        r = self.db.q("SELECT fetched_at, payload FROM edgar_cache WHERE key=?", (key,))
        if not r:
            return None, None
        at = datetime.fromisoformat(r[0]["fetched_at"])
        return json.loads(r[0]["payload"]), (at if datetime.now(timezone.utc) - at < ttl else None)

    async def _get(self, url: str):
        if not self.enabled:
            raise ProviderUnavailable("edgar", "SEC EDGAR is off: set ATLAS_SEC_CONTACT to an email address (the SEC requires a contact in the User-Agent)")
        async with self._lock:                                   # one request at a time, at most ~5 per second: well inside the SEC's 10/second limit
            wait = 0.2 - (time.monotonic() - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()
        try:
            c = self._client or httpx.AsyncClient(timeout=30, follow_redirects=False)
            try:
                r = await c.get(url, headers={"User-Agent": f"ATLAS-Terminal personal research {self.contact}", "Accept-Encoding": "gzip"})
            finally:
                if self._client is None:
                    await c.aclose()
        except httpx.HTTPError as e:
            raise ProviderUnavailable("edgar", f"SEC EDGAR unreachable ({type(e).__name__})") from e
        if r.status_code != 200:
            raise ProviderUnavailable("edgar", f"SEC EDGAR returned HTTP {r.status_code}")
        try:
            return r.json()
        except ValueError as e:
            raise ProviderUnavailable("edgar", "SEC EDGAR returned something that is not JSON") from e

    async def _cached_get(self, key: str, ttl: timedelta, url: str, condense):
        data, fresh = self._cached(key, ttl)
        if data is not None and fresh:
            return data, "cache", fresh
        try:
            raw = await self._get(url)
            data = condense(raw)
        except ProviderUnavailable:
            if data is not None:
                at = datetime.fromisoformat(self.db.q("SELECT fetched_at FROM edgar_cache WHERE key=?", (key,))[0]["fetched_at"])
                return data, "stale", at
            raise
        now = datetime.now(timezone.utc)
        self.db.x("INSERT INTO edgar_cache(key,fetched_at,payload) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET fetched_at=excluded.fetched_at, payload=excluded.payload", (key, now.isoformat(), json.dumps(data)))
        return data, "live", now

    async def cik(self, ticker: str) -> tuple[int, str] | None:
        data, _, _ = await self._cached_get("tickers", TTL["tickers"], TICKERS_URL, lambda raw: {v["ticker"].upper(): [int(v["cik_str"]), v["title"]] for v in raw.values()})
        hit = data.get(ticker.upper()) or data.get(ticker.upper().replace(".", "-"))
        return (hit[0], hit[1]) if hit else None

    async def financials(self, cik: int):
        return await self._cached_get(f"facts:{cik}", TTL["facts"], FACTS_URL.format(cik=cik), condense_facts)

    async def filings(self, cik: int):
        return await self._cached_get(f"subs:{cik}", TTL["subs"], SUBS_URL.format(cik=cik), condense_subs)
