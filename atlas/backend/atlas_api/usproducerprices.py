"""US producer prices: how the prices US producers get for what they sell change, from the Bureau of Labor Statistics' Producer Price Index, as FRED, the St. Louis Fed, carries it (public-domain US government data, citation requested; every series page says so and has no note beyond its units; the banner's copyright line is FRED's template, as on the other Bureau pages).

The nine series, all monthly, seasonally adjusted, dated the 1st and meaning the whole month, each an index with its own base period: PPIFIS, final demand (November 2009 = 100); PPIFES, final demand less foods and energy (April 2010 = 100); WPSFD49207, finished goods; WPSFD49502, finished consumer goods; WPSFD4111, finished consumer foods; WPSFD4121, finished consumer energy goods (all 1982 = 100); WPSID61 and WPSID62, processed and unprocessed goods for intermediate demand (1982 = 100); WPSID63, services for intermediate demand (November 2009 = 100). Producer price indexes have no sums: the levels of two series cannot be added, so every check here is a plain one.
Checks, set from the whole real record before any test was written (every series complete, none skipped, every date the 1st, no blank; the oldest begin in 1947 and the youngest, final demand less foods and energy, in April 2010, which is where every request starts): the nine series end in the same month and cover exactly the same months, each dated the 1st, none skipped, at least 132 of them (ten years of growth on a year earlier need 120 months with a month a year before each); every index lies inside a range set from the whole record (about half the lowest and twice the highest value ever published); no month moves by more than a limit set the same way from the largest monthly rise and fall ever published. The ranges and limits are literals in the tests.
These are the Bureau's own price indexes: the checks show that the series belong to one release, are lined up and are plausible, not that the figures are right. A month is released about 13 days after it ends and stays the newest until the next release, so the card is overdue only after 75 days from the 1st of the month.
It describes prices that already happened: it is not a market signal or a forecast.
"""
from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timezone

import httpx

from .failreason import fail_reason
from .fincond import parse
from .jolts import _num, _range
from .moneysupply import _label, _months_back

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SOURCE = "U.S. Bureau of Labor Statistics, Producer Price Index (final demand, finished goods and intermediate demand), via FRED, St. Louis Fed (official, free public data)"
PAGE = "https://fred.stlouisfed.org/series/PPIFIS"
START = "2010-04-01"                              # the first month of the youngest series (final demand less foods and energy): every request asks for the record from there
FINAL, CORE, FINISHED, CONSUMER, FOODS, ENERGY, PROCESSED, UNPROCESSED, SERVICES = "PPIFIS", "PPIFES", "WPSFD49207", "WPSFD49502", "WPSFD4111", "WPSFD4121", "WPSID61", "WPSID62", "WPSID63"
SERIES = (FINAL, CORE, FINISHED, CONSUMER, FOODS, ENERGY, PROCESSED, UNPROCESSED, SERVICES)
NAMES = {FINAL: "final demand", CORE: "core final demand", FINISHED: "finished goods", CONSUMER: "finished consumer goods", FOODS: "finished consumer foods", ENERGY: "finished consumer energy",
         PROCESSED: "processed intermediate goods", UNPROCESSED: "unprocessed intermediate goods", SERVICES: "intermediate services"}
LABELS = {FINAL: "Final demand", CORE: "Final demand without foods and energy", FINISHED: "Finished goods", CONSUMER: "Finished consumer goods", FOODS: "Finished consumer foods", ENERGY: "Finished consumer energy goods",
          PROCESSED: "Processed goods for intermediate demand", UNPROCESSED: "Unprocessed goods for intermediate demand", SERVICES: "Services for intermediate demand"}
KEYS = {FINAL: "final", CORE: "core", FINISHED: "finished", CONSUMER: "consumer", FOODS: "foods", ENERGY: "energy", PROCESSED: "processed", UNPROCESSED: "unprocessed", SERVICES: "services"}
BASES = {FINAL: "November 2009 = 100", CORE: "April 2010 = 100", FINISHED: "1982 = 100", CONSUMER: "1982 = 100", FOODS: "1982 = 100", ENERGY: "1982 = 100",
         PROCESSED: "1982 = 100", UNPROCESSED: "1982 = 100", SERVICES: "November 2009 = 100"}
GROUPS = (("final", "Final demand", (FINAL, CORE)),
          ("finished", "Finished goods", (FINISHED, CONSUMER, FOODS, ENERGY)),
          ("intermediate", "Intermediate demand: what producers pay", (PROCESSED, UNPROCESSED, SERVICES)))
# About half the lowest and twice the highest index in the whole record (the real extremes are in the comment of each line)
LIMITS = {FINAL: (50.0, 320.0),                   # 100.2 (2009-11) to 160.254
          CORE: (50.0, 315.0),                    # 99.9 to 156.74
          FINISHED: (13.0, 580.0),                # 26.0 (1947-04) to 288.52
          CONSUMER: (14.0, 620.0),                # 28.3 to 310.993
          FOODS: (15.0, 580.0),                   # 31.0 to 290.449
          ENERGY: (10.0, 560.0),                  # 20.0 (1974-01) to 280.601
          PROCESSED: (11.0, 600.0),               # 23.0 to 299.923
          UNPROCESSED: (14.0, 720.0),             # 29.0 to 359.898
          SERVICES: (50.0, 330.0)}                # 100.0 (2009-11) to 166.167
# Percent in a month: about twice the largest fall and rise in the whole record (the real extremes are in the comment of each line)
MOVE_LIMITS = {FINAL: (-4.0, 4.0),                # -1.19 (2020-04) and +1.68 (2022-03)
               CORE: (-3.0, 3.0),                 # -0.37 and +1.20
               FINISHED: (-8.0, 8.0),             # -3.03 (2008-11) and +3.52 (1973-08)
               CONSUMER: (-10.0, 10.0),           # -3.88 (2020-04) and +4.38 (1973-08)
               FOODS: (-20.0, 20.0),              # -4.60 (2020-06) and +9.52 (1973-08)
               ENERGY: (-32.0, 32.0),             # -15.66 (2020-04) and +13.36 (1990-01)
               PROCESSED: (-11.0, 11.0),          # -5.12 (2008-11) and +4.49 (1974-08)
               UNPROCESSED: (-45.0, 45.0),        # -15.77 (2003-04) and +22.10 (1973-08)
               SERVICES: (-4.0, 4.0)}             # -1.72 (2020-04) and +1.29 (2022-03)
MIN_MONTHS = 132
HISTORY_MONTHS = 120
RECENT_MONTHS = 6
OVERDUE_AFTER_DAYS = 75                           # from the 1st of the observed month: a month comes out about 13 days after it ends (October on 13 November) and stays the newest until the next release, 70 to 71 days after its 1st
TTL = 6 * 3600.0
FAIL_TTL = 120.0
CONCURRENCY = 6


def _check(data: dict[str, dict[date, float]]) -> tuple[list[date], dict]:
    if len({max(data[sid]) for sid in SERIES}) != 1:
        raise ValueError("the producer price series end in different months")
    for sid in SERIES[1:]:
        if set(data[sid]) != set(data[FINAL]):
            raise ValueError(f"the {NAMES[sid]} series covers different months than final demand")
    months = sorted(data[FINAL])
    if any(d.day != 1 for d in months):
        raise ValueError("a producer price date is not the 1st of a month")
    for a, b in zip(months, months[1:]):
        if _months_back(b, 1) != a:
            raise ValueError(f"the producer price months skip a month after {_label(a)}")
    if len(months) < MIN_MONTHS:
        raise ValueError(f"the producer price record covers {len(months)} months, fewer than the {MIN_MONTHS} expected")
    for sid in SERIES:
        lo, hi = LIMITS[sid]
        for d in months:
            v = data[sid][d]
            if not (lo <= v <= hi):
                raise ValueError(f"the {NAMES[sid]} index of {_num(v)} in {_label(d)} is outside {_num(lo)} to {_num(hi)}")
    for sid in SERIES:
        lo, hi = MOVE_LIMITS[sid]
        for a, b in zip(months, months[1:]):
            change = round(100.0 * (data[sid][b] / data[sid][a] - 1.0), 4)         # four decimals: a move of exactly the limit is not refused for the last bit of a float
            if not (lo <= change <= hi):
                raise ValueError(f"the {NAMES[sid]} moved {change:+.1f}% in {_label(b)}, outside {lo:g} to {hi:g}")
    return months, {"months_checked": len(months), "first_month": _label(months[0]), "last_month": _label(months[-1])}


def _pct(a: float, b: float) -> float:
    return round(100.0 * (a / b - 1.0), 2) + 0.0                                    # + 0.0 turns a negative zero into zero


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    months, detail = _check(data)
    last = months[-1]
    before, ago = _months_back(last, 1), _months_back(last, 12)
    final, core = data[FINAL], data[CORE]
    window = months[-HISTORY_MONTHS:]
    growth = {d: 100.0 * (final[d] / final[_months_back(d, 12)] - 1.0) for d in window}
    age = (today - last).days

    def line(sid: str) -> dict:
        s = data[sid]
        return {"key": KEYS[sid], "label": LABELS[sid], "base": BASES[sid], "index": s[last], "change_pct": _pct(s[last], s[before]), "change_year_pct": _pct(s[last], s[ago])}

    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "month": _label(last), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "headline": {**line(FINAL), "core_change_year_pct": _pct(core[last], core[ago]), "range": _range(growth, growth[last], window[0])},
            "groups": [{"key": key, "label": label, "items": [line(sid) for sid in sids]} for key, label, sids in GROUPS],
            "recent": [{"month": _label(m), "change_pct": _pct(final[m], final[_months_back(m, 1)]), "core_change_pct": _pct(core[m], core[_months_back(m, 1)])}
                       for m in (_months_back(last, i) for i in range(RECENT_MONTHS - 1, -1, -1))],
            "detail": detail,
            "checks": {"months_in_a_row": True, "range_ok": True, "moves_ok": True},
            "note": ("Producer price indexes from the Bureau of Labor Statistics: how the prices US producers receive for what they sell change over time, seasonally adjusted and published monthly. "
                     "Final demand is what is sold to households, businesses, government and foreign buyers, in goods, services and construction; finished goods are goods ready for sale to final users; intermediate demand is what producers buy from each other as inputs. "
                     "Each series has its own base, the number beside it, so the levels of two series cannot be compared, only their changes. "
                     "The newest months are revised in later releases. "
                     "Plain checks: the units are the ones assumed and no month is missing; the ranges and the monthly moves are in the Check line. "
                     "This describes prices that already happened: it is not a market signal or a forecast.")}


class UsProducerPrices:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def _fetch(self, c: httpx.AsyncClient, gate: asyncio.Semaphore, sid: str) -> dict[date, float]:
        # One series per request: with several ids a single cosd applies to the first series only. No custom User-Agent: FRED stalls and drops connections for an unfamiliar one (seen 2026-11-12) and answers the client's default one fast.
        async with gate:
            r = await c.get(URL, params={"id": sid, "cosd": START})
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        return parse(r.text, sid)

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real US producer price figures are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=25)
        try:
            gate = asyncio.Semaphore(CONCURRENCY)
            got = await asyncio.gather(*[self._fetch(c, gate, sid) for sid in SERIES])
            res = {**base, **summarize(dict(zip(SERIES, got)), now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, KeyError) as e:
            res = {**base, "available": False, "reason": f"US producer prices could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
