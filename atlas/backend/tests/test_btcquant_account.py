"""btcquant account and execution engine: hand-worked numbers for sizing, costs, stops (including gaps and same-candle stops), the armed re-entry rule, trailing stops, the circuit breaker, weight mode and the two
benchmarks; the accounting identity on a random walk; the ledger written on signal; persistence. Fee 0.10% and slippage 0.05% per side, as in the protocol."""
import numpy as np
import pytest

from atlas_api.btcquant import config as C
from atlas_api.btcquant.account import Account, Sig, make_account

T0 = 1_700_000_000 - 1_700_000_000 % 86400
DAY = 86400
FEE, SLIP = 0.001, 0.0005


def bar(i, o, h, l, c, v=1.0):
    return (T0 + i * DAY, o, h, l, c, v)


def acct(**kw):
    kw.setdefault("verbose", True)
    return make_account("t", kw.pop("kind", "stop"), **kw)


def enter_at(a, entry_open=100.0, stop=94.0, prev_close=100.0, **barkw):
    """Create the account's first order from the close before candle 1 and run candle 1 (open, high, low, close given by kwargs)."""
    prev = bar(0, prev_close, prev_close, prev_close, prev_close)
    a.begin(prev, Sig(state=True, stop=stop, info={"why": "test"}))
    b = bar(1, entry_open, barkw.get("h", entry_open + 1), barkw.get("l", entry_open - 1), barkw.get("c", entry_open))
    a.step(b, Sig(state=True, stop=stop))
    return b


# ---- sizing, costs, stops ----

def test_entry_is_sized_so_that_the_loss_at_the_stop_is_one_percent_of_equity():
    a = acct()
    enter_at(a, 100.0, 94.0)
    fill = 100.0 * (1 + SLIP)                                    # 100.05
    q = 0.01 * 10_000 / (fill - 94.0)                            # 100 / 6.05
    assert a.qty == pytest.approx(q, rel=1e-12) and q == pytest.approx(16.528925619834, rel=1e-9)
    cost, fee = q * fill, q * fill * FEE
    assert a.cash == pytest.approx(10_000 - cost - fee) and a.fees_paid == pytest.approx(fee) and a.slip_paid == pytest.approx(q * 0.05)
    assert a.equity(100.0) == pytest.approx(10_000 - fee - q * 0.05)             # at an unchanged price only the fee and the slippage have been lost
    assert a.stop == 94.0 and a.armed is False and a.pending is None


def test_full_sizing_uses_all_the_cash_with_the_fee_reserved_and_the_risk_cap_is_ignored():
    a = acct(sizing="full")
    enter_at(a, 100.0, 94.0)
    fill = 100.05
    assert a.qty == pytest.approx(10_000 / 1.001 / fill) and a.cash == pytest.approx(0.0, abs=1e-9)


def test_a_tight_stop_is_capped_at_100_percent_of_equity_and_a_wide_stop_gives_a_small_position():
    a = acct()
    enter_at(a, 100.0, 99.99, l=100.0)                           # risk-based size would be enormous: capped at all the cash less the fee (the candle's low stays above the stop)
    assert a.qty * 100.05 * 1.001 == pytest.approx(10_000, rel=1e-9)
    b = acct()
    enter_at(b, 100.0, 50.0)                                     # a stop 50% away: 1% / 50% = 2% of equity
    assert b.qty * 100.05 == pytest.approx(0.02 * 10_000, rel=0.01)


def test_the_stop_exit_loses_the_planned_one_percent_plus_the_exit_slippage_and_both_fees():
    a = acct()
    enter_at(a, 100.0, 94.0)
    q, fee_in = a.qty, a.fees_paid
    a.step(bar(2, 99.0, 99.5, 93.0, 95.0), Sig(state=True, stop=94.0))
    assert a.qty == 0 and a.stop is None and len(a.trades) == 1 and a.trades[0]["reason"] == "stop"
    fill = 94.0 * (1 - SLIP)
    fee_out = q * fill * FEE
    assert a.realized == pytest.approx(-(100.0 + q * 94.0 * SLIP + fee_in + fee_out))          # 6.05 x q = 100 planned, then the exit slippage and the fees
    assert a.equity(95.0) == pytest.approx(10_000 + a.realized)


def test_a_gap_through_the_stop_fills_at_the_open_not_at_the_stop():
    a = acct()
    enter_at(a, 100.0, 94.0)
    a.step(bar(2, 90.0, 91.0, 88.0, 89.0), Sig(state=True, stop=94.0))
    ev = [e for e in a.events if e["event"] == "fill" and e["side"] == "sell"][0]
    assert ev["ref_price"] == 90.0 and ev["price"] == pytest.approx(90.0 * (1 - SLIP)) and a.qty == 0


def test_an_entry_is_rejected_when_the_open_is_at_or_below_the_stop_and_the_account_stays_armed():
    a = acct()
    a.begin(bar(0, 100, 100, 100, 100), Sig(state=True, stop=94.0))
    a.step(bar(1, 93.0, 94.0, 92.0, 93.5), Sig(state=True, stop=90.0))
    assert a.qty == 0 and a.armed is True
    rej = [e for e in a.events if e["event"] == "reject"]
    assert len(rej) == 1 and "protective stop" in rej[0]["reason"]
    assert a.pending is not None and a.pending["stop"] == 90.0                  # still ON and armed: a new order at the close with the new stop
    a.step(bar(2, 94.0, 95.0, 93.0, 94.5), Sig(state=True, stop=90.0))
    assert a.qty > 0 and a.stop == 90.0


def test_a_position_entered_at_the_open_can_be_stopped_out_in_the_same_candle():
    a = acct()
    enter_at(a, 100.0, 98.0, l=97.0)
    assert a.qty == 0 and [t["reason"] for t in a.trades] == ["stop"]
    fills = [e for e in a.events if e["event"] == "fill"]
    assert [f["side"] for f in fills] == ["buy", "sell"] and fills[1]["ref_price"] == 98.0


def test_after_a_stop_out_the_account_waits_for_the_state_to_go_off_and_on_again():
    a = acct()
    enter_at(a, 100.0, 98.0, l=97.0)                             # stopped out at once; state still ON
    for i in (2, 3, 4):
        a.step(bar(i, 99, 100, 98.5, 99.5), Sig(state=True, stop=95.0))
        assert a.qty == 0 and a.pending is None                  # ON, flat, but not armed: no order
    a.step(bar(5, 99, 100, 98.5, 99.5), Sig(state=False))        # OFF: armed again
    assert a.armed is True and a.pending is None
    a.step(bar(6, 99, 100, 98.5, 99.5), Sig(state=True, stop=95.0))
    assert a.pending is not None and a.pending["kind"] == "enter"
    a.step(bar(7, 99, 100, 98.5, 99.5), Sig(state=True, stop=95.0))
    assert a.qty > 0


def test_exit_on_signal_executes_at_the_next_open_with_slippage_and_fee():
    a = acct()
    enter_at(a, 100.0, 94.0)
    q = a.qty
    a.step(bar(2, 103.0, 106.0, 102.0, 105.0), Sig(state=False))               # decided at this close, still long during this candle
    assert a.qty == q and a.pending["kind"] == "exit"
    a.step(bar(3, 107.0, 108.0, 106.0, 107.5), Sig(state=False))               # executes at this open
    fill = 107.0 * (1 - SLIP)
    assert a.qty == 0 and a.cash == pytest.approx(a.equity(107.5)) and a.trades[0]["reason"] == "signal"
    assert a.trades[0]["net_pnl"] == pytest.approx(q * fill * (1 - FEE) - q * 100.05 * (1 + FEE)) and a.trades[0]["bars"] == 2 and a.trades[0]["exit_t"] - a.trades[0]["entry_t"] == 2 * DAY
    assert a.trades[0]["ret"] == pytest.approx(a.trades[0]["net_pnl"] / (q * 100.05 * (1 + FEE)))


def test_a_round_trip_at_an_unchanged_price_loses_exactly_the_costs():
    a = acct(sizing="full")
    enter_at(a, 100.0, 90.0)
    a.step(bar(2, 100.0, 101.0, 99.0, 100.0), Sig(state=False))
    a.step(bar(3, 100.0, 101.0, 99.0, 100.0), Sig(state=False))
    q = 10_000 / 1.001 / (100 * 1.0005)
    expected = q * 100 * 0.9995 * 0.999
    assert a.cash == pytest.approx(expected) and a.realized == pytest.approx(expected - 10_000)
    assert expected / 10_000 == pytest.approx(0.9995 * 0.999 / (1.0005 * 1.001), rel=1e-12)             # about -0.30%: two fees and two slippages


def test_a_trailing_stop_only_ever_moves_up_and_the_raised_stop_is_the_one_that_is_hit():
    a = acct(trail=True)
    enter_at(a, 100.0, 94.0)
    seen = []
    for i, cand in enumerate([96.0, 95.0, 97.0, float("nan")], start=2):
        a.step(bar(i, 101, 103, 100, 102), Sig(state=True, stop=cand))
        seen.append(a.stop)
    assert seen == [96.0, 96.0, 97.0, 97.0]
    a.step(bar(6, 98, 99, 96.5, 97.5), Sig(state=True, stop=97.0))                # low 96.5 touches the raised stop 97
    assert a.qty == 0 and a.trades[-1]["reason"] == "stop" and [e for e in a.events if e["event"] == "fill"][-1]["ref_price"] == 97.0


def test_a_fixed_stop_does_not_trail():
    a = acct(trail=False)
    enter_at(a, 100.0, 94.0)
    a.step(bar(2, 101, 103, 100, 102), Sig(state=True, stop=99.0))
    assert a.stop == 94.0


# ---- circuit breaker ----

def test_the_circuit_breaker_closes_at_the_next_open_halts_and_needs_a_human_to_reset():
    a = acct(sizing="full")
    enter_at(a, 100.0, 40.0)                                                      # wide stop: the breaker acts first
    a.step(bar(2, 100, 101, 99, 100), Sig(state=True, stop=40.0))
    a.step(bar(3, 100, 100, 85, 90), Sig(state=True, stop=40.0))                 # about -10%: fine
    assert not a.halted
    a.step(bar(4, 90, 90, 80, 83), Sig(state=True, stop=40.0))                   # 83 is more than 15% below the peak close of 100
    assert a.halted and a.breaker_at == T0 + 4 * DAY and a.pending["kind"] == "exit" and a.pending["reason"] == "circuit_breaker"
    a.step(bar(5, 82, 84, 81, 83), Sig(state=True, stop=40.0))
    assert a.qty == 0 and a.trades[-1]["reason"] == "circuit_breaker"
    a.step(bar(6, 83, 90, 82, 88), Sig(state=False))
    a.step(bar(7, 88, 95, 87, 94), Sig(state=True, stop=80.0))
    assert a.qty == 0 and a.pending is None                                        # halted: no new entries however good the signal
    a.reset_breaker()
    a.step(bar(8, 94, 96, 93, 95), Sig(state=False))
    a.step(bar(9, 95, 98, 94, 97), Sig(state=True, stop=85.0))
    a.step(bar(10, 97, 99, 96, 98), Sig(state=True, stop=85.0))
    assert a.qty > 0 and not a.halted
    assert [e["event"] for e in a.events if e["event"] in ("breaker", "breaker_reset")] == ["breaker", "breaker_reset"]


def test_the_benchmarks_never_halt():
    h = acct(kind="hold")
    h.begin(bar(0, 100, 100, 100, 100), None)
    for i, px in enumerate([100, 60, 30, 20], start=1):
        h.step(bar(i, px, px, px * 0.9, px), None)
    assert not h.halted and h.qty > 0 and h.breaker is False


# ---- weight mode and benchmarks ----

def test_weight_mode_rebalances_only_when_the_target_moves_by_more_than_the_band():
    a = acct(kind="weight")
    a.begin(bar(0, 100, 100, 100, 100), Sig(weight=0.5))
    a.step(bar(1, 100, 101, 99, 100), Sig(weight=0.55))                              # trades the first order at the open; 0.55 is within 0.10 of 0.5: no new order
    fill = 100.05
    q = 5_000 / (fill * 1.001)
    assert a.qty == pytest.approx(q) and a.pending is None
    a.step(bar(2, 100, 101, 99, 100), Sig(weight=0.70))                              # 0.70 is 0.20 from 0.5: order
    assert a.pending["kind"] == "rebalance" and a.pending["weight"] == pytest.approx(0.70)
    a.step(bar(3, 100, 101, 99, 100), Sig(weight=0.70))
    eq0 = 9_997.5                                                                    # roughly; the trade brings the position to 70% of equity at the open
    assert a.qty * 100 / a.equity(100) == pytest.approx(0.70, abs=0.005)
    a.step(bar(4, 100, 101, 99, 100), Sig(weight=0.20))
    a.step(bar(5, 100, 101, 99, 100), Sig(weight=0.20))
    assert a.qty * 100 / a.equity(100) == pytest.approx(0.20, abs=0.005) and a.stop is None


def test_weight_is_capped_at_100_percent_and_never_negative():
    a = acct(kind="weight")
    a.begin(bar(0, 100, 100, 100, 100), Sig(weight=3.0))
    a.step(bar(1, 100, 101, 99, 100), Sig(weight=-1.0))
    assert a.qty * 100 <= a.equity(100) * 1.0000001 and a.cash >= -1e-9
    a.step(bar(2, 100, 101, 99, 100), Sig(weight=-1.0))
    assert a.qty == pytest.approx(0.0, abs=1e-9)


def test_buy_and_hold_buys_everything_at_the_first_open_once():
    h = acct(kind="hold")
    h.begin(bar(0, 99, 99, 99, 99), None)
    closes = [102.0, 110.0, 105.0]
    for i, c in enumerate(closes, start=1):
        h.step(bar(i, 100.0 if i == 1 else closes[i - 2], max(c, 100) + 1, min(c, 100) - 1, c), None)
    q = 10_000 / (100.0 * 1.0005 * 1.001)
    assert h.qty == pytest.approx(q) and h.cash == pytest.approx(0.0, abs=1e-9) and len(h.pending or {}) == 0
    assert h.equity(105.0) == pytest.approx(q * 105.0) and len([e for e in h.events if e["event"] == "fill"]) == 1


def test_cash_does_nothing_and_keeps_its_equity():
    c = acct(kind="cash")
    c.begin(bar(0, 100, 100, 100, 100), Sig(state=True, stop=1.0))
    for i in range(1, 6):
        c.step(bar(i, 100 + i, 105 + i, 95 + i, 101 + i), Sig(state=True, stop=1.0))
    assert c.qty == 0 and c.cash == 10_000 and all(row[1] == 10_000 for row in c.curve) and c.events == []


# ---- the accounting identity ----

@pytest.mark.parametrize("kind, sizing", [("stop", "risk"), ("stop", "full"), ("weight", "risk")])
def test_equity_is_start_plus_realised_plus_unrealised_on_a_random_walk(kind, sizing):
    rng = np.random.default_rng(7)
    a = acct(kind=kind, sizing=sizing, trail=True, breaker=False)
    px = 100.0
    a.begin(bar(0, px, px, px, px), Sig(state=True, stop=px * 0.9, weight=0.6))
    fees = 0.0
    for i in range(1, 400):
        o = px * (1 + rng.normal(0, 0.01))
        c = o * (1 + rng.normal(0, 0.03))
        h, l = max(o, c) * (1 + abs(rng.normal(0, 0.01))), min(o, c) * (1 - abs(rng.normal(0, 0.01)))
        on = bool(rng.random() < 0.55)
        a.step(bar(i, o, h, l, c), Sig(state=on, stop=c * 0.93, weight=float(rng.uniform(0, 1))))
        px = c
        unreal = a.qty * c - a.cost_basis
        assert a.equity(c) == pytest.approx(a.start_equity + a.realized + unreal, rel=1e-9, abs=1e-6)
        assert a.cash >= -1e-7 and a.qty >= -1e-12 and a.qty * c <= a.equity(c) * 1.000001
        assert a.curve[-1][1] == pytest.approx(a.equity(c))
    fills = [e for e in a.events if e["event"] == "fill"]
    assert sum(f["fee"] for f in fills) == pytest.approx(a.fees_paid) and len(fills) >= 4
    assert a.traded == pytest.approx(sum(f["qty"] * f["price"] for f in fills))


# ---- recorded on signal ----

def test_every_order_is_written_when_the_signal_is_created_and_updated_when_it_fills():
    a = acct()
    prev = bar(0, 100, 100, 100, 100)
    a.begin(prev, Sig(state=True, stop=94.0, info={"sma_fast": 101.0, "sma_slow": 99.0}))
    order = a.events[0]
    assert order["event"] == "order" and order["kind"] == "enter" and order["signal_time"] == T0 + DAY and order["signal_bar"] == T0 and order["stop"] == 94.0
    assert order["info"] == {"sma_fast": 101.0, "sma_slow": 99.0} and order["est_qty"] == pytest.approx(0.01 * 10_000 / (100.0 - 94.0))
    a.step(bar(1, 100, 101, 99, 100), Sig(state=False))
    fill = a.events[1]
    assert fill["event"] == "fill" and fill["order_id"] == order["order_id"] and fill["side"] == "buy" and fill["exec_time"] == T0 + DAY and fill["price"] == pytest.approx(100.05)
    assert fill["equity_before"] == 10_000 and fill["qty"] > 0 and fill["fee"] > 0 and fill["slippage_cost"] > 0 and fill["stop"] == 94.0
    ex = a.events[2]
    assert ex["event"] == "order" and ex["kind"] == "exit" and ex["signal_bar"] == T0 + DAY          # the exit was recorded the moment the state went OFF, before it was filled


def test_a_signal_without_a_usable_stop_is_recorded_as_rejected_not_silently_skipped():
    a = acct()
    a.begin(bar(0, 100, 100, 100, 100), Sig(state=True, stop=float("nan")))
    assert a.pending is None and a.events[0]["event"] == "reject" and "protective stop" in a.events[0]["reason"]


# ---- persistence ----

def test_a_restored_account_continues_exactly_like_the_original():
    rng = np.random.default_rng(3)
    seq = []
    px = 100.0
    for i in range(1, 40):
        o = px * (1 + rng.normal(0, 0.01)); c = o * (1 + rng.normal(0, 0.03))
        seq.append((bar(i, o, max(o, c) * 1.01, min(o, c) * 0.99, c), Sig(state=bool(rng.random() < 0.5), stop=c * 0.92)))
        px = c
    a = acct(trail=True, verbose=False)
    a.begin(bar(0, 100, 100, 100, 100), Sig(state=True, stop=92.0))
    for b, s in seq[:20]:
        a.step(b, s)
    clone = Account.from_dict(a.to_dict())
    for b, s in seq[20:]:
        a.step(b, s)
        clone.step(b, s)
    for k in ("cash", "qty", "cost_basis", "stop", "armed", "halted", "peak", "realized", "fees_paid", "slip_paid", "traded", "last_bar", "last_target"):
        assert getattr(a, k) == getattr(clone, k), k


# ---- boundaries found by breaking the engine on purpose ----

def test_an_entry_is_rejected_when_the_stop_equals_the_fill_price_exactly():
    a = acct(slip=0.0)                                                             # no slippage, so the fill is exactly the open
    a.begin(bar(0, 101, 101, 101, 101), Sig(state=True, stop=100.0))              # a usable stop at the signal (below the close of 101) ...
    a.step(bar(1, 100.0, 101.0, 100.0, 100.5), Sig(state=False))                  # ... but the next open is exactly the stop
    assert a.qty == 0 and [e["event"] for e in a.events if e["event"] in ("reject", "fill")] == ["reject"]
    assert "at or below the protective stop" in [e for e in a.events if e["event"] == "reject"][0]["reason"]


def test_the_stop_is_hit_when_the_low_equals_the_stop_exactly():
    a = acct()
    enter_at(a, 100.0, 94.0)
    a.step(bar(2, 99.0, 99.5, 94.0, 96.0), Sig(state=True, stop=94.0))            # the low touches the stop to the cent
    assert a.qty == 0 and a.trades[-1]["reason"] == "stop"


def test_the_breaker_trips_at_exactly_15_percent_below_the_peak():
    a = acct(sizing="full", fee=0.0, slip=0.0)
    enter_at(a, 100.0, 10.0, l=100.0)
    a.step(bar(2, 100, 100, 85, 85), Sig(state=True, stop=10.0))                  # equity 8,500.0 is exactly 85% of the 10,000 peak
    assert a.halted


def test_the_breaker_measures_from_the_running_peak_of_closes_not_from_the_start_and_not_from_opens():
    a = acct(sizing="full", fee=0.0, slip=0.0)
    enter_at(a, 100.0, 10.0, l=100.0)                                             # 100 units
    a.step(bar(2, 100, 120, 100, 120), Sig(state=True, stop=10.0))                # close 120: equity 12,000, the new peak
    a.step(bar(3, 120, 120, 102, 102.5), Sig(state=True, stop=10.0))              # equity 10,250: 14.6% below the peak, so no trip (and far above 85% of the start)
    assert not a.halted
    a.step(bar(4, 102.5, 103, 101.9, 102), Sig(state=True, stop=10.0))            # equity 10,200 is exactly 85% of 12,000
    assert a.halted
    b = acct(sizing="full", fee=0.0, slip=0.0)
    enter_at(b, 100.0, 10.0, l=100.0)
    b.step(bar(2, 100, 110, 100, 110), Sig(state=True, stop=10.0))                # close 110: peak 11,000
    b.step(bar(3, 120, 121, 99, 100), Sig(state=True, stop=10.0))                 # opens at 120 (12,000) but closes at 100 (10,000): threshold from closes is 9,350, so no trip
    assert not b.halted


def test_the_rebalance_band_is_ten_points_of_weight():
    def orders_after(first, second):
        a = acct(kind="weight")
        a.begin(bar(0, 100, 100, 100, 100), Sig(weight=first))
        a.step(bar(1, 100, 101, 99, 100), Sig(weight=second))
        return a.pending is not None
    assert not orders_after(0.50, 0.59) and orders_after(0.50, 0.61) and not orders_after(0.50, 0.41) and orders_after(0.50, 0.39)


def test_a_target_weight_above_one_is_recorded_as_one():
    a = acct(kind="weight")
    a.begin(bar(0, 100, 100, 100, 100), Sig(weight=3.0))
    assert a.pending["weight"] == 1.0 and a.last_target == 1.0


# ---- circuit breaker: the research-account cool-off and the trip record (protocol v1.1) ----

def tripped(**kw):
    """A full-size account that trips its breaker at the close of candle 4 (equity 8,300 against a 10,000 peak). Candle 5 closes the position at its open."""
    a = acct(sizing="full", fee=0.0, slip=0.0, **kw)
    enter_at(a, 100.0, 40.0, l=100.0)
    a.step(bar(2, 100, 101, 99, 100), Sig(state=True, stop=40.0))
    a.step(bar(3, 100, 100, 85, 90), Sig(state=True, stop=40.0))
    a.step(bar(4, 90, 90, 80, 83), Sig(state=True, stop=40.0))
    assert a.halted and a.breaker_at == T0 + 4 * DAY
    a.step(bar(5, 83, 84, 82, 83), Sig(state=True, stop=40.0))                       # the exit order fills at 83: flat with 8,300 in cash
    assert a.qty == 0 and a.cash == pytest.approx(8_300.0)
    return a


def test_a_research_account_resumes_by_itself_exactly_cool_off_days_after_the_trip():
    a = tripped(cool_off_days=3)
    a.step(bar(6, 83, 84, 82, 83), Sig(state=True, stop=40.0))                       # 2 days after the trip: still halted
    assert a.halted and a.pending is None
    a.step(bar(7, 83, 84, 82, 83), Sig(state=True, stop=40.0))                       # exactly 3 days after the trip: resumes at this close and may order for the next open
    assert not a.halted and a.pending is not None and a.pending["kind"] == "enter"
    resets = [e for e in a.events if e["event"] == "breaker_reset"]
    assert len(resets) == 1 and resets[0]["how"] == "cool_off" and resets[0]["equity"] == pytest.approx(8_300.0)


def test_cool_off_is_counted_in_days_not_in_seconds():
    a = tripped(cool_off_days=1)
    assert not a.halted                                                                # one day (86,400 seconds) after the trip is the very next close, which `tripped` has already stepped
    b = tripped(cool_off_days=40)
    for i in range(6, 40):
        b.step(bar(i, 83, 84, 82, 83), Sig(state=False))
    assert b.halted                                                                    # 35 days after the trip is still inside a 40-day cool-off
    b.step(bar(44, 83, 84, 82, 83), Sig(state=False))
    assert not b.halted


def test_without_a_cool_off_only_a_human_resumes_the_account():
    a = tripped()
    assert a.cool_off_days is None
    for i in range(6, 300):
        a.step(bar(i, 83, 84, 82, 83), Sig(state=True, stop=40.0))
    assert a.halted and a.qty == 0 and a.pending is None


def test_after_the_cool_off_the_peak_is_re_based_and_the_account_is_armed_again():
    a = tripped(cool_off_days=3)
    a.step(bar(6, 83, 84, 82, 83), Sig(state=True, stop=40.0))
    a.step(bar(7, 83, 84, 82, 83), Sig(state=True, stop=40.0))                       # resumed; the state has been ON all the time, yet the account enters because it is armed again
    assert a.peak == pytest.approx(8_300.0) and a.armed is True and a.pending["kind"] == "enter"
    a.step(bar(8, 83, 84, 82, 83), Sig(state=True, stop=40.0))
    assert a.qty > 0
    a.step(bar(9, 83, 83, 72, 72.5), Sig(state=True, stop=40.0))                     # 12.7% below the NEW peak (but 27% below the old one): no second trip
    assert not a.halted and len(a.breaker_trips) == 1
    a.step(bar(10, 72.5, 72.5, 70, 70.5), Sig(state=True, stop=40.0))                # 15.1% below the new peak: second trip
    assert a.halted and len(a.breaker_trips) == 2


def test_every_trip_is_recorded_even_when_the_event_log_is_off():
    a = tripped(cool_off_days=2, verbose=False)
    assert a.events == []
    assert a.breaker_trips == [{"t": T0 + 4 * DAY, "equity": pytest.approx(8_300.0), "peak": pytest.approx(10_000.0)}]


def test_a_weight_account_rebuilds_its_position_after_the_cool_off_and_after_a_human_reset():
    def run(resume):
        a = acct(kind="weight", fee=0.0, slip=0.0, **({"cool_off_days": 2} if resume == "cool_off" else {}))
        a.begin(bar(0, 100, 100, 100, 100), Sig(weight=1.0))
        a.step(bar(1, 100, 100, 100, 100), Sig(weight=1.0))                          # fully invested
        a.step(bar(2, 100, 100, 80, 80), Sig(weight=1.0))                            # 20% down: trips at this close
        assert a.halted
        a.step(bar(3, 80, 80, 80, 80), Sig(weight=1.0))                              # exit fills at 80
        assert a.qty == 0
        if resume == "human":
            a.reset_breaker()
        a.step(bar(4, 80, 80, 80, 80), Sig(weight=1.0))                              # cool-off: 2 days after the trip, resumes at this close. Human: the reset came just before. Either way an order is made at this close
        a.step(bar(5, 80, 80, 80, 80), Sig(weight=1.0))                              # and fills at this open: the same target weight as before the trip must buy again
        return a
    for how in ("cool_off", "human"):
        a = run(how)
        assert not a.halted and a.qty == pytest.approx(8_000.0 / 80.0), how


def test_a_human_reset_also_makes_a_stop_account_armed_and_rebases_the_peak():
    a = tripped()
    a.reset_breaker()
    assert not a.halted and a.armed and a.peak == pytest.approx(8_300.0)
    resets = [e for e in a.events if e["event"] == "breaker_reset"]
    assert resets[-1]["how"] == "human"


def test_the_cool_off_and_the_trip_record_survive_a_save_and_a_load():
    a = tripped(cool_off_days=7)
    b = Account.from_dict(a.to_dict())
    assert b.cool_off_days == 7 and b.breaker_trips == a.breaker_trips and b.halted and b.breaker_at == a.breaker_at
