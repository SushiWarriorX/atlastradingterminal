"""US household income, spending and saving: the monthly Personal Income and Outlays and the quarterly split of consumer spending of the Bureau of Economic Analysis, as FRED, the St. Louis Fed, carries them (public-domain US government data, citation requested; every series page read on 2026-11-19 names only the Bureau as its source, with no third-party notice). Free, no key.

How to read it: personal income (PI) is what households receive (pay, business and investment income, benefits); personal current taxes (W055RC1) are what they pay on it; what is left is disposable personal income (DSPI). Personal outlays (A068RC1) are what they spend: consumer spending (PCE, the MONTHLY series), interest payments (B069RC1) and everything else, which the card gets by subtraction. Personal saving (PMSAVE) is disposable income minus outlays, and the personal saving rate (PSAVERT) is saving as a percent of disposable income. All of these are in billions of dollars at a seasonally adjusted annual rate and in the prices of the time (not adjusted for inflation): 24,289.0 means 24.289 trillion dollars a year at the pace of that month. Consumer spending by type comes from the GDP release, quarterly: durable goods (PCDG), nondurable goods (PCND) and services (PCESV) add up to PCEC (the QUARTERLY consumer spending; FRED's PCE is monthly). Each monthly observation is dated the 1st and means the whole month.
Each series is asked for ALONE, never in a combined request: with several ids and one start date FRED applies the date to the FIRST series only and gives every other series in full, without an error (found 2026-11-18 while reading the JOLTS series). Every request starts at 1959-01-01, the first month of the monthly series, so the whole record is checked each time.
Checks, set from the whole real record (813 months from January 1959, 271 quarters from 1959-Q1; the quarterly series start in 1947) before any test was written: the eight monthly series end in the same month, cover the same months and skip none, the four quarterly series end in the same quarter, cover the same quarters and skip none (dated the 1st of January, April, July or October), at least 120 months and 40 quarters are there, and every level and the rate lie inside a range set well outside the real one. Then the sums, all on every month or quarter downloaded because none has an exception: personal income minus taxes equals disposable income and disposable income minus outlays equals saving, each to within 5/32 of a billion (three values each rounded to 0.1 differ by at most 0.15; the real gap is 0 in about three months in four and 0.1 in the rest); the saving rate equals 100 x saving / disposable income to within 9/128 of a point (the published decimal gives 0.05, the rounding of the levels up to 0.0158 more in 1959; the real largest gap is 0.0548); the three types of spending add up to the quarterly total to within 2 to the power -8 (four values each rounded to 0.001; the real gap is at most 0.001); the quarterly consumer spending equals the average of the monthly consumer spending of its three months to within 2 to the power -4 of a billion (the mean of three values rounded to 0.1 plus the quarterly rounding is 0.0505; the real largest gap is 0.0457 in 271 quarters), a check BETWEEN two tables of the same Bureau; and consumer spending plus interest payments never exceed outlays by more than the same rounding (the rest, the real 0.7 to 307.2 billion, is a property that must hold). All tolerances are exact in binary.
These sums are the Bureau's own accounting (it calculates disposable income, saving and the rate from income, taxes and outlays; the series page of the rate says so): they show that the series belong to one release and are lined up, not that the figures are right. The one comparison across two tables is the closest thing to an independent check. NOT checked, and said so: nominal against real spending (different price bases), what the rest of outlays consists of, and any bound on a month's move (April 2020 and March 2021 are the real extremes). A quarter newer than the monthly series, as after an advance estimate of GDP, is skipped by the comparison with its months and counted. A failure says so and shows nothing.
It describes what already happened: it is not a market signal or a forecast. The newest months are revised in later releases.
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
from .usgdp import _qlabel, _quarters_back

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SOURCE = "U.S. Bureau of Economic Analysis, Personal Income and Outlays (monthly) and consumer spending by type from the GDP release (quarterly), via FRED, St. Louis Fed (official, free public data)"
PAGE = "https://fred.stlouisfed.org/series/PSAVERT"
START = "1959-01-01"                             # the first month of the monthly series: every request asks for the whole record
MONTHLY = ("PI", "W055RC1", "DSPI", "A068RC1", "PCE", "B069RC1", "PMSAVE")
RATE = "PSAVERT"
QUARTERLY = ("PCEC", "PCDG", "PCND", "PCESV")
SERIES = [*MONTHLY, RATE, *QUARTERLY]
NAMES = {"PI": "personal income", "W055RC1": "personal taxes", "DSPI": "disposable income", "A068RC1": "personal outlays", "PCE": "monthly consumer spending", "B069RC1": "interest payments",
         "PMSAVE": "personal saving", "PSAVERT": "saving rate", "PCEC": "quarterly consumer spending", "PCDG": "durable goods", "PCND": "nondurable goods", "PCESV": "services"}
LIMITS = {"PI": (200.0, 100_000.0), "W055RC1": (20.0, 15_000.0), "DSPI": (200.0, 80_000.0), "A068RC1": (150.0, 80_000.0), "PCE": (150.0, 80_000.0), "B069RC1": (2.0, 3_000.0),
          "PMSAVE": (-500.0, 20_000.0), "PCEC": (150.0, 80_000.0), "PCDG": (20.0, 10_000.0), "PCND": (60.0, 20_000.0), "PCESV": (60.0, 60_000.0)}      # billions; the real ranges since 1959 are inside (personal income 391.8 to 27,707.8, saving 31.4 to 5,955.2)
RATE_LIMITS = (-10.0, 60.0)                      # percent; the real record runs from 1.4 (2005-07) to 31.8 (2020-04)
INCOME_TOLERANCE = 5 / 32                        # billions: three values each rounded to 0.1 differ by at most 0.15; the real largest gap is 0.1; exact in binary
RATE_TOLERANCE = 9 / 128                         # points: 0.05 for the published decimal plus up to 0.0158 for the rounding of the levels (1959); the real largest gap is 0.0548; exact in binary
SPLIT_TOLERANCE = 2 ** -8                        # billions: four values each rounded to 0.001 differ by at most 0.002; the real largest gap is 0.001; exact in binary
MEAN_TOLERANCE = 2 ** -4                         # billions: the mean of three values rounded to 0.1 plus the quarterly rounding is 0.0505; the real largest gap is 0.0457; exact in binary
OTHER_FLOOR = -5 / 32                            # billions: outlays minus spending minus interest is never below this (three values rounded to 0.1); the real record runs from 0.7 to 307.2
MIN_MONTHS = 120
MIN_QUARTERS = 40
RECENT_MONTHS = 6
OVERDUE_AFTER_DAYS = 100                         # from the 1st of the observed month: a month is released 55 to 61 days after its 1st (September on 29 October, 58 days) and stays the newest until the next release (October on 25 November, when September is 85 days old), so about 91 days is normal; 9 days of slack
QUARTER_OVERDUE_AFTER_DAYS = 240                 # from the 1st of the observed quarter: the next quarter's first estimate comes about 211 days after it, so 29 days of slack
TTL = 6 * 3600.0
FAIL_TTL = 120.0
SPLIT = (("durable", "Durable goods", "PCDG"), ("nondurable", "Nondurable goods", "PCND"), ("services", "Services", "PCESV"))      # a type of spending, its label and its series


def _quarter_months(d: date) -> list[date]:
    """The three months of the quarter that starts on `d` (the 1st of January, April, July or October)."""
    return [date(d.year, d.month + k, 1) for k in range(3)]


def _check(data: dict[str, dict[date, float]]) -> tuple[list[date], list[date], dict]:
    monthly = [*MONTHLY, RATE]
    if len({max(data[sid]) for sid in monthly}) != 1:
        raise ValueError("the monthly household series end in different months")
    if len({max(data[sid]) for sid in QUARTERLY}) != 1:
        raise ValueError("the spending split series end in different quarters")
    for sid in monthly[1:]:
        if set(data[sid]) != set(data["PI"]):
            raise ValueError(f"the {NAMES[sid]} series covers different months than personal income")
    for sid in QUARTERLY[1:]:
        if set(data[sid]) != set(data["PCEC"]):
            raise ValueError(f"the {NAMES[sid]} series covers different quarters than quarterly consumer spending")
    months, quarters = sorted(data["PI"]), sorted(data["PCEC"])
    if any(d.day != 1 for d in months):
        raise ValueError("a household date is not the 1st of a month")
    if any(d.day != 1 or d.month not in (1, 4, 7, 10) for d in quarters):
        raise ValueError("a spending split date is not the 1st of a quarter")
    for a, b in zip(months, months[1:]):
        if _months_back(b, 1) != a:
            raise ValueError(f"the household months skip a month after {_label(a)}")
    for a, b in zip(quarters, quarters[1:]):
        if _quarters_back(b, 1) != a:
            raise ValueError(f"the spending split quarters skip a quarter after {_qlabel(a)}")
    if len(months) < MIN_MONTHS:
        raise ValueError(f"the household record covers {len(months)} months, fewer than the {MIN_MONTHS} expected")
    if len(quarters) < MIN_QUARTERS:
        raise ValueError(f"the spending split covers {len(quarters)} quarters, fewer than the {MIN_QUARTERS} expected")
    for sid, (lo, hi) in LIMITS.items():
        quarterly = sid in QUARTERLY
        for d in (quarters if quarterly else months):
            v = data[sid][d]
            if not (lo <= v <= hi):
                raise ValueError(f"the {NAMES[sid]} of {_num(v)} billion in {_qlabel(d) if quarterly else _label(d)} is outside {_num(lo)} to {_num(hi)}")
    lo, hi = RATE_LIMITS
    for d in months:
        v = data[RATE][d]
        if not (lo <= v <= hi):
            raise ValueError(f"the saving rate of {v:g}% in {_label(d)} is outside {lo:g} to {hi:g}")
    income = saving = rate = 0.0
    for d in months:
        gap = abs(data["PI"][d] - data["W055RC1"][d] - data["DSPI"][d])
        if gap > INCOME_TOLERANCE:
            raise ValueError(f"income minus taxes differs from disposable income by {gap:.2f} billion in {_label(d)}, over {INCOME_TOLERANCE:g}")
        income = max(income, gap)
    for d in months:
        gap = abs(data["DSPI"][d] - data["A068RC1"][d] - data["PMSAVE"][d])
        if gap > INCOME_TOLERANCE:
            raise ValueError(f"disposable income minus outlays differs from saving by {gap:.2f} billion in {_label(d)}, over {INCOME_TOLERANCE:g}")
        saving = max(saving, gap)
    for d in months:
        want = 100.0 * data["PMSAVE"][d] / data["DSPI"][d]
        gap = abs(want - data[RATE][d])
        if gap > RATE_TOLERANCE:
            raise ValueError(f"the saving rate is {data[RATE][d]:g}% in {_label(d)} but {want:.2f}% from the levels, over {RATE_TOLERANCE:g}")
        rate = max(rate, gap)
    smallest = None
    for d in months:
        rest = data["A068RC1"][d] - data["PCE"][d] - data["B069RC1"][d]
        if rest < OTHER_FLOOR:
            raise ValueError(f"spending plus interest exceed personal outlays by {-rest:.1f} billion in {_label(d)}")
        smallest = rest if smallest is None else min(smallest, rest)
    split = 0.0
    for d in quarters:
        gap = abs(data["PCEC"][d] - data["PCDG"][d] - data["PCND"][d] - data["PCESV"][d])
        if gap > SPLIT_TOLERANCE:
            raise ValueError(f"the three spending types differ from the total by {gap:.3f} billion in {_qlabel(d)}, over {SPLIT_TOLERANCE:g}")
        split = max(split, gap)
    mean, compared = 0.0, 0
    for d in quarters:
        inside = _quarter_months(d)
        if not all(m in data["PCE"] for m in inside):
            continue
        gap = abs(data["PCEC"][d] - sum(data["PCE"][m] for m in inside) / 3.0)
        if gap > MEAN_TOLERANCE:
            raise ValueError(f"quarterly spending differs from the average of its months by {gap:.3f} billion in {_qlabel(d)}, over {MEAN_TOLERANCE:g}")
        mean, compared = max(mean, gap), compared + 1
    if compared < MIN_QUARTERS:
        raise ValueError(f"quarterly spending could be compared with its months in only {compared} quarters, fewer than the {MIN_QUARTERS} expected")
    return months, quarters, {"months_checked": len(months), "first_month": _label(months[0]), "last_month": _label(months[-1]),
                              "quarters_checked": len(quarters), "first_quarter": _qlabel(quarters[0]), "last_quarter": _qlabel(quarters[-1]), "quarters_compared": compared,
                              "largest_income_gap": round(income, 3), "largest_saving_gap": round(saving, 3), "largest_rate_gap": round(rate, 4),
                              "largest_split_gap": round(split, 4), "largest_mean_gap": round(mean, 4), "smallest_other_outlays": round(smallest, 1)}


def _pct(a: float, b: float) -> float:
    return round(100.0 * (a / b - 1.0), 2)


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    months, quarters, detail = _check(data)
    last, qlast = months[-1], quarters[-1]
    before, ago, qago = _months_back(last, 1), _months_back(last, 12), _quarters_back(qlast, 4)
    rate, age, qage = data[RATE], (today - last).days, (today - qlast).days

    def line(key: str, label: str, sid: str) -> dict:
        v = data[sid]
        return {"key": key, "label": label, "level_billions": v[last], "change_pct": _pct(v[last], v[before]), "change_year_pct": _pct(v[last], v[ago])}

    out = data["A068RC1"][last]
    rest = round(out - data["PCE"][last] - data["B069RC1"][last], 1)
    sav = data["PMSAVE"]
    parts = [{**line("spending", "Consumer spending", "PCE"), "share_pct": round(100.0 * data["PCE"][last] / out, 1)},
             {**line("interest", "Interest payments", "B069RC1"), "share_pct": round(100.0 * data["B069RC1"][last] / out, 1)},
             {"key": "other", "label": "Everything else", "level_billions": rest, "share_pct": round(100.0 * rest / out, 1)}]
    total = data["PCEC"][qlast]
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "month": _label(last), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "saving": {"rate_pct": rate[last], "month_before_pct": rate[before], "year_ago_pct": rate[ago], "level_billions": sav[last],
                       "change_billions": round(sav[last] - sav[before], 1), "change_year_billions": round(sav[last] - sav[ago], 1), "range": _range(rate, rate[last], months[0])},
            "income": [line("income", "Personal income", "PI"), line("taxes", "Taxes on it", "W055RC1"), line("disposable", "Disposable income", "DSPI")],
            "outlays": {**line("outlays", "Personal outlays", "A068RC1"), "parts": parts},
            "split": {"quarter": _qlabel(qlast), "date": qlast.isoformat(), "age_days": qage, "freshness": "CURRENT" if qage <= QUARTER_OVERDUE_AFTER_DAYS else "OVERDUE",
                      "total_billions": total, "total_change_year_pct": _pct(total, data["PCEC"][qago]),
                      "parts": [{"key": key, "label": label, "level_billions": data[sid][qlast], "share_pct": round(100.0 * data[sid][qlast] / total, 1), "change_year_pct": _pct(data[sid][qlast], data[sid][qago])}
                                for key, label, sid in SPLIT]},
            "recent": [{"month": _label(m), "saving_rate_pct": rate[m], "income_change_pct": _pct(data["DSPI"][m], data["DSPI"][_months_back(m, 1)]), "spending_change_pct": _pct(data["PCE"][m], data["PCE"][_months_back(m, 1)])}
                       for m in (_months_back(last, i) for i in range(RECENT_MONTHS - 1, -1, -1))],
            "detail": detail,
            "checks": {"months_in_a_row": True, "quarters_in_a_row": True, "range_ok": True, "income_adds_up_ok": True, "saving_adds_up_ok": True, "rate_follows_levels_ok": True,
                       "outlays_cover_spending_ok": True, "spending_types_add_up_ok": True, "quarter_matches_months_ok": True},
            "note": ("The monthly Personal Income and Outlays of the US Bureau of Economic Analysis, seasonally adjusted. "
                     "Personal income is what households receive; taxes come off it, and what is left is disposable income. "
                     "Outlays are what they spend: consumer spending, interest payments and everything else (found by subtraction). "
                     "Saving is disposable income minus outlays, and the saving rate is saving as a share of disposable income. "
                     "Figures are billions of dollars at a seasonally adjusted annual rate and in the prices of the time, not adjusted for inflation. "
                     "The split of consumer spending into durable goods, nondurable goods and services is quarterly, from the GDP release. "
                     "The newest months are revised in later releases; each figure carries its month. "
                     "Plain checks: the units are the ones assumed and no month or quarter is missing; the ranges, the sums and the comparison of the quarter with its months are in the Check line. "
                     "This describes household finances that already happened: it is not a market signal or a forecast.")}


class UsHousehold:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def _fetch(self, c: httpx.AsyncClient, sid: str) -> dict[date, float]:
        # One series per request: with several ids a single cosd applies to the first series only. No custom User-Agent: FRED stalls and drops connections for an unfamiliar one (seen 2026-11-12) and answers the client's default one fast.
        r = await c.get(URL, params={"id": sid, "cosd": START})
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        return parse(r.text, sid)

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real US household figures are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=25)
        try:
            got = await asyncio.gather(*[self._fetch(c, sid) for sid in SERIES])
            res = {**base, **summarize(dict(zip(SERIES, got)), now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, KeyError) as e:
            res = {**base, "available": False, "reason": f"US household figures could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
