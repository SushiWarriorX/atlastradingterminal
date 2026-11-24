"""US job openings by industry: how many jobs employers in each industry of the United States had open at the end of a month, from the Job Openings and Labor Turnover Survey (JOLTS) of the Bureau of Labor Statistics, via FRED, the St. Louis Fed (public-domain US government data, citation requested; every series page read on 2026-11-19 names only the Bureau of Labor Statistics as source and carries no third-party notice). Free, no key.

How to read it: job openings are the jobs not filled on the last business day of the month for which a specific position exists with work available, which could start within 30 days, with active recruiting; 7,523 means 7.523 million. Sixteen series, all of them openings (level in thousands, seasonally adjusted, monthly, December 2000 on): total nonfarm (JTSJOL) = total private (JTS1000JOL) + government (JTS9000JOL, of which state and local JTS9200JOL); the private industries construction (JTS2300JOL), manufacturing (JTS3000JOL, of which durable JTS3200JOL and nondurable JTS3400JOL goods), trade, transportation and utilities (JTS4000JOL, of which retail trade JTS4400JOL), professional and business services (JTS540099JOL), private education and health services (JTS6000JOL, of which health care and social assistance JTS6200JOL) and leisure and hospitality (JTS7000JOL, of which arts, entertainment and recreation JTS7100JOL and accommodation and food services JTS7200JOL). FRED's ids are the Bureau's industry code with its trailing zeros cut (JTS1000JOL for 100000), or six digits when the code ends in 99 (JTS540099JOL). The ids tried for the other industries (mining and logging, information, financial activities, other services, wholesale trade, private education, the federal government and a few more) answered HTTP 404 on 2026-11-19, so the card works four figures out BY SUBTRACTION and marks them as such: the federal government (government minus state and local), private educational services (education and health minus health care), wholesale trade with transportation and utilities (trade, transportation and utilities minus retail) and everything else in the private sector (private minus the six industries above: mining and logging, information, financial activities and other services together). Each monthly observation is dated the 1st and means the whole month. The newest month is normally 63 to 95 days old by its date (the release of 2026-11-03 gave September).
Each series is asked for ALONE, never in a combined request: with several ids and one start date FRED applies the date to the FIRST series only and gives every other series in full, without an error (found 2026-11-18). Every request starts at 2000-12-01, the first month, so the whole record is checked each time.
Checks, set from the whole real record (310 months, December 2000 to September 2026; none missing in any series) before any test was written: the sixteen series end in the same month, cover the same months, are dated the 1st and skip no month, and at least 120 months are there; every level is inside its own range (about half the lowest and twice the highest real value of that series, so that a unit slip is caught and a real swing is not; construction ran from 24 to 457); three sums hold to within 1.5 thousand (three values each rounded to a thousand; the real largest gap is 1.0 in all three, in 310 months each: total nonfarm against private plus government, manufacturing against durable plus nondurable goods, leisure and hospitality against arts plus accommodation and food); and no part is more than 1.0 thousand above its whole (retail trade against trade, transportation and utilities, health care against education and health, state and local against government: the closest the real record comes is 25 thousand, government minus state and local in 2009-05) and the six industries are not more than 3.5 thousand above private (seven rounded values; the real remainder runs from 262 to 1,390, 9% to 20% of private). A month missing from one series, or a series that ends in another month, is refused. A missing value ('.') is left out, never filled in.
The sums are the Bureau's own arithmetic (every figure is a count of the same survey, split by industry): they show that the series belong to one release and are lined up, not that the figures are right. NOT checked, and said so: the four remainders (nothing can check the sum of four industries that are not fetched), the revisions of older months, and the survey's sampling error, which FRED does not show.
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
PAGE = "https://fred.stlouisfed.org/series/JTSJOL"
START = "2000-12-01"                                   # the first month of the survey: 310 months to 2026-09
NAMES = {"JTSJOL": "total nonfarm", "JTS1000JOL": "private", "JTS9000JOL": "government", "JTS9200JOL": "state and local", "JTS2300JOL": "construction", "JTS3000JOL": "manufacturing",
         "JTS3200JOL": "durable goods", "JTS3400JOL": "nondurable goods", "JTS4000JOL": "trade and transport", "JTS4400JOL": "retail", "JTS540099JOL": "business services",
         "JTS6000JOL": "education and health", "JTS6200JOL": "health care", "JTS7000JOL": "leisure", "JTS7100JOL": "arts", "JTS7200JOL": "food and lodging"}      # short on purpose: fail_reason shows 110 characters
SERIES = list(NAMES)
TOTAL, PRIVATE = "JTSJOL", "JTS1000JOL"
LIMITS = {"JTSJOL": (1_000.0, 25_000.0), "JTS1000JOL": (1_000.0, 25_000.0), "JTS9000JOL": (130.0, 2_500.0), "JTS9200JOL": (100.0, 2_100.0), "JTS2300JOL": (10.0, 1_000.0),
          "JTS3000JOL": (40.0, 2_000.0), "JTS3200JOL": (20.0, 1_300.0), "JTS3400JOL": (20.0, 800.0), "JTS4000JOL": (150.0, 4_500.0), "JTS4400JOL": (100.0, 3_000.0),
          "JTS540099JOL": (200.0, 5_000.0), "JTS6000JOL": (200.0, 4_500.0), "JTS6200JOL": (200.0, 4_200.0), "JTS7000JOL": (100.0, 3_500.0), "JTS7100JOL": (8.0, 450.0),
          "JTS7200JOL": (80.0, 3_100.0)}                # thousands; about half the lowest and twice the highest real value of each series (the real ranges are in the log)
SUMS = (("JTSJOL", ("JTS1000JOL", "JTS9000JOL")), ("JTS3000JOL", ("JTS3200JOL", "JTS3400JOL")), ("JTS7000JOL", ("JTS7100JOL", "JTS7200JOL")))        # a whole and its two parts
WITHIN = (("JTS4400JOL", "JTS4000JOL"), ("JTS6200JOL", "JTS6000JOL"), ("JTS9200JOL", "JTS9000JOL"))                                                        # a part and its whole
SIX = ("JTS2300JOL", "JTS3000JOL", "JTS4000JOL", "JTS540099JOL", "JTS6000JOL", "JTS7000JOL")                                                              # the private industries that are fetched
SUM_TOLERANCE = 1.5                                    # thousands: three values each rounded to a thousand (0.5 + 0.5 + 0.5); exact in binary; the real largest gap is 1.0
PART_TOLERANCE = 1.0                                   # thousands: two rounded values
REST_TOLERANCE = 3.5                                   # thousands: seven rounded values (private and the six industries)
MIN_MONTHS = 120
HISTORY_MONTHS = 120
OVERDUE_AFTER_DAYS = 105                               # from the 1st of the observed month: the same release as the JOLTS card (the next month arrives 61 to 64 days after its own 1st)
TTL = 6 * 3600.0
FAIL_TTL = 120.0
# the card's industries: key, label, the series of the whole, and its parts (key, label, series); a part without a series is the whole minus the parts that have one
GROUPS = (("education_health", "Private education and health services", "JTS6000JOL", (("health_care", "Health care and social assistance", "JTS6200JOL"), ("education", "Private educational services", None))),
          ("business", "Professional and business services", "JTS540099JOL", ()),
          ("trade_transport", "Trade, transportation and utilities", "JTS4000JOL", (("retail", "Retail trade", "JTS4400JOL"), ("wholesale_transport", "Wholesale trade, transportation and utilities", None))),
          ("government", "Government", "JTS9000JOL", (("state_local", "State and local government", "JTS9200JOL"), ("federal", "Federal government", None))),
          ("leisure", "Leisure and hospitality", "JTS7000JOL", (("food_lodging", "Accommodation and food services", "JTS7200JOL"), ("arts", "Arts, entertainment and recreation", "JTS7100JOL"))),
          ("manufacturing", "Manufacturing", "JTS3000JOL", (("durable", "Durable goods manufacturing", "JTS3200JOL"), ("nondurable", "Nondurable goods manufacturing", "JTS3400JOL"))),
          ("construction", "Construction", "JTS2300JOL", ()))
REST = ("other_private", "Everything else in the private sector (mining and logging, information, financial activities, other services)")


def _check(data: dict[str, dict[date, float]]) -> tuple[list[date], dict]:
    base = data[TOTAL]
    if len({max(data[sid]) for sid in SERIES}) != 1:
        raise ValueError("the JOLTS industry series end in different months")
    for sid in SERIES[1:]:
        if set(data[sid]) != set(base):
            raise ValueError(f"the {NAMES[sid]} series covers different months than total nonfarm")
    months = sorted(base)
    if any(d.day != 1 for d in months):
        raise ValueError("a JOLTS industry date is not the 1st of a month")
    for a, b in zip(months, months[1:]):
        if _months_back(b, 1) != a:
            raise ValueError(f"the JOLTS industry months skip a month after {_label(a)}")
    if len(months) < MIN_MONTHS:
        raise ValueError(f"the JOLTS industries cover {len(months)} months, fewer than the {MIN_MONTHS} expected")
    for sid in SERIES:
        lo, hi = LIMITS[sid]
        for d in months:
            v = data[sid][d]
            if not (lo <= v <= hi):
                raise ValueError(f"{NAMES[sid]} openings of {_num(v)} thousand in {_label(d)} is outside {_num(lo)} to {_num(hi)}")
    sum_gap = 0.0
    for whole, parts in SUMS:
        for d in months:
            gap = abs(data[whole][d] - sum(data[p][d] for p in parts))
            if gap > SUM_TOLERANCE:
                raise ValueError(f"{NAMES[whole]} differs from {' plus '.join(NAMES[p] for p in parts)} by {gap:g} thousand in {_label(d)}, over {SUM_TOLERANCE:g}")
            sum_gap = max(sum_gap, gap)
    margin = None
    for part, whole in WITHIN:
        for d in months:
            room = data[whole][d] - data[part][d]
            if -room > PART_TOLERANCE:
                raise ValueError(f"{NAMES[part]} openings exceed {NAMES[whole]} by {-room:g} thousand in {_label(d)}, over {PART_TOLERANCE:g}")
            margin = room if margin is None else min(margin, room)
    rest_low = None
    for d in months:
        rest = data[PRIVATE][d] - sum(data[sid][d] for sid in SIX)
        if -rest > REST_TOLERANCE:
            raise ValueError(f"the six industries add up to more than private by {-rest:g} thousand in {_label(d)}, over {REST_TOLERANCE:g}")
        rest_low = rest if rest_low is None else min(rest_low, rest)
    return months, {"months_checked": len(months), "first_month": _label(months[0]), "last_month": _label(months[-1]), "largest_sum_gap": round(sum_gap, 3),
                    "closest_part_margin": round(margin, 3), "smallest_rest_of_private": round(rest_low, 3)}


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    months, detail = _check(data)
    last = months[-1]
    window = months[-HISTORY_MONTHS:]
    ago = _months_back(last, 12)
    total = data[TOTAL]
    now_total = total[last]

    def row(key: str, label: str, values: dict[date, float], derived: bool) -> dict:
        now = values[last]
        return {"key": key, "label": label, "derived": derived, "openings_thousands": now, "share_pct": round(100.0 * now / now_total, 1), "year_ago_thousands": values[ago],
                "change_year_pct": _pct(now, values[ago]), "range": _range({d: values[d] for d in window}, now, window[0])}

    industries = []
    for key, label, sid, parts in GROUPS:
        fetched = [p[2] for p in parts if p[2] is not None]
        rows = [row(pkey, plabel, data[psid] if psid is not None else {d: data[sid][d] - sum(data[x][d] for x in fetched) for d in months}, psid is None) for pkey, plabel, psid in parts]
        rows.sort(key=lambda r: (-r["openings_thousands"], r["label"]))
        industries.append({**row(key, label, data[sid], False), "parts": rows})
    industries.sort(key=lambda r: (-r["openings_thousands"], r["label"]))
    industries.append({**row(REST[0], REST[1], {d: data[PRIVATE][d] - sum(data[sid][d] for sid in SIX) for d in months}, True), "parts": []})
    age = (today - last).days
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "month": _label(last), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "total": {"openings_thousands": now_total, "year_ago_thousands": total[ago], "change_year_pct": _pct(now_total, total[ago]),
                      "private_thousands": data[PRIVATE][last], "private_share_pct": round(100.0 * data[PRIVATE][last] / now_total, 1),
                      "government_thousands": data["JTS9000JOL"][last], "government_share_pct": round(100.0 * data["JTS9000JOL"][last] / now_total, 1),
                      "range": _range({d: total[d] for d in window}, now_total, window[0])},
            "industries": industries,
            "detail": detail,
            "checks": {"months_in_a_row": True, "range_ok": True, "totals_add_up_ok": True, "parts_inside_wholes_ok": True},
            "note": ("The Job Openings and Labor Turnover Survey (JOLTS) of the US Bureau of Labor Statistics, seasonally adjusted, monthly: job openings by industry. "
                     "Job openings are jobs not filled on the last business day of the month: a specific position with work available that could start within 30 days, with active recruiting. "
                     "The industries add up to the total, within the rounding of each figure to a thousand. "
                     "FRED carries sixteen of the survey's industry series; the rest are worked out by subtraction and marked as such: the federal government, private educational services, wholesale trade with transportation and utilities, and mining and logging, information, financial activities and other services together. "
                     "The newest months are preliminary and are revised later; each figure carries its month. "
                     "Smaller samples make industry figures noisier than the total. "
                     "Plain checks: the units are the ones assumed and no month is missing; the ranges, the sums and the parts inside their wholes are in the Check line. "
                     "This describes the labour market that already happened: it is not a market signal or a forecast.")}


class JoltsIndustries:
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
            return {**base, "available": False, "reason": "Demo mode: the real US job openings by industry are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=25)
        try:
            got = await asyncio.gather(*[self._fetch(c, sid) for sid in SERIES])
            res = {**base, **summarize(dict(zip(SERIES, got)), now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, KeyError) as e:
            res = {**base, "available": False, "reason": f"US job openings by industry could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
