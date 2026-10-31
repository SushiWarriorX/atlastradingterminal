"""Paper-fill simulation (pure). Decides whether and how an open order fills against the latest quote.

Documented simplifications (see docs/known-limitations.md): quotes are polled, not streamed, so intra-poll price paths, queue
position and hidden liquidity are not modelled. Stops trigger on the last price at poll time, so a gap fills at the then-current
market (stop gap risk is therefore represented, not hidden). Reported volume (24h for crypto, day-to-date for equities) caps
each evaluation's fill to `participation_pct`, which produces partial fills for large orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..models import Quote
from .models import SimParams
from .money import ZERO, D, floor_to, q

CRYPTO_MIN_QTY = Decimal("0.00001")


@dataclass
class Decision:
    qty: Decimal
    price: Decimal
    fee: Decimal
    note: str
    triggered: bool = False       # stop (or stop-limit) condition met during this evaluation


def class_of(asset_class: str) -> str:
    return "crypto" if asset_class == "crypto" else "equity"


def book(quote: Quote, asset_class: str, p: SimParams) -> tuple[Decimal, Decimal, bool]:
    """(bid, ask, quoted). Without a real bid/ask, an assumed symmetrical spread around last is used and flagged."""
    last = D(quote.price)
    if quote.bid is not None and quote.ask is not None and quote.ask >= quote.bid > 0:
        return D(quote.bid), D(quote.ask), True
    h = D(p.assumed_half_spread_bps[class_of(asset_class)]) / Decimal(10_000)
    return last * (1 - h), last * (1 + h), False


def slip(price: Decimal, side: str, bps: float) -> Decimal:
    f = D(bps) / Decimal(10_000)
    return price * (1 + f) if side == "buy" else price * (1 - f)


def fee_for(asset_class: str, qty: Decimal, price: Decimal, p: SimParams) -> Decimal:
    if class_of(asset_class) == "crypto":
        return q(qty * price * D(p.crypto_taker_fee_pct) / Decimal(100), 8)
    return q(qty * D(p.equity_per_share_fee), 8)


def reference_price(quote: Quote, side: str, asset_class: str, p: SimParams) -> Decimal:
    """What a marketable order would pay/receive before slippage (ask for buys, bid for sells)."""
    bid, ask, _ = book(quote, asset_class, p)
    return ask if side == "buy" else bid


def _cap_qty(remaining: Decimal, quote: Quote, asset_class: str, p: SimParams, allow_fractional: bool) -> Decimal:
    qty = remaining
    if quote.volume:
        cap = D(quote.volume) * D(p.participation_pct) / Decimal(100)
        qty = min(qty, cap)
    if class_of(asset_class) == "crypto":
        qty = floor_to(qty, 8)
        return qty if qty >= CRYPTO_MIN_QTY else ZERO
    if not allow_fractional:
        qty = floor_to(qty, 0)
    return qty if qty > 0 else ZERO


def decide(order: dict, quote: Quote, asset_class: str, p: SimParams, allow_fractional: bool = False) -> Decision | None:
    """order: dict with side, type, qty_remaining, limit_price, stop_price, triggered (Decimals/None)."""
    side, typ = order["side"], order["type"]
    last = D(quote.price)
    bid, ask, quoted = book(quote, asset_class, p)
    lim, stp = order.get("limit_price"), order.get("stop_price")
    triggered = bool(order.get("triggered"))
    newly = False
    if typ in ("stop", "stop_limit") and not triggered:
        hit = last >= stp if side == "buy" else last <= stp
        if not hit:
            return None
        triggered = newly = True
    bps = p.slippage_bps[class_of(asset_class)]
    note = "" if quoted else "no bid/ask in quote: assumed spread used; "
    if typ == "market" or (typ == "stop" and triggered):
        price = slip(ask if side == "buy" else bid, side, bps)
        note += "market fill at " + ("ask" if side == "buy" else "bid") + f" + {bps:g}bp slippage"
        if typ == "stop":
            note += f"; stop {stp} triggered, filled at the then-current market (gap risk is real)"
    else:   # limit, or stop_limit after its trigger
        marketable = ask <= lim if side == "buy" else bid >= lim
        if marketable:
            price = min(lim, ask) if side == "buy" else max(lim, bid)
            note += "marketable limit: filled at the better of limit and book"
        else:
            through = last < lim if side == "buy" else last > lim
            touched = last <= lim if side == "buy" else last >= lim
            if not (through if p.conservative_limit_fills else touched):
                return Decision(ZERO, ZERO, ZERO, "", triggered=newly) if newly else None
            price = lim
            note += "passive limit filled at the limit after price traded " + ("through" if p.conservative_limit_fills else "to") + " it"
    qty = _cap_qty(order["qty_remaining"], quote, asset_class, p, allow_fractional)
    if qty <= 0:
        return Decision(ZERO, ZERO, ZERO, "fill below minimum lot at the participation cap", triggered=newly) if newly else None
    if qty < order["qty_remaining"]:
        note += f"; partial fill capped at {p.participation_pct:g}% of reported volume"
    price = q(price, 8)
    return Decision(qty, price, fee_for(asset_class, qty, price, p), note, triggered=newly)
