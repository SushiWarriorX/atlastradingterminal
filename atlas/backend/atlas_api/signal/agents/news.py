"""News agent: finds recent headlines about the asset and its industry, groups duplicates, labels how each is worded, and says why it may matter.

Retrieved headlines and summaries are UNTRUSTED text. In this agent they are only ever classified by fixed patterns and displayed as plain text; nothing in them is
executed, followed or passed to a model as instructions. The agent does not score sentiment: it reports what was published, when, by whom, and how it is worded.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone

from .. import fmt
from ..assets import TOKEN_BY_SYMBOL, Asset
from ..exposure import exposure_for
from ..models import Finding, Interpretation, Missing, Point, Source, Story
from .common import Ctx, ago, iso, mk_fact, unavailable

NEWS_WINDOW_H = 72
MAX_STORIES = 6
TITLE_MAX = 160
UNCONFIRMED = re.compile(r"\b(reportedly|reports? (say|said)|rumou?r(s|ed)?|unconfirmed|sources? (say|said|familiar)|allegedly|alleged|speculat\w+|in talks|considering|may be (planning|exploring))\b", re.I)
OPINION = re.compile(r"^\s*(opinion|commentary|analysis|column|editorial|perspective|op-ed)\b\s*[:|\-–]|\b(op-ed|my take|why you should|should you (buy|sell)|here'?s why)\b", re.I)
CATEGORIES: list[tuple[str, re.Pattern]] = [
    ("security", re.compile(r"\b(hack(ed|s)?|exploit(ed|s)?|breach(ed)?|outage|stolen|theft|rug ?pull|drained)\b", re.I)),
    ("regulatory", re.compile(r"\b(sec|lawsuit|sues?|sued|regulator\w*|regulation|ban(s|ned)?|probe|investigat\w+|fine[sd]?|settle(s|ment)?|court|approv\w+|subpoena|indict\w*)\b", re.I)),
    ("earnings", re.compile(r"\b(earnings|revenue|profit|quarterly results|guidance|outlook|eps|net income)\b", re.I)),
    ("deal", re.compile(r"\b(acquir\w+|acquisition|merger|partnership|buyout|stake|takeover)\b", re.I)),
    ("analyst", re.compile(r"\b(analyst|price target|downgrade[sd]?|initiates coverage|rating)\b", re.I)),
    ("flows", re.compile(r"\b(inflows?|outflows?|etf flows?|fund flows?)\b", re.I)),
    ("product", re.compile(r"\b(launch(es|ed)?|unveil\w*|releases?|upgrade|mainnet|roadmap|rollout)\b", re.I)),
    ("macro", re.compile(r"\b(fed|inflation|rate (cut|hike)s?|tariffs?|jobs report|cpi|treasury yields?|recession)\b", re.I)),
    ("market", re.compile(r"\b(shares|stock|price|rall(y|ies)|surg\w+|plung\w+|jump\w*|tumbl\w+|slid\w+|soar\w*)\b", re.I)),
]
WHY = {
    "security": "Hacks and outages can hurt users and finances; the size of the loss and whether funds are recoverable usually decide how serious it is.",
    "regulatory": "Rules, lawsuits and approvals can change what a company or token is allowed to do, so they are often treated as material.",
    "earnings": "Earnings and guidance reset expectations for revenue and profit, which often moves a stock.",
    "deal": "Deals and partnerships can change scale or competitive position; the terms and any regulatory approval usually decide the effect.",
    "analyst": "A rating or price-target change is one firm's opinion, not a result; it can move prices briefly but adds no new facts.",
    "flows": "Money moving into or out of funds shows investor demand and can add buying or selling pressure.",
    "product": "Launches and upgrades can change demand or usage; markets often react to whether delivery matches expectations.",
    "macro": "Macro news shifts interest-rate and growth expectations, which affect most risk assets.",
    "market": "A price-move story describes what already happened; check whether a cause is named.",
    "general": "Mentioned in connection with this asset. Open the source to see whether it changes anything.",
}
CATEGORY_WEIGHT = {"security": 25, "regulatory": 20, "earnings": 20, "deal": 15, "product": 10, "flows": 10, "macro": 8, "analyst": 5, "market": 3, "general": 0}
INDUSTRY = {
    "crypto": r"\b(crypto(currenc\w*)?|bitcoin|ethereum|stablecoins?|blockchain|digital assets?)\b",
    "Technology": r"\b(semiconductors?|chips?|artificial intelligence|AI|cloud|software|data cent(er|re)s?)\b",
    "Communication Services": r"\b(advertis\w+|streaming|social media|artificial intelligence|AI)\b",
    "Consumer Discretionary": r"\b(retail|consumer spending|electric vehicles?|EVs?|e-commerce)\b",
    "Financials": r"\b(banks?|lenders?|credit|loans?|interest rates?)\b",
    "Energy": r"\b(oil|crude|OPEC|natural gas|refin\w+)\b",
    "Health Care": r"\b(FDA|drugs?|biotech|pharma\w*|clinical trials?)\b",
    "bonds": r"\b(treasur\w+|bond yields?|yields?)\b",
    "gold": r"\bgold\b",
    "energy": r"\b(oil|crude|OPEC|natural gas)\b",
}


def classify_kind(title: str, summary: str = "") -> str:
    text = f"{title} {summary[:200]}"
    if UNCONFIRMED.search(text):
        return "unconfirmed"
    if OPINION.search(text):
        return "opinion"
    return "reporting"


def classify_category(title: str, summary: str = "") -> str:
    for name, rx in CATEGORIES:
        if rx.search(title) or rx.search(summary[:160]):
            return name
    return "general"


def why_text(category: str, kind: str) -> str:
    t = WHY[category]
    return t + (" This report is unconfirmed: wait for a named source or an official statement." if kind == "unconfirmed" else " This is opinion, not reporting." if kind == "opinion" else "")


def _dt(s: str | None) -> datetime | None:
    try:
        d = datetime.fromisoformat(s) if s else None
    except ValueError:
        return None
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def materiality(st: Story, now: datetime) -> int:
    score = 40 + (30 if st.scope == "asset" else 0) + CATEGORY_WEIGHT.get(st.category, 0) + min(15, 5 * len(st.also))
    when = _dt(st.published) or _dt(st.fetched_at)
    if when:
        age_h = (now - when).total_seconds() / 3600
        score += 15 if age_h < 6 else 10 if age_h < 24 else 3 if age_h < 72 else 0
    if st.kind != "reporting":
        score -= 10
    return score


def to_story(it: dict, scope: str, now: datetime, demo: bool) -> Story:
    title = (it.get("title") or "")[:TITLE_MAX]
    summ = it.get("summary") or ""
    kind, cat = classify_kind(title, summ), classify_category(title, summ)
    link = it.get("link") if isinstance(it.get("link"), str) and it["link"].startswith(("http://", "https://")) else None
    return Story(id=str(it.get("id")), title=title, link=link, source=str(it.get("feed") or "unknown feed")[:60], published=it.get("published"), fetched_at=it.get("fetched_at"),
                 scope=scope, kind=kind, category=cat, why_it_matters=why_text(cat, kind),
                 also=[{"source": str(a.get("feed"))[:60], "title": str(a.get("title"))[:TITLE_MAX], "link": a.get("link") if str(a.get("link")).startswith("http") else None} for a in (it.get("also") or [])[:4]],
                 demo=demo)


class NewsAgent:
    name = "news"

    async def run(self, ctx: Ctx) -> Finding:
        a, now = ctx.asset, ctx.now
        tag = a.symbol
        notes: list[str] = []
        if ctx.demo:
            from .. import fixtures
            out = fixtures.news(a, now)
        else:
            try:
                r = await asyncio.wait_for(ctx.news.refresh_symbol(a.inst.provider_symbol, tag), 10)
                if r and r.get("error"):
                    notes.append(f"{r.get('name', 'Symbol feed')}: {r['error']}")
            except Exception as e:  # noqa: BLE001  the stored headlines are still usable
                notes.append(f"Symbol feed unavailable ({type(e).__name__})")
            try:
                out = await asyncio.to_thread(ctx.news.items, tag, None, NEWS_WINDOW_H, 40)
            except Exception as e:  # noqa: BLE001
                return unavailable("news", f"Headline store unavailable ({type(e).__name__})", False)
        meta = out.get("meta", {})
        stories = [to_story(it, "asset", now, ctx.demo) for it in out["items"]]
        exp = exposure_for(a)
        rx = INDUSTRY.get(a.sector or "") or INDUSTRY.get(exp.profile)
        if rx and not ctx.demo:
            try:
                gen = await asyncio.to_thread(ctx.news.items, None, None, 48, 120)
                seen = {s.id for s in stories}
                pat = re.compile(rx, re.I)
                for it in gen["items"]:
                    if str(it.get("id")) not in seen and tag not in it.get("symbols", []) and pat.search(it.get("title", "")):
                        stories.append(to_story(it, "industry", now, False))
            except Exception:  # noqa: BLE001  industry context is optional
                notes.append("Industry headlines unavailable")
        stories.sort(key=lambda s: -materiality(s, now))
        window = now - timedelta(hours=NEWS_WINDOW_H)
        stories = [s for s in stories if (_dt(s.published) or _dt(s.fetched_at) or now) >= window]
        top = stories[:MAX_STORIES]
        n24 = sum(1 for s in stories if (_dt(s.published) or _dt(s.fetched_at) or now) >= now - timedelta(hours=24) and s.scope == "asset")
        n_asset = sum(1 for s in stories if s.scope == "asset")
        src_name = "RSS feeds read by ATLAS (delayed, polled)" if not ctx.demo else "Demo fixture (synthetic, not real)"
        feeds_ok, feeds_on = meta.get("feeds_ok", 0), meta.get("feeds_enabled", 0)
        latest = max((_dt(s.published) or _dt(s.fetched_at) for s in stories if s.scope == "asset"), default=None, key=lambda d: d or datetime.min.replace(tzinfo=timezone.utc))
        facts = [
            mk_fact("stories_72h", f"Stories about {a.symbol}, last {NEWS_WINDOW_H}h", n_asset, str(n_asset), src_name, as_of=meta.get("as_of"), kind="calculated"),
            mk_fact("stories_24h", f"Stories about {a.symbol}, last 24h", n24, str(n24), src_name, as_of=meta.get("as_of"), kind="calculated"),
            mk_fact("feeds_ok", "News feeds responding", feeds_ok, f"{feeds_ok} of {feeds_on}", src_name, as_of=meta.get("as_of"), kind="reported"),
        ]
        if latest:
            facts.append(mk_fact("latest_published", "Newest story published", iso(latest), ago(now, latest), src_name, as_of=iso(latest), kind="reported"))
        missing: list[Missing] = []
        limits = ["Headlines are matched to the asset by explicit mentions (ticker, cashtag, name); relevance is not scored and nothing about sentiment is inferred.",
                  "Each story shows when it was published. The time of the underlying event is not provided by RSS feeds.",
                  "'Unconfirmed' and 'opinion' labels come from wording patterns only and can be wrong. Always open the original source."]
        if a.type == "crypto" and a.symbol not in ("BTC",):
            limits.append("Headline tagging is conservative for tokens other than Bitcoin, so coverage may be incomplete.")
        if ctx.registry is not None:
            twins = ctx.registry.same_symbol(a)
            if twins:
                limits.append(f"The ticker {a.symbol} is also used by {', '.join(sorted({t.name + ' (' + t.type + ')' for t in twins})[:3])}. Headlines are matched by ticker text, so some may belong to the other asset.")
        if feeds_on and feeds_ok < feeds_on and not ctx.demo:
            limits.append(f"Only {feeds_ok} of {feeds_on} news feeds are responding, so quiet news may not mean nothing happened.")
        status = "ok"
        if not ctx.demo and feeds_on and meta.get("never_fetched", 0) >= feeds_on:
            return Finding(agent="news", status="unavailable", takeaway="News feeds have not been fetched yet. Try again in a minute.", error="no feed has been fetched yet",
                           missing=[Missing(what="Headlines", why="no RSS feed has been fetched yet")], sources=[], limitations=limits, demo=ctx.demo)
        if notes or (feeds_on and feeds_ok < feeds_on and not ctx.demo):
            status = "partial"
        if n_asset == 0:
            missing.append(Missing(what=f"Headlines about {a.symbol}", why=f"none found in the last {NEWS_WINDOW_H} hours ({feeds_ok} of {feeds_on} feeds responding)"))
        interp: list[Interpretation] = []
        if n_asset:
            outlets = max((len(s.also) + 1 for s in top if s.scope == "asset"), default=1)
            interp.append(Interpretation(text=f"{n_asset} stor{'y' if n_asset == 1 else 'ies'} in the last {NEWS_WINDOW_H} hours, {n24} in the last 24. The most widely covered was reported by {outlets} outlet{'s' if outlets != 1 else ''}.",
                                         based_on=["stories_72h", "stories_24h"]))
        if any(s.kind == "unconfirmed" for s in top):
            interp.append(Interpretation(text="Some stories are based on unconfirmed reports (wording such as 'reportedly' or 'sources say'). Treat them as unverified until a named source or official statement appears.", based_on=["stories_72h"]))
        cats = {}
        for s in top:
            cats[s.category] = cats.get(s.category, 0) + 1
        if cats:
            c, n = max(cats.items(), key=lambda kv: kv[1])
            if c != "general" and n >= 2:
                interp.append(Interpretation(text=f"Several stories are about {c} developments.", based_on=["stories_72h"]))
        takeaway = _takeaway(a, top, n24, n_asset, now)
        pts = _points(a, top, now)
        sources = [Source(name=s.source, url=s.link, kind="article", as_of=s.published, note=s.title[:80]) for s in top if s.link][:8] or [Source(name=src_name, kind="data", as_of=meta.get("as_of"))]
        return Finding(agent="news", status=status, stance=None, stance_rule="The News agent does not score sentiment: it reports what was published, when, and how it is worded.",
                       takeaway=takeaway, facts=facts, interpretations=interp, stories=top, missing=missing, sources=sources, limitations=limits + notes, points=pts,
                       data_as_of=meta.get("as_of") or iso(latest), demo=ctx.demo)


def _takeaway(a: Asset, top: list[Story], n24: int, n_asset: int, now: datetime) -> str:
    asset_stories = [s for s in top if s.scope == "asset"]
    if not asset_stories:
        return f"No headlines about {a.symbol} in the last {NEWS_WINDOW_H} hours." + (" Industry stories are listed below." if top else "")
    s = asset_stories[0]
    when = _dt(s.published) or _dt(s.fetched_at)
    mark = " (unconfirmed)" if s.kind == "unconfirmed" else " (opinion)" if s.kind == "opinion" else ""
    return f"{n24} stor{'y' if n24 == 1 else 'ies'} in the last 24 hours. Most material of the last {NEWS_WINDOW_H}h: “{s.title}”{mark} ({s.source}, {ago(now, when)})."


def _points(a: Asset, top: list[Story], now: datetime) -> list[Point]:
    P: list[Point] = []
    for s in top[:6]:
        when = _dt(s.published) or _dt(s.fetched_at)
        fresh = when is not None and (now - when) <= timedelta(hours=24)
        label = " (unconfirmed report)" if s.kind == "unconfirmed" else " (opinion)" if s.kind == "opinion" else ""
        if fresh and s.scope == "asset":
            P.append(Point(kind="changed", agent="news", text=f"“{s.title}”{label}: {s.source}, {ago(now, when)}.", fact_keys=["stories_24h"], priority=materiality(s, now), dedupe_key=f"story-{s.id}"))
        if s.category in ("security", "regulatory") and s.kind != "opinion":
            P.append(Point(kind="risk", agent="news", text=f"{'Security' if s.category == 'security' else 'Regulatory or legal'} news: “{s.title}”{label}.", fact_keys=["stories_72h"], priority=60 + (10 if s.kind == "reporting" else 0), dedupe_key=f"story-risk-{s.id}"))
        if s.kind == "unconfirmed" and s.scope == "asset":
            P.append(Point(kind="watch", agent="news", text=f"Unconfirmed report: “{s.title}”. Watch for a named source or official statement.", fact_keys=["stories_72h"], priority=55, dedupe_key=f"story-watch-{s.id}"))
    return P
