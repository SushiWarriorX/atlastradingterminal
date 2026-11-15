"""The European Central Bank's three key interest rates, with the euro overnight market rate beside them, from the ECB Data Portal's public API (official, free, no key).

What is shown: the deposit facility rate (what the ECB pays banks for money left with it overnight), the main refinancing rate (what banks pay for the ECB's regular one-week loans at a fixed rate) and the marginal lending rate (what banks
pay to borrow from the ECB overnight), each as it stood on the latest date, against a year earlier, with when it last changed and by how much (found by comparing every day with the day before, not typed in), and the last six changes of the
deposit rate. Beside them the euro short-term rate (EUR STR), the rate banks actually paid each other for unsecured overnight loans, which the ECB calculates from the transactions banks report: the check that the three policy rates are
the right numbers is that this market rate sits just under the deposit rate, as it has on every business day since it began.
The series are the ECB's "date of changes" series, one value for every calendar day, so a rate that has not changed still has today's value; the card says "in force on" a date, not "decided on".

Checks, with every limit set from the real history before any test was written (all of 1999 to 2026 for the key rates, 1,824 business days from October 2019 for the euro short-term rate):
for each of the three key-rate series, in its last 400 days: every calendar day is present (real: no gap since 2008-10-15 in all three; the main refinancing rate has no fixed-rate value from June 2000 to October 2008, when the ECB
auctioned at variable rates), every value is a multiple of 0.05 (real: all 10,181, 7,150 and 10,181 values), every value is between -1.5 and 10 percent (real: -0.50 to 5.75), and no day moves it by more than 1.5 points (real: 1.00, 0.75 and 1.25); on every
common day the deposit rate is under the main refinancing rate, which is under the marginal lending rate (real: on all 7,150 shared days; the narrowest gaps are 0.15 and 0.25). For the euro short-term rate, in its last 60 observations: every date is a weekday,
no two are more than 7 days apart (real: at most 5, Easter and Christmas), every value is between -1.5 and 10 percent (real: -0.59 to 3.91), the deposit rate has a value for each date, and the euro short-term rate is between 0.30 under and 0.10 over the
deposit rate (real: between 0.120 and 0.011 under on all 1,824 days). A failing check shows nothing. Missing or non-numeric values are left out, never filled in; two values for one day are an error.
It describes what the rates are and were: it is not a market signal or a forecast, and it says nothing about what the ECB will decide next.
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

KEYRATES_URL = "https://data-api.ecb.europa.eu/service/data/FM/D.U2.EUR.4F.KR.DFR+MRR_FR+MLFR.LEV"
ESTR_URL = "https://data-api.ecb.europa.eu/service/data/EST/B.EU000A2X2A25.WT"
SOURCE = "European Central Bank, ECB Data Portal: key interest rates and the euro short-term rate (official, free public data)"
PAGE = "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/key_ecb_interest_rates/html/index.en.html"
RATE_IDS = ("DFR", "MRR_FR", "MLFR")
KEYS = {f"FM.D.U2.EUR.4F.KR.{i}.LEV": i for i in RATE_IDS}
ESTR_KEY = "EST.B.EU000A2X2A25.WT"
NAMES = {"DFR": "Deposit facility rate", "MRR_FR": "Main refinancing rate", "MLFR": "Marginal lending rate"}
MEANINGS = {"DFR": "what the ECB pays banks for money left with it overnight",
            "MRR_FR": "what banks pay for the ECB's regular one-week loans at a fixed rate",
            "MLFR": "what banks pay to borrow from the ECB overnight"}
KEY_LOOKBACK_DAYS = 1500          # about four years: the last six deposit-rate changes, a year-ago figure and the 400 checked days
ESTR_LOOKBACK_DAYS = 120          # about 85 business days: the 60 checked observations
CHECK_DAYS = 400
RATE_LIMITS = (-1.5, 10.0)        # percent; the real range in 27 years is -0.50 (deposit rate, 2019 to 2022) to 5.75 (marginal lending rate, 2008)
STEP = 0.05                       # every value in 27 years of all three series is a multiple of 0.05
MAX_DAY_STEP = 1.5                # points; the real largest one-day change in 27 years is 1.25 (marginal lending rate)
ESTR_CHECK = 60
ESTR_MAX_GAP_DAYS = 7             # the real largest gap between published dates is 5 days (Easter, Christmas)
ESTR_GAP_LIMITS = (-0.30, 0.10)   # euro short-term rate minus the deposit rate; real: -0.120 to -0.011 on all 1,824 business days since October 2019
DECISIONS = 6
OVERDUE_AFTER_DAYS = 5            # the key-rate series has a value for every calendar day, today's included
OVERDUE_ESTR_DAYS = 8             # a business day's rate comes out on the next one: after a long holiday weekend the newest can be about 6 days old
TTL = 3600.0
FAIL_TTL = 120.0


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


_ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def _day(x) -> date | None:
    """A day written exactly YYYY-MM-DD. Not date.fromisoformat alone: from Python 3.11 that also reads a week such as 2026-W46 as a day (its Monday)."""
    if not isinstance(x, str) or not _ISO_DAY.fullmatch(x):
        return None
    try:
        return date.fromisoformat(x)
    except ValueError:
        return None


def parse_keyrates(text: str) -> dict[str, dict[date, float]]:
    """The three series from the ECB's CSV, by id. Rows of any other series, and rows without a date or a number, are left out; two values for one day are an error."""
    out: dict[str, dict[date, float]] = {i: {} for i in RATE_IDS}
    for r in csv.DictReader(io.StringIO(text)):
        sid, d, v = KEYS.get(r.get("KEY") or ""), _day(r.get("TIME_PERIOD")), _num(r.get("OBS_VALUE"))
        if sid is None or d is None or v is None:
            continue
        if d in out[sid]:
            raise ValueError(f"the {NAMES[sid].lower()} has two values for {d.isoformat()}")
        out[sid][d] = v
    missing = [NAMES[i] for i in RATE_IDS if not out[i]]
    if missing:
        raise ValueError("the source returned no values for the " + " or the ".join(m.lower() for m in missing))
    return out


def parse_estr(text: str) -> dict[date, float]:
    out: dict[date, float] = {}
    for r in csv.DictReader(io.StringIO(text)):
        d, v = _day(r.get("TIME_PERIOD")), _num(r.get("OBS_VALUE"))
        if r.get("KEY") != ESTR_KEY or d is None or v is None:
            continue
        if d in out:
            raise ValueError(f"the euro short-term rate has two values for {d.isoformat()}")
        out[d] = v
    if not out:
        raise ValueError("the source returned no euro short-term rate")
    return out


def _check_rates(kr: dict[str, dict[date, float]]) -> None:
    for i in RATE_IDS:
        s, name = kr[i], NAMES[i].lower()
        days = sorted(s)[-CHECK_DAYS:]
        if len(days) < CHECK_DAYS:
            raise ValueError(f"the {name} has {len(days)} days, {CHECK_DAYS} are needed")
        if any((b - a).days != 1 for a, b in zip(days, days[1:])):
            raise ValueError(f"the {name} skips a day in its last {CHECK_DAYS}")
        for d in days:
            if not RATE_LIMITS[0] <= s[d] <= RATE_LIMITS[1]:
                raise ValueError(f"the {name} is {s[d]:g}% on {d.isoformat()}, outside {RATE_LIMITS[0]:g}% to {RATE_LIMITS[1]:g}%")
            if abs(s[d] / STEP - round(s[d] / STEP)) > 1e-6:
                raise ValueError(f"the {name} is {s[d]:g}% on {d.isoformat()}, not a multiple of {STEP}")
        for a, b in zip(days, days[1:]):
            if abs(s[b] - s[a]) > MAX_DAY_STEP:
                raise ValueError(f"the {name} moved {s[b] - s[a]:+.2f} points in one day, to {b.isoformat()}")
    common = sorted(set(kr["DFR"]) & set(kr["MRR_FR"]) & set(kr["MLFR"]))[-CHECK_DAYS:]
    for d in common:
        if not kr["DFR"][d] < kr["MRR_FR"][d] < kr["MLFR"][d]:
            raise ValueError(f"the deposit, main refinancing and marginal lending rates are not in that order on {d.isoformat()}")


def _changes(s: dict[date, float]) -> list[dict]:
    """Every change in the series, oldest first: the day the value differs from the day before (a missing day is never read as a change)."""
    days = sorted(s)
    return [{"date": b.isoformat(), "from": round(s[a], 2), "to": round(s[b], 2), "change": round(s[b] - s[a], 2)}
            for a, b in zip(days, days[1:]) if (b - a).days == 1 and s[b] != s[a]]


def _market(estr: dict[date, float], deposit: dict[date, float], today: date) -> dict:
    days = sorted(estr)[-ESTR_CHECK:]
    if len(days) < ESTR_CHECK:
        raise ValueError(f"the euro short-term rate has {len(days)} days, {ESTR_CHECK} are needed")
    if any(d.weekday() > 4 for d in days):
        raise ValueError("a euro short-term rate date is not a weekday")
    if any((b - a).days > ESTR_MAX_GAP_DAYS for a, b in zip(days, days[1:])):
        raise ValueError(f"two euro short-term rate dates are more than {ESTR_MAX_GAP_DAYS} days apart")
    gaps = []
    for d in days:
        if not RATE_LIMITS[0] <= estr[d] <= RATE_LIMITS[1]:
            raise ValueError(f"the euro short-term rate is {estr[d]:g}% on {d.isoformat()}, outside {RATE_LIMITS[0]:g}% to {RATE_LIMITS[1]:g}%")
        if d not in deposit:
            raise ValueError(f"the deposit rate has no value for {d.isoformat()}, a day the euro short-term rate has")
        g = estr[d] - deposit[d]
        if not ESTR_GAP_LIMITS[0] <= g <= ESTR_GAP_LIMITS[1]:
            raise ValueError(f"the euro short-term rate is {g:+.3f} points from the deposit rate on {d.isoformat()}, outside {ESTR_GAP_LIMITS[0]:+.2f} to {ESTR_GAP_LIMITS[1]:+.2f}")
        gaps.append(g)
    last = days[-1]
    age = max(0, (today - last).days)
    return {"date": last.isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_ESTR_DAYS else "OVERDUE", "rate": round(estr[last], 3), "deposit_rate": round(deposit[last], 2),
            "gap": round(gaps[-1], 3), "observations": len(days), "first_date": days[0].isoformat(), "gap_low": round(min(gaps), 3), "gap_high": round(max(gaps), 3)}


def summarize(kr: dict[str, dict[date, float]], estr: dict[date, float], today: date) -> dict:
    _check_rates(kr)
    market = _market(estr, kr["DFR"], today)
    as_of = min(max(s) for s in kr.values())                         # the oldest of the three newest dates: every figure below is the one in force on this day
    year_ago = as_of - timedelta(days=365)
    rates = []
    for i in RATE_IDS:
        s = kr[i]
        if as_of not in s:
            raise ValueError(f"the {NAMES[i].lower()} has no value for {as_of.isoformat()}")
        ch = _changes(s)
        ya = s.get(year_ago)
        rates.append({"id": i, "name": NAMES[i], "meaning": MEANINGS[i], "rate": round(s[as_of], 2), "above_deposit_rate": None if i == "DFR" else round(s[as_of] - kr["DFR"][as_of], 2),
                      "year_ago": None if ya is None else round(ya, 2), "change_1y": None if ya is None else round(s[as_of] - ya, 2), "last_change": ch[-1] if ch else None})
    age = max(0, (today - as_of).days)
    decisions = list(reversed(_changes(kr["DFR"])))[:DECISIONS]
    return {"available": True, "source": SOURCE, "url": PAGE, "date": as_of.isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "year_ago_date": year_ago.isoformat(), "rates": rates, "decisions": decisions, "market": market,
            "checks": {"days_in_a_row": True, "values_in_range": True, "values_in_steps_of_0_05": True, "daily_moves_ok": True, "rates_in_order": True, "market_rate_in_line": True},
            "note": ("These are the three interest rates the European Central Bank sets for euro-area banks, in percent a year; the ECB's series has a value for every calendar day, so each is the rate in force on the date shown, not the date it was decided. "
                     "The euro short-term rate is, in the ECB's own series title, the volume-weighted trimmed mean rate on unsecured overnight borrowing by financial corporations; it is dated by business day, so its newest value is a few days older than the rates'. "
                     "Checked: every recent day is present, every value is a multiple of 0.05 within a plausible range, no day moves a rate by more than the real record allows, the deposit rate is under the main refinancing rate, which is under the marginal lending rate, "
                     "and the euro short-term rate sits close to the deposit rate on each of the last 60 days. "
                     "This describes what the rates are and were: it is not a market signal or a forecast, and it says nothing about what the ECB will decide next.")}


class EcbRates:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def _get(self, c: httpx.AsyncClient, url: str, start: date) -> str:
        r = await c.get(url, params={"startPeriod": start.isoformat(), "format": "csvdata", "detail": "dataonly"}, headers={"User-Agent": "ATLAS research terminal", "Accept": "text/csv"})
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        return r.text

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real ECB interest rates are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=25)
        try:
            today = now.date()
            kr_text, estr_text = await asyncio.gather(self._get(c, KEYRATES_URL, today - timedelta(days=KEY_LOOKBACK_DAYS)), self._get(c, ESTR_URL, today - timedelta(days=ESTR_LOOKBACK_DAYS)))
            res = {**base, **summarize(parse_keyrates(kr_text), parse_estr(estr_text), today)}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, KeyError) as e:
            res = {**base, "available": False, "reason": f"The ECB interest rates could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
