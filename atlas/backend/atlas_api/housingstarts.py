"""US housing starts: how many new homes builders in the United States began building in a month, as a seasonally adjusted annual rate in thousands of homes, from the Census Bureau and the Department of Housing and Urban Development via FRED, the St. Louis Fed (public-domain US government data, citation requested). Free, no key.

How to read it: the headline is the total (HOUST): 1,221 means builders broke ground at a pace of 1.221 million homes a year, as if that month's pace went on for twelve months. It is split into single-family homes (HOUST1F) and homes in buildings of five or more units (HOUST5F). The rest, homes in buildings of two to four units (about one start in a hundred), is not shown: FRED's series for it (HOUST2F) is calculated by a third party, Haver Analytics, which carries its own copyright notice, as the total minus the other two. A start is counted when digging for the foundation begins. Each monthly observation is dated the 1st and means the whole month. The newest month is an estimate published about the 17th of the next month and revised in later releases, so it is normally 47 to 80 days old by its date and carries it.
Checks, set from the whole real history (813 months, January 1959 to September 2026) before any test was written: each of the last 24 monthly totals is between 300 and 3,000 (the real range is 478 to 2,494) and the months follow each other without a gap; no one-month change under -35% or over +40% (the real extremes are -26.42% in March 1984 and +29.27% in July 1982); no year-on-year change under -65% or over +115% (the real extremes are -54.80% in January 2009 and +96.19% in February 1983, so a real shock is never refused); and for each of the last 24 months single-family plus five-or-more starts are at most the total plus 1 (the remainder is never negative in the real record: its smallest value since 1963 is 3) with single-family starts between 40% and 95% of the total (the real range is 51.4% to 90.2%, so swapped parts are caught: they would give 21% to 36% in the last 24 months). A month missing from one series, or a series that ends in another month, is refused. A missing value is left out, never filled in.
There is NO exact "the parts add up to the total" check here, unlike the retail sales card: the series that would complete such a sum is the one calculated from the other two, so the sum holds by construction in all 813 months and proves nothing (found 2026-11-17 by reading the series notes on the source page; the queue had listed it as an exact check).
It describes what already happened: it is not a market signal or a forecast. A failure says so and shows nothing.
"""
from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from .claims import _pct
from .failreason import fail_reason
from .fincond import parse
from .moneysupply import _growth, _label, _months_back

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SOURCE = "U.S. Census Bureau and U.S. Department of Housing and Urban Development, New Residential Construction, via FRED, St. Louis Fed (official, free public data)"
PAGE = "https://fred.stlouisfed.org/series/HOUST"
SERIES = {"HOUST": "new homes started, total", "HOUST1F": "single-family homes", "HOUST5F": "homes in buildings of five or more units"}
LIMITS = (300.0, 3000.0)             # thousands of homes at an annual rate; the real range is 478 to 2,494 (a x10 or /10 slip is caught)
CHECK_MONTHS = 24
MONTH_MOVE = (-0.35, 0.40)           # one-month change; the real extremes are -26.42% and +29.27%
YOY_LIMITS = (-0.65, 1.15)           # year-on-year change; the real extremes are -54.80% and +96.19%
PARTS_TOLERANCE = 1.0                # thousands: single-family + five-or-more may exceed the total by this much; the real remainder (the rest) is never below 3 since 1963
SINGLE_SHARE = (0.40, 0.95)          # single-family as a share of the total; the real range is 51.4% to 90.2%
HISTORY_MONTHS = 36
OVERDUE_AFTER_DAYS = 90              # from the 1st of the observed month: the next month normally arrives about 76 to 80 days after it
TTL = 6 * 3600.0
FAIL_TTL = 120.0
LOOKBACK_DAYS = 4200                 # about 11.5 years: enough for 120 months of year-on-year growth


def _check(tot: dict[date, float], sf: dict[date, float], mf: dict[date, float]) -> tuple[list[date], dict]:
    if not (max(tot) == max(sf) == max(mf)):
        raise ValueError("the three housing starts series end in different months")
    months = sorted(tot)
    recent = months[-CHECK_MONTHS:]
    if any(d.day != 1 for d in recent):
        raise ValueError("a housing starts date is not the 1st of a month")
    if any(not (LIMITS[0] <= tot[d] <= LIMITS[1]) for d in recent):
        raise ValueError("a housing starts value is outside the plausible range")
    if any(_months_back(b, 1) != a for a, b in zip(recent, recent[1:])):
        raise ValueError(f"the housing starts values skip a month in the last {CHECK_MONTHS}")
    for a, b in zip(recent, recent[1:]):
        ch = tot[b] / tot[a] - 1
        if not (MONTH_MOVE[0] <= ch <= MONTH_MOVE[1]):
            raise ValueError(f"housing starts changed by {ch:.1%} in {_label(b)}, outside {MONTH_MOVE[0]:.0%} to {MONTH_MOVE[1]:+.0%}")
    for d in recent:
        ago = tot.get(_months_back(d, 12))
        if ago is not None and not (YOY_LIMITS[0] <= tot[d] / ago - 1 <= YOY_LIMITS[1]):
            raise ValueError(f"housing starts changed by {tot[d] / ago - 1:.1%} over the year to {_label(d)}, outside {YOY_LIMITS[0]:.0%} to {YOY_LIMITS[1]:+.0%}")
    rests = []
    for d in recent:
        if d not in sf or d not in mf:
            raise ValueError(f"single-family or five-or-more-unit starts are missing for {_label(d)}")
        over = sf[d] + mf[d] - tot[d]
        if over > PARTS_TOLERANCE:
            raise ValueError(f"single-family plus five-or-more-unit starts are {over:+,.1f} thousand above the total in {_label(d)}")
        if not (SINGLE_SHARE[0] <= sf[d] / tot[d] <= SINGLE_SHARE[1]):
            raise ValueError(f"single-family homes are {sf[d] / tot[d]:.1%} of housing starts in {_label(d)}, outside {SINGLE_SHARE[0]:.0%} to {SINGLE_SHARE[1]:.0%}")
        rests.append(tot[d] - sf[d] - mf[d])
    last = months[-1]
    return months, {"months_checked": len(recent), "smallest_remainder_thousands": round(min(rests), 3), "largest_remainder_thousands": round(max(rests), 3),
                    "newest": {"month": _label(last), "total_thousands": tot[last], "single_family_thousands": sf[last], "five_plus_thousands": mf[last], "remainder_thousands": round(tot[last] - sf[last] - mf[last], 3)}}


def _part(s: dict[date, float], total: dict[date, float], last: date) -> dict:
    v = s[last]
    return {"level_thousands": round(v, 1), "share_pct": round(100 * v / total[last], 1), "change_1m_pct": _pct(v, s.get(_months_back(last, 1))), "change_1y_pct": _pct(v, s.get(_months_back(last, 12)))}


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    tot, sf, mf = data["HOUST"], data["HOUST1F"], data["HOUST5F"]
    months, parts = _check(tot, sf, mf)
    last = months[-1]
    v = tot[last]
    age = (today - last).days
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "month": _label(last), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "level_thousands": round(v, 1), "change_1m_pct": _pct(v, tot.get(_months_back(last, 1))), "change_3m_pct": _pct(v, tot.get(_months_back(last, 3))), "change_1y_pct": _pct(v, tot.get(_months_back(last, 12))),
            "single_family": _part(sf, tot, last), "five_plus": _part(mf, tot, last), "growth": _growth(tot, last), "parts": parts,
            "history": [{"date": d.isoformat(), "level": round(tot[d], 1)} for d in months[-HISTORY_MONTHS:]],
            "checks": {"range_ok": True, "months_in_a_row": True, "monthly_move_ok": True, "yearly_change_ok": True, "parts_within_total": True, "single_family_share_ok": True},
            "note": ("Housing starts count the new homes on which builders began construction in a month (the digging of the foundation), as a seasonally adjusted annual rate in thousands: 1,221 means a pace of 1.221 million homes a year. "
                     "Single-family homes and homes in buildings of five or more units are shown; the rest, homes in buildings of two to four units (about one start in a hundred), is not. "
                     "The newest month is an estimate that is revised in later releases; each figure carries its month. "
                     "Checked: every recent monthly total is between 300 and 3,000 thousand with no month missing, no month moved by more than the real record allows, single-family and five-or-more-unit starts never add up to more than the total, and single-family homes are 40% to 95% of it. "
                     "There is no exact parts-add-up check, because FRED's series for the remaining homes is calculated from the total and the other two. "
                     "This describes what already happened: it is not a market signal or a forecast.")}


class HousingStarts:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def _fetch(self, c: httpx.AsyncClient, sid: str) -> dict[date, float]:
        # No custom User-Agent: FRED stalls and drops connections for an unfamiliar one (seen 2026-11-12) and answers the client's default one fast. cosd keeps the download to about 11 years.
        r = await c.get(URL, params={"id": sid, "cosd": (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()})
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        return parse(r.text, sid)

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real housing starts figures are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=25)
        try:
            got = await asyncio.gather(*[self._fetch(c, sid) for sid in SERIES])
            res = {**base, **summarize(dict(zip(SERIES, got)), now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, KeyError) as e:
            res = {**base, "available": False, "reason": f"Housing starts could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
