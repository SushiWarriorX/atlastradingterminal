from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from ...models import DataStatus
from ..assets import Asset
from ..models import AGENT_TITLES, Fact, Finding, Source

PROVIDER_LABEL = {"yahoo": "Yahoo Finance (unofficial)", "coinbase": "Coinbase Exchange", "ibkr": "Interactive Brokers", "demo": "Demo data (synthetic, not real)",
                  "fred": "FRED (St. Louis Fed)"}
DEMO_SOURCE = "Demo fixture (synthetic, not real)"


@dataclass
class Ctx:
    """Everything an agent may use. Agents only read; none of these services can place an order."""
    asset: Asset
    svc: object                 # MarketService
    summary: object             # MarketSummary
    news: object                # NewsService
    fundamentals: object        # FundamentalsService
    macro: object               # MacroService
    fedwatch: object            # FedWatchService
    etf: object                 # YahooEtfData
    coingecko: object | None
    mempool: object | None
    registry: object | None = None
    demo: bool = False
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class Agent(Protocol):
    name: str

    async def run(self, ctx: Ctx) -> Finding: ...


def iso(dt: datetime | None) -> str | None:
    return None if dt is None else dt.astimezone(timezone.utc).isoformat()


def provider_source(prov, demo: bool = False) -> Source:
    name = PROVIDER_LABEL.get(prov.provider, prov.provider)
    return Source(name=name, kind="data", as_of=iso(prov.event_time), status=prov.status.value,
                  note="; ".join(prov.quality[:2]) or (f"delayed about {prov.delay_seconds // 60} min" if prov.delay_seconds else None))


def mk_fact(key: str, label: str, value, display: str, source: str, *, unit: str | None = None, as_of: str | None = None, timeframe: str | None = None,
            kind: str = "calculated") -> Fact:
    return Fact(key=key, label=label, value=value, display=display, unit=unit, as_of=as_of, source=source, timeframe=timeframe, kind=kind)


def unavailable(agent: str, reason: str, demo: bool = False, status: str = "unavailable", sources: list[Source] | None = None) -> Finding:
    from ..models import Missing
    title = AGENT_TITLES[agent]
    return Finding(agent=agent, status=status, takeaway=f"{title} analysis is not available right now." if status == "unavailable" else reason, error=reason[:200],
                   missing=[Missing(what=f"{title} analysis", why=reason[:200])], sources=sources or [], demo=demo)


def status_of(prov_status: DataStatus | str) -> str:
    return prov_status.value if isinstance(prov_status, DataStatus) else str(prov_status)


def ago(now: datetime, then: datetime | None) -> str:
    if then is None:
        return "unknown time"
    s = max(0, int((now - then).total_seconds()))
    if s < 90:
        return "just now"
    if s < 5400:
        return f"{s // 60}m ago"
    if s < 172800:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"
