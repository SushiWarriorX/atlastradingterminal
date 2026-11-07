"""Macro Intelligence: one read-only briefing assembled from data the app already holds.

Layout the client shows: What matters today, key indicators, upcoming events, headlines. Every item says which kind of statement it is:
  fact            - an official observation or a scheduled date, with its source and date
  interpretation  - fixed, conditional, rule-based text tied to a visible fact or headline topic (no AI, no prediction, no advice)
  headline        - a title and link from a named feed, quoted as published. Titles are untrusted text and are never summarised or scored.
Consensus and surprises are never shown (no reliable free source) and the briefing says so. Nothing here writes to the database.
"""
from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, timedelta, timezone

from . import fedwatch as FW
from .news.parse import FeedError, parse as parse_feed

CENTRAL_BANK_FEEDS = [("ECB press", "https://www.ecb.europa.eu/rss/press.html"), ("Bank of England news", "https://www.bankofengland.co.uk/rss/news"),
                      ("Bank of Japan what's new", "https://www.boj.or.jp/en/rss/whatsnew.xml")]
GAPS = ["Consensus forecasts and 'surprise vs expected' are not shown: there is no reliable free source.",
        "Geopolitics appears only as headlines from the feeds you follow, grouped by keyword. There is no structured event feed.",
        "Treasury yields shown are the 2-year and 10-year from FRED; the full curve and auction results are not loaded yet.",
        "PCE and GDP release dates are not loaded; see the BEA schedule link."]

# topic -> (label, keywords, implication). The implication is conditional, educational text, shown with the label 'Interpretation (rule-based)'.
TOPICS = {
    "fed": ("Fed and rates", r"\b(fed|fomc|powell|federal reserve|rate (cut|hike|decision)|interest rates?)\b",
            "Expectations for US rates move bond yields and the dollar first, and often stocks and BTC afterwards. A headline alone does not say which way."),
    "inflation": ("Inflation", r"\b(cpi|pce|inflation|consumer prices?|producer prices?|ppi)\b",
                  "Hotter-than-expected inflation tends to push rate-cut hopes back and yields up; cooler data tends to do the opposite. The headline does not say which this was."),
    "jobs": ("Jobs and growth", r"\b(payrolls?|jobs report|unemployment|jobless|gdp|recession|retail sales)\b",
             "Strong data can mean fewer rate cuts; weak data can raise cut hopes but also growth worries. Markets have reacted both ways."),
    "yields": ("Treasuries and bonds", r"\b(treasury|treasuries|yields?|bond (market|auction)|10-year|2-year)\b",
               "Rising yields raise the rate used to value future earnings and compete with risk assets; falling yields do the reverse unless they reflect a slowdown scare."),
    "central_banks": ("Other central banks", r"\b(ecb|bank of england|boe|bank of japan|boj|snb|rba|pboc|lagarde|bailey|ueda)\b",
                      "Other central banks' decisions can move their currencies and global yields, which feed into US markets through the dollar and bond yields."),
    "geopolitics": ("Geopolitics and trade", r"\b(sanctions?|tariffs?|war|conflict|missile|invasion|ceasefire|embargo|trade (deal|war|talks)|opec)\b",
                    "Geopolitical shocks usually show up as moves in oil, the dollar, gold and safe-haven bonds first. The effect on stocks and BTC varies and is often short-lived."),
}
_TOPIC_RX = {k: re.compile(v[1], re.I) for k, v in TOPICS.items()}
INDICATOR_ORDER = ["fed", "us10y", "us2y", "curve", "cpi", "core_cpi", "core_pce", "pce", "payrolls", "unemployment", "gdp", "usd", "balance_sheet"]


def topic_of(title: str) -> str | None:
    for k, rx in _TOPIC_RX.items():
        if rx.search(title):
            return k
    return None


def headline(feed: str, title: str, link: str | None, published: str | None) -> dict | None:
    t = topic_of(title)
    if t is None:
        return None
    label, _, why = TOPICS[t]
    return {"kind": "headline", "feed": feed, "title": title[:240], "link": link, "published": published, "topic": t, "topic_label": label,
            "implication": why, "implication_kind": "Interpretation (rule-based, about the topic, not this specific story)"}


def clean_reason(err: str) -> str:
    """'unavailable (CPIAUCSL)' -> 'no data came back'. Raw series codes mean nothing to a beginner; the technical detail stays in `errors`."""
    e = str(err)
    if e.startswith("unavailable ("):
        return "no data came back from the source"
    return e[:140]


def indicators_note(ind: list[dict], demo: bool) -> str | None:
    """When NO indicator could be loaded, say so once in plain words instead of listing every one as unavailable."""
    if any(i["available"] for i in ind):
        return None
    if demo:
        return "Demo mode: official indicators are not shown because they would not be real."
    return ("Official indicators could not be loaded right now, so none are shown. They come from FRED (the St. Louis Fed). "
            "Check your internet connection and try again in a few minutes; the technical detail is listed under 'Some sources failed'.")


def indicators(macro: dict, fed: dict) -> list[dict]:
    """Official observations as one flat list: value, unit, latest change, observation date and how current it is. Unavailable ones say why."""
    pool = {f["id"]: f for f in (macro.get("facts") or [])}
    pool.update({f["id"]: f for f in (fed.get("releases") or [])})
    bs = fed.get("balance_sheet")
    if bs:
        pool["balance_sheet"] = bs
    out = []
    for fid in INDICATOR_ORDER:
        f = pool.get(fid)
        if f is None:
            continue
        if "error" in f:
            out.append({"id": fid, "label": f.get("label", fid), "available": False, "reason": clean_reason(f["error"])})
            continue
        if fid == "fed":
            value, unit = f"{f['lower']:.2f}–{f['upper']:.2f}", "%"
        else:
            value, unit = f.get("value"), f.get("unit")
        ch = (f.get("changes") or [None])[-1]
        out.append({"id": fid, "label": f["label"], "available": True, "value": value, "unit": unit, "obs_date": f.get("obs_date"),
                    "change": None if not ch else {"label": ch["label"], "value": ch["value"], "unit": ch["unit"]},
                    "freshness": (f.get("freshness") or {}).get("state"), "series": f.get("series"), "source": "FRED (mirrors BLS, BEA, Federal Reserve data)", "note": f.get("note")})
    return out


def upcoming(fed: dict, today: date, limit: int = 8) -> list[dict]:
    """Scheduled events from the FOMC table and the BLS calendar file, soonest first."""
    ev = []
    for e in fed.get("upcoming") or []:
        ev.append({"kind": "scheduled", "date": (e.get("at_utc") or "")[:10] or None, "at_utc": e.get("at_utc"), "title": e["title"], "source": e.get("source", "Fed FOMC calendar"), "link": e.get("link")})
    for e in fed.get("release_schedule") or []:
        ev.append({"kind": "scheduled", "date": e["date"], "at_utc": e.get("at_utc"), "title": e["label"] + " release", "source": "BLS release calendar", "link": FW.LINKS["bls_schedule"]})
    ev = [e for e in ev if e["date"] and e["date"] >= today.isoformat()]
    ev.sort(key=lambda e: (e["date"], e["at_utc"] or ""))
    return ev[:limit]


def today_items(ind: list[dict], fed: dict, macro: dict, events: list[dict], today: date) -> list[dict]:
    """What matters today: scheduled events within two days, plus the rule-triggered notes behind visible facts. Each is labelled fact or interpretation."""
    out = []
    horizon = (today + timedelta(days=2)).isoformat()
    for e in events:
        if e["date"] <= horizon:
            when = "today" if e["date"] == today.isoformat() else f"on {e['date']}"
            out.append({"kind": "fact", "title": f"{e['title']} {when}", "detail": "A scheduled date. What it contains is not known in advance.", "source": e["source"], "link": e.get("link")})
    for n in macro.get("interpretations") or []:
        out.append({"kind": "interpretation", "title": n["text"], "detail": n["caveat"], "based_on": n["based_on"], "source": "Rule-based note tied to the indicators below"})
    for d in (fed.get("decisions") or [])[:1]:
        if d.get("outcome"):
            n = d["new"]
            out.append({"kind": "fact", "title": f"Latest Fed decision ({d['meeting_end']}): rates {d['outcome']}, target range now {n['lower']:.2f}–{n['upper']:.2f}%", "detail": "Computed from the Fed's target-range series.", "source": d.get("source", "FRED DFEDTARL / DFEDTARU")})
    return out[:8]


def build(macro: dict, fed: dict, stories: list[dict], now: datetime) -> dict:
    today = now.astimezone(timezone.utc).date()
    ind = indicators(macro, fed)
    demo = bool(macro.get("demo") or fed.get("demo"))
    note = indicators_note(ind, demo)
    if note:
        ind = []                                                  # one clear message beats a wall of "unavailable" rows
    ev = upcoming(fed, today)
    heads = []
    seen = set()
    for s in stories:
        h = headline(s["feed"], s["title"], s.get("link"), s.get("published"))
        key = (h or {}).get("title", "").lower()
        if h and key not in seen:
            seen.add(key)
            heads.append(h)
    heads.sort(key=lambda h: h["published"] or "", reverse=True)
    errors = list(fed.get("errors") or [])
    return {"as_of": now.isoformat(), "demo": bool(macro.get("demo") or fed.get("demo")), "today": today_items(ind, fed, macro, ev, today), "indicators": ind, "indicators_note": note, "upcoming": ev,
            "headlines": heads[:40], "topics": {k: v[0] for k, v in TOPICS.items()}, "calendar_warning": (fed.get("calendar") or {}).get("message"),
            "errors": errors, "gaps": GAPS, "notice": (macro.get("notice") or fed.get("notice")),
            "labels": {"fact": "An official observation or scheduled date, with source and date.", "interpretation": "Fixed, conditional, rule-based text. Not a prediction, signal or advice.", "headline": "Title and link as published by the named feed."}}


class MacroBriefService:
    def __init__(self, macro, fedwatch, news, demo: bool = False):
        self.macro, self.fed, self.news, self.demo = macro, fedwatch, news, demo

    async def _central_bank_stories(self) -> tuple[list[dict], list[str]]:
        errs: list[str] = []

        async def one(name, url):
            try:
                _, body, _ = await self.news._get(url, None, None)
                items, _ = await asyncio.to_thread(parse_feed, body)
                return [{"feed": name, "title": i.title, "link": i.link, "published": i.published.isoformat() if i.published else None} for i in items[:20]]
            except FeedError as e:
                errs.append(f"{name}: {str(e)[:80]}")
            except Exception as e:  # noqa: BLE001  never echo the URL
                errs.append(f"{name}: {type(e).__name__} (feed unreachable)")
            return []
        res = await asyncio.gather(*(one(n, u) for n, u in CENTRAL_BANK_FEEDS))
        return [s for r in res for s in r], errs

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        macro = await self.macro.overview() if self.macro else {"facts": [], "interpretations": [], "notice": "The FRED provider is not set up, so official indicators are unavailable."}
        fed = await self.fed.overview(now)
        stories = [{"feed": s["feed"], "title": s["title"], "link": s.get("link"), "published": s.get("published")} for s in (self.news.items(hours=72, limit=200)["items"] if self.news else [])]
        stories += [{"feed": c["feed"], "title": c["title"], "link": c.get("link"), "published": c.get("published_utc")} for c in fed.get("communications") or []]
        extra_err: list[str] = []
        if not self.demo:
            more, extra_err = await self._central_bank_stories()
            stories += more
        out = build(macro, fed, stories, now)
        out["errors"] += extra_err
        return out
