"""Primary dealers' net position in US Treasuries (Federal Reserve Bank of New York, Primary Dealer Statistics, free, no key).

How to read it: primary dealers are the large banks that trade directly with the Federal Reserve and buy Treasury auctions. Their "net position" is what they own (long) minus what they have sold short, in
Treasury notes, bills and bonds excluding inflation-protected securities (TIPS). A bigger number means the dealers are holding more Treasuries on their own books, for example while they work through newly auctioned
debt; a smaller number means they hold less. It is a weekly figure as of a Wednesday and is published with a delay of about a week. It is not the same as how much debt exists, and it does not say which way
prices will go. It describes what already happened: it is not a market signal or a forecast. Amounts are in millions of dollars in the source and shown here in billions. Shown with the date; a failure says
so and shows nothing; demo mode invents nothing.
"""
from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timedelta, timezone

import httpx

URL = "https://markets.newyorkfed.org/api/pd/get/{key}.json"
KEY, KEY_CHANGE = "PDPOSGST-TOT", "PDPOSGST-TOTC"
SOURCE = "Federal Reserve Bank of New York, Primary Dealer Statistics (official, free public data)"
PAGE = "https://www.newyorkfed.org/markets/counterparties/primary-dealers-statistics"
TTL = 6 * 3600.0
FAIL_TTL = 120.0
OVERDUE_AFTER_DAYS = 16                    # a Wednesday's figure is published about the Thursday a week later; two weeks of lag is normal


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None                        # the source uses "*" and "N/A" for weeks it does not report


def parse(payload: dict) -> dict[date, float]:
    """{as-of date: millions of dollars}. Weeks the source marks "*" or "N/A" are left out and counted by the caller; an unreadable date refuses the response."""
    out: dict[date, float] = {}
    for r in (payload.get("pd") or {}).get("timeseries") or []:
        try:
            d = date.fromisoformat(r["asofdate"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("a row had no usable date")
        v = _num(r.get("value"))
        if v is not None:
            out[d] = v
    if len(out) < 10:
        raise ValueError("the response did not contain enough weeks")
    return out


def summarize(level: dict[date, float], change: dict[date, float], today: date) -> dict:
    dates = sorted(level)
    d = dates[-1]
    prev = dates[-2]
    b = lambda v: round(v / 1000.0, 1)
    gap = (d - prev).days
    wk = round(level[d] - level[prev], 6) if gap == 7 else None             # only a true week-on-week change is shown as one
    src = change.get(d)
    check = None
    if wk is not None and src is not None:
        # Own arithmetic against the source's own "change from previous week" series, over the last 26 weeks.
        pairs = [(x, y) for x, y in zip(dates[-27:-1], dates[-26:]) if (y - x).days == 7 and y in change]
        bad = [y for x, y in pairs if abs((level[y] - level[x]) - change[y]) > 1.0]
        check = {"weeks": len(pairs), "mismatches": len(bad), "match": len(pairs) > 0 and not bad, "latest_ours_billions": b(wk), "latest_source_billions": b(src)}
    target = d - timedelta(days=364)
    ya = [x for x in dates if abs((x - target).days) <= 3]
    ya_day = ya[0] if ya else None
    window = [x for x in dates if x > d - timedelta(days=365)]
    lo, hi = min(window, key=lambda x: level[x]), max(window, key=lambda x: level[x])
    lower = sum(1 for x in window if level[x] < level[d])
    age = (today - d).days
    return {"available": True, "date": d.isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE", "source": SOURCE,
            "net_position_billions": b(level[d]), "previous_date": prev.isoformat(), "week_change_billions": b(wk) if wk is not None else None,
            "year_ago_date": ya_day.isoformat() if ya_day else None, "year_ago_billions": b(level[ya_day]) if ya_day else None,
            "range_52w": {"weeks": len(window), "low_billions": b(level[lo]), "low_date": lo.isoformat(), "high_billions": b(level[hi]), "high_date": hi.isoformat(), "weeks_lower_than_now": lower},
            "check": check, "history": [{"date": x.isoformat(), "net_billions": b(level[x])} for x in dates[-104:]],
            "note": "Primary dealers are the large banks that trade directly with the Federal Reserve and buy Treasury auctions. The net position is what they own minus what they have sold short, in Treasury bills, notes "
                    "and bonds (not inflation-protected securities), as of a Wednesday and published about a week later. A bigger number means dealers hold more Treasuries on their own books. It does not say which way "
                    "prices will go. This describes what already happened: not a market signal or a forecast."}


class Dealers:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def _get(self, c: httpx.AsyncClient, key: str) -> dict:
        r = await c.get(URL.format(key=key), headers={"User-Agent": "ATLAS research terminal"})
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        return r.json()

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo, "url": PAGE}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real primary dealer figures are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=30)
        try:
            lv, ch = await asyncio.gather(self._get(c, KEY), self._get(c, KEY_CHANGE))
            try:
                change = parse(ch)
            except ValueError:
                change = {}
            res = {**base, **summarize(parse(lv), change, now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as e:
            res = {**base, "available": False, "reason": f"The New York Fed could not be read right now ({type(e).__name__}: {str(e)[:80]})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
