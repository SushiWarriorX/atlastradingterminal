"""Single-asset BTC simulation with the costs that decide whether a strategy survives: fees, slippage, perpetual funding, leverage and liquidation.

Rules that keep it honest:
- A strategy decides at the CLOSE of bar i (target position -1, 0 or +1, using only bars up to i). The trade happens at the OPEN of bar i+1. No look-ahead.
- Every market fill pays slippage against the trade and a taker fee on the notional, per side.
- Stops are checked inside the bar: a gap through the stop fills at the open (worse than the stop), otherwise at the stop price plus slippage.
  If a stop and the liquidation price are both inside one bar the stop is assumed to hit first only when it is closer to the entry; otherwise liquidation.
- Perpetual positions pay (long) or receive (short) the funding that accrued during each bar, at that bar's notional. Spot has no funding and no shorting.
- Leverage multiplies the position size relative to account equity. Liquidation is approximated: when price touches entry * (1 -/+ (1/leverage - maintenance margin)) the
  account is wiped out. Exchanges differ in the exact formula; this errs on the harsh side.
Equity is marked to market at every close. Everything is deterministic: the same bars and settings always give the same result.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Costs:
    fee_bps: float = 5.0            # taker fee per side, basis points of notional
    slippage_bps: float = 5.0       # per side, applied against the trade
    leverage: float = 1.0           # position notional / equity; 1 for spot
    perp: bool = False              # perpetual swap (funding, shorting, liquidation) vs spot
    maint_margin: float = 0.0125    # maintenance margin used for the liquidation price (approximation)
    stop_pct: float | None = None   # protective stop, % from entry (None = no stop)


def simulate(t, o, h, l, c, target, costs: Costs, start: int, end: int, funding=None) -> dict:
    """Run bars [start, end). `funding[j]` is the funding rate (fraction of notional, positive = longs pay) accrued during bar j; required for perps."""
    fee, slip, lev = costs.fee_bps / 1e4, costs.slippage_bps / 1e4, costs.leverage
    eq = 1.0
    pos = 0
    entry_px = notional = eq_before = 0.0
    entry_j = 0
    fees_paid = fund_paid = 0.0
    curve = [1.0]
    trades: list[dict] = []
    liquidated = False
    in_pos_bars = 0

    def close(j, px, reason):
        nonlocal eq, pos, fees_paid
        fill = px * (1 - pos * slip)
        eq += pos * (fill / entry_px - 1) * notional
        f = fee * notional * (fill / entry_px)             # the exit fee is charged on the notional at exit
        eq -= f
        fees_paid += f
        trades.append({"entry_t": t[entry_j], "exit_t": t[j], "side": "long" if pos > 0 else "short", "entry_px": entry_px, "exit_px": fill, "reason": reason,
                       "bars": j - entry_j + 1, "ret_pct": (eq / eq_before - 1) * 100 if eq_before else 0.0})
        pos = 0

    for j in range(start, end):
        if liquidated:
            curve.append(0.0)
            continue
        want = target[j - 1] if j > 0 else 0
        if want < 0 and not costs.perp:
            want = 0
        if want != pos:
            if pos != 0:
                close(j, o[j], "signal")
            if want != 0 and eq > 0:
                entry_px = o[j] * (1 + want * slip)
                notional = eq * lev
                f = fee * notional
                eq -= f
                fees_paid += f
                eq_before = eq + f
                pos, entry_j = want, j
        if pos != 0:
            in_pos_bars += 1
            stop = entry_px * (1 - pos * costs.stop_pct / 100) if costs.stop_pct else None
            liq = entry_px * (1 - pos * (1 / lev - costs.maint_margin)) if costs.perp and lev > 1 else None
            hit_stop = stop is not None and ((l[j] <= stop) if pos > 0 else (h[j] >= stop))
            hit_liq = liq is not None and ((l[j] <= liq) if pos > 0 else (h[j] >= liq))
            if hit_stop and hit_liq and abs(liq - entry_px) < abs(stop - entry_px):
                hit_stop = False                                       # liquidation is closer than the stop: the stop never gets a chance
            if hit_stop:
                gap = (o[j] <= stop) if pos > 0 else (o[j] >= stop)
                close(j, o[j] if gap else stop, "stop")
            elif hit_liq:
                eq = 0.0
                trades.append({"entry_t": t[entry_j], "exit_t": t[j], "side": "long" if pos > 0 else "short", "entry_px": entry_px, "exit_px": liq, "reason": "liquidated",
                               "bars": j - entry_j + 1, "ret_pct": -100.0})
                pos, liquidated = 0, True
        if pos != 0 and costs.perp and funding is not None:
            fcost = pos * funding[j] * notional                        # long pays when the rate is positive
            eq -= fcost
            fund_paid += fcost
        mark = eq + (pos * (c[j] / entry_px - 1) * notional if pos != 0 else 0.0)
        curve.append(max(mark, 0.0))
    if pos != 0:
        trades.append({"entry_t": t[entry_j], "exit_t": t[end - 1], "side": "long" if pos > 0 else "short", "entry_px": entry_px, "exit_px": c[end - 1], "reason": "open",
                       "bars": end - entry_j, "ret_pct": (curve[-1] / eq_before - 1) * 100 if eq_before else 0.0, "open": True})
    return {"curve": curve, "trades": trades, "liquidated": liquidated, "fees_paid_pct": fees_paid * 100, "funding_paid_pct": fund_paid * 100, "exposure": in_pos_bars / max(end - start, 1)}
