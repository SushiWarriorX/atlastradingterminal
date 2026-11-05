"""Discover: a two-stage, daily scan of the core US universe.

Stage 1 (cheap): daily bars -> momentum and liquidity for every symbol; only liquid names are kept and the strongest few dozen go on.
Stage 2 (careful): SEC EDGAR annual filings for those -> growth, margins, free cash flow, debt, EPS; then all six factors are scored (see score.py).
The five best, with at most two per sector, become the day's shortlist. The result is saved per UTC day so it does not change under you while you read it.
Not included because no reliable free source exists: earnings surprises, IPO calendars and analyst estimates. Those are stated in the response.
"""
from __future__ import annotations

import asyncio
import json
import zlib
from datetime import datetime, timezone

from .. import instruments as I
from ..db import DB
from ..models import ProviderUnavailable
from ..scanner import features as feat
from ..scanner.bars import BarSource
from ..scanner.universe import CORE
from ..stocks import research as R
from . import score as SC

STAGE2 = 30
SHORTLIST = 5
BENCH = "SPY"
GAPS = ["Earnings surprises, IPO calendars and analyst estimates are not included: there is no reliable free source for them.",
        "Financials are from annual 10-K filings and can be up to a year old; guidance and the latest quarter are not included.",
        "The universe is about 100 liquid US large caps (a fixed list), not every NYSE and Nasdaq stock.",
        "Prices are delayed daily bars from Yahoo Finance (unofficial)."]
HOW = ["Stage 1: score every liquid stock on momentum and liquidity from daily bars; keep the strongest %d." % STAGE2,
       "Stage 2: add SEC filing data for those and score six factors from 0 to 100 with fixed weights.",
       "Rank by the weighted score (missing factors are left out and the rest rescaled; five of six are needed). Pick the top five with at most two per sector.",
       "Nothing is learned or tuned. The same inputs always give the same shortlist."]


def demo_fin(sym: str) -> dict:
    """Synthetic annual figures for demo mode. NOT real company data."""
    r = zlib.crc32(sym.encode())
    base = 1e9 * (1 + r % 50)
    years, rev = [], base
    for i in range(5):
        g = 0.02 + ((r >> (i + 2)) % 25) / 100
        prev, rev = rev, rev * (1 + g)
        years.append({"end": f"{2022 + i}-12-31", "revenue": rev, "gross_profit": rev * 0.5, "operating_income": rev * (0.08 + (r % 20) / 100), "net_income": rev * (0.05 + (r % 15) / 100),
                      "eps_diluted": (1 + (r % 90) / 10) * (1.1 ** i) if r % 11 else -1.0, "operating_cash_flow": rev * 0.2, "capex": rev * 0.05, "cash": rev * 0.3, "debt": rev * (0.1 + (r % 8) / 10), "equity": rev * 0.6,
                      "assets": rev, "liabilities": rev * 0.4})
    return {"name": f"{sym} (synthetic)", "years": years}


class DiscoverService:
    def __init__(self, db: DB, bars: BarSource, edgar, demo: bool = False):
        self.db, self.bars, self.edgar, self.demo = db, bars, edgar, demo
        self._lock = asyncio.Lock()

    def method(self) -> dict:
        return {"weights": SC.WEIGHTS, "scales": SC.SCALES, "steps": HOW, "min_factors": SC.MIN_FACTORS, "min_dollar_volume": SC.MIN_DOLLAR_VOLUME, "max_per_sector": SC.MAX_PER_SECTOR,
                "note": "Scores order candidates for your own research. They are not predictions, ratings or advice."}

    def _latest(self):
        r = self.db.q("SELECT payload FROM discover_runs ORDER BY asof DESC LIMIT 1")
        return json.loads(r[0]["payload"]) if r else None

    async def shortlist(self, refresh: bool = False, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        day = now.date().isoformat()
        async with self._lock:
            row = self.db.q("SELECT payload FROM discover_runs WHERE asof=?", (day,))
            if row and not refresh:
                return json.loads(row[0]["payload"])
            run = await self._scan(now)
            if run["shortlist"] or not self._latest():
                self.db.x("INSERT INTO discover_runs(asof,created_at,payload) VALUES(?,?,?) ON CONFLICT(asof) DO UPDATE SET created_at=excluded.created_at, payload=excluded.payload", (day, now.isoformat(), json.dumps(run)))
                return run
            prev = self._latest()                          # a failed scan (no data) must not replace the last good shortlist
            prev["stale_notice"] = f"Today's scan produced no candidates ({'; '.join(run['notes'])[:200]}). Showing the last saved shortlist from {prev['asof']}."
            return prev

    def ranked(self, sector: str | None = None, min_score: float = 0, max_pe: float | None = None, min_growth: float | None = None, limit: int = 25) -> dict:
        run = self._latest()
        if not run:
            return {"items": [], "total": 0, "asof": None}
        items = run["ranked"]
        if sector:
            items = [x for x in items if x["sector"] == sector]
        items = [x for x in items if x["score"] >= min_score]
        if max_pe is not None:
            items = [x for x in items if x["pe"] is not None and x["pe"] <= max_pe]
        if min_growth is not None:
            items = [x for x in items if x["revenue_growth_pct"] is not None and x["revenue_growth_pct"] >= min_growth]
        return {"items": items[:max(1, min(limit, 50))], "total": len(items), "asof": run["asof"], "sectors": sorted({x["sector"] for x in run["ranked"] if x["sector"]})}

    async def _fin(self, sym: str, price: float | None) -> dict | None:
        try:
            if self.demo:
                fin = demo_fin(sym)
            else:
                hit = await self.edgar.cik(sym)
                if hit is None:
                    return None
                fin, _, _ = await self.edgar.financials(hit[0])
                fin = {**fin, "name": hit[1]}
        except (ProviderUnavailable, Exception):  # noqa: BLE001  one company failing must not stop the scan
            return None
        years = R.compute(fin["years"]) if fin.get("years") else []
        if not years:
            return None
        last = years[-1]
        cg = R.cagr(years)
        eps = last.get("eps_diluted")
        return {"last": last, "cagr": cg["value_pct"] if cg else None, "pe": (price / eps) if price and eps and eps > 0 else None, "name": fin.get("name"), "period_end": last["end"]}

    async def _scan(self, now: datetime) -> dict:
        notes: list[str] = []
        if not self.demo and not self.edgar.enabled:
            notes.append("SEC filings are off: set ATLAS_SEC_CONTACT to an email address to turn on Discover (it needs company financials).")
        uni_syms = {s: sec for s, sec in CORE.items() if not self.demo or I.resolve(s)}      # demo mode: only assets the built-in demo watchlist can hold
        syms = list(uni_syms) + [BENCH]
        batch = await self.bars.fetch(syms)
        notes += batch.notes
        bench = batch.bars.get(BENCH)
        feats = {}
        for s in uni_syms:
            if s in batch.bars:
                f = feat.compute(s, batch.bars[s], bench, uni_syms[s])
                if f["sufficient"]:
                    feats[s] = f
        n_priced = len(feats)
        liquid = {s: f for s, f in feats.items() if (f.get("dollar_volume_avg20") or 0) >= SC.MIN_DOLLAR_VOLUME}
        excluded = {"not enough price history or no bars": len(uni_syms) - n_priced, f"below ${SC.MIN_DOLLAR_VOLUME / 1e6:.0f}M average daily dollar volume": n_priced - len(liquid)}

        def prelim(f):
            fx = SC.factors(f, None)
            m, l = fx["momentum"], fx["liquidity"]
            return None if m is None or l is None else (SC.WEIGHTS["momentum"] * m["score"] + SC.WEIGHTS["liquidity"] * l["score"]) / (SC.WEIGHTS["momentum"] + SC.WEIGHTS["liquidity"])
        pre = sorted(((prelim(f), s) for s, f in liquid.items() if prelim(f) is not None), reverse=True)[:STAGE2]
        fins = dict(zip([s for _, s in pre], await asyncio.gather(*(self._fin(s, liquid[s]["price"]) for _, s in pre))))
        by_sector: dict[str, list[float]] = {}
        for f in feats.values():
            if f.get("ret_63d") is not None and f["sector"]:
                by_sector.setdefault(f["sector"], []).append(f["ret_63d"])
        allr = [x for v in by_sector.values() for x in v]
        uni = sum(allr) / len(allr) if allr else None
        ranked = []
        for _, s in pre:
            fi, f = fins[s], liquid[s]
            fx = SC.factors(f, fi)
            sc, cov = SC.total(fx)
            if sc is None:
                excluded["too few factors available (missing filings)"] = excluded.get("too few factors available (missing filings)", 0) + 1
                continue
            sect = by_sector.get(f["sector"] or "", [])
            note = None
            if sect and uni is not None and len(sect) >= 3:
                avg = sum(sect) / len(sect)
                note = f"Sector trend: {f['sector']} stocks in this universe averaged {avg:+.1f}% over three months vs {uni:+.1f}% for all."
            inst = I.resolve(s)
            last = fi["last"]
            ev = [{"label": "Revenue growth, latest fiscal year", "value": last.get("revenue_growth_pct"), "unit": "%", "source": "SEC EDGAR 10-K", "as_of": fi["period_end"]},
                  {"label": "Operating margin", "value": last.get("operating_margin_pct"), "unit": "%", "source": "SEC EDGAR 10-K", "as_of": fi["period_end"]},
                  {"label": "Free-cash-flow margin", "value": last.get("fcf_margin_pct"), "unit": "%", "source": "SEC EDGAR 10-K (calculated)", "as_of": fi["period_end"]},
                  {"label": "Price / last year's EPS", "value": fi["pe"], "unit": "x", "source": "Yahoo price and SEC EPS (calculated)", "as_of": f["last_bar_date"]},
                  {"label": "Six-month price return", "value": f["ret_126d"], "unit": "%", "source": "Yahoo daily bars (delayed)", "as_of": f["last_bar_date"]},
                  {"label": "Distance from 52-week high", "value": f["dist_52w_high_pct"], "unit": "%", "source": "Yahoo daily bars (delayed)", "as_of": f["last_bar_date"]}]
            ranked.append({"symbol": s, "name": fi.get("name"), "sector": f["sector"], "asset_id": inst.id if inst else f"EQUITY:US:{s}", "score": round(sc, 1), "coverage": cov, "of": len(SC.WEIGHTS),
                           "factors": {k: (None if v is None else {"score": round(v["score"], 1), "inputs": v["inputs"]}) for k, v in fx.items()},
                           "reasons": SC.reasons(fx, f, fi, note), "risks": SC.risks(f, fi), "evidence": ev, "price": f["price"], "pe": fi["pe"], "revenue_growth_pct": last.get("revenue_growth_pct"),
                           "as_of": {"prices": f["last_bar_date"], "fiscal_year_end": fi["period_end"]}})
        ranked.sort(key=lambda x: (-x["score"], x["symbol"]))
        short, count = [], {}
        for x in ranked:
            if len(short) < SHORTLIST and count.get(x["sector"], 0) < SC.MAX_PER_SECTOR:
                short.append(x)
                count[x["sector"]] = count.get(x["sector"], 0) + 1
        for i, x in enumerate(short):
            x["rank"] = i + 1
        if not ranked and not notes:
            notes.append("No stock had enough data to be scored.")
        return {"asof": now.date().isoformat(), "created_at": now.isoformat(), "demo": self.demo, "shortlist": short, "ranked": ranked,
                "universe": {"name": "Demo sample list (built-in assets only)" if self.demo else "Core US large caps (fixed list)", "size": len(uni_syms), "priced": n_priced, "liquid": len(liquid), "scored": len(ranked)}, "excluded": excluded, "notes": notes,
                "data": {"prices": batch.provider, "prices_status": str(getattr(batch.status, "value", batch.status)), "prices_as_of": batch.as_of.isoformat() if batch.as_of else None, "fundamentals": "synthetic demo figures" if self.demo else "SEC EDGAR annual filings"},
                "method": self.method(), "gaps": GAPS, "disclaimer": "A ranked list of candidates to research, produced by fixed rules. Not a recommendation, rating or prediction."}
