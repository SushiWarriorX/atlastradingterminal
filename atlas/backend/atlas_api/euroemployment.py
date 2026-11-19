"""Euro-area employment and productivity from the ECB Data Portal's public API (official, free, no key): Eurostat's quarterly national accounts for the euro area of 21 countries (fixed composition as of 1 January 2026, code `I10`), seasonally and calendar adjusted, as published in the ECB's MNA dataflow.

How to read it: employment is the number of people in work (thousands of persons, the domestic concept: everyone working in the euro area) and the hours they worked in the quarter (thousands of hours), as the total, in ten activities (agriculture, industry, construction, trade and transport, information, finance, real estate, professional and support services, public services, other services) and as employees and self-employed. Labour productivity is the ECB's own calculation: real GDP (chain-linked volumes, 2020) divided by the number of persons, or by the hours worked, shown as growth on the previous quarter and on the same quarter a year earlier. Total employment (and real GDP) come out about 45 days after a quarter ends; the breakdown and the hours come with the full accounts about 65 days after, so the breakdown is usually one quarter behind the total (today: total 2026-Q3, breakdown 2026-Q2).
Why `I10` and not another code: the dataflow keeps one series per euro-area composition, and a key written from memory for another one answers without any error and ends quarters ago (the GDP card of the same dataflow found `I9` ending at 2026-Q1). Only `I10` is current.
Checks, set from the whole real record (126 quarters from 1995-Q1 for the 26 employment series, 127 to 2026-Q3 for total employment and real GDP, none missing, all status A, compiled by Eurostat) before any test was written. Every series reports the units the card assumes (persons and hours with the multiplier 3, that is thousands; real GDP in millions of euro; the ECB labels its growth rates EUR with the multiplier 0 although they are percent). The ranges are loose and only catch slips of ten times or a tenth: total employment 100,000 to 250,000 thousand (the real range is 135,697 to 176,547), total hours 40 to 100 billion a quarter (54.2 to 68.7), each of the ten activities between 0.2% and 40% of employment (0.80% to 25.13%), the self-employed between 5% and 45% of persons and of hours (14.0% to 17.1% and 17.6% to 22.4%), 250 to 500 hours a person in a quarter (335.7 to 420.8), employment moving by at most 10% in a quarter (-2.835% in 2020-Q2 to +1.128%), productivity growth per person within 25% on the quarter and 30% on the year (-8.56% to +10.38% and -11.37% to +12.52%) and per hour within 10% and 15% (-2.06% to +2.53% and -2.83% to +3.55%).
**Four checks are the source's own arithmetic** and show that the series fetched belong to one release, not that the figures are right. The two breakdowns of employment are compiled by Eurostat from the national accounts and add up to the total: the ten activities to total employment and employees plus the self-employed to total employment, for persons and for hours. The real gap over all 126 quarters is at most 8.1e-10 thousand persons and 1.3e-7 thousand hours (floating-point noise); the card refuses a quarter off by more than 2 to the power -20 (0.00000095) thousand persons or 2 to the power -12 (0.00024) thousand hours, both exact in binary. Because they hold on every quarter of the record, they are checked on all 45 quarters fetched. Productivity is the fourth: the ECB's growth rate equals real GDP growth over employment growth (persons) or over hours growth, worked out from the levels, to 4.4e-14 points in all 126 quarters (the ECB's metadata says it is calculated, and the tolerance is 2 to the power -30). That one is true by construction, so it proves the units and the alignment of the quarters of three series, nothing more.
Not used: unit labour costs and compensation (the ECB calculates them and nothing here can check them; one request for them timed out at 121 seconds cold), the productivity indexes, the member countries and the series that are not seasonally adjusted.
A series that ends on another quarter than the card needs, or a quarter missing from one, is refused. A missing value is left out, never filled in.
It describes what already happened: it is not a market signal or a forecast. A failure says so and shows nothing.
"""
from __future__ import annotations

import asyncio
import csv
import io
import math
import re
import time
from datetime import date, datetime, timezone

import httpx

from .failreason import fail_reason

BASE = "https://data-api.ecb.europa.eu/service/data/MNA/"
SOURCE = "European Central Bank, euro-area employment, hours worked and labour productivity (Eurostat quarterly national accounts, ESA 2010, euro area of 21 countries, seasonally and calendar adjusted), as published on the ECB Data Portal (official, free public data)"
ACTS = ("A", "BTE", "F", "GTI", "J", "K", "L", "M_N", "OTQ", "RTU")
SECTOR = {"A": "agriculture and fishing", "BTE": "industry", "F": "construction", "GTI": "trade, transport and hospitality", "J": "information and communication", "K": "finance and insurance",
          "L": "real estate", "M_N": "professional and support services", "OTQ": "public services, education and health", "RTU": "arts, recreation and other services"}
PS, HW, EUR6, EUR0 = ("PS", "3"), ("HW", "3"), ("EUR", "6"), ("EUR", "0")      # the ECB's UNIT_MEASURE and UNIT_MULT (persons and hours in thousands, real GDP in millions of euro; growth rates carry EUR and 0)
_E = "Q.Y.I10.W2.S1.S1._Z."


def _series() -> dict[str, tuple[str, tuple[str, str]]]:
    """series id -> (the ECB's series key without "MNA.", the units it reports)."""
    out: dict = {}
    for tag, unit, units in (("p", "PS", PS), ("h", "HW", HW)):
        out[f"{tag}_total"] = (f"{_E}EMP._Z._T._Z.{unit}._Z.N", units)
        for a in ACTS:
            out[f"{tag}_{a}"] = (f"{_E}EMP._Z.{a}._Z.{unit}._Z.N", units)
        out[f"{tag}_employees"] = (f"{_E}SAL._Z._T._Z.{unit}._Z.N", units)
        out[f"{tag}_self"] = (f"{_E}SELF._Z._T._Z.{unit}._Z.N", units)
    out["gdp"] = ("Q.Y.I10.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.N", EUR6)
    for tag, item in (("p", "LPR_PS"), ("h", "LPR_HW")):
        out[f"prod_{tag}_q"] = (f"Q.Y.I10.W0.S1.S1._Z.{item}._Z._T._Z.EUR.LR.G1", EUR0)
        out[f"prod_{tag}_y"] = (f"Q.Y.I10.W0.S1.S1._Z.{item}._Z._T._Z.EUR.LR.GY", EUR0)
    return out


SERIES = _series()
PAGE = BASE + SERIES["p_total"][0]
BREAKDOWN = tuple(s for s in SERIES if s.startswith(("p_", "h_")) and s != "p_total")         # everything that comes with the breakdown, a quarter behind total employment
STATUS_IDS = ("p_employees", "p_self", "h_employees", "h_self")
# the four requests: the key (the OR-list `+` must reach the host unencoded) and the series each one returns
REQUESTS = (
    (f"{_E}EMP._Z._T+{'+'.join(ACTS)}._Z.PS+HW._Z.N", tuple(s for s in SERIES if s.startswith(("p_", "h_")) and s not in STATUS_IDS)),
    (f"{_E}SAL+SELF._Z._T._Z.PS+HW._Z.N", STATUS_IDS),
    (SERIES["gdp"][0], ("gdp",)),
    ("Q.Y.I10.W0.S1.S1._Z.LPR_PS+LPR_HW._Z._T._Z.EUR.LR.G1+GY", ("prod_p_q", "prod_p_y", "prod_h_q", "prod_h_y")),
)
NAMES = {"p_total": "total employment", "h_total": "total hours worked", "p_employees": "employees", "p_self": "the self-employed", "h_employees": "hours worked by employees",
         "h_self": "hours worked by the self-employed", "gdp": "real GDP", "prod_p_q": "productivity per person, quarterly growth", "prod_p_y": "productivity per person, annual growth",
         "prod_h_q": "productivity per hour, quarterly growth", "prod_h_y": "productivity per hour, annual growth"}
NAMES.update({f"p_{a}": f"employment in {SECTOR[a]}" for a in ACTS})
NAMES.update({f"h_{a}": f"hours worked in {SECTOR[a]}" for a in ACTS})
PERSONS_LIMITS = (100000.0, 250000.0)                  # thousand persons; the real total is 135,697 to 176,547
HOURS_LIMITS = (40000000.0, 100000000.0)               # thousand hours in a quarter; the real total is 54,224,569 to 68,669,157
SECTOR_SHARE = (0.2, 40.0)                             # percent of employment; the real shares are 0.80 to 25.13
SELF_SHARE = (5.0, 45.0)                               # percent of persons and of hours; the real shares are 14.03 to 17.09 and 17.63 to 22.39
HOURS_PER_PERSON = (250.0, 500.0)                      # hours a person works in a quarter; the real total is 335.70 to 420.79
JOBS_MOVE = (-10.0, 10.0)                              # percent change of total employment in a quarter; the real range is -2.835 (2020-Q2) to +1.128
PROD_LIMITS = {"prod_p_q": (-25.0, 25.0), "prod_p_y": (-30.0, 30.0), "prod_h_q": (-10.0, 10.0), "prod_h_y": (-15.0, 15.0)}     # percent; the real ranges are -8.56 to 10.38, -11.37 to 12.52, -2.06 to 2.53 and -2.83 to 3.55
PERSONS_TOLERANCE = 2 ** -20                           # thousand persons, exact in binary; the real sums are off by at most 8.1e-10
HOURS_TOLERANCE = 2 ** -12                             # thousand hours, exact in binary; the real sums are off by at most 1.3e-7
PRODUCTIVITY_TOLERANCE = 2 ** -30                      # points; the ECB calculates productivity growth from the levels and the real gap is at most 4.4e-14
LAST_N = 45                                            # quarters fetched and checked: eleven years, so that every year-on-year figure has its level four quarters earlier
RECENT_QUARTERS = 6
OVERDUE_AFTER_DAYS = 135                               # total employment comes out about 45 days after a quarter ends, the next quarter's about 121 days after: 135 leaves two weeks for the ECB to publish it
TTL = 6 * 3600.0
FAIL_TTL = 120.0
TIMEOUT = 90.0                                         # seconds for one request: the ECB's MNA service answered these keys in 5 to 35 s cold
_QUARTER = re.compile(r"\d{4}-Q[1-4]")
_QUARTER_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _quarter(x) -> str | None:
    """A quarter written exactly YYYY-Qn."""
    return x if isinstance(x, str) and _QUARTER.fullmatch(x) else None


def _fmt(x: float) -> str:
    return f"{x:,.1f}"


def _lim(x: float) -> str:
    return f"{x:,.0f}" if x == int(x) and abs(x) >= 1000 else f"{x:g}"


def _idx(q: str) -> int:
    """A running number for a quarter, so that the next quarter is one more."""
    return int(q[:4]) * 4 + int(q[6]) - 1


def _label(i: int) -> str:
    return f"{i // 4}-Q{i % 4 + 1}"


def _end(q: str) -> date:
    month, day = _QUARTER_END[int(q[6])]
    return date(int(q[:4]), month, day)


def parse(text: str, ids: tuple[str, ...]) -> tuple[dict[str, dict[str, float]], dict[str, tuple[str, str]], dict[str, str]]:
    """Values by series id (for example "p_total") and quarter, the units each series reports (the ECB's UNIT_MEASURE and UNIT_MULT) and the status of each series' newest value ("A" normal). Rows of any other series, and rows without a quarter or a number, are left out; two values for one quarter are an error."""
    values: dict[str, dict[str, float]] = {i: {} for i in ids}
    wanted = {"MNA." + SERIES[i][0]: i for i in ids}
    units: dict[str, tuple[str, str]] = {}
    newest: dict[str, tuple[str, str]] = {}
    for r in csv.DictReader(io.StringIO(text)):
        sid, q, v = wanted.get(r.get("KEY") or ""), _quarter(r.get("TIME_PERIOD")), _num(r.get("OBS_VALUE"))
        if sid is None or q is None or v is None:
            continue
        if q in values[sid]:
            raise ValueError(f"{sid} has two values for {q}")
        values[sid][q] = v
        units[sid] = ((r.get("UNIT_MEASURE") or "").strip(), (r.get("UNIT_MULT") or "").strip())
        if sid not in newest or _idx(q) > _idx(newest[sid][0]):
            newest[sid] = (q, (r.get("OBS_STATUS") or "").strip())
    missing = [i for i in ids if not values[i]]
    if missing:
        raise ValueError("the source returned no values for " + ", ".join(missing))
    return values, units, {i: s for i, (q, s) in newest.items()}


def _window(v: dict[str, dict[str, float]], sid: str) -> list[str]:
    """The last LAST_N quarters ending on the newest quarter of the series."""
    end = max(_idx(q) for q in v[sid])
    return [_label(i) for i in range(end - LAST_N + 1, end + 1)]


def _check(v: dict[str, dict[str, float]], units: dict) -> tuple[str, str, dict]:
    for sid, u in units.items():
        if u != SERIES[sid][1]:
            raise ValueError(f"the ECB reports {NAMES[sid]} in other units than the card assumes")
    ends = {sid: max(_idx(q) for q in v[sid]) for sid in SERIES}
    if len({ends[s] for s in BREAKDOWN}) != 1:
        raise ValueError("the employment breakdown series end on different quarters")
    ji, bi = ends["p_total"], ends["h_total"]
    if ji - bi not in (0, 1):
        raise ValueError("total employment and its breakdown end more than a quarter apart")
    for sid in ("prod_p_q", "prod_p_y"):
        if ends[sid] != ji:
            raise ValueError(f"productivity per person ends on {_label(ends[sid])}, not on the newest quarter of employment ({_label(ji)})")
    for sid in ("prod_h_q", "prod_h_y"):
        if ends[sid] != bi:
            raise ValueError(f"productivity per hour ends on {_label(ends[sid])}, not on the newest quarter of the breakdown ({_label(bi)})")
    for sid in SERIES:
        for q in _window(v, sid):
            if q not in v[sid]:
                raise ValueError(f"{NAMES[sid]} is missing for {q}")
    for sid, (lo, hi) in (("p_total", PERSONS_LIMITS), ("h_total", HOURS_LIMITS)):
        for q in _window(v, sid):
            if not (lo <= v[sid][q] <= hi):
                raise ValueError(f"{NAMES[sid]} is {_fmt(v[sid][q])} in {q}, outside {_lim(lo)} to {_lim(hi)}")
    hq = _window(v, "h_total")                                                                           # the breakdown's quarters; total employment has all of them but its oldest when it is a quarter ahead
    pq = [q for q in hq if q in v["p_total"]]
    lo, hi = SECTOR_SHARE
    for a in ACTS:
        for q in pq:
            share = 100 * v[f"p_{a}"][q] / v["p_total"][q]
            if not (lo <= share <= hi):
                raise ValueError(f"{NAMES['p_' + a]} is {share:.2f}% of employment in {q}, outside {_lim(lo)}% to {_lim(hi)}%")
    lo, hi = SELF_SHARE
    for q in pq:
        share = 100 * v["p_self"][q] / v["p_total"][q]
        if not (lo <= share <= hi):
            raise ValueError(f"{NAMES['p_self']} is {share:.2f}% of employment in {q}, outside {_lim(lo)}% to {_lim(hi)}%")
    for q in hq:
        share = 100 * v["h_self"][q] / v["h_total"][q]
        if not (lo <= share <= hi):
            raise ValueError(f"{NAMES['h_self']} is {share:.2f}% of hours worked in {q}, outside {_lim(lo)}% to {_lim(hi)}%")
    lo, hi = HOURS_PER_PERSON
    for q in pq:
        hours_per_person = v["h_total"][q] / v["p_total"][q]
        if not (lo <= hours_per_person <= hi):
            raise ValueError(f"hours per person are {hours_per_person:.1f} in {q}, outside {_lim(lo)} to {_lim(hi)}")
    for sid, (lo, hi) in PROD_LIMITS.items():
        for q in _window(v, sid):
            if not (lo <= v[sid][q] <= hi):
                raise ValueError(f"{NAMES[sid]} is {v[sid][q]:,.2f}% in {q}, outside {_lim(lo)}% to {_lim(hi)}%")
    lo, hi = JOBS_MOVE
    qs = _window(v, "p_total")
    for a, b in zip(qs, qs[1:]):
        ch = 100 * (v["p_total"][b] / v["p_total"][a] - 1)
        if not (lo <= ch <= hi):
            raise ValueError(f"employment moved by {ch:+.2f}% in {b}, outside {lo:+g}% to {hi:+g}%")
    worst_persons = worst_hours = 0.0                                                                    # Eurostat's own arithmetic: shows the series belong together
    for unit, tag, tolerance, quarters in (("persons", "p", PERSONS_TOLERANCE, pq), ("hours", "h", HOURS_TOLERANCE, hq)):
        what = "employment" if tag == "p" else "hours"
        thousand = "thousand persons" if tag == "p" else "thousand hours"
        worst = 0.0
        for q in quarters:
            ten = sum(v[f"{tag}_{a}"][q] for a in ACTS)
            off = v[f"{tag}_total"][q] - ten
            if abs(off) > tolerance:
                raise ValueError(f"the ten activities do not add up to total {what} in {q} (off by {off:+.6f} {thousand})")
            worst = max(worst, abs(off))
        for q in quarters:
            off = v[f"{tag}_total"][q] - (v[f"{tag}_employees"][q] + v[f"{tag}_self"][q])
            if abs(off) > tolerance:
                raise ValueError(f"employees and self-employed do not add up to {what} in {q} (off by {off:+.6f} {thousand})")
            worst = max(worst, abs(off))
        if tag == "p":
            worst_persons = worst
        else:
            worst_hours = worst
    worst_productivity = 0.0                                                                             # the ECB's own arithmetic: productivity growth is real GDP growth over employment growth
    first_gdp = _idx(_window(v, "gdp")[0])                                                               # productivity per hour starts a quarter before real GDP when employment is a quarter ahead: that quarter has nothing to be compared with
    for sid, emp, back, kind in (("prod_p_q", "p_total", 1, "quarterly"), ("prod_p_y", "p_total", 4, "annual"), ("prod_h_q", "h_total", 1, "quarterly"), ("prod_h_y", "h_total", 4, "annual")):
        for q in _window(v, sid):
            before = _label(_idx(q) - back)
            if q not in v["gdp"]:
                if _idx(q) < first_gdp:
                    continue
                raise ValueError(f"{NAMES['gdp']} is missing for {q}")
            if before in v["gdp"] and before in v[emp]:
                rel = 100 * ((v["gdp"][q] / v["gdp"][before]) / (v[emp][q] / v[emp][before]) - 1)
                off = v[sid][q] - rel
                if abs(off) > PRODUCTIVITY_TOLERANCE:
                    what = "person" if emp == "p_total" else "hour"
                    over = "jobs" if emp == "p_total" else "hours"
                    raise ValueError(f"productivity per {what} is not real GDP over {over} in {q} ({kind}, off by {off:+.9f})")
                worst_productivity = max(worst_productivity, abs(off))
    return _label(ji), _label(bi), {"quarters_checked": LAST_N, "persons_quarters_checked": len(pq), "largest_persons_gap": round(worst_persons, 12),
                                    "largest_hours_gap": round(worst_hours, 9), "largest_productivity_gap": round(worst_productivity, 12)}


def summarize(v: dict, units: dict, status: dict[str, str], today: date) -> dict:
    jq, bq, detail = _check(v, units)
    age = (today - _end(jq)).days
    tot, hrs = v["p_total"], v["h_total"]
    prev, yago = _label(_idx(jq) - 1), _label(_idx(jq) - 4)
    bya = _label(_idx(bq) - 4)
    persons, hours = tot[bq], hrs[bq]
    recent = [_label(_idx(jq) - i) for i in range(RECENT_QUARTERS)]
    sectors = sorted(({"id": a, "name": SECTOR[a], "persons": round(v[f"p_{a}"][bq] / 1000, 1), "share": round(100 * v[f"p_{a}"][bq] / persons, 1),
                       "change_year_thousands": round(v[f"p_{a}"][bq] - v[f"p_{a}"][bya]), "change_year": round(100 * (v[f"p_{a}"][bq] / v[f"p_{a}"][bya] - 1), 2)} for a in ACTS),
                     key=lambda s: (-v[f"p_{s['id']}"][bq], s["id"]))
    part = lambda tag: {"persons": round(v[f"p_{tag}"][bq] / 1000, 1), "share": round(100 * v[f"p_{tag}"][bq] / persons, 1), "hours_share": round(100 * v[f"h_{tag}"][bq] / hours, 1)}
    return {"available": True, "source": SOURCE, "url": PAGE, "quarter": jq, "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "provisional": status.get("p_total", "") not in ("", "A"),
            "jobs": {"quarter": jq, "persons": round(tot[jq] / 1000, 1), "quarter_on_quarter": round(100 * (tot[jq] / tot[prev] - 1), 2), "year_on_year": round(100 * (tot[jq] / tot[yago] - 1), 2),
                     "previous_quarter": prev, "year_earlier": yago},
            "recent": [{"quarter": q, "persons": round(tot[q] / 1000, 1), "quarter_on_quarter": round(100 * (tot[q] / tot[_label(_idx(q) - 1)] - 1), 2),
                        "year_on_year": round(100 * (tot[q] / tot[_label(_idx(q) - 4)] - 1), 2)} for q in recent],
            "breakdown": {"quarter": bq, "persons": round(persons / 1000, 1), "hours": round(hours / 1000000, 1), "hours_per_person": round(hours / persons, 1),
                          "hours_change_year": round(100 * (hours / hrs[bya] - 1), 2), "employees": part("employees"), "self_employed": part("self"), "sectors": sectors},
            "productivity": {"per_person": {"quarter": jq, "quarter_on_quarter": round(v["prod_p_q"][jq], 2), "year_on_year": round(v["prod_p_y"][jq], 2)},
                             "per_hour": {"quarter": bq, "quarter_on_quarter": round(v["prod_h_q"][bq], 2), "year_on_year": round(v["prod_h_y"][bq], 2)}},
            "detail": detail,
            "checks": {"units_ok": True, "quarters_in_a_row": True, "range_ok": True, "jobs_move_ok": True, "activities_add_up_ok": True, "status_adds_up_ok": True, "productivity_follows_gdp_and_jobs_ok": True},
            "note": ("Eurostat's quarterly national accounts for the euro area of 21 countries (a fixed composition as of 1 January 2026), seasonally and calendar adjusted, published on the ECB Data Portal. "
                     "Employment counts everyone working in the euro area (persons, and the hours they worked in the quarter). Total employment comes out about 45 days after a quarter ends; the breakdown by activity and by employees and self-employed comes with the full accounts about 65 days after, so it is usually one quarter behind. "
                     "Productivity is the ECB's own calculation: real GDP divided by the persons employed or by the hours they worked. Earlier quarters are revised. "
                     "Plain checks: the units are the ones assumed and no quarter is missing; the ranges, the sums and the growth rebuilt from GDP and jobs are in the Check line. "
                     "This describes employment and productivity that already happened: it is not a market signal or a forecast.")}


class EuroEmployment:
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
            return {**base, "available": False, "reason": "Demo mode: the real euro-area employment is not shown because made-up values would look real."}
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
            res = {**base, "available": False, "reason": f"The euro-area employment could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
