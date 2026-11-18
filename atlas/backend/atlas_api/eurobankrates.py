"""Euro-area bank interest rates from the ECB Data Portal's public API (official, free, no key): what euro-area banks (monetary financial institutions) charge on NEW loans to firms and to households and what they pay on NEW deposits, monthly, with the ECB's own composite "cost of borrowing" indicators.

How to read it: "new business" means the loans and deposits agreed (or renegotiated) in the month, not the stock outstanding, so the rates follow the central bank's rates within a few months. The loan and deposit rates are annualised agreed rates on that new business, averaged over the euro area as it was in each month ("changing composition"), in percent a year; the volumes are the amounts of that new business in the month, in millions of euro. Two composite indicators, the ECB's cost of borrowing for firms and for house purchase, weight the rates on loans with different periods of fixed interest by a moving average of their volumes. The newest month is provisional (the ECB marks it "P") and is revised; it comes about five weeks after the month ends.
Checks, set from the whole real record before any test was written (285 months from January 2003 for all 40 series; eleven of the 22 rates start in 2000 and carry the status "estimated" for their first 36 months, which the card does not read; no month missing in any series): every series reports the units the card assumes (the ECB's own labels: percent per annum for a rate, euro in millions for a volume); all 40 series end in the same month and each has all of the last 36 months; each rate lies in -1% to +12% a year (the real record: -0.36% for firms' short deposits to 8.91% for consumer credit) and each volume in 100 to 1,000,000 million euro (real: 1,120 to 422,182); no loan, term-deposit or composite rate moves by more than 2 points in a month (the real extremes are +0.59 and -0.72) and no overnight deposit rate by more than 1 point (real: +0.10 and -0.37). The two overnight deposit rates and the two composites have no parts to check against; the range and the monthly move guard them.
**Three checks are the source's own arithmetic or a cross-series bound**; they show that the series fetched belong to one release and were not mixed up, not that the figures are right. (1) For each of the six blocks (firms, house purchase, consumer credit, other lending to households, and the term deposits of households and of firms) the volume of all new business equals the volume with a floating rate or up to one year of fixed interest plus the volume fixed for over one year, to 0.016 million euro in every month: the real gap is at most 0.010 in all 285 months of each block (the volumes are rounded to two decimals; the tolerance is 2 to the power -6, so that a gap of exactly the tolerance can be tested). (2) The rate on all new business equals the average of the two parts' rates weighted by their volumes, to 0.016 points: the real gap is at most 0.0093 points in all 285 months of each block (the rates are rounded to two decimals, so two roundings can account for up to 0.01), and it is checked over the last 24 months because the whole record holds without exception. (3) The composite cost of borrowing lies within 1 point of the rate on all new loans of the same borrowers: the real difference runs from -0.03 to +0.48 for firms and -0.11 to +0.12 for house purchase; it is a loose bound that only catches a x10 or /10 slip, not an identity.
A series that ends in another month, or a month missing from one, is refused. A missing value is left out, never filled in.
It describes what already happened: it is not a market signal or a forecast. A failure says so and shows nothing.
"""
from __future__ import annotations

import asyncio
import csv
import io
import math
import re
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from .failreason import fail_reason
from .moneysupply import _label, _months_back

BASE = "https://data-api.ecb.europa.eu/service/data/MIR/"
SOURCE = "European Central Bank, ECB Data Portal: interest rates that euro-area banks charge on new loans and pay on new deposits (MFI interest rate statistics, official, free public data)"
# block id -> (BS_ITEM, counterpart sector, name): six kinds of new business, each with all of it (A), the part with a floating rate or up to one year of fixed interest (F) and the part fixed for over one year (K)
BLOCKS = {
    "firms": ("A2A", "2240", "loans to firms"),
    "house": ("A2C", "2250", "loans for house purchase"),
    "consumer": ("A2B", "2250", "consumer credit"),
    "other": ("A2D", "2250", "other loans to households"),
    "household_term": ("L22", "2250", "household term deposits"),
    "firms_term": ("L22", "2240", "firms' term deposits"),
}
# single id -> (BS_ITEM, maturity code, counterpart sector, name): rates with no parts to check against
SINGLES = {
    "household_overnight": ("L21", "A", "2250", "household overnight deposits"),
    "firms_overnight": ("L21", "A", "2240", "firms' overnight deposits"),
    "firms_cost": ("A2I", "AM", "2240", "the ECB's cost of borrowing for firms"),
    "house_cost": ("A2C", "AM", "2250", "the ECB's cost of borrowing for house purchase"),
}
PARTS = ("A", "F", "K")
PART_WORDS = {"A": "all new business", "F": "floating or up to 1 year fixed", "K": "over 1 year fixed"}
RATE_UNIT = ("PCPA", "0")             # the ECB's own labels: percent per annum
VOLUME_UNIT = ("EUR", "6")            # euro, in millions
LABEL = {**{b: v[2] for b, v in BLOCKS.items()}, **{s: v[3] for s, v in SINGLES.items()}}
LOANS = ("firms", "house", "consumer", "other")
DEPOSITS = ("household_overnight", "household_term", "firms_overnight", "firms_term")
COSTS = ("firms_cost", "house_cost")
OVERNIGHT = ("household_overnight", "firms_overnight")
COST_OF = {"firms_cost": "firms", "house_cost": "house"}      # the composite and the rate on all new loans of the same borrowers


def _key(item: str, maturity: str, kind: str, sector: str) -> str:
    return f"M.U2.B.{item}.{maturity}.{kind}.A.{sector}.EUR.N"


SERIES: dict[str, tuple[str, tuple[str, str]]] = {}             # series id -> (key without "MIR.", units)
NAMES: dict[str, str] = {}
for _b, (_item, _sector, _name) in BLOCKS.items():
    for _p in PARTS:
        SERIES[f"{_b}.{_p}.rate"] = (_key(_item, _p, "R", _sector), RATE_UNIT)
        SERIES[f"{_b}.{_p}.volume"] = (_key(_item, _p, "B", _sector), VOLUME_UNIT)
        NAMES[f"{_b}.{_p}.rate"] = f"the rate on {_name} ({PART_WORDS[_p]})"
        NAMES[f"{_b}.{_p}.volume"] = f"the new business volume of {_name} ({PART_WORDS[_p]})"
for _s, (_item, _maturity, _sector, _name) in SINGLES.items():
    SERIES[f"{_s}.rate"] = (_key(_item, _maturity, "R", _sector), RATE_UNIT)
    NAMES[f"{_s}.rate"] = _name if _s in COSTS else f"the rate on {_name}"
PAGE = BASE + SERIES["firms_cost.rate"][0]


def _ids(blocks: tuple[str, ...], singles: tuple[str, ...] = ()) -> tuple[str, ...]:
    return tuple(f"{b}.{p}.{k}" for b in blocks for p in PARTS for k in ("rate", "volume")) + tuple(f"{s}.rate" for s in singles)


# the four requests: the key (the OR-list `+` must reach the host unencoded) and the series each one returns
REQUESTS = (
    ("M.U2.B.A2C+A2B+A2D.A+F+K.R+B.A.2250.EUR.N", _ids(("house", "consumer", "other"))),
    ("M.U2.B.A2A.A+F+K.R+B.A.2240.EUR.N", _ids(("firms",))),
    ("M.U2.B.L21+L22.A+F+K.R+B.A.2250+2240.EUR.N", _ids(("household_term", "firms_term"), OVERNIGHT)),
    ("M.U2.B.A2I+A2C.AM.R.A.2240+2250.EUR.N", tuple(f"{s}.rate" for s in COSTS)),
)
RATE_LIMITS = (-1.0, 12.0)            # percent a year; the real record runs from -0.36 to 8.91
VOLUME_LIMITS = (100.0, 1_000_000.0)  # millions of euro; the real record runs from 1,120 to 422,182
MONTH_MOVE = 2.0                      # points: the largest one-month move of a loan, term-deposit or composite rate (exact in binary, so a move of exactly the limit can be tested); the real extremes are +0.59 and -0.72
OVERNIGHT_MOVE = 1.0                  # points, for an overnight deposit rate; the real extremes are +0.10 and -0.37
SUM_TOLERANCE = 2 ** -6               # 0.015625 million euro: the real gap is at most 0.010 (two-decimal rounding)
RATE_TOLERANCE = 2 ** -6              # 0.015625 points: the real gap is at most 0.0093
COST_GAP = 1.0                        # points between a composite and the rate on all new loans of the same borrowers; the real record runs from -0.11 to +0.48
CHECK_MONTHS = 24                     # months of rates compared with the volume-weighted average
DEPTH = 36                            # months every series must have: the months of the sums and of the ranges
LAST_N = 125                          # observations asked for: the ten-year window, and a few more
RATE_WINDOW = 120                     # ten years of rates
MIN_WINDOW = 60
RECENT_MONTHS = 6
OVERDUE_AFTER_DAYS = 75               # from the end of the observed month: the next month normally arrives about 64 days after the previous one ends (September came on about 3 November, October on about 3 December)
TTL = 6 * 3600.0
FAIL_TTL = 120.0
TIMEOUT = 90.0                        # seconds for one request: the ECB's MIR service answered these four keys in 0.1 s (when it had them ready) to 84 s (when it did not), and one of 16 asks got no answer in 120 s
_MONTH = re.compile(r"\d{4}-\d{2}")
SHOWN = tuple(f"{b}.A.rate" for b in LOANS + ("household_term", "firms_term")) + tuple(f"{s}.rate" for s in OVERNIGHT + COSTS)     # the rates the card prints


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _month(x) -> date | None:
    """A month written exactly YYYY-MM, as the first of that month."""
    if not isinstance(x, str) or not _MONTH.fullmatch(x):
        return None
    try:
        return date(int(x[:4]), int(x[5:7]), 1)
    except ValueError:
        return None


def parse(text: str, ids: tuple[str, ...]) -> tuple[dict[str, dict[date, float]], dict[str, tuple[str, str]], dict[str, str]]:
    """Values by series id (for example "firms.A.rate") and month, the units each series reports (the ECB's UNIT and UNIT_MULT) and the status of each series' newest value ("A" normal, "P" provisional). Rows of any other series, and rows without a month or a number, are left out; two values for one month are an error."""
    values: dict[str, dict[date, float]] = {i: {} for i in ids}
    wanted = {"MIR." + SERIES[i][0]: i for i in ids}
    units: dict[str, tuple[str, str]] = {}
    newest: dict[str, tuple[date, str]] = {}
    for r in csv.DictReader(io.StringIO(text)):
        sid, d, v = wanted.get(r.get("KEY") or ""), _month(r.get("TIME_PERIOD")), _num(r.get("OBS_VALUE"))
        if sid is None or d is None or v is None:
            continue
        if d in values[sid]:
            raise ValueError(f"{sid} has two values for {_label(d)}")
        values[sid][d] = v
        units[sid] = ((r.get("UNIT") or "").strip(), (r.get("UNIT_MULT") or "").strip())
        if sid not in newest or d > newest[sid][0]:
            newest[sid] = (d, (r.get("OBS_STATUS") or "").strip())
    missing = [i for i in ids if not values[i]]
    if missing:
        raise ValueError("the source returned no values for " + ", ".join(missing))
    return values, units, {i: s for i, (d, s) in newest.items()}


def _check(v: dict[str, dict[date, float]], units: dict) -> tuple[date, dict]:
    for sid, u in units.items():
        if u != SERIES[sid][1]:
            raise ValueError(f"the ECB reports {NAMES[sid]} in other units than the card assumes")
    ends = {max(s) for s in v.values()}
    if len(ends) != 1:
        raise ValueError("the bank interest rate series end in different months")
    last = ends.pop()
    window = [_months_back(last, i) for i in range(DEPTH - 1, -1, -1)]               # oldest first
    for sid, s in v.items():
        for d in window:
            if d not in s:
                raise ValueError(f"{NAMES[sid]} is missing for {_label(d)}")
    for sid in v:
        lo, hi = RATE_LIMITS if sid.endswith(".rate") else VOLUME_LIMITS
        for d in window:
            x = v[sid][d]
            if not (lo <= x <= hi):
                if sid.endswith(".rate"):
                    raise ValueError(f"{NAMES[sid]} is {x:.2f}% in {_label(d)}, outside {lo:g}% to {hi:g}%")
                raise ValueError(f"{NAMES[sid]} is {x:,.0f} million euro in {_label(d)}, outside {lo:,.0f} to {hi:,.0f}")
    for sid in SHOWN:                                                                  # the rates the card prints must not jump
        limit = OVERNIGHT_MOVE if sid.split(".")[0] in OVERNIGHT else MONTH_MOVE
        for a, b in zip(window, window[1:]):
            ch = v[sid][b] - v[sid][a]
            if abs(ch) > limit:
                raise ValueError(f"{NAMES[sid]} moved by {ch:+.2f} points in {_label(b)}, more than {limit:g}")
    worst_sum = {"gap": 0.0, "month": last, "block": "firms"}
    for b in BLOCKS:                                                                   # the ECB's own arithmetic: the volumes add up
        for d in window:
            off = v[f"{b}.A.volume"][d] - v[f"{b}.F.volume"][d] - v[f"{b}.K.volume"][d]
            if abs(off) > SUM_TOLERANCE:
                raise ValueError(f"the new business volume of {LABEL[b]} is not the sum of its floating-rate and its longer-fixation parts in {_label(d)} (off by {off:+,.2f} million euro)")
            if abs(off) > abs(worst_sum["gap"]):
                worst_sum = {"gap": off, "month": d, "block": b}
    worst_rate = {"gap": 0.0, "month": last, "block": "firms"}
    for b in BLOCKS:                                                                   # and the rate on all of it is the volume-weighted average of the two parts' rates
        for d in window[-CHECK_MONTHS:]:
            vf, vk = v[f"{b}.F.volume"][d], v[f"{b}.K.volume"][d]
            average = (vf * v[f"{b}.F.rate"][d] + vk * v[f"{b}.K.rate"][d]) / (vf + vk)
            gap = v[f"{b}.A.rate"][d] - average
            if abs(gap) > RATE_TOLERANCE:
                raise ValueError(f"the rate on new {LABEL[b]} in {_label(d)} is {abs(gap):.3f} points away from the average of its two parts weighted by their volumes, more than {RATE_TOLERANCE:g}")
            if abs(gap) > abs(worst_rate["gap"]):
                worst_rate = {"gap": gap, "month": d, "block": b}
    for c, total in COST_OF.items():                                                   # a loose bound between two separately published rates
        for d in window:
            gap = v[f"{c}.rate"][d] - v[f"{total}.A.rate"][d]
            if abs(gap) > COST_GAP:
                raise ValueError(f"{NAMES[c + '.rate']} is {abs(gap):.2f} points away from the rate on {LABEL[total]} in {_label(d)}, more than {COST_GAP:g}")
    sum_shown, rate_shown = round(worst_sum["gap"], 4), round(worst_rate["gap"], 4)    # compared unrounded above, so two equal gaps keep the earlier one
    return last, {"months_checked": DEPTH, "sums_checked": len(BLOCKS) * DEPTH, "rate_months_checked": CHECK_MONTHS, "rates_checked": len(BLOCKS) * CHECK_MONTHS,
                  "largest_sum_gap_millions": sum_shown, "largest_sum_gap_month": _label(worst_sum["month"]) if sum_shown else None, "largest_sum_gap_series": LABEL[worst_sum["block"]] if sum_shown else None,
                  "largest_rate_gap_points": rate_shown, "largest_rate_gap_month": _label(worst_rate["month"]) if rate_shown else None, "largest_rate_gap_series": LABEL[worst_rate["block"]] if rate_shown else None}


def _range(g: dict[date, float], last: date) -> dict | None:
    window = sorted(d for d in g if d <= last)[-RATE_WINDOW:]
    if len(window) < MIN_WINDOW:
        return None
    lo, hi = min(window, key=lambda d: g[d]), max(window, key=lambda d: g[d])
    return {"months": len(window), "lowest": {"pct": round(g[lo], 2), "month": _label(lo)}, "highest": {"pct": round(g[hi], 2), "month": _label(hi)},
            "share_lower_pct": round(100 * sum(1 for d in window if g[d] < g[last]) / len(window))}


def _row(v: dict, e: str, last: date) -> dict:
    sid = f"{e}.A.rate" if e in BLOCKS else f"{e}.rate"
    g = v[sid]
    row = {"id": e, "label": LABEL[e], "rate_pct": round(g[last], 2), "change_month_points": round(g[last] - g[_months_back(last, 1)], 2), "change_year_points": round(g[last] - g[_months_back(last, 12)], 2),
           "window": _range(g, last)}
    row["volume_millions"] = round(v[f"{e}.A.volume"][last], 0) if e in BLOCKS else None
    return row


def _month_end(d: date) -> date:
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1) - timedelta(days=1)


def summarize(v: dict, units: dict, status: dict[str, str], today: date) -> dict:
    last, detail = _check(v, units)
    age = (today - _month_end(last)).days
    recent = [_months_back(last, i) for i in range(RECENT_MONTHS)]
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "month": _label(last), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "provisional": any(status.get(sid, "") not in ("", "A") for sid in SHOWN),
            "loans": [_row(v, e, last) for e in LOANS], "deposits": [_row(v, e, last) for e in DEPOSITS], "costs": [_row(v, e, last) for e in COSTS],
            "recent": [{"date": d.isoformat(), "month": _label(d), "firms_cost_pct": round(v["firms_cost.rate"][d], 2), "house_cost_pct": round(v["house_cost.rate"][d], 2)} for d in recent],
            "detail": detail,
            "checks": {"units_ok": True, "months_in_a_row": True, "range_ok": True, "monthly_move_ok": True, "volume_sums_ok": True, "rates_follow_the_volumes_ok": True, "cost_of_borrowing_ok": True},
            "note": ("The interest rates that euro-area banks (monetary financial institutions) charge on NEW loans and pay on NEW deposits: the loans and deposits agreed or renegotiated in the month, not the stock outstanding, so the rates follow the central bank's rates within a few months. "
                     "Rates are annualised agreed rates in percent a year, averaged over the euro area as it was at the time; the volume is the amount of that new business in the month, in euro. Two composite indicators, the ECB's cost of borrowing for firms and for house purchase, weight the rates on loans with different periods of fixed interest by a moving average of their volumes. "
                     "The newest month is provisional and is revised later; each figure carries its month. "
                     "Checked: the units are the ones assumed, no month is missing, no rate, volume or monthly move is outside what the real record allows (plain checks), and three checks held in each of the last 36 months (the rate identity in the last 24): "
                     "for six kinds of new business the volume of all of it equals the volume with a floating rate or up to one year of fixed interest plus the volume fixed for over one year (to 0.016 million euro); the rate on all of it equals the average of the two parts' rates weighted by their volumes (to 0.016 points); "
                     "and each composite lies within one point of the rate on all new loans of the same borrowers. The first two are the ECB's own arithmetic, so they show that the series belong together, not that the figures are right; the third is a loose bound. "
                     "The four overnight and composite rates have no identity of their own to check. This describes what already happened: it is not a market signal or a forecast.")}


class EuroBankRates:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def _get(self, c: httpx.AsyncClient, key: str) -> str:
        r = await c.get(BASE + key, params={"lastNObservations": LAST_N, "format": "csvdata"}, headers={"User-Agent": "ATLAS research terminal", "Accept": "text/csv"})
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        return r.text

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real euro-area bank interest rates are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=TIMEOUT)
        try:
            texts = await asyncio.gather(*(self._get(c, key) for key, ids in REQUESTS))
            values: dict = {}
            units: dict = {}
            status: dict = {}
            for text, (key, ids) in zip(texts, REQUESTS):
                vv, uu, ss = parse(text, ids)
                values.update(vv)
                units.update(uu)
                status.update(ss)
            res = {**base, **summarize(values, units, status, now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, KeyError) as e:
            res = {**base, "available": False, "reason": f"The euro-area bank interest rates could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
