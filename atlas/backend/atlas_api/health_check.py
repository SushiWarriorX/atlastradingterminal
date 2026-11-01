"""On-demand provider health check. READ-ONLY: it calls the existing adapters/fetchers directly and never touches the database,
the market-data cache, provider health counters, RSS feed rows, derivatives history or the journal. It never sends orders.

Four separate questions per provider (a successful HTTP response is NOT proof of good data):
  connectivity - could we reach it?      structure - did the response have the expected fields?
  freshness    - how old is the newest observation?      quality - are prices/timestamps/numbers valid?
Every probe has a timeout and the whole run has bounded concurrency; request budgets below are the most outbound calls each probe makes.
"""
from __future__ import annotations

import asyncio
import math
import re
import time
from datetime import datetime, timedelta, timezone

import httpx

from . import instruments as I
from .derivatives.venues import LABELS as VENUE_LABELS, VENUES, VenueError
from .models import DataStatus, ProviderUnavailable
from .news.parse import FeedError, parse as parse_feed
from .status import classify

PROBE_TIMEOUT = 14.0          # seconds per probe (yfinance has its own 10 s request timeout inside)
RUN_TIMEOUT = 30.0            # seconds for the whole run
CONCURRENCY = 4
COOLDOWN = 30.0               # seconds between runs
MAX_FEEDS_CHECKED = 8
DERIV_STALE_SECONDS = 300
RSS_STALE_HOURS = 72

BUDGET = {"coinbase": 2, "yahoo": 2, "fred": 1, "ibkr": 1, "hyperliquid": 1, "binance": 2, "bybit": 1, "okx": 4}   # outbound requests per probe
_URL = re.compile(r"https?://\S+")


def safe(msg: object) -> str:
    """Error text for the screen: no URLs (they can carry keys), no long tracebacks."""
    return _URL.sub("[url]", str(msg)).replace("\n", " ")[:160]


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def row(key: str, label: str, group: str, state: str, *, connectivity="skipped", structure="skipped", quality="skipped", freshness=None,
        observed_at=None, issues=None, error=None, action=None, requests=0, detail=None) -> dict:
    age = None
    if observed_at:
        age = max(0, int((datetime.now(timezone.utc) - observed_at).total_seconds()))
    return {"provider": key, "label": label, "group": group, "state": state, "connectivity": connectivity, "structure": structure,
            "quality": quality, "freshness": freshness, "observed_at": observed_at.isoformat() if observed_at else None, "age_seconds": age,
            "issues": issues or [], "error": error, "action": action, "request_budget": requests, "detail": detail}


def skipped(key, label, group, state, why, action=None):
    return row(key, label, group, state, error=why, action=action)


def _err_kind(msg: str) -> str:
    """Adapters wrap everything in ProviderUnavailable(text). Tell 'could not reach it' from 'reached it, content was wrong'."""
    m = msg.lower()
    if any(k in m for k in ("keyerror", "valueerror", "typeerror", "indexerror", "no data", "empty", "no history", "not json", "decode", "attributeerror")):
        return "structure"
    return "connectivity"


def _action_for(msg: str, kind: str) -> str:
    m = msg.lower()
    if kind == "structure":
        return "The service answered but not in the expected format. It may have changed. Report this provider name and the issue list so the adapter can be updated."
    if "403" in m or "451" in m or "blocked" in m or "refused" in m:
        return "The service is refusing your network or region. Try another network, or ignore this provider."
    if "429" in m or "rate" in m:
        return "Rate limited. Wait a few minutes before checking again."
    if "timed out" in m or "timeout" in m:
        return "Too slow. Check your internet connection and try again in a minute."
    return "Check your internet connection and any firewall or VPN, then try again."


def quote_quality(q) -> list[str]:
    issues: list[str] = []
    if not _finite(q.price) or q.price <= 0:
        issues.append("price missing or not a positive number")
    if q.prov.event_time is None:
        issues.append("no timestamp on the quote")
    elif q.prov.event_time > datetime.now(timezone.utc).replace(microsecond=0) + timedelta(minutes=5):
        issues.append("timestamp is in the future")
    for f in ("bid", "ask", "open", "high", "low", "prev_close"):
        v = getattr(q, f, None)
        if v is not None and (not _finite(v) or v <= 0):
            issues.append(f"{f} is not a positive number")
    if q.volume is not None and (not _finite(q.volume) or q.volume < 0):
        issues.append("volume is invalid")
    if q.bid and q.ask and q.bid > q.ask:
        issues.append("bid is above ask (crossed book)")
    if q.high and q.low and q.high < q.low:
        issues.append("high is below low")
    return issues


def _state(connectivity, structure, quality, freshness) -> str:
    if connectivity != "pass":
        return "UNAVAILABLE"
    if structure != "pass" or quality != "pass":
        return "INVALID"
    return "STALE" if freshness == "STALE" else "OK"


async def probe_quote(svc, key: str, label: str, group: str, provider, inst) -> dict:
    """One quote through an existing adapter, uncached, then the normal status classification. Counters and cache are untouched."""
    try:
        q = await svc.probe_quote(inst, provider)
    except ProviderUnavailable as e:
        kind = _err_kind(e.message)
        return row(key, label, group, "UNAVAILABLE" if kind == "connectivity" else "INVALID",
                   connectivity="fail" if kind == "connectivity" else "pass", structure="fail" if kind == "structure" else "skipped",
                   error=safe(e.message), action=_action_for(e.message, kind), requests=BUDGET[key])
    issues = quote_quality(q)
    st = q.prov.status.value
    action = None
    if issues:
        action = "Do not trust this provider's numbers until this is fixed. Report the issue list."
    elif q.prov.status == DataStatus.STALE:
        action = "The newest price is old for the current market session. Retry; if it stays STALE during market hours the feed is lagging."
    return row(key, label, group, _state("pass", "pass", "fail" if issues else "pass", st), connectivity="pass", structure="pass",
               quality="fail" if issues else "pass", freshness=st, observed_at=q.prov.event_time, issues=issues, action=action,
               requests=BUDGET[key], detail="; ".join(q.prov.quality)[:200] or None)


async def probe_venue(derivs, venue: str) -> dict:
    """One exchange via the derivatives fetcher only. derivs.refresh()/snapshot() would record history, so they are never called."""
    key, label = venue, VENUE_LABELS[venue]
    try:
        r = await derivs.client.fetch(venue)
    except VenueError as e:
        if e.code == "shape":
            return row(key, label, "derivatives", "INVALID", connectivity="pass", structure="fail", error=safe(e.message),
                       action=_action_for(e.message, "structure"), requests=BUDGET[venue])
        return row(key, label, "derivatives", "UNAVAILABLE", connectivity="fail", error=safe(e.message), action=_action_for(e.code + " " + e.message, "connectivity"),
                   requests=BUDGET[venue])
    issues = []
    for f in ("mark", "index", "oi_btc"):
        if not _finite(r.get(f)) or r[f] <= 0:
            issues.append(f"{f} missing or not positive")
    if not _finite(r.get("funding_rate")) or abs(r["funding_rate"]) > 0.05:
        issues.append("funding rate missing or implausible")
    if r.get("funding_interval_h") not in (1.0, 2.0, 4.0, 8.0):
        issues.append("funding interval is not 1, 2, 4 or 8 hours")
    ts = r.get("ts_ms")
    obs = datetime.fromtimestamp(ts / 1000, timezone.utc) if _finite(ts) and ts > 0 else None
    if obs is None:
        issues.append("no exchange timestamp")
    fresh = None
    if obs is not None:
        age = (datetime.now(timezone.utc) - obs).total_seconds()
        if age < -300:
            issues.append("timestamp is in the future")
        fresh = "LIVE" if age <= DERIV_STALE_SECONDS else "STALE"
    q = "fail" if issues else "pass"
    return row(key, label, "derivatives", _state("pass", "pass", q, fresh), connectivity="pass", structure="pass", quality=q, freshness=fresh, observed_at=obs,
               issues=issues, action=("Do not use this venue's numbers until fixed." if issues else None), requests=BUDGET[venue], detail="; ".join(r.get("notes") or [])[:200] or None)


async def probe_rss(news) -> dict:
    """Fetch (never store) the enabled feeds: news._get + parse only. Feed rows (etag, last_ok, errors) and news items are not written."""
    key, label = "rss", "RSS news feeds"
    feeds = [f for f in news.feeds() if f["enabled"]]
    if not feeds:
        return skipped(key, label, "news", "NOT_CONFIGURED", "No RSS feed is enabled.", "Enable or add a feed in the News page.")
    rows = news.db.q("SELECT id, name, url FROM news_feeds WHERE kind='rss' AND enabled=1 ORDER BY builtin DESC, name LIMIT ?", (MAX_FEEDS_CHECKED,))

    async def one(r):
        try:
            async with news._sem:
                status, body, _ = await news._get(r["url"], None, None)
            items, _dropped = await asyncio.to_thread(parse_feed, body)
            return r["name"], None, items
        except FeedError as e:
            return r["name"], ("structure" if any(k in str(e).lower() for k in ("xml", "rss or atom", "doctype")) else "connectivity", safe(e)), []
        except httpx.HTTPError as e:
            return r["name"], ("connectivity", f"{type(e).__name__} (feed unreachable)"), []
        except Exception as e:  # noqa: BLE001
            return r["name"], ("structure", type(e).__name__), []

    res = await asyncio.gather(*(one(r) for r in rows))
    reached = [x for x in res if x[1] is None or x[1][0] == "structure"]
    good = [x for x in res if x[1] is None and x[2]]
    failing = [f"{n}: {e[1]}" for n, e, _ in res if e]
    empty = [n for n, e, it in res if e is None and not it]
    issues = [*failing[:5], *(f"{n}: no items" for n in empty[:3])]
    newest = None
    for _, _, items in res:
        for it in items:
            if it.published and (newest is None or it.published > newest):
                newest = it.published
    nolink = sum(1 for _, _, items in res for it in items if not it.title)
    if nolink:
        issues.append(f"{nolink} item(s) without a title")
    conn = "pass" if reached else "fail"
    struct = "pass" if good else ("fail" if reached else "skipped")
    quality = "skipped" if not good else ("fail" if (nolink or newest is None) else "pass")
    if good and newest is None:
        issues.append("no item carries a publish date")
    fresh = None
    if newest is not None:
        fresh = "STALE" if (datetime.now(timezone.utc) - newest).total_seconds() > RSS_STALE_HOURS * 3600 else "DELAYED"
    state = _state(conn, struct, quality, fresh) if reached else "UNAVAILABLE"
    if state in ("OK", "STALE") and len(good) < len(res):
        state = "DEGRADED"               # some feeds work, some do not
    return row(key, label, "news", state, connectivity=conn, structure=struct, quality=quality, freshness=fresh, observed_at=newest, issues=issues,
               error=(f"{len(res) - len(good)} of {len(res)} feeds failed or were empty" if len(good) < len(res) else None),
               action=("Open the News page > Feeds to disable or fix the failing feeds." if len(good) < len(res) else None),
               requests=min(len(feeds), MAX_FEEDS_CHECKED), detail=f"{len(good)} of {len(res)} checked feeds returned items (RSS is polled, so items are DELAYED)")


async def _guard(coro, key, label, group, budget) -> dict:
    """Timeout wrapper: wait_for cancels the probe when time is up, so nothing keeps running in the background."""
    try:
        return await asyncio.wait_for(coro, PROBE_TIMEOUT)
    except asyncio.TimeoutError:
        return row(key, label, group, "UNAVAILABLE", connectivity="fail", error="timed out", action=_action_for("timed out", "connectivity"), requests=budget)
    except Exception as e:  # noqa: BLE001  a bug in one probe must not break the others
        return row(key, label, group, "UNAVAILABLE", connectivity="fail", error=f"internal error ({type(e).__name__})", action="Report this to the developer.", requests=budget)


async def run_checks(*, svc, provs: dict, ibkr_md, broker, derivs, news, demo: bool) -> dict:
    started = time.monotonic()
    sem = asyncio.Semaphore(CONCURRENCY)
    jobs: list = []
    out: dict[str, dict] = {}

    def add(key, label, group, make, budget):
        async def go():
            async with sem:
                t0 = time.monotonic()
                r = await _guard(make(), key, label, group, budget)
                r["duration_ms"] = int((time.monotonic() - t0) * 1000)
                out[key] = r
        jobs.append(asyncio.ensure_future(go()))

    order = ["coinbase", "yahoo", "ibkr", "fred", "hyperliquid", "binance", "bybit", "okx", "rss"]
    labels = {"coinbase": ("Coinbase (BTC)", "crypto"), "yahoo": ("Yahoo Finance (stocks/ETFs)", "equities"), "ibkr": ("IBKR market data", "equities"), "fred": ("FRED (macro)", "macro")}

    if demo:
        for k in order:
            lab = labels.get(k, (VENUE_LABELS.get(k, "RSS news feeds"), "derivatives" if k in VENUES else "news"))
            if k == "ibkr":
                out[k] = skipped(k, lab[0], lab[1], "NOT_CONFIGURED", "IBKR data is never used in demo mode.", None)
            else:
                out[k] = skipped(k, lab[0], lab[1], "DEMO", "Demo mode: all data is synthetic and no network checks were made.", "Start without ATLAS_DEMO=1 to check the real providers.")
    else:
        for k, sym in (("coinbase", "BTC"), ("yahoo", "SPY"), ("fred", "US10Y")):
            lab, grp = labels[k]
            p = provs.get(k)
            if p is None:
                out[k] = skipped(k, lab, grp, "NOT_CONFIGURED", "This provider is not set up.", "Restart ATLAS normally.")
                continue
            inst = I.by_symbol(sym) or I.resolve(sym)
            add(k, lab, grp, (lambda p=p, k=k, lab=lab, grp=grp, inst=inst: probe_quote(svc, k, lab, grp, p, inst)), BUDGET[k])
        lab, grp = labels["ibkr"]
        if ibkr_md is None:
            out["ibkr"] = skipped("ibkr", lab, grp, "NOT_CONFIGURED", "IBKR market data is switched off.", "Set ATLAS_IBKR_DATA=1 (the Windows launcher does this with -Real) and connect IB Gateway.")
        elif not ibkr_md.available:
            out["ibkr"] = skipped("ibkr", lab, grp, "UNAVAILABLE", "IBKR is enabled but not connected.", "Start IB Gateway, then press Connect in Settings > IBKR.")
        else:
            add("ibkr", lab, grp, lambda: probe_quote(svc, "ibkr", lab, grp, ibkr_md, I.by_symbol("SPY")), BUDGET["ibkr"])
        for v in VENUES:
            add(v, VENUE_LABELS[v], "derivatives", (lambda v=v: probe_venue(derivs, v)), BUDGET[v])
        add("rss", "RSS news feeds", "news", lambda: probe_rss(news), MAX_FEEDS_CHECKED)
        try:
            await asyncio.wait_for(asyncio.gather(*jobs), RUN_TIMEOUT)
        except asyncio.TimeoutError:
            for j in jobs:
                j.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)
            for k in order:
                out.setdefault(k, skipped(k, k, "other", "UNAVAILABLE", "check did not finish in time", "Try again in a minute."))
    rows = [out[k] for k in order if k in out]
    return {"checked_at": datetime.now(timezone.utc).isoformat(), "duration_ms": int((time.monotonic() - started) * 1000), "demo": demo,
            "max_outbound_requests": sum(r["request_budget"] for r in rows), "cooldown_seconds": int(COOLDOWN), "rows": rows,
            "note": "Read-only check. Nothing was saved, no feed or setting was changed, and no order code was touched. 'OK' means the response was reachable, well-formed and valid at this moment."}
