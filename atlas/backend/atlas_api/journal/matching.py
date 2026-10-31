"""FIFO round-trip construction from raw executions (pure, Decimal).

A TRADE is one lifecycle of a position in one symbol of one source: flat -> ... -> flat. Scaling in/out stays inside one trade. A fill that
crosses through zero is split: the closing part ends the trade, the remainder opens the next one (fee prorated by quantity).
Realized P&L is FIFO lot matching (a different, equally valid convention from the paper engine's average cost; they agree on single-lot trades).
Shorts are supported (perps). Fees of every execution in the lifecycle are charged to the trade; funding payments are attributed to the
trade that was open at that moment.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from ..trading.money import ZERO


@dataclass(frozen=True)
class Exec:
    source: str
    ext_id: str
    ts: datetime
    symbol: str
    asset_class: str
    side: str                 # buy | sell
    qty: Decimal              # positive
    price: Decimal
    fee: Decimal = ZERO       # cost, positive
    kind: str = "trade"       # trade | liquidation | settlement
    currency: str = "USD"
    multiplier: Decimal = Decimal(1)
    instrument_id: str | None = None


@dataclass(frozen=True)
class Flow:
    source: str
    ext_id: str
    ts: datetime
    symbol: str | None
    kind: str                 # funding | fee | transfer | other
    amount: Decimal           # signed: positive = credit to the account
    currency: str = "USD"


@dataclass
class Trade:
    key: str
    source: str
    symbol: str
    asset_class: str
    side: str                          # long | short (direction of the opening fill)
    currency: str
    multiplier: Decimal
    opened_at: datetime
    closed_at: datetime | None = None
    qty_max: Decimal = ZERO
    qty_open: Decimal = ZERO
    entry_cost: Decimal = ZERO         # sum(qty*price) over opening fills
    entry_qty: Decimal = ZERO
    exit_value: Decimal = ZERO
    exit_qty: Decimal = ZERO
    gross_pnl: Decimal = ZERO
    fees: Decimal = ZERO
    funding: Decimal = ZERO
    liquidated: bool = False
    exec_ids: list[str] = field(default_factory=list)
    instrument_id: str | None = None

    @property
    def status(self) -> str:
        return "closed" if self.closed_at is not None else "open"

    @property
    def net_pnl(self) -> Decimal:
        return self.gross_pnl - self.fees + self.funding

    @property
    def entry_avg(self) -> Decimal | None:
        return self.entry_cost / self.entry_qty if self.entry_qty else None

    @property
    def exit_avg(self) -> Decimal | None:
        return self.exit_value / self.exit_qty if self.exit_qty else None

    @property
    def holding_seconds(self) -> float | None:
        return (self.closed_at - self.opened_at).total_seconds() if self.closed_at else None


def build_trades(executions: list[Exec], flows: list[Flow] | None = None) -> tuple[list[Trade], list[Flow]]:
    """Returns (trades ordered by open time, unattributed flows)."""
    trades: list[Trade] = []
    groups: dict[tuple[str, str], list[Exec]] = {}
    for e in executions:
        if e.qty <= 0 or e.price < 0:
            raise ValueError(f"invalid execution {e.source}/{e.ext_id}: qty must be positive and price non-negative")
        groups.setdefault((e.source, e.symbol), []).append(e)
    for (source, symbol), evs in groups.items():
        lots: deque[list] = deque()          # [qty_remaining, price], all lots share the same direction
        direction = 0                         # +1 long, -1 short, 0 flat
        cur: Trade | None = None
        for e in sorted(evs, key=lambda x: (x.ts, x.ext_id)):
            sign = 1 if e.side == "buy" else -1
            remaining = e.qty
            while remaining > 0:
                if cur is None:
                    direction = sign
                    cur = Trade(key=f"{source}|{symbol}|{e.ext_id}", source=source, symbol=symbol, asset_class=e.asset_class,
                                side="long" if sign == 1 else "short", currency=e.currency, multiplier=e.multiplier, opened_at=e.ts,
                                instrument_id=e.instrument_id)
                    trades.append(cur)
                part = remaining
                fee_part = e.fee * part / e.qty
                if sign == direction:                                   # opening / scaling in
                    lots.append([part, e.price])
                    cur.entry_cost += part * e.price
                    cur.entry_qty += part
                    cur.qty_open += part
                    cur.qty_max = max(cur.qty_max, cur.qty_open)
                else:                                                   # reducing / closing (FIFO)
                    part = min(remaining, cur.qty_open)
                    fee_part = e.fee * part / e.qty
                    need = part
                    while need > 0:
                        lot = lots[0]
                        take = min(need, lot[0])
                        cur.gross_pnl += (e.price - lot[1]) * take * direction * cur.multiplier
                        lot[0] -= take
                        need -= take
                        if lot[0] == 0:
                            lots.popleft()
                    cur.exit_value += part * e.price
                    cur.exit_qty += part
                    cur.qty_open -= part
                cur.fees += fee_part
                if e.ext_id not in cur.exec_ids:
                    cur.exec_ids.append(e.ext_id)
                if e.kind == "liquidation":
                    cur.liquidated = True
                remaining -= part
                if cur.qty_open == 0:
                    cur.closed_at = e.ts
                    cur, direction = None, 0
    trades.sort(key=lambda t: (t.opened_at, t.key))
    leftover: list[Flow] = []
    now_far = datetime.max.replace(tzinfo=executions[0].ts.tzinfo) if executions else None
    for f in flows or []:
        owner = None
        if f.symbol is not None:
            for t in trades:
                if t.source == f.source and t.symbol == f.symbol and t.opened_at <= f.ts <= (t.closed_at or now_far):
                    owner = t
                    break
        if owner is None or f.kind == "transfer":
            leftover.append(f)
        elif f.kind == "fee":
            owner.fees -= f.amount           # a negative amount is a cost; a positive one (rebate) reduces fees
        else:
            owner.funding += f.amount
    return trades, leftover
