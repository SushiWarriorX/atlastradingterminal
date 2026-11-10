"""The jobs the scheduler runs. Each one is ordinary deterministic code that calls an existing service (which already caches and deduplicates); none of them calls Claude yet.
Jobs that need a key or a contact that is not configured are registered DISABLED and say why, instead of failing every time.
"""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from .engine import JobSpec, RunContext, Scheduler
from . import settings as ST

MB = 1024 * 1024


def watchlist_stocks(db, resolve) -> list:
    out = []
    for r in db.q("SELECT symbol FROM signal_watchlist WHERE asset_type='stock' ORDER BY position LIMIT 25"):
        inst = resolve(r["symbol"])
        if inst is not None and inst.asset_class == "equity":
            out.append(inst)
    return out


def register_default_jobs(s: Scheduler, d: dict) -> None:
    """d holds the app's services: db, news, stock_research, macro_brief, extras (name -> service with an async overview()), btc_data, resolve."""
    db = d["db"]

    async def news_refresh(ctx: RunContext) -> dict:
        res = await d["news"].refresh()
        ctx.call("rss", len(res))
        bad = [r for r in res if r.get("error")]
        if res and len(bad) == len(res):
            raise RuntimeError(f"all {len(res)} feeds failed (first: {str(bad[0].get('error'))[:100]})")
        return {"feeds": len(res), "feeds_failed": len(bad), "new_items": sum(int(r.get("new", 0) or 0) for r in res)}

    async def filings_refresh(ctx: RunContext) -> dict:
        insts = watchlist_stocks(db, d["resolve"])
        if not insts:
            return {"skipped": "no stocks on the watchlist"}
        ctx.check()
        feed = await d["stock_research"].filings_feed(insts, limit=100, days=30)
        ctx.call("sec", len(insts) * 2)
        if feed.get("needs_contact"):
            raise RuntimeError("ATLAS_SEC_CONTACT is not set")
        return {"symbols": len(insts), "filings_last_30_days": len(feed["items"]), "errors": feed["errors"][:5]}

    async def macro_refresh(ctx: RunContext) -> dict:
        done, failed = [], []
        for name in ("macro_brief", "treasury", "ecb_fx", "world_bank", "fed_ops", "tga", "auctions", "budget", "interest", "buybacks", "bill_auctions", "borrowing", "dealers", "debt_rates", "debt_mix", "fed_holdings", "fed_rates"):
            svc = d["extras"].get(name)
            if svc is None:
                continue
            ctx.check()
            try:
                out = await svc.overview()
                ctx.call("public_api", 1)
                (failed if isinstance(out, dict) and out.get("available") is False else done).append(name)
            except Exception as e:  # noqa: BLE001
                failed.append(f"{name}: {type(e).__name__}")
        if failed and not done:
            raise RuntimeError("every macro source failed: " + "; ".join(failed))
        return {"refreshed": done, "failed": failed}

    async def crypto_refresh(ctx: RunContext) -> dict:
        done, failed = [], []
        if d.get("btc_data") is not None:
            notes = await d["btc_data"].ensure("1d", False)
            ctx.call("public_api", 1)
            (failed if notes else done).append("btc daily bars")
        for name in ("fear_greed", "stablecoins", "onchain", "cg_global", "cftc_btc"):
            svc = d["extras"].get(name)
            if svc is None:
                continue
            ctx.check()
            try:
                out = await svc.overview()
                ctx.call("public_api", 1)
                (failed if out.get("available") is False and not str(out.get("reason", "")).startswith("Demo") else done).append(name)
            except Exception as e:  # noqa: BLE001
                failed.append(f"{name}: {type(e).__name__}")
        if failed and not done:
            raise RuntimeError("every crypto source failed: " + "; ".join(failed))
        return {"refreshed": done, "failed": failed}

    async def listings_refresh(ctx: RunContext) -> dict:
        out = await d["listings"].refresh(call=ctx.call)
        if out.get("available") is False:
            raise RuntimeError(out.get("reason") or "listings are not available")
        if out["rows"] == 0:
            raise RuntimeError("the IPO calendar returned no rows: " + "; ".join(out["errors"][:3]))
        return {"deals": out["rows"], "confirmed_trading": out["confirmed"], "verified_by_sec": out["verified"], "notes": out["errors"][:4]}

    async def discovery_refresh(ctx: RunContext) -> dict:
        run = await d["new_to_me"].refresh(call=ctx.call, check=ctx.check)
        if not run.get("available"):
            raise RuntimeError(run.get("reason") or "the daily study could not run")
        return {"universe": run["universe"], "studied": run["studied"], "passed": run["passed"], "left_out": sum(run["left_out_reasons"].values()), "could_not_study": sum(run["could_not_study"].values())}

    async def health_check(ctx: RunContext) -> dict:
        checks = []

        def add(name, status, detail):
            checks.append({"name": name, "status": status, "detail": detail})
        qc = db.q("PRAGMA quick_check")[0][0]
        add("database integrity", "ok" if qc == "ok" else "critical", qc)
        path = getattr(db, "path", None)
        if path and path not in (":memory:", ""):
            free = shutil.disk_usage(Path(path).resolve().parent).free
            add("disk space", "critical" if free < 100 * MB else "warn" if free < 500 * MB else "ok", f"{free // MB} MB free")
        now = s.clock()
        for j in s.overview()["jobs"]:
            if j["id"] == "health_check" or not j["enabled"] or j["paused"] or not j["registered"]:
                continue
            if j["last_success_at"] is None:
                continue
            if j["stale"]:
                add(f"freshness: {j['id']}", "warn", f"last success {int(j['age_s'] // 60)} min ago, older than 3 times its interval")
        dl = db.q("SELECT COUNT(*) FROM sched_dead_letters WHERE resolved=0")[0][0]
        if dl:
            add("dead letters", "critical", f"{dl} job(s) failed repeatedly and need attention")
        for b in s.budget.snapshot(now, ST.get(db)["reserve_pct"]).values():
            if b["remaining_fraction"] is not None and b["remaining_fraction"] <= 0:
                add(f"budget: {b['bucket']}", "critical", f"exhausted until {b['resets_at'][:16]} UTC")
            elif b["remaining_fraction"] is not None and not b["optional_work_allowed"]:
                add(f"budget: {b['bucket']}", "warn", "only the usage reserve is left; optional jobs are deferred")
        for c in checks:
            if c["status"] in ("warn", "critical"):
                s.emit("stale" if c["name"].startswith("freshness") else "budget" if c["name"].startswith("budget") else "failure", f"health:{c['name']}", c["status"], f"{c['name']}: {c['detail']}")
        if not any(c["status"] != "ok" for c in checks):
            add("all checks", "ok", "database, disk, freshness, budgets and dead letters are fine")
        return {"checks": checks, "problems": sum(1 for c in checks if c["status"] != "ok")}

    sec_on = bool(getattr(d["stock_research"].edgar, "enabled", False)) and not d.get("demo")
    s.register(JobSpec("news_refresh", "Refresh news feeds", "refresh", news_refresh, interval_market_s=300, interval_off_s=1800, priority=4, buckets={"rss": 12}, max_runtime_s=120,
                       description="Fetches the RSS feeds you follow. New or changed items only are stored."))
    s.register(JobSpec("filings_refresh", "Refresh SEC filings for the watchlist", "refresh", filings_refresh, interval_market_s=1800, interval_off_s=7200, priority=3, buckets={"sec": 30}, max_runtime_s=300,
                       enabled=sec_on, description="Reads the latest 10-K, 10-Q, 8-K and Form 4 filings for stocks on the watchlist. Needs ATLAS_SEC_CONTACT."))
    s.register(JobSpec("macro_refresh", "Refresh macro data", "refresh", macro_refresh, interval_market_s=900, interval_off_s=3600, priority=3, buckets={"public_api": 6}, max_runtime_s=180,
                       description="Keeps the Macro screen current: key indicators, Treasury, exchange rates, World Bank."))
    s.register(JobSpec("crypto_refresh", "Refresh crypto data", "refresh", crypto_refresh, interval_market_s=900, interval_off_s=900, priority=3, buckets={"public_api": 8}, max_runtime_s=180,
                       description="BTC daily prices, Fear and Greed, stablecoins, network, market, CFTC positioning."))
    if d.get("listings") is not None:
        s.register(JobSpec("listings_refresh", "Refresh newly listed companies", "discovery", listings_refresh, interval_market_s=3600 * 3, interval_off_s=3600 * 8, priority=4, buckets={"public_api": 4, "sec": 50},
                           max_runtime_s=300, enabled=not d.get("demo"), description="Reads the Nasdaq IPO calendar (upcoming and recent), looks for a confirmed first trading day and the SEC final prospectus. Fundamental research ranks above optional experiments."))
    if d.get("new_to_me") is not None:
        s.register(JobSpec("discovery_refresh", "Daily new-to-me research candidates", "discovery", discovery_refresh, interval_market_s=86400, interval_off_s=86400, priority=4, buckets={"public_api": 2, "sec": 130},
                           max_runtime_s=1800, enabled=sec_on, freshness_s=3 * 86400, description="Studies a varied sample of listed companies from SEC filings and saves the ones that pass the evidence gate. Needs ATLAS_SEC_CONTACT. Fewer candidates are better than weak ones."))
    s.register(JobSpec("health_check", "Health and data-quality checks", "health", health_check, interval_market_s=600, interval_off_s=600, priority=5, max_runtime_s=60,
                       description="Database integrity, disk space, stale jobs, exhausted budgets and dead letters. Reports problems; never changes code."))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
