"""US hires, quits and layoffs by industry: how many people the employers of the United States hired during a month and how many left their jobs, from the Job Openings and Labor Turnover Survey (JOLTS) of the Bureau of Labor Statistics, via FRED, the St. Louis Fed (public-domain US government data, citation requested; the pages of all 33 series, read on 2026-11-24 at 17:48 UTC, say Source: U.S. Bureau of Labor Statistics, Release: Job Openings and Labor Turnover Survey and "Public Domain: Citation Requested", with no third-party notice and no "calculated by" remark).

How to read it: hires are all the people added to the payroll during the month; separations are all the people who left it: quits (the worker chose to go), layoffs and discharges (the employer ended the job) and other separations (retirements, deaths, transfers and disability); every level is in thousands, seasonally adjusted, monthly, December 2000 on, so 5,402 means 5.402 million. The net of a month is hires minus separations. Thirty-three series: for total nonfarm (JTS), the private sector (JTS1000) and government (JTS9000) all five measures (hires HIL, quits QUL, layoffs and discharges LDL, total separations TSL, other separations OSL); for six private industries (construction 2300, manufacturing 3000, trade, transportation and utilities 4000, professional and business services 540099, private education and health services 6000, leisure and hospitality 7000) hires, quits and total separations. FRED carries layoffs and other separations only for those three totals (the same ids for an industry answer HTTP 404, probed 2026-11-24), so by industry the card shows what left without quitting only as separations minus quits, and it says so.
Each series is asked for ALONE, never in a combined request: with several ids and one start date FRED applies the date to the FIRST series only and gives every other series in full, without an error (found 2026-11-18). Every request starts at 2000-12-01, the first month, so the whole record is checked each time; at most eight requests are open at once.
Checks, set from the whole real record (310 months, December 2000 to September 2026; none missing in any series) before any test was written: the 33 series end in the same month, cover the same months, are dated the 1st and skip no month, and at least 120 months are there; every level is inside its own range (a lower limit near half the lowest and an upper limit beyond the highest real value of that series, so that a unit slip is caught and no real month is). The Bureau's own arithmetic then has to hold in every month, within the rounding of the figures (each is rounded to a thousand, so three figures can be 1.5 apart and four 2.0 apart; the real largest gap is 1 thousand in all eight): total nonfarm equals private plus government in each of the five measures, and in each of the three totals separations equal quits plus layoffs plus other separations. In each of the six industries the quits are not more than the separations (the real closest margin is 102 thousand, manufacturing, 2013-10; one thousand of rounding is allowed), and in each of hires, quits and separations the six industries add up to no more than private (what is left is at least 154 thousand; 3.5 allowed for the rounding of seven figures).
The sums are the Bureau's own arithmetic (every figure is a count of the same survey): they show that the series belong to one release and are lined up, not that the figures are right. NOT checked, and said so: the revisions of older months, the survey's sampling error, which FRED does not carry, and the four private industries that FRED lacks (mining and logging, information, financial activities and other services), which are worked out by subtraction and marked as such.
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
SOURCE = "U.S. Bureau of Labor Statistics, Job Openings and Labor Turnover Survey, via FRED, St. Louis Fed (official, free public data)"
PAGE = "https://fred.stlouisfed.org/series/JTSHIL"
START = "2000-12-01"                                   # the first month of the survey: 310 months to 2026-09
MEASURES = {"HIL": "hires", "QUL": "quits", "LDL": "layoffs", "TSL": "separations", "OSL": "other separations"}      # short on purpose: fail_reason shows 110 characters
SECTOR_MEASURES = ("HIL", "QUL", "LDL", "TSL", "OSL")
INDUSTRY_MEASURES = ("HIL", "QUL", "TSL")
GROUPS = (("nonfarm", "JTS", "nonfarm", SECTOR_MEASURES), ("private", "JTS1000", "private", SECTOR_MEASURES), ("government", "JTS9000", "government", SECTOR_MEASURES),
          ("construction", "JTS2300", "construction", INDUSTRY_MEASURES), ("manufacturing", "JTS3000", "manufacturing", INDUSTRY_MEASURES),
          ("trade_transport", "JTS4000", "trade, transport and utilities", INDUSTRY_MEASURES), ("professional", "JTS540099", "professional and business services", INDUSTRY_MEASURES),
          ("education_health", "JTS6000", "education and health services", INDUSTRY_MEASURES), ("leisure", "JTS7000", "leisure and hospitality", INDUSTRY_MEASURES))
NAMES = {f"{prefix}{m}": f"{name} {MEASURES[m]}" for _key, prefix, name, ms in GROUPS for m in ms}
SERIES = list(NAMES)
GROUP_NAMES = {prefix: name for _key, prefix, name, _ms in GROUPS}
LIMITS = {"JTSHIL": (1_500.0, 20_000.0), "JTSQUL": (800.0, 9_000.0), "JTSLDL": (600.0, 26_000.0), "JTSTSL": (1_900.0, 32_000.0), "JTSOSL": (100.0, 900.0),
          "JTS1000HIL": (1_500.0, 20_000.0), "JTS1000QUL": (700.0, 9_000.0), "JTS1000LDL": (600.0, 26_000.0), "JTS1000TSL": (1_800.0, 32_000.0), "JTS1000OSL": (90.0, 800.0),
          "JTS9000HIL": (100.0, 1_500.0), "JTS9000QUL": (40.0, 550.0), "JTS9000LDL": (25.0, 700.0), "JTS9000TSL": (130.0, 1_100.0), "JTS9000OSL": (20.0, 190.0),
          "JTS2300HIL": (100.0, 1_500.0), "JTS2300QUL": (15.0, 500.0), "JTS2300TSL": (100.0, 1_700.0),
          "JTS3000HIL": (80.0, 1_300.0), "JTS3000QUL": (30.0, 700.0), "JTS3000TSL": (100.0, 1_800.0),
          "JTS4000HIL": (350.0, 3_200.0), "JTS4000QUL": (150.0, 2_100.0), "JTS4000TSL": (350.0, 5_600.0),
          "JTS540099HIL": (300.0, 2_900.0), "JTS540099QUL": (120.0, 1_700.0), "JTS540099TSL": (330.0, 3_900.0),
          "JTS6000HIL": (200.0, 2_300.0), "JTS6000QUL": (100.0, 1_400.0), "JTS6000TSL": (200.0, 4_200.0),
          "JTS7000HIL": (200.0, 4_100.0), "JTS7000QUL": (150.0, 1_900.0), "JTS7000TSL": (300.0, 11_500.0)}      # thousands; about half the lowest and beyond the highest real value of each series (the real ranges are in the log)
TOTAL_SUMS = tuple((f"JTS{m}", (f"JTS1000{m}", f"JTS9000{m}")) for m in SECTOR_MEASURES)                                      # total nonfarm = private + government, one measure at a time
SEPARATION_SUMS = (("JTS", "nonfarm"), ("JTS1000", "private"), ("JTS9000", "government"))                                      # separations = quits + layoffs + other, one total at a time
INDUSTRIES = (("construction", "JTS2300", "Construction"), ("manufacturing", "JTS3000", "Manufacturing"), ("trade_transport", "JTS4000", "Trade, transportation and utilities"),
              ("professional", "JTS540099", "Professional and business services"), ("education_health", "JTS6000", "Private education and health services"), ("leisure", "JTS7000", "Leisure and hospitality"))
SIX = tuple(prefix for _key, prefix, _label_text in INDUSTRIES)
REST = ("other_private", "Everything else in the private sector (mining and logging, information, financial activities, other services)")
SUM_TOLERANCE = 1.5                                    # thousands: three values each rounded to a thousand (0.5 + 0.5 + 0.5); exact in binary; the real largest gap is 1.0
SEPARATIONS_TOLERANCE = 2.0                            # thousands: four values each rounded to a thousand; the real largest gap is 1.0
PART_TOLERANCE = 1.0                                   # thousands: two rounded values
REST_TOLERANCE = 3.5                                   # thousands: seven rounded values (private and the six industries)
MIN_MONTHS = 120
HISTORY_MONTHS = 120
RECENT_MONTHS = 6
OVERDUE_AFTER_DAYS = 105                               # from the 1st of the observed month: the same release as the other JOLTS cards (the next month arrives 61 to 64 days after its own 1st)
TTL = 6 * 3600.0
FAIL_TTL = 120.0
CONCURRENCY = 8


def _check(data: dict[str, dict[date, float]]) -> tuple[list[date], dict]:
    base = data["JTSHIL"]
    if len({max(data[sid]) for sid in SERIES}) != 1:
        raise ValueError("the JOLTS flow series end in different months")
    for sid in SERIES[1:]:
        if set(data[sid]) != set(base):
            raise ValueError(f"the {NAMES[sid]} series covers different months than nonfarm hires")
    months = sorted(base)
    if any(d.day != 1 for d in months):
        raise ValueError("a JOLTS flow date is not the 1st of a month")
    for a, b in zip(months, months[1:]):
        if _months_back(b, 1) != a:
            raise ValueError(f"the JOLTS flow months skip a month after {_label(a)}")
    if len(months) < MIN_MONTHS:
        raise ValueError(f"the JOLTS flows cover {len(months)} months, fewer than the {MIN_MONTHS} expected")
    for sid in SERIES:
        lo, hi = LIMITS[sid]
        for d in months:
            v = data[sid][d]
            if not (lo <= v <= hi):
                raise ValueError(f"{NAMES[sid]} of {_num(v)} thousand in {_label(d)} is outside {_num(lo)} to {_num(hi)}")
    sum_gap = 0.0
    for whole, parts in TOTAL_SUMS:
        for d in months:
            gap = abs(data[whole][d] - sum(data[p][d] for p in parts))
            if gap > SUM_TOLERANCE:
                raise ValueError(f"nonfarm {MEASURES[whole[3:]]} differ from private plus government by {gap:g} thousand in {_label(d)}, over {SUM_TOLERANCE:g}")
            sum_gap = max(sum_gap, gap)
    for prefix, name in SEPARATION_SUMS:
        for d in months:
            gap = abs(data[prefix + "TSL"][d] - data[prefix + "QUL"][d] - data[prefix + "LDL"][d] - data[prefix + "OSL"][d])
            if gap > SEPARATIONS_TOLERANCE:
                raise ValueError(f"{name} separations differ from quits plus layoffs plus other by {gap:g} thousand in {_label(d)}, over {SEPARATIONS_TOLERANCE:g}")
            sum_gap = max(sum_gap, gap)
    margin = None
    for _key, prefix, _text in INDUSTRIES:
        for d in months:
            room = data[prefix + "TSL"][d] - data[prefix + "QUL"][d]
            if -room > PART_TOLERANCE:
                raise ValueError(f"{GROUP_NAMES[prefix]} quits exceed its separations by {-room:g} thousand in {_label(d)}, over {PART_TOLERANCE:g}")
            margin = room if margin is None else min(margin, room)
    rest_low = None
    for m in INDUSTRY_MEASURES:
        for d in months:
            rest = data["JTS1000" + m][d] - sum(data[p + m][d] for p in SIX)
            if -rest > REST_TOLERANCE:
                raise ValueError(f"the six industries add up to more than private {MEASURES[m]} by {-rest:g} thousand in {_label(d)}, over {REST_TOLERANCE:g}")
            rest_low = rest if rest_low is None else min(rest_low, rest)
    return months, {"months_checked": len(months), "first_month": _label(months[0]), "last_month": _label(months[-1]), "largest_sum_gap": round(sum_gap, 3),
                    "closest_part_margin": round(margin, 3), "smallest_rest_of_private": round(rest_low, 3)}


def _change(now: float, ago: float) -> float | None:
    v = _pct(now, ago)
    return None if v is None else v + 0.0              # a tiny fall that rounds to nothing is 0.0, not -0.0 (JSON would write the sign)


def _share(quits: float, separations: float) -> float | None:
    return round(100.0 * quits / separations, 1) if separations > 0 else None


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    months, detail = _check(data)
    last = months[-1]
    window = months[-HISTORY_MONTHS:]
    ago = _months_back(last, 12)

    def flows(prefix: str) -> dict:
        h, q, l, s, o = (data[prefix + m][last] for m in SECTOR_MEASURES)
        return {"hires_thousands": h, "quits_thousands": q, "layoffs_thousands": l, "other_thousands": o, "separations_thousands": s, "net_thousands": h - s, "quits_share_pct": _share(q, s),
                "hires_change_year_pct": _change(h, data[prefix + "HIL"][ago]), "quits_change_year_pct": _change(q, data[prefix + "QUL"][ago])}

    def industry(key: str, label: str, hires: dict, quits: dict, seps: dict, derived: bool) -> dict:
        h, q, s = hires[last], quits[last], seps[last]
        return {"key": key, "label": label, "derived": derived, "hires_thousands": h, "quits_thousands": q, "separations_thousands": s, "net_thousands": h - s, "quits_share_pct": _share(q, s),
                "hires_change_year_pct": _change(h, hires[ago]), "quits_change_year_pct": _change(q, quits[ago])}

    nf = {m: data["JTS" + m] for m in SECTOR_MEASURES}
    total = {**flows("JTS"), "layoffs_change_year_pct": _change(nf["LDL"][last], nf["LDL"][ago]), "separations_change_year_pct": _change(nf["TSL"][last], nf["TSL"][ago]),
             "hires_range": _range({d: nf["HIL"][d] for d in window}, nf["HIL"][last], window[0]), "quits_range": _range({d: nf["QUL"][d] for d in window}, nf["QUL"][last], window[0]),
             "layoffs_range": _range({d: nf["LDL"][d] for d in window}, nf["LDL"][last], window[0])}
    rows = [industry(key, label, data[prefix + "HIL"], data[prefix + "QUL"], data[prefix + "TSL"], False) for key, prefix, label in INDUSTRIES]
    rows.sort(key=lambda r: (-r["hires_thousands"], r["label"]))
    left = {m: {d: data["JTS1000" + m][d] - sum(data[p + m][d] for p in SIX) for d in months} for m in INDUSTRY_MEASURES}
    rows.append(industry(REST[0], REST[1], left["HIL"], left["QUL"], left["TSL"], True))
    age = (today - last).days
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "month": _label(last), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "total": total,
            "sectors": [{"key": "private", "label": "Private sector", **flows("JTS1000")}, {"key": "government", "label": "Government", **flows("JTS9000")}],
            "industries": rows,
            "recent": [{"month": _label(d), "hires_thousands": nf["HIL"][d], "quits_thousands": nf["QUL"][d], "layoffs_thousands": nf["LDL"][d], "separations_thousands": nf["TSL"][d],
                        "net_thousands": nf["HIL"][d] - nf["TSL"][d]} for d in months[-RECENT_MONTHS:]],
            "detail": detail,
            "checks": {"months_in_a_row": True, "range_ok": True, "totals_add_up_ok": True, "quits_inside_separations_ok": True, "industries_inside_private_ok": True},
            "note": ("The Job Openings and Labor Turnover Survey (JOLTS) of the US Bureau of Labor Statistics, seasonally adjusted, monthly. "
                     "Hires are all additions to the payroll during the month; separations are all departures: quits (the worker chose to leave), layoffs and discharges (the employer ended the job) and other separations (retirement, death, transfer, disability). "
                     "Total separations equal quits plus layoffs plus other separations; the net of a month is hires minus total separations. "
                     "FRED carries layoffs and other separations only for total nonfarm, the private sector and government, so by industry it shows hires, quits and total separations; the private industries it lacks are worked out by subtraction and marked as such. "
                     "The newest months are preliminary and are revised later. "
                     "Smaller samples make industry figures noisier than the total. "
                     "Plain checks: the units are the ones assumed and no month is missing; the ranges, the sums and the quits inside the separations are in the Check line. "
                     "This describes the labour market that already happened: it is not a market signal or a forecast.")}


class JoltsFlows:
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
            return {**base, "available": False, "reason": "Demo mode: the real US hires, quits and layoffs by industry are not shown because made-up values would look real."}
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
            res = {**base, "available": False, "reason": f"US hires, quits and layoffs by industry could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
