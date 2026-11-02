"""The Signal service: one object the API routes talk to. It owns the asset registry, the watchlist, market summaries and the research orchestrator, and
reuses the app's market service, news, fundamentals, macro and Fed Watch services (so provenance, caching and provider fallbacks are shared with the terminal)."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

from ..db import DB
from ..models import ProviderUnavailable
from . import fmt
from .agents.common import Ctx
from .agents.fundamentals import FundamentalsAgent
from .agents.macro import MacroAgent
from .agents.news import NewsAgent
from .agents.technical import TechnicalAgent
from .assets import Asset, AssetRegistry
from .cryptodata import CoinGeckoClient, MempoolClient
from .etf import YahooEtfData
from .models import AGENTS
from .orchestrator import Orchestrator
from .summary import MarketSummary, ROW_TIMEOUT, SummaryError, prov_dict
from .watchlist import WatchlistError, WatchlistStore


class SignalError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


ERRORS = (SignalError, WatchlistError, SummaryError)


class SignalService:
    def __init__(self, *, db: DB, svc, news, fundamentals, macro, fedwatch, demo: bool, llm=None, registry: AssetRegistry | None = None, etf=None, coingecko=None, mempool=None):
        self.demo, self.svc = demo, svc
        self.registry = registry or AssetRegistry(demo=demo)
        self.store = WatchlistStore(db)
        self.summary = MarketSummary(svc)
        self._parts = dict(news=news, fundamentals=fundamentals, macro=macro, fedwatch=fedwatch, etf=etf or YahooEtfData(),
                           coingecko=coingecko if coingecko is not None else (None if demo else CoinGeckoClient(api_key=os.getenv("COINGECKO_API_KEY") or None)),
                           mempool=mempool if mempool is not None else (None if demo else MempoolClient()))
        explainer = None
        if llm is not None and os.getenv("ATLAS_SIGNAL_AI") == "1":
            from .explain import Explainer
            explainer = Explainer(llm)
        self.explainer = explainer
        agents = {"news": NewsAgent(), "technical": TechnicalAgent(), "macro": MacroAgent(), "fundamentals": FundamentalsAgent()}
        self.orch = Orchestrator(agents, self._ctx, demo=demo, explainer=explainer)

    def _ctx(self, asset: Asset) -> Ctx:
        return Ctx(asset=asset, svc=self.svc, summary=self.summary, registry=self.registry, demo=self.demo, **self._parts)

    async def _asset(self, asset_id: str) -> Asset:
        a = await self.registry.get(asset_id)
        if a is None:
            raise SignalError("UNKNOWN_ASSET", "That asset id is not recognised. Search for the asset and use the id from the results.", 404)
        return a

    # --- meta and search ------------------------------------------------------------------------------------------------------------------------
    def meta(self) -> dict:
        return {"service": "signal", "version": 1, "demo": self.demo, "agents": list(AGENTS),
                "ai": {"enabled": self.explainer is not None, "model": getattr(self.explainer.llm, "model", None) if self.explainer else None,
                       "note": "AI wording is optional, validated, and never supplies figures." if self.explainer else "Off: summaries are rule-based."},
                "coverage": {"crypto": "Large tokens that trade against USD on Coinbase (hand-entered list, checked against Coinbase's product list when reachable).",
                             "stocks_etfs": "ATLAS catalog plus the Nasdaq Trader US-listed directory when it can be loaded; other tickers are shown as unverified."},
                "directory": {"loaded": self.registry.directory_loaded, "error": self.registry.directory_error},
                "live_trading": False, "notes": ["Research and paper trading only. Nothing in this service places or authorises an order."]}

    async def search(self, q: str, limit: int = 20) -> dict:
        return await self.registry.search(q, max(1, min(limit, 40)))

    # --- watchlist ------------------------------------------------------------------------------------------------------------------------------
    async def watchlist(self) -> dict:
        saved = self.store.list()

        async def one(item: dict) -> dict:
            a = await self.registry.get(item["asset_id"])
            pub = a.public() if a else {"id": item["asset_id"], "support": "unverified", "note": None}
            pub.update(symbol=item["symbol"], name=item["name"], type=item["asset_type"], venue=item["venue"])
            if a is None:
                return {"asset": pub, "quote": None, "spark": None, "takeaway": None, "error": {"code": "UNKNOWN_ASSET", "message": "This saved asset id is no longer recognised."}}
            try:
                row = await asyncio.wait_for(self.summary.row(a), ROW_TIMEOUT)
            except asyncio.TimeoutError:
                row = {"asset": pub, "quote": None, "spark": None, "takeaway": None, "error": {"code": "TIMEOUT", "message": "The data provider took too long."}}
            row["asset"] = pub
            return row
        rows = await asyncio.gather(*(one(i) for i in saved))
        return {"items": list(rows), "count": len(rows), "demo": self.demo, "as_of": datetime.now(timezone.utc).isoformat()}

    async def add(self, asset_id: str) -> dict:
        a = await self._asset(asset_id)
        if asset_id not in self.registry._by_id:                      # an unverified ticker: only if it really has a price
            if self.demo:
                raise SignalError("UNSUPPORTED_IN_DEMO", "Demo mode only supports the assets in the built-in list.", 422)
            try:
                await self.svc.quote(a.inst)
            except ProviderUnavailable as e:
                raise SignalError("NO_DATA", f"No price could be found for {a.symbol} ({e.message[:80]}), so it was not added.", 422) from None
        added = self.store.add(a)
        return {"added": added, "id": a.id, "ids": self.store.ids()}

    def remove(self, asset_id: str) -> dict:
        removed = self.store.remove(asset_id)
        return {"removed": removed, "id": asset_id, "ids": self.store.ids()}

    def reorder(self, ids: list[str]) -> dict:
        self.store.reorder(ids)
        return {"ids": self.store.ids()}

    # --- asset screen ---------------------------------------------------------------------------------------------------------------------------
    async def chart(self, asset_id: str, rng: str) -> dict:
        return await self.summary.chart(await self._asset(asset_id), rng)

    async def asset_header(self, asset_id: str) -> dict:
        a = await self._asset(asset_id)
        row = await self.summary.row(a)
        row["saved"] = asset_id in self.store.ids()
        return row

    async def research(self, asset_id: str, wait: float = 6.0) -> dict:
        a = await self._asset(asset_id)
        return await self.orch.research(a, max(0.0, min(wait, 25.0)))

    async def refresh(self, asset_id: str, agent: str) -> dict:
        return await self.orch.refresh(await self._asset(asset_id), agent)
