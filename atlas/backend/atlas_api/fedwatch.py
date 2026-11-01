"""Fed Watch: scheduled FOMC events, published decisions and releases, Fed communications, and rule-based educational scenarios.

Three kinds of content, kept apart and labelled in the response:
  scheduled      - what is due and when (FOMC calendar table, BLS calendar file when it can be read)
  published fact - FRED observations (BLS/BEA/Fed data), Fed RSS items quoted verbatim, decisions computed from the target-range series
  interpretation - fixed conditional text. No AI, no prediction, no trading advice. "Consensus" is never shown: there is no reliable free source.
Read-only: it fetches with the news service's guarded HTTP client but writes nothing to the database.
"""
from __future__ import annotations

import asyncio
import re
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import macro as M
from .models import ProviderUnavailable
from .news.parse import FeedError, parse as parse_feed

NY = ZoneInfo("America/New_York")
LINKS = {
    "fomc_calendar": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
    "bls_schedule": "https://www.bls.gov/schedule/news_release/",
    "bea_schedule": "https://www.bea.gov/news/schedule",
}
BLS_ICS = "https://www.bls.gov/schedule/news_release/bls.ics"
FEEDS = [("Fed: monetary policy", "https://www.federalreserve.gov/feeds/press_monetary.xml"),
         ("Fed: all press releases", "https://www.federalreserve.gov/feeds/press_all.xml"),
         ("Fed: speeches and testimony", "https://www.federalreserve.gov/feeds/speeches_and_testimony.xml")]
CACHE_SECONDS = 900.0
FAIL_CACHE_SECONDS = 60.0      # a result with a failed source is kept briefly (errors stay visible) so page loads do not refetch everything
RULES = {"balance_sheet_flat_pct_13w": 0.5, "minutes_after_days": 21, "statement_et": "14:00", "press_conference_et": "14:30"}

# FOMC meetings (first day, last day = decision day, has Summary of Economic Projections). Entered from the Fed's published calendar by hand:
# verify against LINKS["fomc_calendar"]. A meeting not in this table is simply not shown.
MEETINGS = [
    (date(2025, 1, 28), date(2025, 1, 29), False), (date(2025, 3, 18), date(2025, 3, 19), True), (date(2025, 5, 6), date(2025, 5, 7), False),
    (date(2025, 6, 17), date(2025, 6, 18), True), (date(2025, 7, 29), date(2025, 7, 30), False), (date(2025, 9, 16), date(2025, 9, 17), True),
    (date(2025, 10, 28), date(2025, 10, 29), False), (date(2025, 12, 9), date(2025, 12, 10), True),
    (date(2026, 1, 27), date(2026, 1, 28), False), (date(2026, 3, 17), date(2026, 3, 18), True), (date(2026, 4, 28), date(2026, 4, 29), False),
    (date(2026, 6, 16), date(2026, 6, 17), True), (date(2026, 7, 28), date(2026, 7, 29), False), (date(2026, 9, 15), date(2026, 9, 16), True),
    (date(2026, 10, 27), date(2026, 10, 28), False), (date(2026, 12, 8), date(2026, 12, 9), True),
]


def et_to_utc(d: date, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime(d.year, d.month, d.day, h, m, tzinfo=NY).astimezone(timezone.utc)


def meeting_label(start: date, end: date) -> str:
    """'FOMC meeting Oct 27–28, 2026'. Built from .day, because day-without-zero strftime codes are not portable (they fail on Windows)."""
    if start.month == end.month:
        return f"FOMC meeting {start:%b} {start.day}–{end.day}, {end.year}"
    return f"FOMC meeting {start:%b} {start.day}–{end:%b} {end.day}, {end.year}"


def calendar_status(now: datetime) -> dict:
    """The built-in table ends; when no future decision remains, say so instead of inventing dates."""
    last = max(e for _, e, _ in MEETINGS)
    needs = not any(datetime.fromisoformat(e["at_utc"]) > now for e in scheduled_events(now, 1000) if e["type"] == "statement")
    return {"needs_update": needs, "last_meeting": last.isoformat(), "link": LINKS["fomc_calendar"],
            "message": f"Schedule needs updating: the built-in FOMC table ends with the {last:%b} {last.day}, {last.year} meeting. See the official Fed calendar for later meetings." if needs else None}


def scheduled_events(now: datetime, limit: int = 6) -> list[dict]:
    """Upcoming FOMC statement / press conference / minutes, in UTC (the browser converts to the user's timezone)."""
    out = []
    for start, end, sep in MEETINGS:
        label = meeting_label(start, end)
        out += [
            {"id": f"statement-{end}", "type": "statement", "title": "FOMC statement and rate decision" + (" with projections (dot plot)" if sep else ""), "meeting": label,
             "at_utc": et_to_utc(end, RULES["statement_et"]).isoformat(), "projections": sep},
            {"id": f"presser-{end}", "type": "press_conference", "title": "Chair's press conference", "meeting": label, "at_utc": et_to_utc(end, RULES["press_conference_et"]).isoformat(), "projections": sep},
            {"id": f"minutes-{end}", "type": "minutes", "title": "FOMC meeting minutes", "meeting": label,
             "at_utc": et_to_utc(end + timedelta(days=RULES["minutes_after_days"]), RULES["statement_et"]).isoformat(), "projections": False},
        ]
    up = sorted((e for e in out if datetime.fromisoformat(e["at_utc"]) > now), key=lambda e: e["at_utc"])[:limit]
    for e in up:
        e.update(kind="scheduled", source="Fed FOMC calendar (entered by hand; times are the usual ones, confirm on the Fed site)", link=LINKS["fomc_calendar"])
    return up


# --- decisions: computed from the published target range ----------------------------------------------------------------------------------
def decision(end: date, lo: list[tuple[date, float]], hi: list[tuple[date, float]]) -> dict:
    lom, him = dict(lo), dict(hi)
    common = sorted(set(lom) & set(him))
    before = [d for d in common if d <= end - timedelta(days=1)]
    after = [d for d in common if end + timedelta(days=1) <= d <= end + timedelta(days=6)]
    base = {"kind": "published_fact", "meeting_end": end.isoformat(), "announced_date": end.isoformat(), "announced_utc": et_to_utc(end, RULES["statement_et"]).isoformat()}
    if not before or not after:
        return {**base, "outcome": None, "note": "Decision not available yet: the target-range series has no observations on both sides of the meeting."}
    p, n = (lom[before[-1]], him[before[-1]]), (lom[after[0]], him[after[0]])
    delta = ((n[0] + n[1]) - (p[0] + p[1])) / 2 * 100
    outcome = "raised" if delta > 0 else "cut" if delta < 0 else "held"
    return {**base, "outcome": outcome, "previous": {"lower": p[0], "upper": p[1], "obs_date": before[-1].isoformat()},
            "new": {"lower": n[0], "upper": n[1], "obs_date": after[0].isoformat()}, "change_bps": delta,
            "announced_date": end.isoformat(), "effective_obs_date": after[0].isoformat() if outcome != "held" else None,
            "date_note": ("The decision is announced on the meeting's last day at 2:00 pm ET. FRED dates are EFFECTIVE dates: the new range normally takes effect the next day, "
                          "so the date it first appears in FRED is not the announcement time."),
            "source": "FRED DFEDTARL/DFEDTARU (Federal Reserve)"}


def decisions(lo, hi, today: date, count: int = 4) -> list[dict]:
    done = [e for _, e, _ in MEETINGS if e < today]
    return [decision(e, lo, hi) for e in sorted(done, reverse=True)[:count]]


# --- scenarios (interpretation) --------------------------------------------------------------------------------------------------------------
SCENARIOS = {
    "raised": {"equities": "Higher borrowing costs can weigh on valuations, especially growth stocks, unless the market expected the move or reads it as a sign of a strong economy.",
               "bonds": "Short-term yields usually rise first. Longer-term yields depend on whether investors think the hike will slow inflation or the economy.",
               "dollar": "Higher US rates can attract money to dollar assets and support the dollar, if other central banks are not tightening as well.",
               "crypto": "Tighter financial conditions have often been a headwind for BTC, but the broader risk mood and BTC-specific news can outweigh it."},
    "cut": {"equities": "Lower borrowing costs can support valuations. If the cut is read as a response to weakening growth, stocks may fall instead.",
            "bonds": "Short-term yields usually fall. Bond prices rise when yields fall, though long-term yields can rise if investors worry about inflation.",
            "dollar": "Lower US rates can reduce the appeal of dollar assets and soften the dollar, if other central banks are not cutting as well.",
            "crypto": "Easier financial conditions have often been supportive for BTC, but a cut driven by economic stress can coincide with weaker risk appetite."},
    "held": {"equities": "A hold is often neutral by itself. Markets tend to focus on the statement wording and the projected path for future rates.",
             "bonds": "Yields tend to move on any change in tone about future cuts or hikes rather than on the unchanged rate.",
             "dollar": "The dollar tends to react to changes in expected future rates, not to the unchanged level.",
             "crypto": "BTC usually reacts to the shift in expected liquidity and the overall risk mood rather than to the hold itself."},
}
SCENARIO_NOTE = ("Possible scenarios, not predictions. Markets mostly react to surprises relative to what was expected, and this panel does not show expectations "
                 "(no reliable free consensus source). The same decision has produced different reactions in different periods.")

# type -> (label, why it matters)
TYPES = {
    "statement": ("FOMC statement", "The statement is the Fed's official explanation of its rate decision and its view of the economy. Changes in wording are read for clues about future rate moves."),
    "implementation": ("Implementation note", "Technical instructions that carry out the decision, such as the administered rates and balance-sheet settings."),
    "minutes": ("FOMC minutes", "A detailed record of the debate, released about three weeks after each meeting. It shows how divided officials were and which risks they discussed."),
    "projections": ("Economic projections", "The Summary of Economic Projections (including the dot plot) shows where officials expect rates, growth, unemployment and inflation to be."),
    "press_conference": ("Press conference", "The Chair explains the decision and answers questions. Tone and hints about future decisions can move markets even when the decision is expected."),
    "speech": ("Speech or testimony", "Officials sometimes signal how they view the economy and policy. A single speech is one view and does not set policy."),
    "balance_sheet": ("Balance sheet", "Changes to how many bonds the Fed holds affect liquidity in financial markets: shrinking holdings (runoff, or quantitative tightening) tends to tighten conditions, growing holdings to ease them."),
    "facility": ("Lending or liquidity facility", "Facilities provide emergency or routine funding to banks and markets. New or changed facilities usually respond to stress or aim to keep money markets working smoothly."),
    "guidance": ("Policy framework or guidance", "Changes to the Fed's stated approach or goals alter how markets interpret future decisions."),
}
_RULES = [
    ("minutes", re.compile(r"\bminutes\b", re.I)), ("projections", re.compile(r"economic projections|dot plot", re.I)),
    ("press_conference", re.compile(r"press conference", re.I)), ("implementation", re.compile(r"implementation note", re.I)),
    ("statement", re.compile(r"fomc statement", re.I)), ("balance_sheet", re.compile(r"balance sheet|securities holdings|runoff|reinvest|plans for reducing", re.I)),
    ("facility", re.compile(r"\bfacilit|standing repo|discount window|swap line|liquidity", re.I)),
    ("guidance", re.compile(r"forward guidance|statement on longer-run goals|monetary policy framework|policy strategy", re.I)),
]
_NORM = re.compile(r"[^a-z0-9 ]+")


def classify(title: str, speech_feed: bool = False) -> str | None:
    for t, rx in _RULES:
        if rx.search(title):
            return t
    return "speech" if speech_feed else None


def significant_speech(title: str) -> bool:
    return bool(re.match(r"\s*(Chair|Vice Chair)\s", title)) and not title.lstrip().startswith("Vice Chair for")


def communications(batches: list[tuple[str, bool, list]]) -> list[dict]:
    """Fed RSS items -> classified, de-duplicated (same link or same normalised title+date), newest first."""
    seen, out = set(), []
    for feed, speech_feed, items in batches:
        for it in items:
            t = classify(it.title, speech_feed)
            if t is None:
                continue
            key = (" ".join(_NORM.sub("", it.title.lower()).split()), it.published.date().isoformat() if it.published else "")
            if key in seen or (it.link and it.link in seen):
                continue
            seen.add(key)
            it.link and seen.add(it.link)
            label, why = TYPES[t]
            out.append({"kind": "published_fact", "type": t, "type_label": label, "title": it.title, "link": it.link, "summary": it.summary, "published_utc": it.published.isoformat() if it.published else None,
                        "feed": feed, "significant": significant_speech(it.title) if t == "speech" else True, "why_it_matters": why})
    out.sort(key=lambda x: x["published_utc"] or "", reverse=True)
    return out


# --- BLS release calendar (iCalendar file) ---------------------------------------------------------------------------------------------------
_WANT = (("Consumer Price Index", "cpi", "CPI"), ("Employment Situation", "jobs", "Employment report"))


def parse_ics(text: str) -> list[dict]:
    lines: list[str] = []
    for ln in text.replace("\r\n", "\n").split("\n"):
        if ln[:1] in (" ", "\t") and lines:
            lines[-1] += ln[1:]
        else:
            lines.append(ln)
    events, cur = [], None
    for ln in lines:
        if ln.startswith("BEGIN:VEVENT"):
            cur = {}
        elif ln.startswith("END:VEVENT") and cur is not None:
            events.append(cur)
            cur = None
        elif cur is not None and ":" in ln:
            k, v = ln.split(":", 1)
            cur[k.split(";")[0].upper()] = v.strip()
            if k.upper().startswith("DTSTART"):
                cur["_params"] = k
    out = []
    for e in events:
        name = e.get("SUMMARY", "")
        hit = next((w for w in _WANT if w[0].lower() in name.lower()), None)
        raw = e.get("DTSTART")
        if not hit or not raw:
            continue
        try:
            if "T" in raw:
                dt = datetime.strptime(raw.rstrip("Z"), "%Y%m%dT%H%M%S")
                at = dt.replace(tzinfo=timezone.utc) if raw.endswith("Z") else dt.replace(tzinfo=NY).astimezone(timezone.utc)
                d, when = at.astimezone(NY).date(), at.isoformat()
            else:
                d, when = datetime.strptime(raw, "%Y%m%d").date(), None
        except ValueError:
            continue
        out.append({"series": hit[1], "label": hit[2], "name": name[:120], "date": d.isoformat(), "at_utc": when})
    return sorted(out, key=lambda x: x["date"])


# --- release facts (FRED mirrors of BLS / BEA / Fed data) -------------------------------------------------------------------------------------
RELEVANCE = {
    "cpi": "The Fed watches consumer inflation because price stability is half of its mandate. Core CPI strips out food and energy to show the underlying trend.",
    "core_cpi": "The Fed watches consumer inflation because price stability is half of its mandate. Core CPI strips out food and energy to show the underlying trend.",
    "pce": "PCE inflation is the measure the Fed's 2% goal is officially based on, so it carries more weight in policy discussion than CPI.",
    "core_pce": "Core PCE (excluding food and energy) is the Fed's preferred gauge of underlying inflation.",
    "payrolls": "Job growth shows how strong the labor market is. Maximum employment is the other half of the Fed's mandate: strong hiring can keep rates higher, sharp weakness can bring cuts.",
    "unemployment": "The unemployment rate is the Fed's main labor-market gauge. A rising rate can signal a cooling economy.",
    "gdp": "GDP growth measures the overall economy. Faster growth can add to inflation pressure, a contraction can increase pressure to ease.",
}


def _monthly_change(sid: str, fid: str, pts, today: date, unit: str) -> dict:
    """Latest value minus the EXACT previous month (None if that month is missing)."""
    d, v = pts[-1]
    pm = M.prev_month(d)
    prev = dict(pts).get(pm)
    f = {**M._base(fid, M.ALL[sid][0], M.ALL[sid][1]), "series": sid, "obs_date": d.isoformat(), "freshness": M.freshness(sid, d, today), "level": v, "changes": []}
    if sid == "PAYEMS":
        f.update(unit="thousand jobs (change from previous month)", value=None if prev is None else v - prev)
        if prev is None:
            f["note"] = "Previous month's level is missing, so no monthly change is shown."
    else:
        f["value"] = v
        if prev is not None:
            f["changes"].append({"label": "vs previous month", "ref_date": pm.isoformat(), "value": v - prev, "unit": unit})
    return f


def release_facts(P: dict, today: date) -> list[dict]:
    out = []

    def add(fid, build, *need):
        miss = [s for s in need if not P.get(s)]
        f = {"id": fid, "label": fid, "error": "unavailable (" + ", ".join(miss) + ")"} if miss else build()
        f["relevance"], f["consensus_note"] = RELEVANCE[fid], "Consensus: not shown (no reliable free consensus source)."
        out.append(f)
    add("cpi", lambda: M.cpi_fact("CPIAUCSL", "cpi", P["CPIAUCSL"], today), "CPIAUCSL")
    add("core_cpi", lambda: M.cpi_fact("CPILFESL", "core_cpi", P["CPILFESL"], today), "CPILFESL")
    add("pce", lambda: M.cpi_fact("PCEPI", "pce", P["PCEPI"], today), "PCEPI")
    add("core_pce", lambda: M.cpi_fact("PCEPILFE", "core_pce", P["PCEPILFE"], today), "PCEPILFE")
    add("payrolls", lambda: _monthly_change("PAYEMS", "payrolls", P["PAYEMS"], today, "thousand"), "PAYEMS")
    add("unemployment", lambda: _monthly_change("UNRATE", "unemployment", P["UNRATE"], today, "percentage points"), "UNRATE")
    add("gdp", lambda: _quarterly("A191RL1Q225SBEA", "gdp", P["A191RL1Q225SBEA"], today), "A191RL1Q225SBEA")
    for f in out:
        if "label" in f and f["label"] == f["id"]:
            f["label"] = {"cpi": "CPI", "core_cpi": "Core CPI", "pce": "PCE inflation", "core_pce": "Core PCE inflation", "payrolls": "Nonfarm payrolls", "unemployment": "Unemployment rate", "gdp": "Real GDP growth"}[f["id"]]
    return out


def _quarterly(sid, fid, pts, today) -> dict:
    d, v = pts[-1]
    pq = (d.replace(day=1) - timedelta(days=1)).replace(day=1)
    pq = pq.replace(month=((pq.month - 1) // 3) * 3 + 1)
    prev = dict(pts).get(pq)
    f = {**M._base(fid, M.ALL[sid][0], "% annualized"), "series": sid, "value": v, "obs_date": d.isoformat(), "freshness": M.freshness(sid, d, today), "changes": [],
         "note": "Dated the first day of the quarter. Early estimates are revised."}
    if prev is not None:
        f["changes"].append({"label": "vs previous quarter", "ref_date": pq.isoformat(), "value": v - prev, "unit": "percentage points"})
    return f


def balance_sheet_fact(pts: list[tuple[date, float]], today: date) -> dict:
    d, v = pts[-1]
    f = {**M._base("balance_sheet", M.ALL["WALCL"][0], "$ trillions"), "series": "WALCL", "value": v / 1e6, "obs_date": d.isoformat(), "freshness": M.freshness("WALCL", d, today), "changes": []}
    for weeks, name in ((4, "~4 weeks"), (13, "~13 weeks")):
        r = M.on_or_before(pts, d - timedelta(days=7 * weeks))
        if r and r[0] <= d - timedelta(days=7 * weeks - 3):
            f["changes"].append({"label": f"vs {name} earlier", "ref_date": r[0].isoformat(), "value": M.pct(v, r[1]), "unit": "%"})
    c13 = next((c["value"] for c in f["changes"] if "13" in c["label"]), None)
    if c13 is not None:
        t = RULES["balance_sheet_flat_pct_13w"]
        f["trend"] = "shrinking" if c13 <= -t else "growing" if c13 >= t else "roughly flat"
        f["trend_rule"] = f"Over ~13 weeks: shrinking if down {t}% or more, growing if up {t}% or more, otherwise roughly flat. Total assets are a rough proxy for runoff (QT) or expansion."
    f["why_it_matters"] = TYPES["balance_sheet"][1]
    return f


# --- service ------------------------------------------------------------------------------------------------------------------------------
FRED_IDS = ["DFEDTARL", "DFEDTARU", "CPIAUCSL", "CPILFESL", "PCEPI", "PCEPILFE", "PAYEMS", "UNRATE", "A191RL1Q225SBEA", "WALCL"]
HISTORY = {"DFEDTARL": 800, "DFEDTARU": 800, "CPIAUCSL": 900, "CPILFESL": 900, "PCEPI": 900, "PCEPILFE": 900, "PAYEMS": 900, "UNRATE": 900, "A191RL1Q225SBEA": 1500, "WALCL": 200}


class FedWatchService:
    def __init__(self, fred, news, demo: bool = False):
        self.fred, self.news, self.demo = fred, news, demo
        self._cache: tuple[float, dict] | None = None
        self._lock = asyncio.Lock()

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo, "links": LINKS, "rules": RULES, "scenario_note": SCENARIO_NOTE, "scenarios": SCENARIOS,
                "upcoming": scheduled_events(now), "calendar": calendar_status(now), "interpretation_note": "Everything labelled 'why it matters' or 'scenario' is educational, rule-based text, not a prediction or advice."}
        if self.demo:
            return {**base, "decisions": [], "decisions_error": None, "communications": [], "feed_status": [], "releases": [], "release_schedule": [], "schedule_note": "",
                    "balance_sheet": None, "errors": [],
                    "notice": "Demo mode: only the FOMC calendar is shown. Published decisions, Fed news and releases need real data."}
        async with self._lock:
            if not (self._cache and self._cache[0] > time.monotonic()):
                raw = await self._fetch(now.date())
                self._cache = (time.monotonic() + (FAIL_CACHE_SECONDS if raw["errors"] else CACHE_SECONDS), raw)
            else:
                raw = self._cache[1]
        P, today = raw["P"], now.date()
        lo, hi = P.get("DFEDTARL"), P.get("DFEDTARU")
        return {**base, "decisions": decisions(lo, hi, today) if lo and hi else [], "decisions_error": None if lo and hi else "Target-range series unavailable.",
                "communications": raw["comms"], "feed_status": raw["feeds"], "releases": release_facts(P, today),
                "release_schedule": [e for e in raw["ics"] if e["date"] >= today.isoformat()][:4], "schedule_note": raw["ics_note"],
                "balance_sheet": balance_sheet_fact(P["WALCL"], today) if P.get("WALCL") else {"id": "balance_sheet", "label": M.ALL["WALCL"][0], "error": "unavailable (WALCL)"},
                "errors": raw["errors"]}

    async def _fetch(self, today: date) -> dict:
        errors: list[str] = []

        async def fred_one(sid):
            try:
                pts = await self.fred.series(M.instrument(sid), today - timedelta(days=HISTORY[sid]))
                return sid, [(t.date(), v) for t, v in pts]
            except ProviderUnavailable as e:
                errors.append(f"{sid}: {e.message[:80]}")
            except Exception as e:  # noqa: BLE001
                errors.append(f"{sid}: {type(e).__name__}")
            return sid, None

        async def feed_one(name, url, speech):
            try:
                _, body, _ = await self.news._get(url, None, None)
                items, _ = await asyncio.to_thread(parse_feed, body)
                return (name, speech, items), {"feed": name, "ok": True, "items": len(items), "error": None}
            except FeedError as e:
                msg = str(e)[:100]
            except Exception as e:  # noqa: BLE001  never echo the URL
                msg = f"{type(e).__name__} (feed unreachable)"
            errors.append(f"{name}: {msg}")
            return (name, speech, []), {"feed": name, "ok": False, "items": 0, "error": msg}

        async def ics():
            try:
                _, body, _ = await self.news._get(BLS_ICS, None, None)
                return parse_ics(body.decode("utf-8", "replace")), None
            except Exception as e:  # noqa: BLE001
                return [], f"BLS release calendar could not be read ({type(e).__name__ if not isinstance(e, FeedError) else str(e)[:60]}); see the official schedule links."

        fred_res, feed_res, (events, ics_err) = await asyncio.gather(asyncio.gather(*(fred_one(s) for s in FRED_IDS)), asyncio.gather(*(feed_one(n, u, "speeches" in u) for n, u in FEEDS)), ics())
        if ics_err:
            errors.append("BLS release calendar: unavailable")
        return {"P": dict(fred_res), "comms": communications([b for b, _ in feed_res])[:30], "feeds": [s for _, s in feed_res], "ics": events,
                "ics_note": ics_err or "CPI and Employment dates come from the BLS calendar file. PCE and GDP release dates are not loaded; see the BEA schedule link.", "errors": errors}
