"""Pre-trade risk checks (pure). Limits are enforced here in code; nothing depends on an AI prompt.

Verdicts mirror the spec's Risk Agent wording. APPROVE_FOR_PAPER_REVIEW is not an authorization for live trading
(there is no live path), only permission to submit a PAPER order after the user's explicit confirmation.
Statuses: pass | warn | fail | needs_data | not_checked (informational, cannot be evaluated yet).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..models import DataStatus, Quote
from .models import OrderIn, RiskLimits, SimParams
from .money import ZERO, D, q
from .sim import CRYPTO_MIN_QTY, book, class_of, reference_price, slip

HUNDRED = Decimal(100)


@dataclass
class RiskContext:
    limits: RiskLimits
    sim: SimParams
    halted: bool
    asset_class: str
    tradable: bool
    symbol: str
    quote: Quote | None
    session: str | None                 # equity session state, None for crypto
    equity: Decimal
    cash_available: Decimal             # cash minus cash reserved by working buy orders
    sellable_qty: Decimal               # held minus qty reserved by working sell orders
    position_value: Decimal             # current value of this instrument (0 if none)
    other_planned_risk: Decimal         # quantified stop-based risk of existing positions, in currency
    unquantified_positions: int         # held positions with no planned stop
    day_start_equity: Decimal | None
    duplicate_working: int
    valuation_note: str | None = None
    venue: str = "sim"
    venue_block: str | None = None      # set when the destination cannot take this order (e.g. crypto on IBKR)


def entry_estimate(order: OrderIn, quote: Quote, asset_class: str, p: SimParams) -> Decimal:
    """Per-unit price the order is expected to trade at (worst case for the account). Used for sizing and cost checks."""
    bps = p.slippage_bps[class_of(asset_class)]
    ref = reference_price(quote, order.side, asset_class, p)
    if order.type == "market":
        return slip(ref, order.side, bps)
    if order.type in ("limit", "stop_limit"):
        return order.limit_price
    return slip(max(order.stop_price, ref) if order.side == "buy" else min(order.stop_price, ref), order.side, bps)


def _c(name: str, status: str, detail: str) -> dict:
    return {"name": name, "status": status, "detail": detail}


def check(order: OrderIn, ctx: RiskContext, fee_fn) -> dict:
    L, cls, buy = ctx.limits, class_of(ctx.asset_class), order.side == "buy"
    out: list[dict] = []
    add = lambda *a: out.append(_c(*a))
    add("environment", "pass", "PAPER only. Live trading is disabled and no live order path exists.")

    add("kill_switch", "fail" if ctx.halted else "pass", "Trading is HALTED by the kill switch." if ctx.halted else "Trading is enabled.")
    if ctx.venue_block:
        add("venue", "fail", f"Cannot route this order: {ctx.venue_block}.")
    elif ctx.venue == "ibkr":
        add("venue", "pass", "Routed to your IBKR PAPER account (orders are placed there; fills come from IBKR, not the simulator).")

    if not ctx.tradable:
        add("instrument", "fail", f"{ctx.symbol} is not a tradable instrument (index or macro series).")
    elif ctx.symbol in {s.upper() for s in L.blocked_symbols}:
        add("instrument", "fail", f"{ctx.symbol} is on the blocked-symbol list.")
    else:
        add("instrument", "pass", f"{ctx.symbol} ({ctx.asset_class}) is tradable.")

    st = ctx.quote.prov.status if ctx.quote else None
    if ctx.quote is None or st in (DataStatus.STALE, DataStatus.UNAVAILABLE):
        add("data_fresh", "needs_data", f"No fresh price ({st.value if st else 'no quote'}); cannot size or simulate a fill.")
    elif st == DataStatus.DELAYED:
        add("data_fresh", "warn", "Price data is DELAYED: fills and cost estimates are indicative only.")
    elif st == DataStatus.DEMO:
        add("data_fresh", "warn", "Price data is SYNTHETIC (demo mode): not market data.")
    elif st == DataStatus.HISTORICAL:
        add("data_fresh", "warn", "Market closed: price is the last session's. Orders will wait for the open.")
    else:
        add("data_fresh", "pass", f"Price is {st.value}.")

    if ctx.asset_class == "crypto":
        add("market_session", "pass", "Crypto trades 24/7.")
    elif ctx.session == "REGULAR":
        add("market_session", "pass", "US regular session is open.")
    elif order.type == "market":
        add("market_session", "fail", f"US market is {ctx.session}: a market order would gap at the open. Use a limit order or wait.")
    else:
        add("market_session", "warn", f"US market is {ctx.session}: the order will queue until the regular session (extended hours are not simulated).")

    qty = order.qty
    if cls == "crypto":
        ok_qty = qty >= CRYPTO_MIN_QTY and qty == q(qty, 8)
        add("quantity", "pass" if ok_qty else "fail", "Quantity OK." if ok_qty else f"Crypto quantity must be >= {CRYPTO_MIN_QTY} with at most 8 decimals.")
    else:
        whole = qty == qty.to_integral_value()
        ok_qty = whole or L.allow_fractional_equities
        add("quantity", "pass" if ok_qty else "fail", "Quantity OK." if ok_qty else "Equities trade in whole shares (fractional shares are disabled in risk limits).")

    est = entry_estimate(order, ctx.quote, ctx.asset_class, ctx.sim) if ctx.quote else None
    fee = fee_fn(qty, est) if est else ZERO
    notional = qty * est if est else None

    if ctx.quote is not None:
        bid, ask, quoted = book(ctx.quote, ctx.asset_class, ctx.sim)
        if quoted:
            bps = (ask - bid) / ((ask + bid) / 2) * 10_000
            cap = D(L.max_spread_bps[cls])
            add("spread", "fail" if bps > cap else "pass", f"Spread {bps:.1f} bp vs limit {cap:g} bp.")
        else:
            add("spread", "not_checked", "The quote has no bid/ask (e.g. Yahoo data): spread cannot be verified; a small spread is assumed in simulation.")
    else:
        add("spread", "needs_data", "No quote.")

    if not buy:
        ok_sell = ctx.sellable_qty >= qty
        add("position_available", "pass" if ok_sell else "fail",
            f"Selling {qty} of {ctx.sellable_qty} available." if ok_sell else f"Only {ctx.sellable_qty} available to sell (short selling is not supported).")
    else:
        if est is None:
            add("buying_power", "needs_data", "Cannot estimate cost without a price.")
        else:
            need = notional + fee
            ok_bp = need <= ctx.cash_available
            add("buying_power", "pass" if ok_bp else "fail",
                f"Estimated cost {q(need, 2)} vs available cash {q(ctx.cash_available, 2)} (no leverage/margin).")
            if ctx.equity > 0:
                post = (ctx.position_value + notional) / ctx.equity * HUNDRED
                cap = D(L.max_position_pct)
                add("position_cap", "pass" if post <= cap else "fail", f"Position would be {q(post, 1)}% of equity vs cap {cap:g}%.")
            else:
                add("position_cap", "needs_data", "Account equity is not positive.")
            if L.max_order_notional is not None:
                cap_n = D(L.max_order_notional)
                add("order_notional", "pass" if notional <= cap_n else "fail", f"Order notional {q(notional, 2)} vs cap {cap_n:g}.")

        # planned (stop-based) risk: only for orders that ADD exposure
        if order.planned_stop is None:
            add("risk_per_trade", "needs_data" if L.require_stop else "not_checked",
                "No planned stop/invalidation level: stop-based risk cannot be computed." + (" A stop is required by the risk limits." if L.require_stop else ""))
            add("aggregate_risk", "needs_data" if L.require_stop else "not_checked", "Aggregate planned risk needs this trade's stop.")
        elif est is not None and ctx.equity > 0:
            if order.planned_stop >= est:
                add("risk_per_trade", "fail", f"For a long, the stop ({order.planned_stop}) must be below the entry estimate ({q(est, 4)}).")
                add("aggregate_risk", "not_checked", "Skipped: invalid stop.")
            else:
                risk = qty * (est - order.planned_stop) + fee
                pct = risk / ctx.equity * HUNDRED
                cap = D(L.max_risk_per_trade_pct)
                add("risk_per_trade", "pass" if pct <= cap else "fail",
                    f"Planned risk {q(risk, 2)} = {q(pct, 2)}% of equity vs {cap:g}% limit. A stop does not cap the real loss: gaps and slippage can exceed it.")
                agg = (ctx.other_planned_risk + risk) / ctx.equity * HUNDRED
                acap = D(L.max_aggregate_risk_pct)
                add("aggregate_risk", "pass" if agg <= acap else "fail", f"Aggregate planned risk {q(agg, 2)}% vs {acap:g}% limit.")
                if ctx.unquantified_positions:
                    add("aggregate_risk_coverage", "warn", f"{ctx.unquantified_positions} existing position(s) have no planned stop: aggregate risk is UNDERSTATED.")

        if ctx.day_start_equity and ctx.day_start_equity > 0:
            loss = (ctx.day_start_equity - ctx.equity) / ctx.day_start_equity * HUNDRED
            if loss >= D(L.max_daily_loss_pct):
                add("daily_loss", "fail", f"Day loss {q(loss, 2)}% reached the {L.max_daily_loss_pct:g}% limit: new risk-increasing orders are blocked (exits are allowed).")
            elif loss >= D(L.daily_loss_warning_pct):
                add("daily_loss", "warn", f"Day loss {q(loss, 2)}% is past the {L.daily_loss_warning_pct:g}% warning level.")
            else:
                add("daily_loss", "pass", f"Day P&L {q(-loss, 2)}%.")
        else:
            add("daily_loss", "not_checked", "No start-of-day equity recorded yet.")

    add("event_risk", "not_checked", "No economic-calendar integration yet: scheduled events (CPI, FOMC, earnings) are NOT checked.")
    add("duplicate", "warn" if ctx.duplicate_working else "pass",
        f"{ctx.duplicate_working} identical working order(s) exist: possible duplicate." if ctx.duplicate_working else "No identical working order. Retries are also protected by an idempotency key.")
    if ctx.valuation_note:
        add("valuation", "warn", ctx.valuation_note)
    add("confirmation", "pass", "Explicit confirmation is required: the order is only submitted with a valid preview id.")

    if any(c["status"] == "fail" for c in out):
        verdict = "REJECT"
    elif any(c["status"] == "needs_data" for c in out):
        verdict = "NEEDS_MORE_DATA"
    else:
        verdict = "APPROVE_FOR_PAPER_REVIEW"
    return {"verdict": verdict, "checks": out, "estimate": {"price": est, "notional": notional, "fee": fee},
            "disclaimer": "Approval for paper review is not authorization for live trading. Stop-based risk is planned risk, not worst-case loss."}
