"""US financial conditions: the Chicago Fed National Financial Conditions Index (NFCI), a weekly reading built from 105 measures of risk, credit and leverage in money markets, debt and equity markets and the banking system. Free public data from FRED (the St. Louis Fed's database), no key.

How to read it (the Chicago Fed's own definition): zero is the average level of financial conditions since 1971; a positive value means conditions are tighter than average, a negative value looser than average. The adjusted index (ANFCI) removes what the economy itself would explain, so it shows the part that is financial only. The three pieces (risk, credit, leverage) are published separately.
Checks: all series are for the same latest week, every value is in a plausible range, the last weeks are spaced one week apart, and a missing value ('.') is left out, never filled in. There is no published total to reconcile against (the three pieces are NOT added up to the headline, they do not sum to it), so a check that cannot be made is not claimed.
It describes what already happened: it is not a market signal or a forecast. A failure says so and shows nothing.
"""
from __future__ import annotations

import asyncio
import csv
import io
import time
from datetime import date, datetime, timedelta, timezone

import httpx

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SOURCE = "Chicago Fed National Financial Conditions Index, via FRED, St. Louis Fed (official, free public data)"
PAGE = "https://fred.stlouisfed.org/series/NFCI"
SERIES = {"NFCI": "headline", "ANFCI": "adjusted", "NFCIRISK": "risk", "NFCICREDIT": "credit", "NFCILEVERAGE": "leverage"}
TTL = 6 * 3600.0
FAIL_TTL = 120.0
OVERDUE_AFTER_DAYS = 21          # weekly, published on Wednesdays for the week ending the Friday before
LO, HI = -6.0, 12.0              # a value outside this range is treated as a bad reading
WEEK = 7


def parse(text: str, sid: str) -> dict[date, float]:
    """{week: value} from a FRED CSV. '.' means no value and is skipped. Anything unreadable raises."""
    rows = list(csv.reader(io.StringIO(text.strip())))
    if not rows or len(rows[0]) != 2 or rows[0][1].strip() != sid:
        raise ValueError(f"unexpected columns for {sid}")
    out: dict[date, float] = {}
    for r in rows[1:]:
        if len(r) != 2:
            raise ValueError(f"a {sid} row had the wrong shape")
        if r[1].strip() in ("", "."):
            continue
        try:
            out[date.fromisoformat(r[0].strip())] = float(r[1])
        except ValueError:
            raise ValueError(f"a {sid} row was unreadable")
    if not out:
        raise ValueError(f"{sid} had no values")
    return out


def _chg(s: dict[date, float], last: date, weeks: int) -> float | None:
    ref = [d for d in s if (last - d).days == weeks * WEEK]
    return round(s[last] - s[ref[0]], 3) if ref else None


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    heads = {sid: max(s) for sid, s in data.items()}
    last = heads["NFCI"]
    if len(set(heads.values())) != 1:
        raise ValueError("the series are not for the same week")
    for sid, s in data.items():
        if any(not (LO <= v <= HI) for v in list(s.values())[-60:]):
            raise ValueError(f"{sid} has a value outside the plausible range")
    wk = sorted(data["NFCI"])[-12:]
    if any((b - a).days != WEEK for a, b in zip(wk, wk[1:])):
        raise ValueError("the last weeks are not one week apart")
    n = data["NFCI"]
    year = [n[d] for d in sorted(n) if 0 <= (last - d).days <= 52 * WEEK]
    v = n[last]
    age = (today - last).days
    return {"available": True, "date": last.isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "source": SOURCE, "url": PAGE, "nfci": v, "adjusted": data["ANFCI"][last],
            "reading": "tighter than average" if v > 0 else "looser than average" if v < 0 else "at the average",
            "pieces": {"risk": data["NFCIRISK"][last], "credit": data["NFCICREDIT"][last], "leverage": data["NFCILEVERAGE"][last]},
            "change_1w": _chg(n, last, 1), "change_4w": _chg(n, last, 4), "change_1y": _chg(n, last, 52),
            "year_low": min(year), "year_high": max(year), "weeks_in_year": len(year),
            "history": [{"date": d.isoformat(), "nfci": n[d]} for d in sorted(n)[-52:]],
            "checks": {"same_week": True, "range_ok": True, "weekly_spacing_ok": True, "pieces_sum_to_headline": "not claimed: the pieces do not sum to it"},
            "note": ("Zero is the average level of financial conditions since 1971. Positive means tighter than average, negative means looser. The adjusted index removes what the economy itself would explain. "
                     "Checked: every series is for the same week, every value is in a plausible range and the last weeks are one week apart. The three pieces are shown as published, not added up. "
                     "This describes what already happened: it is not a market signal or a forecast.")}


class FinConditions:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def _one(self, c: httpx.AsyncClient, sid: str) -> dict[date, float]:
        # No custom User-Agent: FRED stalls and drops connections for an unfamiliar one (seen 2026-11-12), and answers the client's default one in 0.2 s. cosd keeps the download to about two years.
        r = await c.get(URL, params={"id": sid, "cosd": (date.today() - timedelta(days=800)).isoformat()})
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        return parse(r.text, sid)

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real financial conditions data is not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=25)
        try:
            got = await asyncio.gather(*[self._one(c, sid) for sid in SERIES])
            res = {**base, **summarize(dict(zip(SERIES, got)), now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, KeyError) as e:
            res = {**base, "available": False, "reason": f"Financial conditions could not be read right now ({type(e).__name__}: {str(e)[:80]})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
