"""US retail gasoline price: the weekly national average for regular grade, in dollars a gallon, from the US Energy Information Administration (public-domain US government data) via FRED, the St. Louis Fed. Free, no key.

How to read it: it is the national average pump price on the Monday shown (the EIA samples about 900 retail outlets at 8:00AM that Monday; FRED lists the series as weekly, ending Monday). It follows crude oil with a delay and adds refining, distribution, marketing and taxes. EIA data reach FRED within a day or two, so the newest figure is normally 1 to 8 days old and carries its own date.
Checks: every date is a Monday, the last 12 weeks are exactly one week apart, the last 60 prices are between $0.50 and $10 a gallon, no weekly move over 25% in the last 60 weeks, and the price is consistent with crude oil: gasoline per barrel (price x 42 gallons) minus the WTI crude price on or before that Monday is between $10 and $130 a barrel (it has been $40 to $113 since 2018; a unit slip in either series would break it). A missing value ('.') is left out, never filled in.
The crude price: for each of the last 8 Mondays the nearest WTI price on the Monday or up to 5 days before it (after a Monday holiday it is the Friday, 3 days back; measured 2026-11-25 on the record from 2018-01-01: of 465 Mondays 412 have crude on the day and 51 three days back, and of the other two one is the newest, below, and one is the first of the window, which has no earlier crude in it). The newest Monday alone may use a price up to 8 days before it: EIA posts the Monday gasoline price on Tuesday morning and the crude prices only once a week, on Wednesday, through the Tuesday before, so for about 27 hours every week the newest Monday has its crude price 6 days back (read 2026-11-25: GASREGW to 2026-11-23, DCOILWTICO to 2026-11-17). Before 2026-11-25 the card refused itself in that window (found 2026-11-24); now it shows the newest price and the day of the crude price it was checked against.
It describes what already happened: it is not a market signal or a forecast. A failure says so and shows nothing.
"""
from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from .claims import _pct, reading
from .fincond import parse
from .failreason import fail_reason

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SOURCE = "US Energy Information Administration weekly retail gasoline prices, via FRED, St. Louis Fed (official, free public data)"
PAGE = "https://fred.stlouisfed.org/series/GASREGW"
SERIES = {"GASREGW": "gasoline", "DCOILWTICO": "wti"}
GALLONS_PER_BARREL = 42.0
LIMITS = (0.5, 10.0)                 # dollars a gallon (the real range since 2018 is 1.77 to 5.01)
MAX_WEEK_MOVE = 0.25                 # the largest real weekly move since 2018 is 16.2%
MARGIN_LIMITS = (10.0, 130.0)        # gasoline per barrel minus WTI, dollars a barrel (the real range since 2018 is 40.1 to 113.1; a /10 slip in WTI would give about 159)
OVERDUE_AFTER_DAYS = 14
TTL = 6 * 3600.0
FAIL_TTL = 120.0
WEEK = 7
LOOKUP_DAYS = 5                      # a settled Monday: its crude price is on the Monday or, after a holiday, 3 days back
NEWEST_LOOKUP_DAYS = 8               # the newest Monday only: it waits for the weekly crude release (6 days back for about 27 hours a week); 8 leaves two days for a delayed or holiday-shifted release


def _wti_near(wti: dict[date, float], day: date, lookup: int) -> tuple[date, float] | None:
    """The day and price of the nearest WTI price on `day` or up to `lookup` days before it."""
    for back in range(lookup + 1):
        d = day - timedelta(days=back)
        v = wti.get(d)
        if v is not None:
            return d, v
    return None


def _words(d: date) -> str:
    """A day as a person reads it ("November 23, 2026"): a refusal is shown on the phone, which writes dates in words (the Macro browser test fails on a raw 2026-11-23)."""
    return f"{d:%B} {d.day}, {d.year}"


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    g, w = data["GASREGW"], data["DCOILWTICO"]
    if any(d.weekday() != 0 for d in g):
        raise ValueError("GASREGW has a date that is not a Monday")
    weeks = sorted(g)
    last = weeks[-1]
    if any((b - a).days != WEEK for a, b in zip(weeks[-12:], weeks[-11:])):
        raise ValueError("the last weeks are not one week apart")
    recent = weeks[-60:]
    if any(not (LIMITS[0] <= g[d] <= LIMITS[1]) for d in recent):
        raise ValueError("a gasoline price is outside the plausible range")
    if any(abs(g[b] / g[a] - 1) > MAX_WEEK_MOVE for a, b in zip(recent, recent[1:])):
        raise ValueError(f"gasoline moved more than {MAX_WEEK_MOVE:.0%} in a week")
    margins, crude_day = {}, {}
    for d in weeks[-8:]:
        near = _wti_near(w, d, NEWEST_LOOKUP_DAYS if d == last else LOOKUP_DAYS)
        if near is None:
            raise ValueError(f"there is no WTI crude price near {_words(d)} to check the gasoline price against")
        crude_day[d] = near[0]
        margins[d] = g[d] * GALLONS_PER_BARREL - near[1]
    if any(not (MARGIN_LIMITS[0] <= m <= MARGIN_LIMITS[1]) for m in margins.values()):
        bad = next(d for d, m in margins.items() if not (MARGIN_LIMITS[0] <= m <= MARGIN_LIMITS[1]))
        raise ValueError(f"gasoline per barrel minus WTI crude is {margins[bad]:.1f} on {_words(bad)}, outside {MARGIN_LIMITS[0]:g} to {MARGIN_LIMITS[1]:g}")
    v = g[last]
    year = [d for d in weeks if 0 <= (last - d).days <= 52 * WEEK]
    vals = [g[d] for d in year]
    rank = round(100 * sum(1 for x in vals if x <= v) / len(vals))
    prev, four, yago = g.get(last - timedelta(days=WEEK)), g.get(last - timedelta(days=4 * WEEK)), g.get(last - timedelta(days=52 * WEEK))
    wti_last = w[crude_day[last]]
    age = (today - last).days
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "price": round(v, 3), "change_1w": None if prev is None else round(v - prev, 3), "change_4w_pct": _pct(v, four), "change_1y_pct": _pct(v, yago),
            "year_low": round(min(vals), 3), "year_high": round(max(vals), 3), "weeks_in_year": len(vals), "rank_in_year": rank, "reading": reading(rank),
            "crude": {"wti": round(wti_last, 2), "date": crude_day[last].isoformat(), "per_barrel": round(v * GALLONS_PER_BARREL, 2), "gap": round(margins[last], 2)},
            "history": [{"date": d.isoformat(), "price": round(g[d], 3)} for d in weeks[-52:]],
            "checks": {"mondays_ok": True, "weekly_spacing_ok": True, "range_ok": True, "weekly_move_ok": True, "consistent_with_crude": True},
            "note": ("This is the national average price of regular gasoline at the pump in dollars a gallon, on the Monday shown (a sample of about 900 retail outlets at 8:00AM that Monday), from the US Energy Information Administration. It follows crude oil with a delay and adds refining, distribution, marketing and taxes. "
                     "Checked: every date is a Monday, the last 12 weeks are one week apart, recent prices are between $0.50 and $10, no weekly move is over 25%, and gasoline per barrel minus WTI crude is inside the range it has really had (crude prices come once a week, after the gasoline price, so the newest Monday is checked against the latest crude price, which can be a few days older). "
                     "This describes what already happened: it is not a market signal or a forecast.")}


class GasolinePrices:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def _fetch(self, c: httpx.AsyncClient, sid: str) -> dict[date, float]:
        # No custom User-Agent: FRED stalls and drops connections for an unfamiliar one (seen 2026-11-12) and answers the client's default one fast. cosd keeps the download to about two years.
        r = await c.get(URL, params={"id": sid, "cosd": (date.today() - timedelta(days=800)).isoformat()})
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        return parse(r.text, sid)

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real gasoline prices are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=25)
        try:
            got = await asyncio.gather(*[self._fetch(c, sid) for sid in SERIES])
            res = {**base, **summarize(dict(zip(SERIES, got)), now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, KeyError) as e:
            res = {**base, "available": False, "reason": f"Gasoline prices could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
