"""Euro-area bank interest rates on EXISTING loans and deposits, from the ECB Data Portal's public API (official, free, no key): the average rate euro-area banks (monetary financial institutions) have on everything they have already lent or taken in, monthly, from the MFI interest rate statistics (the MIR dataflow, "outstanding amounts"), with the ECB's own split of each month's change into a part that comes from changes in the rates and a part that comes from changes in the weights.

How to read it: the rates on NEW business (the other euro bank rates card) follow the central bank within a few months. The rates here are on the STOCK: every loan and deposit still on the books at the end of the month, so an old loan keeps the rate it was agreed at until it is repaid or its rate is reset, and the average moves slowly behind the new-business rates. Amounts are not in this slice (the dataflow gives rates only for the stock): the rates are annualised agreed rates in percent a year, averaged over the euro area as it was in each month ("changing composition"). The ECB publishes for each rate a Bennet decomposition of the month-to-month change: the "interest rate component" (what the change would be if only the rates had moved) and the "weight component" (what is left because the weights of its parts moved), and their running totals since January 2003 (the "index on interest rates", the "index on weights" and the "accumulated changes"); all in percentage points. The card shows both parts and does not explain more than the ECB's names say: the ECB page on the method could not be read from this machine.
Series: six rows, each a rate of the stock: loans to firms, to households, for house purchase and for consumption and other purposes, and firms' and households' deposits with an agreed maturity; the first five carry the full decomposition and the rate on all loans to households carries the rate only; the loans also by original maturity (up to 1 year, over 1 and up to 5 years, over 5 years) and the deposits by agreed maturity (up to 2 years, over 2 years). 44 series in 4 requests. Left out on purpose: repurchase agreements and house purchase up to one year, whose decomposition does not add up in the real record (gaps of 0.58 and 0.14 points), and the finer maturity splits, which start in 2014.
Checks, set from the whole real record before any test was written (285 months from January 2003 for the 44 series, none missing, one provisional value each): every series reports the units the card assumes (the ECB's own labels: percent per annum for a rate, percentage points for the components); all 44 series end in the same month and each has all of the last 120 months; each rate lies in -1% to +12% a year (the real record: -0.07% for firms' short deposits to 9.43% for consumer credit up to a year, and 7.88% in the last ten years), each month's component in -2 to +2 points (-0.50 to +0.31 for the rate part, -0.02 to +0.06 for the weight part) and each running total in -10 to +10 points (-3.99 to +1.62); no rate moves by more than 1.5 points in a month (the real extremes are +0.43 and -0.61, in January 2009).
**Six checks are the source's own arithmetic or a bound between its own series**; they show that the series fetched belong to one release and were not mixed up, not that the figures are right. For each of the five rates with a decomposition, over the last 120 months: (a) the month's change in the rate equals its rate component plus its weight component; (b) the running total of the rate component grows by that month's rate component; (c) the same for the weight component; (d) the accumulated change equals the two running totals added; (e) over the whole window the rate moved as far as the accumulated change moved, so that small gaps cannot add up unseen; all to within 0.015625 points (two decimals are published, so gaps of 0.01 are rounding; the real gaps are exactly 0 or 0.01 in every one of the 1,420 monthly pairs, and between any two months in about 190,000 pairs); (f) each total rate lies within 0.015625 points of the range of its parts' rates (loans to firms, house purchase and consumption by original maturity; deposits by agreed maturity; loans to households between house purchase and consumption), as a weighted average must (the real record: always inside or exactly on the edge). Two other series of the same dataflow do NOT pass (a)-(e) in the real record and are not used: the rate part is not simply the change minus the weight part, so the identity can fail, and then nothing is shown.
Not checked, and said so: the decomposition is the ECB's method and its page could not be read, so what exactly its weights are is not claimed; a one-hundredth slip in a published figure can hide inside the rounding allowance; the figures of the newest month are provisional and are revised. A series that ends in another month, or a month missing from one, is refused. A missing value is left out, never filled in.
It describes what already happened: it is not a market signal or a forecast. A failure says so and shows nothing.
"""
from __future__ import annotations

import asyncio
import csv
import io
import re
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from .eurobankrates import _month, _num
from .failreason import fail_reason
from .moneysupply import _label, _months_back

BASE = "https://data-api.ecb.europa.eu/service/data/MIR/"
SOURCE = "European Central Bank, ECB Data Portal: interest rates on the loans and deposits euro-area banks already have on their books, the outstanding amounts (MFI interest rate statistics, official, free public data)"
# block id -> (BS_ITEM, counterpart sector, label of the row)
BLOCKS = {
    "firms": ("A20", "2240", "loans to firms"),
    "households": ("A20", "2250", "loans to households"),
    "house": ("A22", "2250", "loans for house purchase"),
    "consumer": ("A25", "2250", "loans for consumption and other purposes"),
    "firms_dep": ("L22", "2240", "firms' deposits with an agreed maturity"),
    "hh_dep": ("L22", "2250", "households' deposits with an agreed maturity"),
}
SHORT = {"firms": "loans to firms", "households": "loans to households", "house": "house purchase loans", "consumer": "consumer and other loans", "firms_dep": "firms' deposits", "hh_dep": "households' deposits"}
SPLIT = ("firms", "house", "consumer", "firms_dep", "hh_dep")          # the blocks the ECB publishes the rate and weight components for
LOANS = ("firms", "households", "house", "consumer")
DEPOSITS = ("firms_dep", "hh_dep")
PARTS = {"firms": ("F", "I", "J"), "households": (), "house": ("F", "I", "J"), "consumer": ("F", "I", "J"), "firms_dep": ("L", "H"), "hh_dep": ("L", "H")}
PART_WORDS = {"F": "up to 1 year", "I": "1 to 5 years", "J": "over 5 years", "L": "up to 2 years", "H": "over 2 years"}
# kind -> the ECB's DATA_TYPE_MIR code: the rate; the month's rate and weight components; their running totals since 2003-01; the running total of the whole change
KINDS = {"rate": "R", "rate_step": "I", "mix_step": "J", "rate_cum": "M", "mix_cum": "N", "total_cum": "O"}
KIND_WORDS = {"rate_step": "the rate component of the change in {}", "mix_step": "the weight component of the change in {}", "rate_cum": "the accumulated rate component for {}",
              "mix_cum": "the accumulated weight component for {}", "total_cum": "the accumulated change for {}"}
RATE_UNIT = ("PCPA", "0")             # the ECB's own labels: percent per annum
POINT_UNIT = ("PO", "0")              # percentage points


def _key(item: str, maturity: str, code: str, sector: str) -> str:
    return f"M.U2.B.{item}.{maturity}.{code}.A.{sector}.EUR.O"


SERIES: dict[str, tuple[str, tuple[str, str]]] = {}             # series id -> (key without "MIR.", units)
NAMES: dict[str, str] = {}
for _b, (_item, _sector, _row_label) in BLOCKS.items():
    for _k in (KINDS if _b in SPLIT else ("rate",)):
        SERIES[f"{_b}.A.{_k}"] = (_key(_item, "A", KINDS[_k], _sector), RATE_UNIT if _k == "rate" else POINT_UNIT)
        NAMES[f"{_b}.A.{_k}"] = f"the rate on {SHORT[_b]}" if _k == "rate" else KIND_WORDS[_k].format(SHORT[_b])
    for _p in PARTS[_b]:
        SERIES[f"{_b}.{_p}.rate"] = (_key(_item, _p, "R", _sector), RATE_UNIT)
        NAMES[f"{_b}.{_p}.rate"] = f"the rate on {SHORT[_b]} ({PART_WORDS[_p]})"
RATES = tuple(sid for sid in SERIES if sid.endswith(".rate"))
PAGE = BASE + SERIES["firms.A.rate"][0]
# (total rate, the rates of its parts): a weighted average lies inside the range of the rates it averages
BETWEEN = (
    ("firms.A.rate", ("firms.F.rate", "firms.I.rate", "firms.J.rate")),
    ("households.A.rate", ("house.A.rate", "consumer.A.rate")),
    ("house.A.rate", ("house.F.rate", "house.I.rate", "house.J.rate")),
    ("consumer.A.rate", ("consumer.F.rate", "consumer.I.rate", "consumer.J.rate")),
    ("firms_dep.A.rate", ("firms_dep.L.rate", "firms_dep.H.rate")),
    ("hh_dep.A.rate", ("hh_dep.L.rate", "hh_dep.H.rate")),
)


def _head(b: str) -> tuple[str, ...]:
    return tuple(f"{b}.A.{k}" for k in KINDS)


# the four requests: the key (the OR-list `+` must reach the host unencoded) and the series each one returns
REQUESTS = (
    ("M.U2.B.A20+A22+A25.A.R+I+J+M+N+O.A.2240+2250.EUR.O", _head("firms") + ("households.A.rate",) + _head("house") + _head("consumer")),
    ("M.U2.B.L22.A.R+I+J+M+N+O.A.2240+2250.EUR.O", _head("firms_dep") + _head("hh_dep")),
    ("M.U2.B.A20+A22+A25.F+I+J.R.A.2240+2250.EUR.O", tuple(f"{b}.{p}.rate" for b in ("firms", "house", "consumer") for p in "FIJ")),
    ("M.U2.B.L22.L+H.R.A.2240+2250.EUR.O", tuple(f"{b}.{p}.rate" for b in ("firms_dep", "hh_dep") for p in "LH")),
)
RATE_LIMITS = (-1.0, 12.0)            # percent a year; the real record runs from -0.07 to 9.43
STEP_LIMITS = (-2.0, 2.0)             # points, a month's rate or weight component; the real record runs from -0.50 to +0.31
CUM_LIMITS = (-10.0, 10.0)            # points, the running totals since 2003-01; the real record runs from -3.99 to +1.62
MONTH_MOVE = 1.5                      # points: the largest one-month move of a rate (exact in binary, so a move of exactly the limit can be tested); the real extremes are +0.43 and -0.61
TOLERANCE = 2 ** -6                   # 0.015625 points: every identity and every bound between a total and its parts; the real gaps are exactly 0 or 0.01 (two decimals are published)
DEPTH = 120                           # months every series must have: the months of the identities and the ranges, and the ten-year window of the comparison
LAST_N = 125                          # observations asked for: the ten-year window, and a few more
RATE_WINDOW = 120                     # ten years of rates
MIN_WINDOW = 60
OVERDUE_AFTER_DAYS = 75               # from the end of the observed month: the next month arrives about 64 days after the previous one ends, with the new-business rates
TTL = 6 * 3600.0
FAIL_TTL = 120.0
TIMEOUT = 90.0                        # seconds for one request: the ECB's MIR service answered in 0.1 s (when it had the answer ready) to 84 s (when it did not)


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


def _gap(a: float, b: float) -> float:
    return round(abs(a - b), 9)                                                        # nine decimals: the float noise of two decimal figures is gone, so a gap of exactly the tolerance is not "over" it


def _check(v: dict[str, dict[date, float]], units: dict) -> tuple[date, dict]:
    for sid in SERIES:
        if sid in units and units[sid] != SERIES[sid][1]:
            raise ValueError(f"the ECB reports {NAMES[sid]} in other units than the card assumes")
    ends = {max(s) for s in v.values()}
    if len(ends) != 1:
        raise ValueError("the stock rate series end in different months")
    last = ends.pop()
    window = [_months_back(last, i) for i in range(DEPTH - 1, -1, -1)]               # oldest first
    for sid in SERIES:
        for d in window:
            if d not in v[sid]:
                raise ValueError(f"{NAMES[sid]} is missing for {_label(d)}")
    for sid in SERIES:
        kind = sid.rsplit(".", 1)[1]
        lo, hi = RATE_LIMITS if kind == "rate" else STEP_LIMITS if kind.endswith("_step") else CUM_LIMITS
        for d in window:
            x = v[sid][d]
            if not (lo <= x <= hi):
                if kind == "rate":
                    raise ValueError(f"{NAMES[sid]} is {x:.2f}% in {_label(d)}, outside {lo:g}% to {hi:g}%")
                raise ValueError(f"{NAMES[sid]} is {x:.2f} in {_label(d)}, outside {lo:g} to {hi:g} points")
    for sid in RATES:                                                                  # no rate jumps
        for a, b in zip(window, window[1:]):
            ch = v[sid][b] - v[sid][a]
            if abs(ch) > MONTH_MOVE:
                raise ValueError(f"{NAMES[sid]} moved by {ch:+.2f} points in {_label(b)}, more than {MONTH_MOVE:g}")
    worst = {"gap": 0.0, "month": last, "block": SPLIT[0]}
    checked = 0
    pairs = list(zip(window, window[1:]))

    def seen(gap: float, d: date, b: str) -> None:                                     # the largest gap so far, the earlier of two equal ones kept
        if gap > worst["gap"]:
            worst.update(gap=gap, month=d, block=b)

    for b in SPLIT:                                                                    # (a) the month's change in the rate is its rate component plus its weight component
        r, i, j = v[f"{b}.A.rate"], v[f"{b}.A.rate_step"], v[f"{b}.A.mix_step"]
        for a, d in pairs:
            ch, s = r[d] - r[a], i[d] + j[d]
            gap = _gap(ch, s)
            if gap > TOLERANCE:
                raise ValueError(f"{SHORT[b]}: the rate moved {ch:+.2f} in {_label(d)}, its two components add up to {s:+.2f} (gap {gap:.3f})")
            seen(gap, d, b)
            checked += 1
    for b in SPLIT:                                                                    # (b) the running total of the rate component grows by the month's rate component
        c, i = v[f"{b}.A.rate_cum"], v[f"{b}.A.rate_step"]
        for a, d in pairs:
            x, y = c[d] - c[a], i[d]
            gap = _gap(x, y)
            if gap > TOLERANCE:
                raise ValueError(f"{SHORT[b]}: accumulated rate part moved {x:+.2f}, month's part {y:+.2f} in {_label(d)} (gap {gap:.3f})")
            seen(gap, d, b)
            checked += 1
    for b in SPLIT:                                                                    # (c) the same for the weight component
        c, j = v[f"{b}.A.mix_cum"], v[f"{b}.A.mix_step"]
        for a, d in pairs:
            x, y = c[d] - c[a], j[d]
            gap = _gap(x, y)
            if gap > TOLERANCE:
                raise ValueError(f"{SHORT[b]}: accumulated weight part moved {x:+.2f}, month's part {y:+.2f} in {_label(d)} (gap {gap:.3f})")
            seen(gap, d, b)
            checked += 1
    for b in SPLIT:                                                                    # (d) the accumulated change is the two running totals added
        o, m, n = v[f"{b}.A.total_cum"], v[f"{b}.A.rate_cum"], v[f"{b}.A.mix_cum"]
        for d in window:
            gap = _gap(o[d], m[d] + n[d])
            if gap > TOLERANCE:
                raise ValueError(f"{SHORT[b]}: accumulated change {o[d]:+.2f} is not {m[d]:+.2f} plus {n[d]:+.2f} in {_label(d)} (gap {gap:.3f})")
            seen(gap, d, b)
            checked += 1
    for b in SPLIT:                                                                    # (e) over the whole window the rate moved as far as the accumulated change moved
        r, o = v[f"{b}.A.rate"], v[f"{b}.A.total_cum"]
        moved, accumulated = r[window[-1]] - r[window[0]], o[window[-1]] - o[window[0]]
        gap = _gap(moved, accumulated)
        if gap > TOLERANCE:
            raise ValueError(f"{SHORT[b]}: over {DEPTH - 1} months the rate moved {moved:+.2f} but the accumulated change {accumulated:+.2f} (gap {gap:.3f})")
        seen(gap, window[-1], b)
        checked += 1
    for total, parts in BETWEEN:                                                       # (f) a total rate lies inside the range of its parts' rates
        for d in window:
            t, rest = v[total][d], [v[p][d] for p in parts]
            lo, hi = min(rest), max(rest)
            out = round(max(lo - t, t - hi), 9)
            if out > TOLERANCE:
                raise ValueError(f"{SHORT[total.split('.')[0]]}: {t:.2f}% in {_label(d)} is {out:.3f} outside its parts' {lo:.2f}% to {hi:.2f}%")
    shown = round(worst["gap"], 4)                                                     # compared unrounded above, so two equal gaps keep the earlier one
    return last, {"months_checked": DEPTH, "identities_checked": checked, "largest_identity_gap_points": shown, "largest_identity_gap_month": _label(worst["month"]) if shown else None,
                  "largest_identity_gap_series": SHORT[worst["block"]] if shown else None, "between_checked": len(BETWEEN) * DEPTH}


def _r2(x: float) -> float:
    return round(x, 2) + 0.0                                                            # + 0.0 turns a minus zero into zero


def _range(g: dict[date, float], last: date) -> dict | None:
    window = sorted(d for d in g if d <= last)[-RATE_WINDOW:]
    if len(window) < MIN_WINDOW:
        return None
    lo, hi = min(window, key=lambda d: g[d]), max(window, key=lambda d: g[d])
    return {"months": len(window), "lowest": {"pct": _r2(g[lo]), "month": _label(lo)}, "highest": {"pct": _r2(g[hi]), "month": _label(hi)},
            "share_lower_pct": round(100 * sum(1 for d in window if g[d] < g[last]) / len(window))}


def _row(v: dict, b: str, last: date) -> dict:
    g = v[f"{b}.A.rate"]
    prev, year = _months_back(last, 1), _months_back(last, 12)
    row = {"id": b, "label": BLOCKS[b][2], "rate_pct": _r2(g[last]), "change_month_points": _r2(g[last] - g[prev]), "change_year_points": _r2(g[last] - g[year]), "window": _range(g, last),
           "month_split": None, "year_split": None}
    if b in SPLIT:
        rc, mc = v[f"{b}.A.rate_cum"], v[f"{b}.A.mix_cum"]
        row["month_split"] = {"rates_points": _r2(v[f"{b}.A.rate_step"][last]), "mix_points": _r2(v[f"{b}.A.mix_step"][last])}
        row["year_split"] = {"rates_points": _r2(rc[last] - rc[year]), "mix_points": _r2(mc[last] - mc[year])}
    row["parts"] = [{"id": p, "label": PART_WORDS[p], "rate_pct": _r2(v[f"{b}.{p}.rate"][last])} for p in PARTS[b]]
    return row


def _month_end(d: date) -> date:
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1) - timedelta(days=1)


def summarize(v: dict, units: dict, status: dict[str, str], today: date) -> dict:
    last, detail = _check(v, units)
    age = (today - _month_end(last)).days
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "month": _label(last), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "provisional": any(status.get(sid, "") not in ("", "A") for sid in RATES),
            "loans": [_row(v, b, last) for b in LOANS], "deposits": [_row(v, b, last) for b in DEPOSITS],
            "detail": detail,
            "checks": {"units_ok": True, "months_in_a_row": True, "range_ok": True, "monthly_move_ok": True, "identities_ok": True, "totals_inside_parts_ok": True},
            "note": ("The average interest rates euro-area banks (monetary financial institutions) already have on their books: the rate on all the loans and deposits still outstanding at the end of the month, not only on those agreed that month "
                     "(the rates on new business are on the euro bank rates card). An old loan keeps its rate until it is repaid or reset, so these rates move slowly behind the central bank's. "
                     "Rates are annualised agreed rates in percent a year, averaged over the euro area as it was at the time. The ECB splits each month's change into a rate component and a weight component, shown as published: "
                     "what the change would be if only the rates had moved, and the rest. "
                     "The newest month is provisional and is revised later; each figure carries its month. "
                     "Plain checks: the units are the ones assumed and no month is missing; the ranges, the ECB's rate and weight components and the totals inside their parts are in the Check line. "
                     "This describes what already happened: it is not a market signal or a forecast.")}


class EuroStockRates:
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
            return {**base, "available": False, "reason": "Demo mode: the real euro-area rates on existing loans and deposits are not shown because made-up values would look real."}
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
            res = {**base, "available": False, "reason": f"The euro-area rates on existing loans and deposits could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
