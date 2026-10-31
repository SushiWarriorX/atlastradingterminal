"""Read-only tool registry with per-agent permissions. There is deliberately NO order/execution tool."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from .. import instruments as I
from ..models import ProviderUnavailable
from ..service import ALL_INTERVALS, MarketService
from ..sessions import session_state
from .. import mtf_service, technical


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    handler: Callable[[dict], Awaitable[dict]]
    agents: frozenset[str]


class ToolError(Exception):
    pass


class Registry:
    def __init__(self, svc: MarketService, journal=None, fundamentals=None):
        self.svc, self.journal, self.fundamentals = svc, journal, fundamentals
        sym = {"symbol": {"type": "string", "description": "Ticker or alias, e.g. BTC, AAPL, SPY, VIX"}}
        iv = {"interval": {"type": "string", "enum": ALL_INTERVALS}}
        both = frozenset({"desk", "technical"})
        self.tools = {t.name: t for t in [
            Tool("get_quote", "Latest quote with provenance (provider, venue, timestamps, LIVE/DELAYED/STALE status).",
                 {"type": "object", "properties": sym, "required": ["symbol"]}, self._quote, both),
            Tool("get_technical_features", "Deterministic indicators (RSI, ATR, MACD, Bollinger, RVOL, EMA/SMA), trend classification "
                 "and key levels with derivations for a symbol and interval, computed in code.",
                 {"type": "object", "properties": {**sym, **iv}, "required": ["symbol", "interval"]}, self._features, both),
            Tool("get_multi_timeframe", "Deterministic multi-timeframe analysis (1w, 1d, 4h, 1h, 15m): trend, swing structure, BOS/CHoCH events, RSI, MACD sign, "
                 "ATR%, RVOL, nearest support/resistance, an alignment verdict, and a transparent technical score with factor weights. Computed in code.",
                 {"type": "object", "properties": {**sym, "benchmark": {"type": "string", "description": "Optional relative-strength benchmark symbol, or 'none'"}},
                  "required": ["symbol"]}, self._mtf, both),
            Tool("get_journal_stats", "The user's own trading performance from their journal (closed trades only): summary statistics and breakdowns by setup, symbol, source, "
                 "side, time of day, holding time, R bucket and tags. Each group carries n and reliable. NEVER draw conclusions from groups with reliable=false (fewer than 30 trades): "
                 "say the sample is too small. Past results do not predict future results.",
                 {"type": "object", "properties": {"symbol": {"type": "string"}, "source": {"type": "string"}}}, self._journal, frozenset({"desk"})),
            Tool("get_fundamentals", "Company fundamentals for an equity or ETF: valuation, growth, margins, balance sheet, dividend and 52-week position, every ratio COMPUTED in code "
                 "from raw figures with its basis. Fields that could not be computed are listed in `missing` or `not_meaningful` (with the reason): never fill them in. "
                 "Data is unofficial and lags filings: check `financials_as_of` and `flags`. Not available for crypto or indices.",
                 {"type": "object", "properties": sym, "required": ["symbol"]}, self._fundamentals, frozenset({"desk"})),
            Tool("search_instruments", "Search the instrument catalog by symbol or name.",
                 {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}, self._search, frozenset({"desk"})),
            Tool("get_market_session", "US equity market session state (NYSE calendar).",
                 {"type": "object", "properties": {}}, self._session, frozenset({"desk"})),
        ]}

    def specs(self, agent: str) -> list[dict]:
        return [{"name": t.name, "description": t.description, "input_schema": t.schema}
                for t in self.tools.values() if agent in t.agents]

    async def call(self, agent: str, name: str, args: dict) -> dict:
        t = self.tools.get(name)
        if t is None or agent not in t.agents:
            raise ToolError(f"tool '{name}' not permitted for agent '{agent}'")
        try:
            return await t.handler(args or {})
        except ProviderUnavailable as e:
            return {"error": "DATA_UNAVAILABLE", "detail": str(e)}

    def _inst(self, args):
        inst = I.resolve(str(args.get("symbol", "")))
        if inst is None:
            raise ToolError(f"unknown symbol {args.get('symbol')!r}")
        return inst

    async def _quote(self, a):
        q = await self.svc.quote(self._inst(a))
        return {"source_id": f"{q.instrument_id}:quote", **q.model_dump(mode="json")}

    async def _features(self, a):
        inst = self._inst(a)
        interval = a.get("interval")
        if interval not in ALL_INTERVALS:
            raise ToolError(f"interval must be one of {ALL_INTERVALS}")
        o = await self.svc.ohlcv(inst, interval, 300)
        f = technical.features(o.candles, interval, equity_tz=inst.is_equity_like)
        return {"source_id": f"{inst.id}:features:{interval}", "instrument_id": inst.id, "data_status": o.prov.status.value,
                "provider": o.prov.provider, "as_of": o.prov.event_time.isoformat() if o.prov.event_time else None, **f}

    async def _mtf(self, a):
        inst = self._inst(a)
        b = a.get("benchmark")
        bench = I.resolve(b) if b and str(b).lower() != "none" else (I.by_symbol("SPY") if b is None and inst.is_equity_like and inst.symbol != "SPY" else None)
        if b and str(b).lower() != "none" and bench is None:
            raise ToolError(f"unknown benchmark {b!r}")
        m = await mtf_service.run_mtf(self.svc, inst, 3, bench)
        return {"source_id": f"{inst.id}:mtf", "instrument_id": inst.id, "as_of": m["as_of"], **mtf_service.compact(m)}

    async def _journal(self, a):
        if self.journal is None:
            return {"error": "DATA_UNAVAILABLE", "detail": "journal is not available"}
        from ..journal import stats as jstats
        closed = self.journal.trades(a.get("source"), "closed", a.get("symbol"))["trades"]
        r = jstats.analyze(closed)
        top = {g: rows[:6] for g, rows in r["groups"].items()}
        return {"source_id": "journal:stats", "currency": r["currency"], "excluded_currencies": r["excluded"], "summary": r["summary"],
                "groups": top, "caveats": r.get("caveats", []), "closed_trades": len(closed)}

    async def _fundamentals(self, a):
        if self.fundamentals is None:
            return {"error": "DATA_UNAVAILABLE", "detail": "fundamentals are not available"}
        inst = self._inst(a)
        f = await self.fundamentals.get(inst)
        return {"source_id": f"{inst.id}:fundamentals", "instrument_id": inst.id, "name": f["name"], "sector": f["sector"], "price": f["price"], "values": f["values"],
                "missing": f["missing"], "not_meaningful": f["not_meaningful"], "next_earnings_date": f["next_earnings_date"], "financials_as_of": f["financials_as_of"],
                "flags": f["flags"], "data_status": f["prov"]["status"], "provider": f["prov"]["provider"], "as_of": f["prov"]["fetched_at"]}

    async def _search(self, a):
        return {"results": [{"id": i.id, "symbol": i.symbol, "name": i.name, "asset_class": i.asset_class}
                            for i in I.search(str(a.get("query", "")), 8)]}

    async def _session(self, a):
        return session_state()
