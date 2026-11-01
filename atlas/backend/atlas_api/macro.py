"""Macro dashboard: official FRED observations (facts) and rule-based educational notes (interpretations). No AI, no scores, no signals.

Facts are computed here and nowhere else. Dates are matched exactly before any spread or year-over-year figure: a figure whose matching
observation is missing is None (shown as unavailable), never an approximation from a neighbouring date.
"""
from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timedelta, timezone

from .instruments import Instrument
from .models import ProviderUnavailable

SOURCE = "FRED (Federal Reserve Bank of St. Louis), public CSV. Observation dates are not publication dates."
RULES = {"curve_flat_bps": 50.0, "yield_move_bps_1m": 25.0, "core_cpi_high": 3.0, "inflation_goal": 2.0, "usd_move_pct_1m": 2.0, "fed_unchanged_note_days": 90}

# series id -> (label, unit, cadence text, stale-after days, how that was chosen)
SERIES = {
    "DGS10": ("US 10-Year Treasury yield", "%", "daily (business days)", 6, "published the next business day; allows a long weekend plus a holiday"),
    "DGS2": ("US 2-Year Treasury yield", "%", "daily (business days)", 6, "published the next business day; allows a long weekend plus a holiday"),
    "CPIAUCSL": ("CPI, all items (seasonally adjusted)", "index", "monthly", 80, "dated the 1st of the reference month and released around mid next month, so 6-7 weeks old is normal"),
    "CPILFESL": ("Core CPI, excl. food & energy (seasonally adjusted)", "index", "monthly", 80, "same schedule as CPI"),
    "DFEDTARL": ("Fed funds target range, lower bound", "%", "daily (changes only at FOMC decisions)", 7, "posted daily; an unchanged value is normal and is not stale"),
    "DFEDTARU": ("Fed funds target range, upper bound", "%", "daily (changes only at FOMC decisions)", 7, "posted daily; an unchanged value is normal and is not stale"),
    "DTWEXBGS": ("Nominal Broad U.S. Dollar Index (NOT DXY)", "index", "daily, published weekly (Mondays)", 14, "released weekly with data through the prior Friday, so about 10 days old is normal"),
}


def instrument(sid: str) -> Instrument:
    return Instrument(f"MACRO:FRED:{sid}", sid, SERIES[sid][0], "macro", "FRED", "fred", sid, currency=SERIES[sid][1])


def freshness(sid: str, obs: date, today: date) -> dict:
    age = (today - obs).days
    limit, why = SERIES[sid][3], SERIES[sid][4]
    return {"state": "CURRENT" if age <= limit else "OVERDUE", "age_days": age, "limit_days": limit, "rule": f"{SERIES[sid][2]}; overdue after {limit} days: {why}"}


# --- pure calculations (points are (date, value) ascending) ---------------------------------------------------------------------------
def on_or_before(pts: list[tuple[date, float]], d: date) -> tuple[date, float] | None:
    best = None
    for x in pts:
        if x[0] <= d:
            best = x
        else:
            break
    return best


def bps(a: float, b: float) -> float:
    return (a - b) * 100.0


def pct(a: float, b: float) -> float | None:
    return None if not b else (a / b - 1.0) * 100.0


def spread(a: list[tuple[date, float]], b: list[tuple[date, float]]) -> list[tuple[date, float]]:
    """a - b on dates present in BOTH series only."""
    bm = dict(b)
    return [(d, v - bm[d]) for d, v in a if d in bm]


def minus_year(d: date) -> date | None:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return None


def yoy(pts: list[tuple[date, float]]) -> list[tuple[date, float]]:
    """Year-over-year % for each month whose same calendar month one year earlier is also present."""
    m = dict(pts)
    out = []
    for d, v in pts:
        p = minus_year(d)
        r = pct(v, m[p]) if p in m else None
        if r is not None:
            out.append((d, r))
    return out


def prev_month(d: date) -> date:
    return (d.replace(day=1) - timedelta(days=1)).replace(day=1)          # CPI observations are dated the 1st of their month


def unchanged_since(pts: list[tuple[date, float]]) -> tuple[date, bool]:
    """Start of the final run of equal values, and whether that run reaches the start of the data (so the true start is unknown)."""
    last = pts[-1][1]
    i = len(pts) - 1
    while i > 0 and pts[i - 1][1] == last:
        i -= 1
    return pts[i][0], i == 0


# --- facts -------------------------------------------------------------------------------------------------------------------------------
def _base(fid: str, label: str, unit: str) -> dict:
    return {"id": fid, "label": label, "unit": unit, "status": "HISTORICAL"}


def _unavailable(fid: str, label: str, why: str) -> dict:
    return {"id": fid, "label": label, "error": why}


def yield_fact(sid: str, fid: str, pts: list[tuple[date, float]], today: date) -> dict:
    d, v = pts[-1]
    f = {**_base(fid, SERIES[sid][0], "%"), "series": sid, "value": v, "obs_date": d.isoformat(), "freshness": freshness(sid, d, today), "changes": []}
    if len(pts) > 1:
        f["changes"].append({"label": "vs previous observation", "ref_date": pts[-2][0].isoformat(), "value": bps(v, pts[-2][1]), "unit": "bps"})
    r = on_or_before(pts, d - timedelta(days=30))
    if r:
        f["changes"].append({"label": "vs ~1 month earlier", "ref_date": r[0].isoformat(), "value": bps(v, r[1]), "unit": "bps"})
    return f


def curve_fact(y10: list[tuple[date, float]], y2: list[tuple[date, float]], today: date) -> dict:
    sp = spread(y10, y2)
    if not sp:
        return _unavailable("curve", "Yield curve (10Y minus 2Y)", "no dates in common between the 10Y and 2Y series")
    d, v = sp[-1]
    f = {**_base("curve", "Yield curve (10Y minus 2Y)", "bps"), "series": "DGS10 - DGS2", "value": v * 100, "obs_date": d.isoformat(), "inverted": v < 0,
         "freshness": freshness("DGS10", d, today), "changes": []}
    if y10[-1][0] != d or y2[-1][0] != d:
        f["note"] = f"Uses {d.isoformat()}, the latest date present in both series."
    if len(sp) > 1:
        f["changes"].append({"label": "vs previous common date", "ref_date": sp[-2][0].isoformat(), "value": bps(v, sp[-2][1]), "unit": "bps"})
    r = on_or_before(sp, d - timedelta(days=30))
    if r:
        f["changes"].append({"label": "vs ~1 month earlier", "ref_date": r[0].isoformat(), "value": bps(v, r[1]), "unit": "bps"})
    return f


def cpi_fact(sid: str, fid: str, pts: list[tuple[date, float]], today: date) -> dict:
    ys = yoy(pts)
    if not ys:
        return _unavailable(fid, SERIES[sid][0], "needs the same month one year earlier; not enough matching data")
    d, v = ys[-1]
    f = {**_base(fid, SERIES[sid][0], "% year-over-year"), "series": sid, "value": v, "obs_date": d.isoformat(), "index_level": dict(pts)[d],
         "freshness": freshness(sid, d, today), "changes": [], "note": "Observation date is the reference month (dated the 1st); release comes about 2 weeks after that month ends."}
    prev = dict(ys).get(prev_month(d))
    if prev is not None:
        f["changes"].append({"label": "vs previous month's year-over-year", "ref_date": prev_month(d).isoformat(), "value": v - prev, "unit": "percentage points"})
    else:
        f["note"] += " Previous month's figure is missing, so no monthly change is shown."
    return f


def fed_fact(lo: list[tuple[date, float]], hi: list[tuple[date, float]], today: date) -> dict:
    common = sorted(set(dict(lo)) & set(dict(hi)))
    if not common:
        return _unavailable("fed", "Fed funds target range", "lower and upper bound have no date in common")
    d = common[-1]
    l, h = dict(lo)[d], dict(hi)[d]
    both = [(x, dict(lo)[x] + dict(hi)[x]) for x in common]            # a change in either bound changes the sum
    since, open_ended = unchanged_since(both)
    return {**_base("fed", "Fed funds target range", "%"), "series": "DFEDTARL / DFEDTARU", "lower": l, "upper": h, "obs_date": d.isoformat(),
            "unchanged_since": since.isoformat(), "unchanged_since_is_lower_bound": open_ended, "freshness": freshness("DFEDTARU", d, today),
            "note": "The range changes only at FOMC decisions. An unchanged value is expected and is not a sign of old data."}


def usd_fact(pts: list[tuple[date, float]], today: date) -> dict:
    d, v = pts[-1]
    f = {**_base("usd", SERIES["DTWEXBGS"][0], "index"), "series": "DTWEXBGS", "value": v, "obs_date": d.isoformat(), "freshness": freshness("DTWEXBGS", d, today), "changes": [],
         "note": "A trade-weighted index from the Federal Reserve. It is NOT the ICE DXY index and its level is not comparable with DXY."}
    if len(pts) > 1:
        f["changes"].append({"label": "vs previous observation", "ref_date": pts[-2][0].isoformat(), "value": pct(v, pts[-2][1]), "unit": "%"})
    r = on_or_before(pts, d - timedelta(days=30))
    if r:
        f["changes"].append({"label": "vs ~1 month earlier", "ref_date": r[0].isoformat(), "value": pct(v, r[1]), "unit": "%"})
    return f


def _chg(f: dict, label_part: str) -> float | None:
    return next((c["value"] for c in f.get("changes", []) if label_part in c["label"]), None)


# --- interpretations: conditional, educational, tied to visible facts ----------------------------------------------------------------------
def interpretations(F: dict[str, dict]) -> list[dict]:
    out = []

    def add(iid, based_on, text, caveat):
        out.append({"id": iid, "based_on": based_on, "text": text, "caveat": caveat})

    c = F.get("curve")
    if c and "value" in c:
        v = c["value"]
        if v < 0:
            add("curve", ["curve"], f"The 10Y yield is {abs(v):.0f} bps BELOW the 2Y yield (an inverted curve). Historically, inversions have often come before economic slowdowns, which tend to matter for stocks and for risk assets such as BTC.",
                "The gap between an inversion and any slowdown has ranged from months to years, and some inversions were not followed by one. It is background context, not a timing tool.")
        elif v < RULES["curve_flat_bps"]:
            add("curve", ["curve"], f"The curve is nearly flat ({v:.0f} bps). Short and long rates are close, which usually means markets see little difference between near-term and long-term conditions.",
                "A flat curve can precede either an inversion or a steepening.")
        else:
            add("curve", ["curve"], f"The curve is positively sloped ({v:.0f} bps): longer-term yields are higher than short-term yields, the usual shape when growth and inflation expectations are not alarming.",
                "Slope alone does not describe growth; it can steepen because rates fall (growth worries) or because long yields rise.")
    for fid, name in (("us10y", "10Y"), ("us2y", "2Y")):
        f, ch = F.get(fid), None
        ch = _chg(f, "1 month") if f else None
        if ch is not None and abs(ch) >= RULES["yield_move_bps_1m"]:
            if ch > 0:
                add(f"{fid}_move", [fid], f"The {name} yield rose {ch:.0f} bps over about a month. Higher yields make safe assets more attractive and raise the rate used to value future earnings, which has often weighed on growth stocks and on BTC.",
                    "Reactions differ by period. If yields rise because the economy is strong, stocks can rise too.")
            else:
                add(f"{fid}_move", [fid], f"The {name} yield fell {abs(ch):.0f} bps over about a month. Lower yields ease financing conditions, which has often helped growth stocks and BTC.",
                    "Yields also fall when investors fear a slowdown, which can hurt risk assets. The reason for the move matters.")
    core, fed = F.get("core_cpi"), F.get("fed")
    if core and "value" in core:
        v = core["value"]
        goal = RULES["inflation_goal"]
        if v >= RULES["core_cpi_high"]:
            t = f"Core CPI is {v:.1f}% year-over-year, well above the Fed's 2% goal. When inflation stays high, the Fed tends to keep rates higher for longer, which can pressure valuations."
        elif v > goal:
            t = f"Core CPI is {v:.1f}% year-over-year, somewhat above the Fed's 2% goal. Progress toward the goal is what markets watch for clues about future rate cuts."
        else:
            t = f"Core CPI is {v:.1f}% year-over-year, at or below the Fed's 2% goal, which leaves the Fed more room to ease if growth weakens."
        add("inflation", ["core_cpi"], t, "The Fed's formal goal is based on a different measure (PCE inflation), so CPI is only a guide. One month of data is noisy.")
    if fed and "upper" in fed:
        add("fed", ["fed"], f"The Fed's target range is {fed['lower']:.2f}% to {fed['upper']:.2f}%. Higher policy rates raise borrowing costs and cash yields across the economy, which generally tightens financial conditions for stocks and BTC.",
            "Markets move mostly on expected changes in the range, not on the current level.")
    u = F.get("usd")
    ch = _chg(u, "1 month") if u else None
    if ch is not None and abs(ch) >= RULES["usd_move_pct_1m"]:
        if ch > 0:
            add("usd", ["usd"], f"The broad dollar index rose {ch:.1f}% over about a month. A stronger dollar tends to tighten global financial conditions and can weigh on commodities, overseas earnings of US companies and often BTC.",
                "This index is not DXY, and the dollar's link to stocks and BTC changes over time.")
        else:
            add("usd", ["usd"], f"The broad dollar index fell {abs(ch):.1f}% over about a month. A weaker dollar tends to ease global financial conditions and has often been friendlier to commodities, overseas earnings of US companies and BTC.",
                "This index is not DXY, and the dollar's link to stocks and BTC changes over time.")
    return out


# --- service -----------------------------------------------------------------------------------------------------------------------------
HISTORY_DAYS = {"DGS10": 400, "DGS2": 400, "DFEDTARL": 800, "DFEDTARU": 800, "DTWEXBGS": 400, "CPIAUCSL": 900, "CPILFESL": 900}
CACHE_SECONDS = 1800.0


class MacroService:
    def __init__(self, fred, demo: bool = False):
        self.fred, self.demo = fred, demo
        self._cache: tuple[float, dict] | None = None
        self._lock = asyncio.Lock()

    async def overview(self, today: date | None = None) -> dict:
        if self.demo:
            return {"demo": True, "facts": [], "interpretations": [], "source": SOURCE, "rules": RULES,
                    "notice": "Demo mode: the macro dashboard only shows real FRED observations, so it is empty here."}
        async with self._lock:
            if self._cache and self._cache[0] > time.monotonic():
                return self._cache[1]
            res = await self._build(today or datetime.now(timezone.utc).date())
            if res["facts"] and all("error" not in f for f in res["facts"]):
                self._cache = (time.monotonic() + CACHE_SECONDS, res)          # only a fully successful result is cached
            return res

    async def _build(self, today: date) -> dict:
        async def one(sid):
            try:
                pts = await self.fred.series(instrument(sid), today - timedelta(days=HISTORY_DAYS[sid]))
                return sid, [(t.date(), v) for t, v in pts], None
            except ProviderUnavailable as e:
                return sid, None, e.message[:120]
            except Exception as e:  # noqa: BLE001  one bad series must not hide the others
                return sid, None, type(e).__name__
        data = {sid: (p, e) for sid, p, e in await asyncio.gather(*(one(s) for s in SERIES))}

        def need(*sids):
            bad = [f"{s}: {data[s][1] or 'no data'}" for s in sids if not data[s][0]]
            return "unavailable (" + "; ".join(bad) + ")" if bad else None
        P = {s: data[s][0] for s in SERIES}
        facts: list[dict] = []
        for sid, fid in (("DGS10", "us10y"), ("DGS2", "us2y")):
            facts.append(_unavailable(fid, SERIES[sid][0], need(sid)) if need(sid) else yield_fact(sid, fid, P[sid], today))
        facts.append(_unavailable("curve", "Yield curve (10Y minus 2Y)", need("DGS10", "DGS2")) if need("DGS10", "DGS2") else curve_fact(P["DGS10"], P["DGS2"], today))
        for sid, fid in (("CPIAUCSL", "cpi"), ("CPILFESL", "core_cpi")):
            facts.append(_unavailable(fid, SERIES[sid][0], need(sid)) if need(sid) else cpi_fact(sid, fid, P[sid], today))
        facts.append(_unavailable("fed", "Fed funds target range", need("DFEDTARL", "DFEDTARU")) if need("DFEDTARL", "DFEDTARU") else fed_fact(P["DFEDTARL"], P["DFEDTARU"], today))
        facts.append(_unavailable("usd", SERIES["DTWEXBGS"][0], need("DTWEXBGS")) if need("DTWEXBGS") else usd_fact(P["DTWEXBGS"], today))
        F = {f["id"]: f for f in facts if "error" not in f}
        return {"demo": False, "as_of": datetime.now(timezone.utc).isoformat(), "source": SOURCE, "rules": RULES, "facts": facts, "interpretations": interpretations(F),
                "interpretation_note": "Educational and rule-based. Each note is triggered by a visible fact above. These are not predictions, trading signals or advice."}
