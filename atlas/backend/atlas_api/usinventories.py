"""US business inventories and sales: what American manufacturers, merchant wholesalers and retailers held on their shelves at the end of a month, what they sold during it, and how many months of sales the shelves hold (the inventories-to-sales ratio), from the Manufacturing and Trade Inventories and Sales release of the U.S. Census Bureau (public-domain US government data), via FRED, the St. Louis Fed. Free, no key.

How to read it: inventories are what is on hand at the END of the month and sales are the whole month's sales, both in millions of dollars of the day (not corrected for price changes) and seasonally adjusted; the ratio is the month's inventories over the same month's sales, so 1.33 means the shelves hold about one and a third months of sales. A ratio that rises says goods are piling up faster than they sell; one that falls says shelves are emptying faster than they refill. It is a description of what already happened, not a forecast.
Each series is asked for ALONE, never in a combined request: with several ids and one start date FRED applies the date to the FIRST series only and gives every other series in full, without an error (found 2026-11-18). Every request starts at 1992-01-01 and no custom User-Agent is sent (FRED stalls on an unfamiliar one).
Checks, set from the whole real record (417 months, January 1992 to September 2026; none missing in any of the 12 series) before any test was written: the 12 series end in the same month, cover the same months, are dated the 1st and skip no month; every series stays inside a limit fixed from its real lowest and highest value (a level: about half the lowest and about twice the highest, because levels grow; a ratio: 0.8 times the lowest and 1.26 times the highest); total inventories equal manufacturers' plus wholesalers' plus retailers' inventories and total sales equal the sum of the three kinds' sales, and they hold EXACTLY in all 417 months (a gap of 0), so the tolerance of 2 million is not a measured gap but the arithmetic bound of four figures each rounded to a million; and each of the four published ratios matches its inventories over its sales to its two decimals: the real largest gap is 0.004996 (half a hundredth is 0.005), so the tolerance is 0.0051. The checks run in this order, the oldest month first: the months, the ranges, the inventory sum, the sales sum, then the ratios.
The sums and the ratios are the Census Bureau's own arithmetic: they show that the series belong to one release and are lined up, not that the figures are right. NOT checked, and said so: the revisions of older months, which of the series is wrong when a check fails (the message says only that they disagree), and the figures in prices that remove inflation (the same release has them; they are not used here).
It describes what already happened: it is not a market signal or a forecast. A failure says so and shows nothing.
"""
from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timezone

import httpx

from .claims import _pct
from .failreason import fail_reason
from .fincond import parse
from .jolts import _num, _range
from .moneysupply import _label, _months_back

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SOURCE = "U.S. Census Bureau, Manufacturing and Trade Inventories and Sales, via FRED, St. Louis Fed (official, free public data)"
PAGE = "https://fred.stlouisfed.org/series/BUSINV"
START = "1992-01-01"                                   # the first month of the record: 417 months to 2026-09
KINDS = (("manufacturers", "Manufacturers", "MNFCTRIMSA", "MNFCTRSMSA", "MNFCTRIRSA"),
         ("wholesalers", "Merchant wholesalers", "WHLSLRIMSA", "WHLSLRSMSA", "WHLSLRIRSA"),
         ("retailers", "Retailers", "RETAILIMSA", "RETAILSMSA", "RETAILIRSA"))
NAMES = {"BUSINV": "total inventories", "TOTBUSSMSA": "total sales", "ISRATIO": "total ratio", "MNFCTRIMSA": "manufacturers' inventories", "WHLSLRIMSA": "wholesalers' inventories",
         "RETAILIMSA": "retailers' inventories", "MNFCTRSMSA": "manufacturers' sales", "WHLSLRSMSA": "wholesalers' sales", "RETAILSMSA": "retailers' sales",
         "MNFCTRIRSA": "manufacturers' ratio", "WHLSLRIRSA": "wholesalers' ratio", "RETAILIRSA": "retailers' ratio"}           # short on purpose: fail_reason shows 110 characters
SERIES = list(NAMES)
RATIO_IDS = ("ISRATIO", "MNFCTRIRSA", "WHLSLRIRSA", "RETAILIRSA")
LIMITS = {"BUSINV": (400_000.0, 6_000_000.0), "TOTBUSSMSA": (250_000.0, 4_500_000.0), "ISRATIO": (1.0, 2.2),
          "MNFCTRIMSA": (180_000.0, 2_000_000.0), "WHLSLRIMSA": (90_000.0, 2_100_000.0), "RETAILIMSA": (110_000.0, 1_800_000.0),
          "MNFCTRSMSA": (110_000.0, 1_400_000.0), "WHLSLRSMSA": (70_000.0, 1_700_000.0), "RETAILSMSA": (70_000.0, 1_300_000.0),
          "MNFCTRIRSA": (0.9, 2.4), "WHLSLRIRSA": (0.9, 2.1), "RETAILIRSA": (0.9, 2.2)}      # millions of dollars, and ratios; the real ranges are in the log
SUMS = (("BUSINV", ("MNFCTRIMSA", "WHLSLRIMSA", "RETAILIMSA")), ("TOTBUSSMSA", ("MNFCTRSMSA", "WHLSLRSMSA", "RETAILSMSA")))          # a total and the three kinds that make it
RATIOS = (("ISRATIO", "BUSINV", "TOTBUSSMSA"), ("MNFCTRIRSA", "MNFCTRIMSA", "MNFCTRSMSA"), ("WHLSLRIRSA", "WHLSLRIMSA", "WHLSLRSMSA"), ("RETAILIRSA", "RETAILIMSA", "RETAILSMSA"))
SUM_TOLERANCE = 2.0                                    # millions: four values each rounded to a million (0.5 each); the real largest gap is 0.0; exact in binary
RATIO_TOLERANCE = 0.0051                               # half a hundredth (the ratios are published to two decimals) plus the rounding of the figures they are worked from; the real largest gap is 0.004996
MIN_MONTHS = 120
HISTORY_MONTHS = 120
RECENT_MONTHS = 6
OVERDUE_AFTER_DAYS = 110                               # from the 1st of the observed month: the figures of a month come about the 15th of the second month after it, so they are replaced about 105 days after their own 1st; 5 days of grace
TTL = 6 * 3600.0
FAIL_TTL = 120.0
CONCURRENCY = 6


def _fmt(sid: str, v: float) -> str:
    return f"{v:.2f}" if sid in RATIO_IDS else _num(v)


def _limit(sid: str, lo: float, hi: float) -> str:
    return f"{lo:g} to {hi:g}" if sid in RATIO_IDS else f"{_num(lo)} to {_num(hi)}"


def _check_ranges(data: dict[str, dict[date, float]], months: list[date]) -> None:
    for sid in SERIES:
        lo, hi = LIMITS[sid]
        for d in months:
            v = data[sid][d]
            if not (lo <= v <= hi):
                raise ValueError(f"{NAMES[sid]} of {_fmt(sid, v)} in {_label(d)} is outside {_limit(sid, lo, hi)}")


def _check(data: dict[str, dict[date, float]]) -> tuple[list[date], dict]:
    base = data["BUSINV"]
    if len({max(data[sid]) for sid in SERIES}) != 1:
        raise ValueError("the inventory series end in different months")
    for sid in SERIES[1:]:
        if set(data[sid]) != set(base):
            raise ValueError(f"the {NAMES[sid]} series covers different months than total inventories")
    months = sorted(base)
    if any(d.day != 1 for d in months):
        raise ValueError("an inventory date is not the 1st of a month")
    for a, b in zip(months, months[1:]):
        if _months_back(b, 1) != a:
            raise ValueError(f"the inventory months skip a month after {_label(a)}")
    if len(months) < MIN_MONTHS:
        raise ValueError(f"the inventory series cover {len(months)} months, fewer than the {MIN_MONTHS} expected")
    _check_ranges(data, months)
    sum_gap = 0.0
    for whole, parts in SUMS:
        for d in months:
            gap = abs(data[whole][d] - sum(data[p][d] for p in parts))
            if gap > SUM_TOLERANCE:
                raise ValueError(f"{NAMES[whole]} are {_num(gap)} million off the sum of the three kinds in {_label(d)}, over {SUM_TOLERANCE:g}")
            sum_gap = max(sum_gap, gap)
    ratio_gap = 0.0
    for ratio, inv, sales in RATIOS:
        for d in months:
            gap = abs(data[ratio][d] - data[inv][d] / data[sales][d])
            if gap > RATIO_TOLERANCE:
                raise ValueError(f"{NAMES[ratio]} {data[ratio][d]:.2f} is {gap:.4f} off inventories over sales in {_label(d)}, over {RATIO_TOLERANCE:g}")
            ratio_gap = max(ratio_gap, gap)
    return months, {"months_checked": len(months), "first_month": _label(months[0]), "last_month": _label(months[-1]), "largest_sum_gap": round(sum_gap, 5), "largest_ratio_gap": round(ratio_gap, 5)}


def _change(now: float, ago: float) -> float | None:
    v = _pct(now, ago)
    return None if v is None else v + 0.0              # a tiny fall that rounds to nothing is 0.0, not -0.0 (JSON would write the sign)


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    months, detail = _check(data)
    last = months[-1]
    window = months[-HISTORY_MONTHS:]
    ago, before = _months_back(last, 12), _months_back(last, 1)
    inv, sal, rat = data["BUSINV"], data["TOTBUSSMSA"], data["ISRATIO"]
    total = {"inventories_millions": inv[last], "sales_millions": sal[last], "ratio": rat[last],
             "inventories_change_month_pct": _change(inv[last], inv[before]), "sales_change_month_pct": _change(sal[last], sal[before]),
             "inventories_change_year_pct": _change(inv[last], inv[ago]), "sales_change_year_pct": _change(sal[last], sal[ago]), "ratio_year_ago": rat[ago],
             "ratio_range": _range({d: rat[d] for d in window}, rat[last], window[0])}
    rows = []
    for key, label, i, s, r in KINDS:
        rows.append({"key": key, "label": label, "inventories_millions": data[i][last], "sales_millions": data[s][last], "ratio": data[r][last],
                     "share_pct": round(100.0 * data[i][last] / inv[last], 1), "inventories_change_year_pct": _change(data[i][last], data[i][ago]),
                     "sales_change_year_pct": _change(data[s][last], data[s][ago]), "ratio_year_ago": data[r][ago],
                     "ratio_range": _range({d: data[r][d] for d in window}, data[r][last], window[0])})
    rows.sort(key=lambda x: (-x["inventories_millions"], x["label"]))
    age = (today - last).days
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "month": _label(last), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "total": total, "sectors": rows,
            "recent": [{"month": _label(d), "inventories_millions": inv[d], "sales_millions": sal[d], "ratio": rat[d]} for d in months[-RECENT_MONTHS:]],
            "detail": detail,
            "checks": {"months_in_a_row": True, "range_ok": True, "totals_add_up_ok": True, "ratios_match_ok": True},
            "note": ("The Manufacturing and Trade Inventories and Sales release of the US Census Bureau, seasonally adjusted, monthly, in millions of dollars of the day (not corrected for price changes). "
                     "Inventories are what manufacturers, merchant wholesalers and retailers hold on the last day of the month; sales are the whole month's sales; the ratio is the month's inventories over the same month's sales, the number of months of sales the shelves hold. "
                     "A rising ratio says goods are piling up faster than they sell; a falling one says shelves are emptying faster than they refill. "
                     "The newest months are preliminary and are revised later. "
                     "Plain checks: the units are the ones assumed and no month is missing; the ranges, the sums and the ratios rebuilt from the levels are in the Check line. "
                     "This describes business activity that already happened: it is not a market signal or a forecast.")}


class UsInventories:
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
            return {**base, "available": False, "reason": "Demo mode: the real US business inventories and sales are not shown because made-up values would look real."}
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
            res = {**base, "available": False, "reason": f"US business inventories and sales could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
