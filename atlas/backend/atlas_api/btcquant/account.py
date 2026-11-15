"""The account and execution engine of the btcquant system. ONE step function used by both the backtester and the paper trader, so a backtest is the paper engine replayed on history and the two cannot disagree
(a test steps candle by candle and compares).

Timing (protocol section 3). A strategy decides at the CLOSE of candle j using candles up to j. The order it creates executes at the OPEN of candle j+1, at that price moved against the trade by the slippage, and pays
the fee on the notional. Nothing inside a candle is known when the decision is made.
Within one candle the engine does, in this order: (1) execute the pending order at the open; (2) check the protective stop against the candle's low; (3) mark equity at the close and update the running peak;
(4) trip the circuit breaker if equity is 15% below the peak; (5) decide for the next candle.

Kinds of account:
  "stop"   long-only spot position, entered when the strategy's state turns ON (and the account is armed), exited when it turns OFF or the protective stop is hit. Size = the smaller of 1% of equity divided by the
           distance to the stop and 100% of equity (fee reserved). `sizing="full"` drops the 1% cap (a labelled sensitivity). The stop may trail (ratchet up only).
  "weight" holds a target fraction of equity in Bitcoin (risk-managed exposure), rebalanced only when the target moves by more than the band. Exempt from the 1% rule; capped at 100%.
  "hold"   buy-and-hold benchmark: all cash into Bitcoin at the first open, one entry.
  "cash"   cash-only benchmark.
Armed rule: an account is armed at the start and whenever the strategy's state is OFF; it may enter only when armed, flat and ON; entering disarms it. So after a stop-out it waits for OFF then ON again.
Circuit breaker (except for the two benchmarks): equity at a close 15% below the running peak closes everything at the next open and halts the account until `reset_breaker` (a human) is called.
Records: every order is written to the log when the signal is created ("on signal"), then a fill (or a reject, a stop, a breaker action) when it happens, with the numbers behind it. Accounting identity checked by a test:
equity = start + realised + unrealised, and cash never goes negative.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import config as C

TINY = 1e-12


@dataclass
class Sig:
    """What a strategy says at the close of a candle. state: wants to be long (stop kinds). weight: target fraction (weight kind). stop: the protective stop level to use (candidate for a trailing stop)."""
    state: bool | None = None
    weight: float | None = None
    stop: float | None = None
    info: dict | None = None                         # the numbers behind the signal, for the ledger


def _fin(x) -> bool:
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x)


@dataclass
class Account:
    id: str
    kind: str = "stop"                               # stop | weight | hold | cash
    start_equity: float = C.START_EQUITY_STRATEGY
    fee: float = C.FEE
    slip: float = C.SLIPPAGE
    sizing: str = "risk"                             # risk (1% rule, the protocol default) | full (sensitivity: 100% when long)
    risk: float = C.RISK_PER_TRADE
    trail: bool = False
    breaker: bool = True
    band: float = C.REBALANCE_BAND
    verbose: bool = False                            # keep the full event log (paper accounts); backtests keep only trades and the curve
    cash: float = field(default=-1.0)
    qty: float = 0.0
    cost_basis: float = 0.0
    stop: float | None = None
    armed: bool = True
    halted: bool = False
    peak: float = field(default=-1.0)
    realized: float = 0.0
    fees_paid: float = 0.0
    slip_paid: float = 0.0
    traded: float = 0.0                              # notional traded, both sides
    pending: dict | None = None
    last_target: float | None = None
    last_bar: int | None = None
    order_seq: int = 0
    breaker_at: int | None = None
    open_trade: dict | None = None
    trades: list = field(default_factory=list)
    curve: list = field(default_factory=list)        # (t_open, equity, exposure, cash, qty, close)
    events: list = field(default_factory=list)

    def __post_init__(self):
        if self.cash < 0:
            self.cash = self.start_equity
        if self.peak < 0:
            self.peak = self.start_equity

    # ---- records ----
    def _log(self, event: str, **kw):
        if self.verbose:
            self.events.append({"event": event, "account": self.id, **kw})

    def equity(self, mark: float) -> float:
        return self.cash + self.qty * mark

    # ---- orders created at a close ("on signal") ----
    def _order(self, kind: str, t_bar: int, interval: int, ref_close: float, reason: str, **kw):
        self.order_seq += 1
        self.pending = {"id": self.order_seq, "kind": kind, "signal_bar": t_bar, "signal_time": t_bar + interval, "reason": reason, **kw}
        self._log("order", order_id=self.order_seq, kind=kind, reason=reason, signal_bar=t_bar, signal_time=t_bar + interval, ref_close=ref_close, **kw)

    def decide(self, t_bar: int, close: float, sig: Sig | None, interval: int = C.DAY) -> None:
        """Called at the close of candle `t_bar`: create the order (if any) that will execute at the next open."""
        if self.halted or sig is None:
            return
        if self.kind == "stop":
            state = bool(sig.state)
            if not state:
                self.armed = True
            if self.qty > TINY:
                if self.trail and _fin(sig.stop) and self.stop is not None and sig.stop > self.stop:
                    self._log("stop_raised", signal_bar=t_bar, old=self.stop, new=sig.stop)
                    self.stop = sig.stop                                     # ratchet: never lowered
                if not state:
                    self._order("exit", t_bar, interval, close, "signal", info=sig.info)
            elif self.armed and state:
                if not _fin(sig.stop) or sig.stop >= close:
                    self._log("reject", reason="no usable protective stop at the signal", signal_bar=t_bar, stop=sig.stop, ref_close=close)
                    return
                est = self.size_for(self.equity(close), close, sig.stop) if sig.stop < close else 0.0
                self._order("enter", t_bar, interval, close, "signal", stop=sig.stop, est_qty=est, info=sig.info)
        elif self.kind == "weight" and _fin(sig.weight):
            w = min(max(sig.weight, 0.0), C.MAX_EXPOSURE)
            if self.last_target is None or abs(w - self.last_target) > self.band:
                self._order("rebalance", t_bar, interval, close, "signal", weight=w, info=sig.info)
                self.last_target = w

    def size_for(self, equity: float, fill: float, stop: float) -> float:
        """Quantity to buy: 1% of equity over the distance to the stop (unless sizing is "full"), never more than 100% of equity, with the fee reserved from cash."""
        cap = min(C.MAX_EXPOSURE * equity, self.cash / (1.0 + self.fee)) / fill
        if self.sizing == "risk" and fill > stop:
            return max(min(self.risk * equity / (fill - stop), cap), 0.0)
        return max(cap, 0.0)

    # ---- trades ----
    def _buy(self, t: int, ref: float, qty: float, reason: str, order_id: int | None, stop: float | None = None, eq_before: float | None = None):
        fill = ref * (1.0 + self.slip)
        cost = qty * fill
        fee = cost * self.fee
        self.cash -= cost + fee
        self.qty += qty
        self.cost_basis += cost + fee
        self.fees_paid += fee
        self.slip_paid += qty * (fill - ref)
        self.traded += cost
        if self.open_trade is None:
            self.open_trade = {"entry_t": t, "buys": 0.0, "buy_qty": 0.0, "sells": 0.0, "sell_qty": 0.0, "fees": 0.0, "slip": 0.0, "bars": 0}
        ot = self.open_trade
        ot["buys"] += cost + fee; ot["buy_qty"] += qty; ot["fees"] += fee; ot["slip"] += qty * (fill - ref)
        self._log("fill", order_id=order_id, side="buy", reason=reason, exec_time=t, ref_price=ref, price=fill, qty=qty, fee=fee, slippage_cost=qty * (fill - ref), stop=stop,
                  equity_before=eq_before, cash_after=self.cash, qty_after=self.qty)

    def _sell(self, t: int, ref: float, qty: float, reason: str, order_id: int | None, eq_before: float | None = None):
        qty = min(qty, self.qty)
        fill = ref * (1.0 - self.slip)
        proceeds = qty * fill
        fee = proceeds * self.fee
        net = proceeds - fee
        basis = self.cost_basis * (qty / self.qty) if self.qty > 0 else 0.0
        self.realized += net - basis
        self.cash += net
        self.qty -= qty
        self.cost_basis -= basis
        self.fees_paid += fee
        self.slip_paid += qty * (ref - fill)
        self.traded += proceeds
        ot = self.open_trade
        if ot is not None:
            ot["sells"] += net; ot["sell_qty"] += qty; ot["fees"] += fee; ot["slip"] += qty * (ref - fill)
        self._log("fill", order_id=order_id, side="sell", reason=reason, exec_time=t, ref_price=ref, price=fill, qty=qty, fee=fee, slippage_cost=qty * (ref - fill), equity_before=eq_before,
                  cash_after=self.cash, qty_after=self.qty)
        if self.qty <= TINY:
            self.qty, self.cost_basis, self.stop = 0.0, 0.0, None
            if ot is not None:
                ot.update(exit_t=t, reason=reason, net_pnl=ot["sells"] - ot["buys"], ret=(ot["sells"] / ot["buys"] - 1.0) if ot["buys"] > 0 else 0.0,
                          entry_px=ot["buys"] / ot["buy_qty"] if ot["buy_qty"] else None, exit_px=ot["sells"] / ot["sell_qty"] if ot["sell_qty"] else None)
                self.trades.append(ot)
                self.open_trade = None

    # ---- one candle ----
    def step(self, bar: tuple, sig: Sig | None, interval: int = C.DAY) -> None:
        t, o, h, l, c, v = bar
        # (1) the order created at the previous close executes at this open
        od, self.pending = self.pending, None
        if od is not None:
            eq0 = self.equity(o)
            if od["kind"] == "enter":
                fill = o * (1.0 + self.slip)
                if self.halted:
                    self._log("reject", order_id=od["id"], reason="account is halted", exec_time=t)
                elif od["stop"] >= fill:
                    self._log("reject", order_id=od["id"], reason="the open is at or below the protective stop", exec_time=t, price=fill, stop=od["stop"])
                else:
                    q = self.size_for(eq0, fill, od["stop"])
                    if q * fill < 1e-6:
                        self._log("reject", order_id=od["id"], reason="size rounds to nothing", exec_time=t)
                    else:
                        self._buy(t, o, q, od["reason"], od["id"], stop=od["stop"], eq_before=eq0)
                        self.stop, self.armed = od["stop"], False
            elif od["kind"] == "exit":
                if self.qty > TINY:
                    self._sell(t, o, self.qty, od["reason"], od["id"], eq_before=eq0)
            elif od["kind"] == "rebalance":
                target_val = od["weight"] * eq0
                delta = target_val - self.qty * o
                if delta > 0:
                    fill = o * (1.0 + self.slip)
                    q = min(delta, self.cash) / (fill * (1.0 + self.fee)) if fill > 0 else 0.0
                    if q * fill >= 1e-6:
                        self._buy(t, o, q, od["reason"], od["id"], eq_before=eq0)
                elif delta < 0 and self.qty > TINY:
                    self._sell(t, o, min(self.qty, -delta / o), od["reason"], od["id"], eq_before=eq0)
        # (2) protective stop, against this candle's low
        if self.qty > TINY and self.stop is not None and l <= self.stop:
            ref = o if o <= self.stop else self.stop                         # a gap through the stop fills at the open
            eq1 = self.equity(self.stop)
            self._log("stop_hit", exec_time=t, stop=self.stop, open=o, low=l, gap=o <= self.stop)
            self._sell(t, ref, self.qty, "stop", None, eq_before=eq1)
        # (3) mark at the close
        eq = self.equity(c)
        self.peak = max(self.peak, eq)
        exposure = self.qty * c / eq if eq > 0 else 0.0
        self.curve.append((t, eq, exposure, self.cash, self.qty, c))
        if self.open_trade is not None:
            self.open_trade["bars"] += 1
        self.last_bar = t
        # (4) circuit breaker
        if self.breaker and not self.halted and eq <= self.peak * (1.0 - C.CIRCUIT_BREAKER):
            self.halted, self.breaker_at = True, t
            self._log("breaker", signal_bar=t, equity=eq, peak=self.peak, drawdown=eq / self.peak - 1.0)
            if self.qty > TINY:
                self._order("exit", t, interval, c, "circuit_breaker")
            return
        # (5) decide for the next candle
        self.decide(t, c, sig, interval)

    def begin(self, prev_bar: tuple | None, sig: Sig | None, interval: int = C.DAY) -> None:
        """Before the first candle: the decision at the close before it (so a rule that is already ON can enter at the first open). The buy-and-hold benchmark buys at the first open."""
        if self.kind == "hold":
            self._order("rebalance", (prev_bar[0] if prev_bar else 0), interval, prev_bar[4] if prev_bar else 0.0, "benchmark", weight=1.0)
            self.last_target = 1.0
        elif prev_bar is not None and sig is not None:
            self.decide(prev_bar[0], prev_bar[4], sig, interval)

    def reset_breaker(self) -> None:
        """A human re-enables an account whose circuit breaker tripped. The peak restarts from the current equity."""
        self.halted = False
        self.peak = self.equity(self.curve[-1][5]) if self.curve else self.start_equity
        self._log("breaker_reset", equity=self.peak)

    # ---- persistence ----
    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["events"] = []                                                     # the log lives in the ledger file, not in the state
        d["curve"] = []
        d["trades"] = []
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Account":
        a = cls(id=d["id"])
        for k, v in d.items():
            setattr(a, k, v)
        return a


def make_account(id: str, kind: str, **kw) -> Account:
    kw.setdefault("breaker", kind in ("stop", "weight"))
    return Account(id=id, kind=kind, **kw)
