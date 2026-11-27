"""Narrative of the day: which market theme (Quantum, Nuclear, Robotics, ...) has the most going on right now, found with fixed rules and shown in Discover.

How it picks, in plain words:
 - Each theme is a fixed basket of liquid US-listed stocks plus a few headline keywords (see THEMES). The baskets and the one-paragraph context are written by hand
   and are labelled that way; everything else is calculated from market data.
 - Four measures per theme, each turned into 0-100: how far the basket beat the S&P 500 (SPY) over about a month; how many of its stocks trade above their 50-day
   average; how heavy today's volume is versus normal; how many headlines in the last 48 hours mention the theme (from the RSS feeds you follow).
 - Fixed weights add them up. The top theme that has NOT been the narrative in the last 5 days is featured. The result is saved per UTC day so it does not change
   while you read it. Nothing is learned or tuned.
A narrative is a story the market is telling itself, not a forecast. Themes that run hot are volatile and often reverse; the page says so and shows the risks.
"""
from __future__ import annotations

import asyncio
import json
import statistics
from datetime import date, datetime, timedelta, timezone

from ..db import DB
from ..scanner import features as feat

BENCH = "SPY"
HISTORY_DAYS = 5
MIN_NAMES = 4
MAX_KEYWORDS = 3            # every theme uses at most this many keywords, so one theme cannot collect more headlines just by listing more words
WEIGHTS = {"relative_strength": 0.40, "breadth": 0.25, "volume": 0.15, "news": 0.20}
SCALES = {
    "relative_strength": "Basket's median one-month return minus SPY's. 0 points at -20 percentage points, 50 at 0, 100 at +20.",
    "breadth": "Share of the basket trading above its 50-day average, 0% to 100%.",
    "volume": "Median of today's volume divided by the 20-day average. 50 points at 1.0x, 100 at 2.0x or more, 0 at 0x.",
    "news": "Headlines in the last 48 hours that mention the theme's keywords. 10 points each, capped at 100.",
}

# id, name, hand-written context, basket, headline keywords, hand-written risks. Baskets are fixed lists, not a screen of every company in the theme.
THEMES = [
    {"id": "quantum", "name": "Quantum computing", "tickers": "IONQ RGTI QBTS QUBT IBM", "keywords": ["quantum"],
     "context": "Companies building quantum computers, which aim to solve certain problems far faster than normal computers. Mostly early-stage, with small revenues and large research costs.",
     "risks": ["Revenue is tiny compared with valuations, so prices swing on headlines.", "Commercial use is still years away; timelines slip often.", "Several names have raised money by selling new shares, which dilutes holders."]},
    {"id": "nuclear", "name": "Nuclear and uranium", "tickers": "CCJ SMR OKLO LEU BWXT CEG", "keywords": ["nuclear", "uranium", "reactor"],
     "context": "Uranium miners, fuel suppliers, small modular reactor developers and nuclear power operators, driven by rising electricity demand from data centres.",
     "risks": ["Reactor developers have little or no revenue yet.", "Approvals and construction take years and run over budget.", "Uranium prices and policy news can move the whole group at once."]},
    {"id": "robotics", "name": "Robotics and automation", "tickers": "ISRG TER ROK SYM PATH", "keywords": ["robot", "humanoid", "automation"],
     "context": "Surgical and industrial robots, automation software and the equipment that tests them. Interest grows whenever humanoid robot demos or factory-automation orders make headlines.",
     "risks": ["Demos are not sales; many announcements have no near-term revenue.", "Industrial names depend on factory investment, which falls in downturns.", "The basket mixes mature and speculative companies."]},
    {"id": "ai_infra", "name": "AI infrastructure and data centres", "tickers": "NVDA AVGO VRT SMCI ANET DELL", "keywords": ["data center", "AI chip", "AI infrastructure"],
     "context": "Chips, servers, networking and cooling used to build AI data centres. Moves with spending plans from the largest cloud companies.",
     "risks": ["Demand depends on a few very large customers' budgets.", "Expectations are high, so small disappointments cause large drops.", "Export rules and supply limits can change quickly."]},
    {"id": "power", "name": "Power and electrification", "tickers": "GEV ETN VST PWR NRG CEG", "keywords": ["power grid", "electricity demand", "turbine"],
     "context": "Electricity generators, grid equipment and builders benefiting from higher power demand (data centres, electric vehicles, reshoring).",
     "risks": ["Regulated prices and permitting can cap profits.", "Equipment makers are cyclical and capacity-constrained.", "Several names have already re-rated sharply."]},
    {"id": "space", "name": "Space", "tickers": "RKLB ASTS LUNR PL", "keywords": ["rocket", "satellite", "space"],
     "context": "Launch providers, satellite networks and lunar missions. News about launches, contracts and funding drives interest.",
     "risks": ["Launch failures and delays are common.", "Most names burn cash and raise money often.", "Prices can rise or fall 20% on one headline."]},
    {"id": "cyber", "name": "Cybersecurity", "tickers": "CRWD PANW ZS FTNT S OKTA", "keywords": ["cyber", "ransomware", "data breach"],
     "context": "Security software for companies. Interest rises after large breaches and when companies add security budgets.",
     "risks": ["Valuations are often high for growth that is slowing.", "A single outage or breach at a vendor can hit its stock.", "Software spending is sensitive to the economy."]},
    {"id": "defense", "name": "Defense and drones", "tickers": "LMT RTX NOC AVAV KTOS", "keywords": ["defense", "drone", "missile"],
     "context": "Defence contractors and drone makers. Moves with government budgets and geopolitical news.",
     "risks": ["Revenue depends on government budgets and contract timing.", "Geopolitical spikes fade as quickly as they come.", "Large contracts are lumpy."]},
    {"id": "glp1", "name": "Obesity drugs (GLP-1)", "tickers": "LLY NVO VKTX AMGN", "keywords": ["GLP-1", "obesity", "weight loss"],
     "context": "Makers and developers of weight-loss and diabetes drugs. Driven by trial results, supply and pricing news.",
     "risks": ["Trial results can reverse a stock in a day.", "Pricing pressure and insurer coverage decisions matter.", "Smaller names depend on one drug."]},
    {"id": "chip_equipment", "name": "Chip equipment and memory", "tickers": "ASML AMAT LRCX KLAC TSM MU", "keywords": ["semiconductor", "chipmaker", "memory chip"],
     "context": "Machines and manufacturing used to make chips, plus memory makers. Cyclical: orders swing with chip demand.",
     "risks": ["Strongly cyclical; booms are followed by inventory slumps.", "Export controls on China can change sales quickly.", "Memory prices are volatile."]},
    {"id": "gold", "name": "Gold and miners", "tickers": "NEM AEM FNV WPM GOLD", "keywords": ["gold price", "gold miner", "bullion"],
     "context": "Gold miners and royalty companies. Tends to follow gold, real interest rates and the dollar.",
     "risks": ["Miners move more than gold itself, both up and down.", "Costs and mine problems can hurt even when gold rises.", "Gold can stall for years."]},
    {"id": "crypto_equities", "name": "Crypto-linked stocks", "tickers": "COIN MSTR MARA RIOT CLSK HOOD", "keywords": ["bitcoin", "crypto", "stablecoin"],
     "context": "Exchanges, treasury holders and miners whose results move with Bitcoin and trading activity.",
     "risks": ["They usually move more than Bitcoin itself.", "Regulation news can swing the group.", "Some rely on borrowing or share sales to fund Bitcoin purchases."]},
    {"id": "clean_energy", "name": "Solar and clean energy", "tickers": "ENPH FSLR NEE RUN", "keywords": ["solar", "renewable", "clean energy"],
     "context": "Solar makers, installers and renewable utilities. Sensitive to interest rates and subsidy policy.",
     "risks": ["Policy changes can erase incentives.", "Higher interest rates hurt financed installations.", "Price competition from overseas makers."]},
    {"id": "fintech", "name": "Fintech and payments", "tickers": "PYPL AFRM SOFI HOOD XYZ", "keywords": ["fintech", "buy now pay later", "neobank"],
     "context": "Payments, lending and online brokerage companies. Sensitive to consumer credit and interest rates.",
     "risks": ["Loan losses rise when the economy weakens.", "Competition squeezes fees.", "Valuations depend on continued rapid growth."]},
    {"id": "oil_gas", "name": "Oil and gas", "tickers": "XOM CVX COP OXY SLB", "keywords": ["oil price", "crude", "OPEC"],
     "context": "Oil and gas producers and services. Follows crude oil and gas prices, OPEC decisions and geopolitics.",
     "risks": ["Profits track commodity prices, which are volatile.", "Demand forecasts shift with the economy.", "Policy and energy-transition news cut both ways."]},
]
for _t in THEMES:
    _t["tickers"] = _t["tickers"].split()


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def theme_metrics(theme: dict, feats: dict[str, dict], bench: dict | None, headline_count: int | None) -> dict | None:
    """Measures for one theme from its stocks' features; None if too few stocks have data."""
    rows = [feats[s] for s in theme["tickers"] if s in feats and feats[s].get("sufficient") and feats[s].get("ret_21d") is not None]
    if len(rows) < MIN_NAMES:
        return None
    rets = [r["ret_21d"] for r in rows]
    b = bench.get("ret_21d") if bench else None
    rel = statistics.median(rets) - (b if b is not None else 0.0)
    above = [r["above_sma50"] for r in rows if r.get("above_sma50") is not None]
    breadth = sum(above) / len(above) if above else None
    rv = [r["rvol"] for r in rows if r.get("rvol") is not None]
    vol = statistics.median(rv) if rv else None
    parts = {"relative_strength": _clamp(50 + rel * 2.5), "breadth": None if breadth is None else breadth * 100, "volume": None if vol is None else _clamp(50 + (vol - 1.0) * 50),
             "news": None if headline_count is None else min(100.0, headline_count * 10.0)}
    use = {k: v for k, v in parts.items() if v is not None}
    total = sum(WEIGHTS[k] * v for k, v in use.items()) / sum(WEIGHTS[k] for k in use)
    return {"score": round(total, 1), "parts": {k: (None if v is None else round(v, 1)) for k, v in parts.items()}, "names": len(rows),
            "facts": {"median_return_1m_pct": round(statistics.median(rets), 1), "spy_return_1m_pct": None if b is None else round(b, 1), "relative_1m_pct": round(rel, 1),
                      "share_above_50d": None if breadth is None else round(breadth, 2), "median_volume_vs_normal": None if vol is None else round(vol, 2), "headlines_48h": headline_count,
                      "median_daily_range_pct": round(statistics.median([r["atr_pct"] for r in rows if r.get("atr_pct") is not None] or [0]), 1)}}


def pick(scored: list[tuple[str, dict]], recent: list[str]) -> tuple[str, dict] | None:
    """Highest score among themes not featured in the last HISTORY_DAYS days; if every theme was recent, the highest overall."""
    ordered = sorted(scored, key=lambda x: (-x[1]["score"], x[0]))
    fresh = [x for x in ordered if x[0] not in recent]
    return (fresh or ordered or [None])[0]


class NarrativeService:
    def __init__(self, db: DB, bars, news, demo: bool = False):
        self.db, self.bars, self.news, self.demo = db, bars, news, demo
        self._lock = asyncio.Lock()

    def method(self) -> dict:
        return {"weights": WEIGHTS, "scales": SCALES, "themes": [{"id": t["id"], "name": t["name"], "tickers": t["tickers"], "keywords": t["keywords"]} for t in THEMES], "recent_days_excluded": HISTORY_DAYS,
                "steps": ["Measure every theme's basket: relative strength versus SPY, breadth, volume and headline count.", "Add the four measures with fixed weights (missing ones are left out and the rest rescaled).",
                          f"Feature the highest-scoring theme not featured in the last {HISTORY_DAYS} days.", "Nothing is learned or tuned. The same inputs give the same answer."],
                "note": "A narrative is a story the market is telling itself. It is not a forecast, rating or advice."}

    def _headlines(self, theme: dict) -> list[dict]:
        seen, out = set(), []
        for kw in theme["keywords"]:
            try:
                for it in self.news.items(q=kw, hours=48, limit=20)["items"]:
                    key = (it.get("title") or "").strip().lower()
                    if key and key not in seen:
                        seen.add(key)
                        out.append({"title": it["title"], "link": it.get("link"), "feed": it.get("feed"), "published": it.get("published")})
            except Exception:  # noqa: BLE001  a news problem must not stop the narrative; the news score is then left out
                return None
        out.sort(key=lambda x: x["published"] or "", reverse=True)
        return out

    def recent_ids(self, before: str, n: int = HISTORY_DAYS) -> list[str]:
        """Themes featured on the n calendar days before `before` (not simply the last n saved rows: a gap of a week means nothing is recent)."""
        cut = (date.fromisoformat(before) - timedelta(days=n)).isoformat()
        return [r["theme"] for r in self.db.q("SELECT theme FROM narrative_runs WHERE asof >= ? AND asof < ? ORDER BY asof DESC", (cut, before))]

    def history(self, limit: int = 30) -> list[dict]:
        return [{"asof": r["asof"], "theme": r["theme"], "name": json.loads(r["payload"])["name"], "score": json.loads(r["payload"])["score"]} for r in self.db.q("SELECT asof,theme,payload FROM narrative_runs ORDER BY asof DESC LIMIT ?", (limit,))]

    async def today(self, refresh: bool = False, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        day = now.date().isoformat()
        async with self._lock:
            row = self.db.q("SELECT payload FROM narrative_runs WHERE asof=?", (day,))
            if row and not refresh:
                return json.loads(row[0]["payload"])
            run = await self._build(now)
            if run.get("theme"):
                self.db.x("INSERT INTO narrative_runs(asof,created_at,theme,payload) VALUES(?,?,?,?) ON CONFLICT(asof) DO UPDATE SET created_at=excluded.created_at, theme=excluded.theme, payload=excluded.payload",
                          (day, now.isoformat(), run["theme"], json.dumps(run)))
            return run

    async def _build(self, now: datetime) -> dict:
        day = now.date().isoformat()
        base = {"asof": day, "created_at": now.isoformat(), "demo": self.demo, "method": self.method(), "theme": None,
                "disclaimer": "A theme the market is paying attention to, found by fixed rules. Not a recommendation, rating or prediction. Themes that run hot are volatile and often reverse.",
                "gaps": ["Baskets are fixed hand-picked lists of liquid US-listed stocks, not every company in a theme.", "Prices are delayed daily bars (Yahoo Finance, unofficial). Volume is the latest bar, which may be a partial day.",
                         "Headline counts only include the RSS feeds you follow in News, so a quiet feed list understates attention.", "Theme context and risk notes are written by hand, not computed."]}
        syms = sorted({s for t in THEMES for s in t["tickers"]} | {BENCH})
        batch = await self.bars.fetch(syms)
        base["notes"] = list(batch.notes)
        base["data"] = {"prices": batch.provider, "prices_status": str(getattr(batch.status, "value", batch.status)), "prices_as_of": batch.as_of.isoformat() if batch.as_of else None}
        feats = {s: feat.compute(s, batch.bars[s], batch.bars.get(BENCH)) for s in syms if s in batch.bars and s != BENCH}
        bench = feat.compute(BENCH, batch.bars[BENCH]) if BENCH in batch.bars else None
        scored, heads = [], {}
        for t in THEMES:
            h = self._headlines(t)
            heads[t["id"]] = h
            m = theme_metrics(t, feats, bench, None if h is None else len(h))
            if m:
                scored.append((t["id"], m))
        if not scored:
            base["notes"].append("No theme had enough price data today, so no narrative was chosen.")
            return base
        recent = self.recent_ids(day)
        win_id, win = pick(scored, recent)
        t = next(x for x in THEMES if x["id"] == win_id)
        basket = []
        for s in t["tickers"]:
            f = feats.get(s)
            basket.append({"symbol": s, "available": bool(f and f.get("sufficient")),
                           **({} if not (f and f.get("sufficient")) else {"price": f["price"], "change_1d_pct": f["change_pct"], "return_5d_pct": f["ret_5d"], "return_1m_pct": f["ret_21d"], "above_50d": f["above_sma50"], "volume_vs_normal": f["rvol"], "last_bar": f["last_bar_date"]})})
        order = sorted(scored, key=lambda x: (-x[1]["score"], x[0]))
        why = [f"The {t['name']} basket returned a median {win['facts']['median_return_1m_pct']:+.1f}% over about a month" + (f", versus {win['facts']['spy_return_1m_pct']:+.1f}% for the S&P 500 (SPY)." if win["facts"]["spy_return_1m_pct"] is not None else "."),
               f"{round((win['facts']['share_above_50d'] or 0) * 100)}% of its stocks trade above their 50-day average." if win["facts"]["share_above_50d"] is not None else None,
               f"Volume is running at a median {win['facts']['median_volume_vs_normal']:.1f}x normal." if win["facts"]["median_volume_vs_normal"] is not None else None,
               f"{win['facts']['headlines_48h']} headline{'' if win['facts']['headlines_48h'] == 1 else 's'} in the last 48 hours from your news feeds mention it." if win["facts"]["headlines_48h"] is not None else "Headline counts were not available, so news was left out of the score."]
        base.update({"theme": win_id, "name": t["name"], "score": win["score"], "parts": win["parts"], "facts": win["facts"], "context": t["context"], "context_note": "Written by hand to explain the theme. It is not live data.",
                     "why_now": [w for w in why if w], "basket": basket, "headlines": (heads.get(win_id) or [])[:6], "risks": t["risks"],
                     "volatility_note": f"This basket's typical daily range is about {win['facts']['median_daily_range_pct']:.1f}% (average true range), so single-day moves of several percent are normal.",
                     "recent_excluded": recent, "runners_up": [{"theme": i, "name": next(x["name"] for x in THEMES if x["id"] == i), "score": m["score"], "relative_1m_pct": m["facts"]["relative_1m_pct"]} for i, m in order if i != win_id][:4],
                     "all_themes": [{"theme": i, "name": next(x["name"] for x in THEMES if x["id"] == i), "score": m["score"], "recently_featured": i in recent} for i, m in order]})
        if recent and win_id != order[0][0]:
            base["notes"].append(f"{next(x['name'] for x in THEMES if x['id'] == order[0][0])} scored highest but was featured in the last {HISTORY_DAYS} days, so the next theme is shown.")
        return base
