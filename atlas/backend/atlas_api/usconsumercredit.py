"""US consumer credit: how much American households owe on credit cards and other revolving plans (revolving credit) and on car, student and other instalment loans (nonrevolving credit), from the G.19 Consumer Credit release of the Board of Governors of the Federal Reserve System (public-domain US government data), via FRED, the St. Louis Fed. Free, no key.

How to read it: the figures are the amount owed at the END of the month, in millions of dollars, seasonally adjusted, and they leave out loans secured by real estate (mortgages and home-equity loans). Total consumer credit is revolving plus nonrevolving. A month-to-month change is how much the amount owed grew or shrank; it says nothing about whether the loans are repaid. It is a description of what already happened, not a forecast.
Each series is asked for ALONE, never in a combined request: with several ids and one start date FRED applies the date to the FIRST series only and gives every other series in full, without an error (found 2026-11-18). Every request starts at 1990-01-01 and no custom User-Agent is sent (FRED stalls on an unfamiliar one).
Checks, set from the whole real record (441 months, January 1990 to September 2026; none missing in any of the 3 series) before any test was written: the 3 series end in the same month, cover the same months, are dated the 1st and skip no month; every series stays inside a limit fixed from its real lowest and highest value (a level: about half the lowest and about twice the highest, because levels grow); and total consumer credit equals revolving plus nonrevolving credit to the rounding of the published figures: the figures are kept to 0.01 million dollars, the real largest gap is 0.01 (in 104 of the 441 months, exactly 0 in the other 337) and the tolerance is the arithmetic bound of three figures each rounded to 0.01, 0.015. The checks run in this order, the oldest month first: the months, the ranges, the sum.
The sum is the Federal Reserve's own arithmetic: it shows that the series belong to one release and are lined up, not that the figures are right. NOT checked, and said so: the revisions of older months (the Board revises the whole history from time to time), which of the series is wrong when the sum fails (the message says only that they disagree), and the breakdown of nonrevolving credit by lender or by purpose (the release has it; it is not used here).
It describes what already happened: it is not a market signal or a forecast. A failure says so and shows nothing.
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
from .usinventories import _change

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SOURCE = "Board of Governors of the Federal Reserve System, G.19 Consumer Credit, via FRED, St. Louis Fed (official, free public data)"
PAGE = "https://fred.stlouisfed.org/series/TOTALSL"
START = "1990-01-01"                                   # the first month of the record: 441 months to 2026-09
NAMES = {"TOTALSL": "total consumer credit", "REVOLSL": "revolving credit", "NONREVSL": "nonrevolving credit"}           # short on purpose: fail_reason shows 110 characters
SERIES = list(NAMES)
KINDS = (("revolving", "Revolving credit (credit cards and other revolving plans)", "REVOLSL"),
         ("nonrevolving", "Nonrevolving credit (car, student and other instalment loans)", "NONREVSL"))
LIMITS = {"TOTALSL": (400_000.0, 10_500_000.0), "REVOLSL": (100_000.0, 2_800_000.0), "NONREVSL": (260_000.0, 8_000_000.0)}          # millions of dollars; the real ranges are in the log
SUM_TOLERANCE = 0.015                                  # millions: three values each rounded to 0.01 (0.005 each); the real largest gap is 0.01
MIN_MONTHS = 132                                       # ten years of year-on-year growth need 120 months with a month a year before each
HISTORY_MONTHS = 120
RECENT_MONTHS = 6
OVERDUE_AFTER_DAYS = 105                               # from the 1st of the observed month: the figures of a month come about the 5th business day of the second month after it, so they are replaced about 97 days after their own 1st; a week of grace (assumed, not verified)
TTL = 6 * 3600.0
FAIL_TTL = 120.0
CONCURRENCY = 3


def _check_ranges(data: dict[str, dict[date, float]], months: list[date]) -> None:
    for sid in SERIES:
        lo, hi = LIMITS[sid]
        for d in months:
            v = data[sid][d]
            if not (lo <= v <= hi):
                raise ValueError(f"{NAMES[sid]} of {_num(v)} in {_label(d)} is outside {_num(lo)} to {_num(hi)}")


def _check(data: dict[str, dict[date, float]]) -> tuple[list[date], dict]:
    base = data["TOTALSL"]
    if len({max(data[sid]) for sid in SERIES}) != 1:
        raise ValueError("the consumer credit series end in different months")
    for sid in SERIES[1:]:
        if set(data[sid]) != set(base):
            raise ValueError(f"the {NAMES[sid]} series covers different months than total consumer credit")
    months = sorted(base)
    if any(d.day != 1 for d in months):
        raise ValueError("a consumer credit date is not the 1st of a month")
    for a, b in zip(months, months[1:]):
        if _months_back(b, 1) != a:
            raise ValueError(f"the consumer credit months skip a month after {_label(a)}")
    if len(months) < MIN_MONTHS:
        raise ValueError(f"the consumer credit series cover {len(months)} months, fewer than the {MIN_MONTHS} expected")
    _check_ranges(data, months)
    gap_max = 0.0
    for d in months:
        gap = abs(data["TOTALSL"][d] - data["REVOLSL"][d] - data["NONREVSL"][d])
        if gap > SUM_TOLERANCE:
            raise ValueError(f"{NAMES['TOTALSL']} is {gap:.3f} million off revolving plus nonrevolving in {_label(d)}, over {SUM_TOLERANCE:g}")
        gap_max = max(gap_max, gap)
    return months, {"months_checked": len(months), "first_month": _label(months[0]), "last_month": _label(months[-1]), "largest_sum_gap": round(gap_max, 4)}


def _diff(now: float, then: float) -> float:
    return round(now - then, 2) + 0.0                  # millions to the cent; a fall that rounds to nothing is 0.0, not -0.0


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    months, detail = _check(data)
    last = months[-1]
    window = months[-HISTORY_MONTHS:]
    ago, before = _months_back(last, 12), _months_back(last, 1)
    tot, rev, non = data["TOTALSL"], data["REVOLSL"], data["NONREVSL"]
    growth = {d: _change(tot[d], tot[_months_back(d, 12)]) for d in window}
    total = {"total_millions": tot[last], "revolving_millions": rev[last], "nonrevolving_millions": non[last], "revolving_share_pct": round(100.0 * rev[last] / tot[last], 1),
             "change_month_millions": _diff(tot[last], tot[before]), "change_month_pct": _change(tot[last], tot[before]),
             "change_year_millions": _diff(tot[last], tot[ago]), "change_year_pct": growth[last],
             "growth_range": _range(growth, growth[last], window[0])}
    kinds = []
    for key, label, sid in KINDS:
        s = data[sid]
        kinds.append({"key": key, "label": label, "millions": s[last], "share_pct": round(100.0 * s[last] / tot[last], 1),
                      "change_month_millions": _diff(s[last], s[before]), "change_month_pct": _change(s[last], s[before]),
                      "change_year_millions": _diff(s[last], s[ago]), "change_year_pct": _change(s[last], s[ago])})
    age = (today - last).days
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "month": _label(last), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "total": total, "kinds": kinds,
            "recent": [{"month": _label(d), "total_millions": tot[d], "revolving_millions": rev[d], "nonrevolving_millions": non[d], "change_millions": _diff(tot[d], tot[_months_back(d, 1)])} for d in months[-RECENT_MONTHS:]],
            "detail": detail,
            "checks": {"months_in_a_row": True, "range_ok": True, "totals_add_up_ok": True},
            "note": ("The G.19 Consumer Credit release of the Federal Reserve Board, seasonally adjusted, monthly, in millions of dollars owed at the end of the month. "
                     "Revolving credit is mostly credit cards; nonrevolving credit is mostly car and student loans. Loans secured by real estate (mortgages, home-equity loans) are not included. "
                     "A month-to-month change is how much the amount owed grew or shrank: it does not say whether the loans are being repaid. "
                     "The newest months are preliminary and are revised later, and the whole history is revised from time to time. "
                     "Plain checks: the units are the ones assumed and no month is missing; the ranges and the sum are in the Check line. "
                     "This describes household borrowing that already happened: it is not a market signal or a forecast.")}


class UsConsumerCredit:
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
            return {**base, "available": False, "reason": "Demo mode: the real US consumer credit figures are not shown because made-up values would look real."}
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
            res = {**base, "available": False, "reason": f"US consumer credit could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
