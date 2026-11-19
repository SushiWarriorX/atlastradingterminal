"""btcquant paper engine: accounts that persist in files, a ledger that records a trade on its signal, idempotent catch-up, a refusal to step across a missing candle, and exact parity with the backtest
(stepping one candle at a time with the state saved and reloaded between steps gives the backtest's equity curve, trades and costs to the last digit)."""
import json

import numpy as np
import pytest

from atlas_api.btcquant import backtest as B
from atlas_api.btcquant import config as C
from atlas_api.btcquant import paper as P
from atlas_api.btcquant import strategies as S

DAY = 86400
T0 = 1_546_300_800                                                                      # 2019-01-01 00:00 UTC


def history(n, seed=1, start=20_000.0, vol=0.03):
    rng = np.random.default_rng(seed)
    c = start * np.exp(np.cumsum(rng.normal(0.0004, vol, n)))
    o = np.concatenate([[start], c[:-1]])
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.01, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.01, n)))
    return [(T0 + i * DAY, float(o[i]), float(h[i]), float(l[i]), float(c[i]), 100.0) for i in range(n)]


def from_closes(closes):
    o = [closes[0]] + list(closes[:-1])
    return [(T0 + i * DAY, float(o[i]), float(max(o[i], closes[i])), float(min(o[i], closes[i])), float(closes[i]), 1.0) for i in range(len(closes))]


def book(tmp_path):
    clock = iter(f"2031-03-04T10:{i // 60 % 60:02d}:{i % 60:02d}Z" for i in range(100000))
    return P.PaperBook(tmp_path / "state", now=lambda: next(clock))


# ---- opening ----

def test_opening_an_account_writes_its_state_and_the_first_ledger_rows(tmp_path):
    pb = book(tmp_path)
    prep = B.Prepared(from_closes([100.0 + i for i in range(60)]))                      # a steady rise: the 20/50 average rule is ON at the close of the last candle
    meta = pb.open("sma_cross-test", "sma_cross", {"fast": 20, "slow": 50}, prep)
    assert pb.exists("sma_cross-test") and pb.ids() == ["sma_cross-test"] and meta["last_bar"] == T0 + 59 * DAY and meta["last_bar_iso"] == "2019-03-01T00:00:00Z"
    assert meta["spec_hash"] == S.spec_hash("sma_cross", {"fast": 20, "slow": 50}) and meta["stage"] == "challenger" and meta["start_equity"] == 10_000.0
    rows = pb.ledger("sma_cross-test")
    assert [r["event"] for r in rows] == ["account_opened", "order"] and [r["seq"] for r in rows] == [1, 2]
    order = rows[1]
    assert order["kind"] == "enter" and order["reason"] == "signal" and order["signal_bar"] == T0 + 59 * DAY and order["signal_time"] == T0 + 60 * DAY and order["ref_close"] == 159.0
    assert order["info"]["close"] == 159.0 and order["info"]["sma_fast"] == pytest.approx(149.5) and order["info"]["sma_slow"] == pytest.approx(134.5) and order["stop"] < 159.0
    with pytest.raises(ValueError, match="already exists"):
        pb.open("sma_cross-test", "sma_cross", {"fast": 20, "slow": 50}, prep)


def test_the_stage_and_the_starting_balance_are_kept(tmp_path):
    pb = book(tmp_path)
    prep = B.Prepared(history(320, seed=6))
    meta = pb.open("portfolio", "cash", {}, prep, at_index=299, start_equity=100_000.0, cool_off_days=None, stage="portfolio")
    assert meta["stage"] == "portfolio" and meta["start_equity"] == 100_000.0 and meta["cool_off_days"] is None and meta["opened_at"].startswith("2031-03-04T")
    assert pb.ledger("portfolio")[0]["stage"] == "portfolio" and pb.ledger("portfolio")[0]["start_equity"] == 100_000.0
    pb.catch_up("portfolio", prep)
    a, m = pb.load("portfolio")
    assert a.curve[-1][1] == 100_000.0 and a.start_equity == 100_000.0 and a.cool_off_days is None and m["stage"] == "portfolio"
    pb.open("bench", "buy_hold", {}, prep, at_index=299, stage="benchmark")
    pb.open("big", "sma_filter", {"L": 50}, prep, at_index=299, start_equity=50_000.0)
    pb.catch_up("big", prep)
    small = B.run(prep, "sma_filter", {"L": 50}, 300, 319, start_equity=10_000.0)
    assert pb.load("bench")[1]["stage"] == "benchmark" and pb.load("big")[0].curve[-1][1] == pytest.approx(50_000.0 * (1 + small.metrics["total_return"]), rel=1e-9)


def test_an_account_that_is_off_at_opening_has_no_order(tmp_path):
    pb = book(tmp_path)
    prep = B.Prepared(from_closes([200.0 - i for i in range(60)]))
    pb.open("a", "sma_cross", {"fast": 20, "slow": 50}, prep)
    assert [r["event"] for r in pb.ledger("a")] == ["account_opened"]


# ---- catching up ----

def test_catching_up_steps_each_new_candle_once_and_is_idempotent(tmp_path):
    pb = book(tmp_path)
    cs = history(400, seed=3)
    prep = B.Prepared(cs[:300])
    pb.open("tsmom-1", "tsmom", {"L": 30}, prep)
    same = pb.catch_up("tsmom-1", prep)
    assert same["processed"] == 0 and same["last_bar"] == "2019-10-27T00:00:00Z"
    longer = B.Prepared(cs)
    first = pb.catch_up("tsmom-1", longer)
    assert first["processed"] == 100 and first["last_bar"] == "2020-02-04T00:00:00Z"
    a, meta = pb.load("tsmom-1")
    assert len(a.curve) == 100 and meta["last_bar"] == T0 + 399 * DAY
    again = pb.catch_up("tsmom-1", longer)
    assert again["processed"] == 0 and len(pb.load("tsmom-1")[0].curve) == 100
    more = B.Prepared(cs + history(410, seed=3)[400:410])
    assert pb.catch_up("tsmom-1", more)["processed"] == 10


def test_a_missing_candle_stops_the_account_there_and_says_so(tmp_path):
    pb = book(tmp_path)
    cs = history(330, seed=4)
    pb.open("t", "tsmom", {"L": 30}, B.Prepared(cs[:300]))
    pb.open("u", "tsmom", {"L": 60}, B.Prepared(cs[:300]))
    broken = B.Prepared(cs[:310] + cs[311:])                                              # candle 310 is missing from the stored data
    with pytest.raises(P.GapError, match="is missing"):
        pb.catch_up("t", broken)
    a, meta = pb.load("t")
    assert meta["last_bar"] == T0 + 309 * DAY and len(a.curve) == 10                      # it did step up to the gap, and saved there
    out = pb.catch_up_all(broken)
    assert "error" in out["t"] and "error" in out["u"] and out["u"]["id"] == "u"
    repaired = B.Prepared(cs)
    assert pb.catch_up("t", repaired)["processed"] == 20 and pb.load("t")[1]["last_bar"] == T0 + 329 * DAY


def test_catch_up_all_steps_every_account(tmp_path):
    pb = book(tmp_path)
    cs = history(320, seed=5)
    prep = B.Prepared(cs[:300])
    for i, fid in enumerate(("sma_cross", "donchian", "buy_hold", "cash")):
        pb.open(f"{fid}-x", fid, S.configs(S.FAMILIES[fid])[0], prep)
    out = pb.catch_up_all(B.Prepared(cs))
    assert sorted(out) == ["buy_hold-x", "cash-x", "donchian-x", "sma_cross-x"] and all(v["processed"] == 20 for v in out.values())


# ---- trades are recorded on signal ----

def donchian_prep():
    c = [10, 10, 10, 10, 12, 13, 14, 13, 15, 15]
    h = [10.5, 10.5, 10.5, 10.5, 12.5, 13.5, 14.5, 14.0, 15.5, 15.5]
    l = [9.5, 9.5, 9.5, 9.5, 11.0, 12.5, 13.0, 12.0, 14.0, 14.5]
    o = [10] + c[:-1]
    return B.Prepared([(T0 + i * DAY, float(o[i]), h[i], l[i], float(c[i]), 1.0) for i in range(10)])


def test_an_order_is_written_when_the_signal_is_made_and_its_fill_when_it_happens(tmp_path):
    pb = book(tmp_path)
    prep = donchian_prep()
    pb.open("d", "donchian", {"N": 4}, prep, at_index=3)
    pb.catch_up("d", prep, max_candles=1)                                                 # candle 4 completes: the breakout signal is made at its close
    rows = pb.ledger("d")
    assert [r["event"] for r in rows] == ["account_opened", "order"]
    sig = rows[1]
    assert sig["kind"] == "enter" and sig["signal_bar"] == T0 + 4 * DAY and sig["signal_time"] == T0 + 5 * DAY and sig["ref_close"] == 12.0 and sig["stop"] == 9.5
    assert sig["info"] == {"close": 12.0, "highest_high_prior_N": 10.5, "trailing_stop_candidate": 9.5}      # the numbers behind the signal
    assert sig["est_qty"] == pytest.approx(0.01 * 10_000 / (12.0 - 9.5))                                     # the size it intends at the signal: 1% of equity over the distance from the close to the stop
    pb.catch_up("d", prep, max_candles=1)                                                 # candle 5 completes: the order fills at its open
    rows = pb.ledger("d")
    fill = rows[-1] if rows[-1]["event"] == "fill" else [r for r in rows if r["event"] == "fill"][0]
    assert fill["side"] == "buy" and fill["exec_time"] == T0 + 5 * DAY and fill["order_id"] == sig["order_id"] and fill["price"] == pytest.approx(12.0 * (1 + C.SLIPPAGE))
    assert fill["qty"] == pytest.approx(0.01 * 10_000 / (12.0 * (1 + C.SLIPPAGE) - 9.5)) and fill["qty"] < sig["est_qty"] and fill["fee"] == pytest.approx(fill["qty"] * fill["price"] * C.FEE) and fill["equity_before"] == pytest.approx(10_000.0)
    pb.catch_up("d", prep)
    events = [r["event"] for r in pb.ledger("d")]
    assert events.index("order") < events.index("fill") < events.index("stop_hit") and "stop_raised" in events
    seqs = [r["seq"] for r in pb.ledger("d")]
    assert seqs == list(range(1, len(seqs) + 1)) and all(r["recorded_at"].startswith("2031-03-04T") for r in pb.ledger("d"))
    stop = [r for r in pb.ledger("d") if r["event"] == "stop_hit"][0]
    assert stop["exec_time"] == T0 + 7 * DAY and stop["stop"] == 12.5 and stop["gap"] is False


def test_a_ledger_row_is_never_written_twice(tmp_path):
    pb = book(tmp_path)
    prep = donchian_prep()
    pb.open("d", "donchian", {"N": 4}, prep, at_index=3)
    pb.catch_up("d", prep)
    n = len(pb.ledger("d"))
    pb.catch_up("d", prep)
    assert len(pb.ledger("d")) == n


# ---- parity with the backtest ----

def crash_history():
    closes = [100.0 * 1.002 ** i for i in range(300)]
    closes += [closes[-1] * 0.85, closes[-1] * 0.85 * 0.85]
    closes += [closes[-1] * 1.015 ** k for k in range(1, 260)]
    return from_closes(closes)


@pytest.mark.parametrize("fid,params,cs", [("sma_cross", {"fast": 10, "slow": 50}, None), ("donchian", {"N": 20}, None), ("ma_atr_trend", {"L": 100, "m": 3}, None), ("tsmom", {"L": 30}, None),
                                          ("rsi_oversold", {"n": 7, "enter": 30, "exit": 50}, None), ("vol_target", {"target": 0.4, "window": 20}, None), ("sma_filter", {"L": 50}, "crash"),
                                          ("buy_hold", {}, None), ("cash", {}, None)])
def test_stepping_one_candle_at_a_time_with_state_saved_between_steps_equals_the_backtest(tmp_path, fid, params, cs):
    candles = crash_history() if cs == "crash" else history(520, seed=12, vol=0.035)
    prep = B.Prepared(candles)
    i0, i1 = 300, len(candles) - 1
    ref = B.run(prep, fid, params, i0, i1, keep_account=True).account
    pb = book(tmp_path)
    pb.open("p", fid, params, prep, at_index=i0 - 1)
    for _ in range(i1 - i0 + 1):
        assert pb.catch_up("p", prep, max_candles=1)["processed"] == 1                 # a fresh load and save around every single candle
    a, meta = pb.load("p")
    assert meta["last_bar"] == candles[i1][0]
    assert a.curve == [tuple(r) for r in ref.curve]
    assert a.trades == ref.trades and a.fills == ref.fills and a.fees_paid == ref.fees_paid and a.slip_paid == ref.slip_paid and a.traded == ref.traded
    no_info = lambda od: None if od is None else {k: v for k, v in od.items() if k != "info"}                 # the paper account also keeps the numbers behind a signal; the backtest does not
    assert a.cash == ref.cash and a.qty == ref.qty and a.stop == ref.stop and no_info(a.pending) == no_info(ref.pending) and a.halted == ref.halted and a.peak == ref.peak and a.armed == ref.armed
    assert a.breaker_trips == ref.breaker_trips and a.open_trade == ref.open_trade and a.last_target == ref.last_target and a.order_seq == ref.order_seq
    if fid == "sma_filter":
        assert len(a.breaker_trips) == 1                                               # the crash series trips the breaker, so the saved breaker state was exercised too


def test_the_ledger_has_one_row_for_every_order_fill_and_stop_the_account_made(tmp_path):
    candles = history(520, seed=12, vol=0.035)
    prep = B.Prepared(candles)
    pb = book(tmp_path)
    pb.open("p", "sma_cross", {"fast": 10, "slow": 50}, prep, at_index=299)
    pb.catch_up("p", prep)
    a, _ = pb.load("p")
    rows = pb.ledger("p")
    count = lambda ev: sum(1 for r in rows if r["event"] == ev)
    assert count("fill") == a.fills and count("stop_hit") == sum(1 for t in a.trades if t["reason"] == "stop") and count("order") >= a.fills - count("stop_hit")
    orders = {r["order_id"]: r for r in rows if r["event"] == "order"}
    for r in rows:
        if r["event"] == "fill" and r["order_id"] is not None:
            assert r["order_id"] in orders and orders[r["order_id"]]["signal_time"] <= r["exec_time"]


def test_state_files_are_plain_json_with_the_curve_and_the_closed_trades(tmp_path):
    pb = book(tmp_path)
    prep = B.Prepared(history(420, seed=2, vol=0.035))
    pb.open("p", "sma_cross", {"fast": 10, "slow": 50}, prep, at_index=299)
    pb.catch_up("p", prep)
    raw = json.loads(pb.account_path("p").read_text())
    assert set(raw) == {"meta", "account"} and len(raw["account"]["curve"]) == 120 and len(raw["account"]["trades"]) == len(pb.load("p")[0].trades) and raw["meta"]["family"] == "sma_cross"
