"""US bank loans and leases: what US commercial banks held in loans and leases on a Wednesday, in all and by kind (business loans, real estate, consumer loans, all other loans and leases), with real estate split into residential (closed-end loans and home equity lines) and commercial (nonfarm nonresidential, multifamily, construction and land development, farmland) and the loans to nondepository financial institutions inside the all-other kind, from the Board of Governors of the Federal Reserve System's H.8 Assets and Liabilities of Commercial Banks release (public-domain US government data), via FRED, the St. Louis Fed. Free, no key.

How to read it: every figure is the level on a Wednesday (the release comes on the Friday nine days later), weekly, seasonally adjusted, in billions of dollars, for all commercial banks in the United States. A change is how much the banks' loan book grew or shrank, not how many loans were made or repaid. The levels are NOT corrected for breaks: in the week of 2025-01-01 about 236 billion dollars moved into loans to nondepository financial institutions out of business loans (134 billion) and consumer loans (118 billion) while the total moved by -10 billion, which looks like a reclassification between kinds, not lending (read from the data; the series pages do not say), so a change over a period that spans that week mixes real lending with relabelled loans. It is a description of what already happened, not a forecast.
Each series is asked for ALONE, never in a combined request: with several ids and one start date FRED applies the date to the FIRST series only and gives every other series in full, without an error (found 2026-11-18). Every request starts at 2015-01-07, the first Wednesday all 14 series share (619 weeks to 2026-11-11), and no custom User-Agent is sent (FRED stalls on an unfamiliar one).
Checks, set from the whole real record (619 weeks, none missing in any of the 14 series; the 14 series pages say Public Domain: Citation Requested and their notes hold only contact lines) before any test was written: the 14 series end in the same week, cover the same weeks, are dated a Wednesday and skip no week; every series stays inside a limit fixed from its real lowest and highest value (about half the lowest and about twice the highest, because levels grow); four sums hold to the rounding of the published figures, which are kept to 0.0001 billion dollars, so each tolerance is the arithmetic bound of its figures each rounded to 0.0001 (0.00005 each): total loans = business + real estate + consumer + all other (the real largest gap is 0.0002 and the tolerance 0.00025, five figures), real estate = residential + commercial (0.0001; 0.00015, three figures), residential = closed-end + home equity (0.0001; 0.00015) and commercial real estate = construction + nonfarm nonresidential + multifamily + farmland (0.0002; 0.00025); and loans to nondepository financial institutions never exceed all other loans (the real smallest margin is 706 billion). The checks run in this order, the oldest week first: the weeks, the ranges, the four sums in the order above, then the nondepository check.
The sums are the Federal Reserve's own arithmetic: they show that the series belong to one release and are lined up, not that the figures are right. NOT checked, and said so: revisions of older weeks, which series is wrong when a check fails (the message says only that they disagree), the breaks described above, the other groups of banks the release has (domestically chartered, large, small and foreign-related) and the not seasonally adjusted figures.
It describes what already happened: it is not a market signal or a forecast. A failure says so and shows nothing.
"""
from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from .failreason import fail_reason
from .fincond import parse
from .jolts import _num
from .usinventories import _change

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SOURCE = "Board of Governors of the Federal Reserve System, H.8 Assets and Liabilities of Commercial Banks, via FRED, St. Louis Fed (official, free public data)"
PAGE = "https://fred.stlouisfed.org/series/TOTLL"
START = "2015-01-07"                                   # the first Wednesday all 14 series share: 619 weeks to 2026-11-11
TOT, CI, REL, CON, AOL = "TOTLL", "TOTCI", "RELACBW027SBOG", "CLSACBW027SBOG", "AOLACBW027SBOG"
RRE, CRE, CRL, RHE = "RREACBW027SBOG", "CREACBW027SBOG", "CRLACBW027SBOG", "RHEACBW027SBOG"
CLD, SNF, SMP, SBF, LNF = "CLDACBW027SBOG", "SNFACBW027SBOG", "SMPACBW027SBOG", "SBFACBW027SBOG", "LNFACBW027SBOG"
NAMES = {TOT: "total loans", CI: "business loans", REL: "real estate loans", CON: "consumer loans", AOL: "other loans", RRE: "residential loans", CRE: "commercial real estate", CRL: "closed-end residential",
         RHE: "home equity loans", CLD: "construction loans", SNF: "nonfarm nonresidential", SMP: "multifamily loans", SBF: "farmland loans", LNF: "nondepository loans"}           # short on purpose: fail_reason shows 110 characters
SERIES = list(NAMES)
LIMITS = {TOT: (3810.0, 28600.0), CI: (890.0, 6200.0), REL: (1820.0, 11800.0), CON: (590.0, 3900.0), AOL: (510.0, 7000.0), RRE: (1010.0, 5500.0), CRE: (800.0, 6400.0), CRL: (780.0, 4900.0),
          RHE: (120.0, 920.0), CLD: (110.0, 990.0), SNF: (530.0, 3900.0), SMP: (110.0, 1300.0), LNF: (160.0, 4300.0), SBF: (40.0, 250.0)}                                     # billions of dollars; the real ranges are in the log
SUMS = ((TOT, (CI, REL, CON, AOL), 0.00025, "the four kinds"), (REL, (RRE, CRE), 0.00015, "residential plus commercial"),
        (RRE, (CRL, RHE), 0.00015, "closed-end plus home equity"), (CRE, (CLD, SNF, SMP, SBF), 0.00025, "its four parts"))                  # a whole, its parts, the tolerance (0.00005 for each figure) and how the message says the parts
KINDS = (("business", "Business loans (commercial and industrial)", CI), ("real_estate", "Real estate loans", REL), ("consumer", "Consumer loans", CON), ("other", "All other loans and leases", AOL))
REAL_ESTATE = (("residential", "Residential real estate", RRE, (("closed_end", "Closed-end residential loans", CRL), ("home_equity", "Home equity lines of credit", RHE))),
               ("commercial", "Commercial real estate", CRE, (("nonfarm_nonresidential", "Office, retail and other nonfarm nonresidential", SNF), ("multifamily", "Multifamily housing", SMP),
                                                                ("construction", "Construction and land development", CLD), ("farmland", "Farmland", SBF))))
MIN_WEEKS = 572                                        # ten years of year-on-year growth need 520 weeks with a week 52 weeks before each
HISTORY_WEEKS = 520
RECENT_WEEKS = 6
OVERDUE_AFTER_DAYS = 18                                # from the Wednesday: the figures come on the Friday 9 days later and are replaced 7 days after that, so they are 9 to 15 days old; a missed release shows as overdue at 18 (read from the series pages on 2026-11-25, not verified over a longer time)
TTL = 6 * 3600.0
FAIL_TTL = 120.0
CONCURRENCY = 6
WEEK = timedelta(days=7)
YEAR = timedelta(days=364)                             # 52 weeks


def _check_ranges(data: dict[str, dict[date, float]], weeks: list[date]) -> None:
    for sid in SERIES:
        lo, hi = LIMITS[sid]
        for d in weeks:
            v = data[sid][d]
            if not (lo <= v <= hi):
                raise ValueError(f"{NAMES[sid]} of {_num(v)} on {d.isoformat()} is outside {_num(lo)} to {_num(hi)}")


def _check(data: dict[str, dict[date, float]]) -> tuple[list[date], dict]:
    base = data[TOT]
    if len({max(data[sid]) for sid in SERIES}) != 1:
        raise ValueError("the bank loan series end in different weeks")
    for sid in SERIES[1:]:
        if set(data[sid]) != set(base):
            raise ValueError(f"the {NAMES[sid]} series covers different weeks than total loans")
    weeks = sorted(base)
    if any(d.weekday() != 2 for d in weeks):
        raise ValueError("a bank loan date is not a Wednesday")
    for a, b in zip(weeks, weeks[1:]):
        if b - a != WEEK:
            raise ValueError(f"the bank loan weeks skip a week after {a.isoformat()}")
    if len(weeks) < MIN_WEEKS:
        raise ValueError(f"the bank loan series cover {len(weeks)} weeks, fewer than the {MIN_WEEKS} expected")
    _check_ranges(data, weeks)
    gap_max = 0.0
    for whole, parts, tolerance, what in SUMS:
        for d in weeks:
            gap = abs(data[whole][d] - sum(data[p][d] for p in parts))
            if gap > tolerance:
                raise ValueError(f"{NAMES[whole]} is {gap:.4f} billion off {what} on {d.isoformat()}, over {tolerance:g}")
            gap_max = max(gap_max, gap)
    for d in weeks:
        if data[LNF][d] > data[AOL][d]:
            raise ValueError(f"nondepository loans of {_num(data[LNF][d])} exceed other loans of {_num(data[AOL][d])} on {d.isoformat()}")
    return weeks, {"weeks_checked": len(weeks), "first_week": weeks[0].isoformat(), "last_week": weeks[-1].isoformat(), "largest_sum_gap": round(gap_max, 5)}


def _diff(now: float, then: float) -> float:
    return round(now - then, 4) + 0.0                  # billions to 0.0001; a fall that rounds to nothing is 0.0, not -0.0


def _range_weeks(values: dict[date, float], now: float, first: date) -> dict:
    """Lowest, highest (the earliest week when several are equal) and the share of weeks strictly lower than `now`, over the weeks in `values` (oldest first)."""
    lo, hi = min(values, key=values.get), max(values, key=values.get)
    return {"weeks": len(values), "first": first.isoformat(), "lowest": {"value": values[lo], "date": lo.isoformat()}, "highest": {"value": values[hi], "date": hi.isoformat()},
            "share_lower_pct": round(100 * sum(1 for v in values.values() if v < now) / len(values))}


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    weeks, detail = _check(data)
    last = weeks[-1]
    window = weeks[-HISTORY_WEEKS:]
    before, ago = last - WEEK, last - YEAR
    tot = data[TOT]
    growth = {d: _change(tot[d], tot[d - YEAR]) for d in window}
    total = {"loans_billions": tot[last], "change_week_billions": _diff(tot[last], tot[before]), "change_week_pct": _change(tot[last], tot[before]),
             "change_year_billions": _diff(tot[last], tot[ago]), "change_year_pct": growth[last], "growth_range": _range_weeks(growth, growth[last], window[0])}
    kinds = []
    for key, label, sid in KINDS:
        s = data[sid]
        kinds.append({"key": key, "label": label, "billions": s[last], "share_pct": round(100.0 * s[last] / tot[last], 1),
                      "change_week_billions": _diff(s[last], s[before]), "change_week_pct": _change(s[last], s[before]),
                      "change_year_billions": _diff(s[last], s[ago]), "change_year_pct": _change(s[last], s[ago])})
    real_estate = [{"key": key, "label": label, "billions": data[sid][last], "share_pct": round(100.0 * data[sid][last] / data[REL][last], 1),
                    "parts": [{"key": k, "label": lb, "billions": data[p][last]} for k, lb, p in parts]} for key, label, sid, parts in REAL_ESTATE]
    age = (today - last).days
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "total": total, "kinds": kinds, "real_estate": real_estate,
            "other": {"nondepository_billions": data[LNF][last], "share_of_other_pct": round(100.0 * data[LNF][last] / data[AOL][last], 1)},
            "recent": [{"date": d.isoformat(), "total_billions": tot[d], "change_billions": _diff(tot[d], tot[d - WEEK])} for d in weeks[-RECENT_WEEKS:]],
            "detail": detail,
            "checks": {"weeks_in_a_row": True, "range_ok": True, "sums_ok": True, "nondepository_within_other_ok": True},
            "note": ("The H.8 release of the Federal Reserve Board for all commercial banks in the United States: the level on a Wednesday, weekly, seasonally adjusted, in billions of dollars, published on the Friday nine days later. "
                     "A change is how much the banks' loan book grew or shrank, not how many loans were made or repaid. "
                     "The levels are not corrected for reclassifications between kinds: in the week of January 1, 2025 about $236 billion moved into loans to nondepository financial institutions out of business and consumer loans while the total hardly moved, "
                     "so a change across that week mixes real lending with relabelled loans. The newest weeks are revised later. "
                     "Plain checks: the units are the ones assumed and no week is missing; the ranges, the sums and the nondepository check are in the Check line. "
                     "This describes bank lending that already happened: it is not a market signal or a forecast.")}


class UsBankLoans:
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
            return {**base, "available": False, "reason": "Demo mode: the real US bank loan figures are not shown because made-up values would look real."}
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
            res = {**base, "available": False, "reason": f"US bank loans could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
