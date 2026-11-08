"""The daily "new to me" research candidates.

A daily job studies a varied sample of the listed universe from filed figures and saves a POOL of the candidates that pass the evidence gate. The page then narrows that pool with my filters, removes
what I have already dismissed, saved or researched (and what I saw recently without anything new), keeps the list varied, and shows FEWER than the target when evidence is weak. Nothing is padded.
Prices come from the screener feed (delayed, unofficial) and are labelled as such; filings come from the SEC.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone

import httpx

from . import candidates as C
from . import universe as U
from .store import COOLDOWN_DAYS, DiscoveryStore

SCREENER_TTL = timedelta(hours=12)
STUDY = 60
POOL_MAX = 40
GAPS = ["Companies are studied from SEC filings, so only US-GAAP filers with eight quarters of history can qualify; foreign (IFRS) filers and very new listings do not appear here.",
        "Scores order candidates for my own research. They are not ratings, predictions or advice, and a high score does not mean a stock is cheap.",
        "Prices are delayed and come from Nasdaq's public screener feed (unofficial).",
        "Banks, insurers and REITs are not scored well by company-style measures, and sector-specific measures are not built yet."]


def compact(c: dict, ev: dict, research: dict, price_time: str, now: datetime) -> dict:
    rev, v, r40 = research.get("revenue") or {}, research.get("valuation") or {}, research.get("rule_of_40") or {}
    fm = next((r["value"] for r in (research.get("quality") or {}).get("rows", []) if r["key"] == "fcf_margin"), None)
    return {"symbol": c["symbol"], "name": c["name"], "exchange": c["exchange"], "sector": c["sector"], "industry": c["industry"], "country": c["country"], "market_cap": c["market_cap"],
            "size_bucket": U.size_bucket(c["market_cap"]), "ipo_year": c["ipo_year"], "dollar_volume": c["dollar_volume"], "price": c["price"], "price_time": price_time,
            "price_source": "Nasdaq screener (delayed, unofficial)", "score": ev["score"], "factors": ev["factors"], "why_selected": ev["why_selected"], "risks": ev["risks"],
            "main_opportunity": ev["main_opportunity"], "main_risk": ev["main_risk"], "material": C.material_key(research),
            "description": {"classification": (research.get("company") or {}).get("sic"), "industry": c["industry"], "sector": c["sector"],
                            "note": "This is a classification, not a summary of what the company sells. Read Item 1 (Business) of the latest annual report."},
            "revenue": {"ttm": (rev.get("ttm") or {}).get("value"), "ttm_period_end": (rev.get("ttm") or {}).get("period_end"), "growth_pct": rev.get("ttm_growth_pct"), "trend": (rev.get("trend") or {}).get("label"),
                        "fcf_margin_pct": fm, "age_days": rev.get("age_days"), "latest_period_end": rev.get("latest_period_end")},
            "rule_of_40": {"applicable": r40.get("applicable"), "label": r40.get("label"), "score": (r40.get("current") or {}).get("score") if r40.get("available") else None},
            "valuation": {"label": v.get("label"), "label_key": v.get("label_key"), "evidence": (v.get("evidence") or {}).get("level"), "base_fair_value": (v.get("fair_value_range") or {}).get("base")},
            "studied_at": now.isoformat()}


class NewToMe:
    def __init__(self, db, store: DiscoveryStore, researcher, client: httpx.AsyncClient | None = None, demo: bool = False, watchlist=lambda: []):
        self.db, self.store, self.researcher, self._client, self.demo, self.watchlist = db, store, researcher, client, demo, watchlist

    # ---- universe -----------------------------------------------------------------------
    async def universe(self, now: datetime) -> tuple[list[dict], list[str]]:
        out, errors = [], []
        c = self._client or httpx.AsyncClient(timeout=90)
        try:
            for ex, label in (("nasdaq", "Nasdaq"), ("nyse", "NYSE")):
                key = f"screener:{ex}"
                r = self.db.q("SELECT fetched_at, payload FROM listing_cache WHERE key=?", (key,))
                if r and now - datetime.fromisoformat(r[0]["fetched_at"]) < SCREENER_TTL:
                    out += json.loads(r[0]["payload"])
                    continue
                try:
                    resp = await c.get(U.URL.format(exchange=ex), headers={"User-Agent": "ATLAS research terminal", "Accept": "application/json"})
                    if resp.status_code != 200:
                        raise ValueError(f"HTTP {resp.status_code}")
                    rows = U.parse_screener(resp.json(), label)
                    if len(rows) < 100:
                        raise ValueError("the feed returned too few companies")
                    self.db.x("INSERT INTO listing_cache(key,fetched_at,payload) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET fetched_at=excluded.fetched_at, payload=excluded.payload",
                              (key, now.isoformat(), json.dumps(rows)))
                    out += rows
                except (httpx.HTTPError, ValueError, TypeError, KeyError) as e:
                    if r:
                        errors.append(f"{label}: could not refresh ({type(e).__name__}); using the copy saved {r[0]['fetched_at'][:10]}")
                        out += json.loads(r[0]["payload"])
                    else:
                        errors.append(f"{label}: could not be read ({type(e).__name__}: {str(e)[:60]})")
        finally:
            if self._client is None:
                await c.aclose()
        seen, unique = set(), []
        for c in out:                                                       # one row per symbol, first listing wins
            if c["symbol"] not in seen:
                seen.add(c["symbol"])
                unique.append(c)
        return unique, errors

    # ---- the daily study ----------------------------------------------------------------
    async def refresh(self, now: datetime | None = None, call=None, check=None, study: int = STUDY, pool_max: int = POOL_MAX) -> dict:
        now = now or datetime.now(timezone.utc)
        day = now.date().isoformat()
        base = {"asof": day, "created_at": now.isoformat(), "demo": self.demo, "gaps": GAPS}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: candidates are studied from real filings, and made-up companies would look real, so none are shown.", "pool": []}
        companies, errors = await self.universe(now)
        if not companies:
            return {**base, "available": False, "reason": "The company universe could not be read right now: " + "; ".join(errors), "pool": []}
        keep, excluded = U.apply_filters(companies, None, now.year)
        held = {s.upper() for s in self.watchlist()}
        skip = {c["symbol"] for c in keep if self.store.get(c["symbol"])["dismissed_at"] or self.store.get(c["symbol"])["saved_at"] or self.store.get(c["symbol"])["researched_at"]} | held
        sample = U.sample_for_study(keep, day, study, skip)
        pool, left_out, failed = [], {}, {}
        sem = asyncio.Semaphore(3)

        async def one(c):
            async with sem:
                if check:
                    check()
                price_time = now.isoformat()
                r = await self.researcher(c["symbol"], c["price"], price_time, "Nasdaq screener (delayed, unofficial)", now)
                if call:
                    call("sec", 2)
                return c, r, price_time
        for coro in asyncio.as_completed([one(c) for c in sample]):
            try:
                c, r, pt = await coro
            except Exception as e:  # noqa: BLE001  one company failing must not stop the others
                failed[type(e).__name__] = failed.get(type(e).__name__, 0) + 1
                continue
            if not r.get("available"):
                key = (r.get("reason") or "unavailable")[:80]
                failed[key] = failed.get(key, 0) + 1
                continue
            ev = C.evaluate(r)
            if not ev["eligible"]:
                left_out[ev["excluded_because"]] = left_out.get(ev["excluded_because"], 0) + 1
                continue
            pool.append(compact(c, ev, r, pt, now))
        pool.sort(key=lambda x: (-x["score"], x["symbol"]))
        run = {**base, "available": True, "universe": len(companies), "after_filters": len(keep), "excluded_by_filters": excluded, "studied": len(sample), "passed": len(pool), "left_out_reasons": left_out,
               "could_not_study": failed, "errors": errors, "pool": pool[:pool_max], "source": {"universe": U.SOURCE, "filings": "SEC EDGAR XBRL company facts (official)"}}
        self.db.x("INSERT INTO disc_feed_runs(kind,asof,created_at,payload) VALUES('new_to_me',?,?,?) ON CONFLICT(kind,asof) DO UPDATE SET created_at=excluded.created_at, payload=excluded.payload",
                  (day, now.isoformat(), json.dumps(run)))
        return run

    def latest_run(self) -> dict | None:
        r = self.db.q("SELECT payload FROM disc_feed_runs WHERE kind='new_to_me' ORDER BY asof DESC LIMIT 1")
        return json.loads(r[0]["payload"]) if r else None

    # ---- what I see ---------------------------------------------------------------------
    def read(self, filters: dict | None = None, target: int = C.DEFAULT_TARGET, now: datetime | None = None, mark: bool = True) -> dict:
        now = now or datetime.now(timezone.utc)
        run = self.latest_run()
        if run is None:
            return {"available": False, "reason": "No daily study has run yet. It runs once a day through the scheduler (needs ATLAS_SEC_CONTACT); once it has, candidates appear here.", "items": [], "gaps": GAPS}
        if not run.get("available"):
            return {"available": False, "reason": run.get("reason"), "items": [], "gaps": GAPS, "asof": run.get("asof")}
        pool = run["pool"]
        kept, excl = U.apply_filters([{**p, "symbol": p["symbol"], "market_cap": p["market_cap"], "dollar_volume": p["dollar_volume"]} for p in pool], filters or {"min_market_cap": 0, "max_market_cap": float("inf"), "min_dollar_volume": 0}, now.year)
        keep_syms = {p["symbol"] for p in kept}
        eligible, hidden = [], []
        for p in pool:
            if p["symbol"] not in keep_syms:
                continue
            ok, why = self.store.eligible(p["symbol"], p["material"], now)
            (eligible if ok else hidden).append({**p, "_why_shown": why} if ok else {"symbol": p["symbol"], "reason": why})
        chosen, skipped = C.pick(eligible, max(1, min(int(target), 20)))
        items = []
        for p in chosen:
            st = self.store.get(p["symbol"])
            why_again = "New since you last saw it: a new quarter was filed or the valuation reading changed." if p["_why_shown"].startswith("material") else None
            items.append({**{k: v for k, v in p.items() if k != "_why_shown"}, "state": {"seen": bool(st["first_seen_at"]), "opened": bool(st["opened_at"]), "saved": bool(st["saved_at"]), "shown_count": st["shown_count"]},
                          "why_shown_again": why_again})
            if mark:
                self.store.mark_shown(p["symbol"], p["material"], p["score"], now)
        age = (now.date() - date.fromisoformat(run["asof"])).days
        return {"available": True, "asof": run["asof"], "age_days": age, "stale": age > 2, "target": target, "shown": len(items), "items": items,
                "pool_size": len(pool), "filters_applied": {k: (None if isinstance(v, float) and v in (float("inf"), float("-inf")) else v) for k, v in (filters or {}).items()}, "excluded_by_my_filters": excl, "hidden_because_seen": hidden, "kept_varied": skipped,
                "evidence_note": (f"Showing {len(items)} of a target of {target}: fewer are shown when evidence is weak or when I have already seen, saved or dismissed the rest." if len(items) < target
                                  else f"Showing {len(items)} candidates."),
                "study": {"universe": run["universe"], "after_filters": run["after_filters"], "studied": run["studied"], "passed": run["passed"], "left_out_reasons": run["left_out_reasons"],
                          "could_not_study": run["could_not_study"]}, "method": {"weights": C.WEIGHTS, "min_total": C.MIN_TOTAL, "min_factors": C.MIN_FACTORS, "max_per_sector": C.MAX_PER_SECTOR,
                                                                                 "cooldown_days": COOLDOWN_DAYS}, "gaps": GAPS, "source": run["source"]}
