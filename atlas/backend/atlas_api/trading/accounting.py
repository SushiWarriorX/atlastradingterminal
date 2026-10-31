"""Average-cost position accounting in Decimal. Buy fees are capitalised into cost; sell fees reduce proceeds.
No short selling in paper v1: selling more than held raises."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .money import ZERO


class AccountingError(ValueError):
    pass


@dataclass(frozen=True)
class Position:
    qty: Decimal = ZERO
    avg_cost: Decimal = ZERO     # per unit, including capitalised buy fees
    realized: Decimal = ZERO


def apply_fill(pos: Position, cash: Decimal, side: str, qty: Decimal, price: Decimal, fee: Decimal) -> tuple[Position, Decimal]:
    if qty <= 0 or price <= 0 or fee < 0:
        raise AccountingError("qty and price must be positive and fee non-negative")
    if side == "buy":
        cost = qty * price + fee
        if cost > cash:
            raise AccountingError(f"insufficient cash: need {cost}, have {cash}")
        new_qty = pos.qty + qty
        avg = (pos.qty * pos.avg_cost + cost) / new_qty
        return Position(new_qty, avg, pos.realized), cash - cost
    if qty > pos.qty:
        raise AccountingError(f"cannot sell {qty}: only {pos.qty} held (short selling is not supported)")
    proceeds = qty * price - fee
    realized = pos.realized + proceeds - qty * pos.avg_cost
    left = pos.qty - qty
    return Position(left, pos.avg_cost if left > 0 else ZERO, realized), cash + proceeds
