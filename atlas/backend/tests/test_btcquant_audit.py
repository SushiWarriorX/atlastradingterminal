"""btcquant paper-account audit: worlds worked out by hand (six daily candles, three accounts: `cash` stays in cash, `buy_hold` bought and held, the monitor `sma_cross-c0f76650` bought and was stopped out), then every rule broken one at a time.
The hand-worked figures of the world (checked in the first test, outside the module): candle 0 closes at 102; both buying accounts fill at the open of candle 1, 102, moved 0.05% against the trade to 102.051;
`buy_hold` buys 90 Bitcoin (notional 9,184.59, fee 9.18459, cash left 806.22541) and the monitor (called `stopped` in the comments below) buys 50 (notional 5,102.55, fee 5.10255, cash left 4,892.34745) and is sold at the stop of 95 on candle 3
(price 94.9525, proceeds 4,747.625, fee 4.747625, cash 9,635.224825).
The three accounts carry the real specifications and fingerprints that the engine wrote on 2026-11-15 for the accounts of the same names (the fingerprint is the first 16 hexadecimal characters of the SHA-256 of the specification written as JSON with sorted keys, worked out again in the second test with `hashlib`, outside the module);
the registry of the world holds the one record a monitor needs: its specification, logged two minutes before the account opened."""
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from atlas_api.btcquant import audit as A
from atlas_api.btcquant import config as C

T0 = 1794614400                                                           # 2026-11-14 00:00 UTC
DAY = 86400
FEE, SLIP = 0.001, 0.0005
OHLC = [(100.0, 105.0, 95.0, 102.0), (102.0, 110.0, 100.0, 108.0), (108.0, 112.0, 104.0, 110.0), (110.0, 111.0, 90.0, 92.0), (92.0, 96.0, 91.0, 95.0), (95.0, 99.0, 94.0, 97.0)]
GAP_CANDLE = (90.0, 94.0, 88.0, 92.0)                                     # candle 3 in the gap world: it opens below the stop of 95
STOPPED = "sma_cross-c0f76650"                                            # the monitor of the world: <family>-<first 8 characters of its fingerprint>
OPENED_AT, LOGGED_AT = "2026-11-15T10:36:08Z", "2026-11-15T10:34:08Z"     # the real times: the specification was logged two minutes before the account opened
WHO = {"cash": ("cash", {}, "benchmark", "1e5761cabd51ba39"), "buy_hold": ("buy_hold", {}, "benchmark", "f47fc86f454d2ac6"), STOPPED: ("sma_cross", {"fast": 10, "slow": 50}, "monitor", "c0f76650213f0d13")}     # id: (family, parameters, stage, fingerprint)


def spec_of(family, params):
    """The specification the engine writes for a family at protocol 1.2, version 1 (the keys and values of the real accounts)."""
    return {"atr_n": 14, "band": 0.1, "breaker": 0.15, "cool_off": 30, "family": family, "fee": 0.001, "params": params, "protocol": "1.2", "risk": 0.01, "slippage": 0.0005, "stop_k": 3.0, "version": 1}


def bar(i):
    return T0 + i * DAY


def fill_row(aid, seq, n, side, i, ref, qty, cash, held, reason):
    sign = 1 if side == "buy" else -1
    price = ref * (1 + sign * SLIP)
    notional = qty * price
    fee = notional * FEE
    row = {"account": aid, "event": "fill", "order_id": n, "side": side, "reason": reason, "exec_time": bar(i), "ref_price": ref, "price": price, "qty": qty, "fee": fee,
           "slippage_cost": qty * abs(price - ref), "cash_after": cash - (notional + fee) if sign == 1 else cash + (notional - fee), "qty_after": held + sign * qty, "recorded_at": "2026-11-17T04:18:55Z", "seq": seq}
    return row, row["cash_after"], row["qty_after"]


def opened_row(aid, start=10000.0):
    family, params, stage, fingerprint = WHO[aid]
    return {"account": aid, "after_candle": "2026-11-14T00:00:00Z", "event": "account_opened", "family": family, "params": params, "recorded_at": OPENED_AT, "seq": 1, "spec_hash": fingerprint, "stage": stage, "start_equity": start}


def order_row(aid, seq, n, kind, ref_close, **kw):
    return {"account": aid, "event": "order", "kind": kind, "order_id": n, "reason": "signal", "recorded_at": "2026-11-15T10:36:08Z", "ref_close": ref_close, "seq": seq, "signal_bar": bar(0), "signal_time": bar(1), **kw}


def curve_rows(candles, steps, start):
    """One row a day from candle 1 to the last: (day, equity, exposure, cash, quantity, close, open exposure), with the cash and quantity that `steps` ({candle index: (cash, quantity)}) set on or before that day."""
    cash, qty, rows = start, 0.0, []
    for i in range(1, len(candles)):
        cash, qty = steps.get(i, (cash, qty))
        close = candles[i][3]
        eq = cash + qty * close
        rows.append([bar(i), eq, qty * close / eq, cash, qty, close, 0.0])
    return rows


def account(aid, ledger, candles, steps, pending=None, start=10000.0):
    fills = [e for e in ledger if e["event"] == "fill"]
    curve = curve_rows(candles, steps, start)
    last = curve[-1]
    acc = {"id": aid, "start_equity": start, "cash": last[3], "qty": last[4], "fees_paid": sum(f["fee"] for f in fills), "slip_paid": sum(f["slippage_cost"] for f in fills),
           "traded": sum(f["qty"] * f["price"] for f in fills), "fills": len(fills), "curve": curve, "last_bar": last[0], "pending": pending, "stop": None, "kind": "x"}
    family, params, stage, fingerprint = WHO[aid]
    return {"account": acc, "meta": {"id": aid, "start_equity": start, "stage": stage, "last_bar": last[0], "opened_after_candle": "2026-11-14T00:00:00Z", "opened_at": OPENED_AT,
                                     "family": family, "params": params, "version": 1, "spec": spec_of(family, params), "spec_hash": fingerprint}}


def registered(aid):
    """The record the registry holds for an account that trades a registered specification."""
    family, params, _, fingerprint = WHO[aid]
    return {"decision": "rejected", "family": family, "logged_at": LOGGED_AT, "params": params, "protocol": "1.2", "spec": spec_of(family, params), "spec_hash": fingerprint}


def make_world(gap=False):
    candles = list(OHLC)
    if gap:
        candles[3] = GAP_CANDLE
    ledgers, accounts = {}, {}
    ledgers["cash"] = [opened_row("cash")]
    accounts["cash"] = account("cash", ledgers["cash"], candles, {})
    hold = [opened_row("buy_hold"), order_row("buy_hold", 2, 1, "rebalance", 102.0, weight=1.0)]
    f, cash, held = fill_row("buy_hold", 3, 1, "buy", 1, 102.0, 90.0, 10000.0, 0.0, "signal")
    ledgers["buy_hold"] = hold + [f]
    accounts["buy_hold"] = account("buy_hold", ledgers["buy_hold"], candles, {1: (cash, held)})
    stopped = [opened_row(STOPPED), order_row(STOPPED, 2, 1, "enter", 102.0, stop=95.0, est_qty=50.0, info={})]
    f1, cash1, held1 = fill_row(STOPPED, 3, 1, "buy", 1, 102.0, 50.0, 10000.0, 0.0, "signal")
    o3, h3 = candles[3][0], candles[3][2]
    hit = {"account": STOPPED, "event": "stop_hit", "exec_time": bar(3), "stop": 95.0, "open": o3, "low": h3, "gap": o3 <= 95.0, "recorded_at": "2026-11-17T04:18:55Z", "seq": 4}
    f2, cash2, held2 = fill_row(STOPPED, 5, None, "sell", 3, o3 if o3 <= 95.0 else 95.0, 50.0, cash1, held1, "stop")
    ledgers[STOPPED] = stopped + [f1, hit, f2]
    accounts[STOPPED] = account(STOPPED, ledgers[STOPPED], candles, {1: (cash1, held1), 3: (cash2, held2)})
    dash = {"accounts": [{"id": k, "equity": accounts[k]["account"]["curve"][-1][1]} for k in accounts]}
    return {"candles": candles, "ledgers": ledgers, "accounts": accounts, "dashboard": dash, "registry": [registered(STOPPED)]}


def write(world, root):
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "state" / "accounts").mkdir(parents=True, exist_ok=True)
    (root / "state" / "ledger").mkdir(parents=True, exist_ok=True)
    rows = ["t,o,h,l,c,v"] + [f"{bar(i)},{o!r},{h!r},{l!r},{c!r},1.0" for i, (o, h, l, c) in enumerate(world["candles"])]
    (root / "data" / "btcusd_1d.csv").write_text("\n".join(rows) + "\n")
    (root / "dashboard.json").write_text(json.dumps(world["dashboard"]))
    if "registry" in world:
        (root / "registry").mkdir(parents=True, exist_ok=True)
        (root / "registry" / "candidates.jsonl").write_text("".join(json.dumps(r) + "\n" for r in world["registry"]))
    for aid, doc in world["accounts"].items():
        (root / "state" / "accounts" / f"{aid}.json").write_text(json.dumps(doc))
    for aid, rows in world["ledgers"].items():
        (root / "state" / "ledger" / f"{aid}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return root


def problems(world, tmp_path):
    return A.audit(write(world, tmp_path))["problems"]


def test_the_world_is_the_one_worked_out_by_hand_and_passes_every_rule(tmp_path):
    w = make_world()
    f = w["ledgers"]["buy_hold"][2]
    assert (f["price"], f["qty"], f["cash_after"]) == (pytest.approx(102.051), 90.0, pytest.approx(806.22541)) and f["fee"] == pytest.approx(9.18459) and f["slippage_cost"] == pytest.approx(4.59)
    b, s = w["ledgers"][STOPPED][2], w["ledgers"][STOPPED][4]
    assert (b["cash_after"], b["fee"]) == (pytest.approx(4892.34745), pytest.approx(5.10255)) and (s["price"], s["fee"], s["cash_after"], s["qty_after"]) == (pytest.approx(94.9525), pytest.approx(4.747625), pytest.approx(9635.224825), 0.0)
    assert [round(r[1], 6) for r in w["accounts"]["buy_hold"]["account"]["curve"]] == [round(806.22541 + 90 * c, 6) for c in (108.0, 110.0, 92.0, 95.0, 97.0)]
    assert [round(r[1], 6) for r in w["accounts"][STOPPED]["account"]["curve"]] == [round(4892.34745 + 50 * 108.0, 6), round(4892.34745 + 50 * 110.0, 6)] + [pytest.approx(9635.224825)] * 3
    r = A.audit(write(w, tmp_path))
    assert r["problems"] == [] and (r["accounts"], r["fills"], r["curve_days"], r["candles"]) == (3, 3, 15, 6) and (r["first_candle"], r["last_candle"]) == ("2026-11-14", "2026-11-19")
    assert all(v == 0.0 for v in r["worst"].values())                                                                       # the replay does the engine's arithmetic in its order: no difference at all


def test_a_stop_out_through_a_gap_fills_at_the_open_and_passes(tmp_path):
    w = make_world(gap=True)
    s = w["ledgers"][STOPPED][4]
    assert s["ref_price"] == 90.0 and s["price"] == pytest.approx(89.955)                                                      # the candle opens at 90, below the stop of 95: the sale is at the open, moved 0.05%
    assert problems(w, tmp_path) == []


def test_the_real_paper_accounts_of_the_repository_pass_the_audit():
    r = A.audit()
    assert r["problems"] == [] and r["accounts"] >= 18 and r["fills"] >= 5 and r["candles"] > 2800                                # the stored state of the system itself is what the audit is for


def test_the_protocol_figures_are_the_ones_of_the_configuration():
    assert (A.FEE, A.SLIPPAGE, A.DAY) == (C.FEE, C.SLIPPAGE, C.DAY) == (0.001, 0.0005, 86400)                                 # an amendment of the protocol must be followed here on purpose
    assert (A.TOL, A.TOL_PRICE) == (1e-9, 1e-12)


def check(world, tmp_path, change, expected, only=None):
    change(world)
    found = problems(world, tmp_path)
    assert any(expected in p for p in found), (expected, found)
    if only is not None:
        assert len(found) == only, found
    return found


def test_a_ledger_that_does_not_begin_with_its_opening_is_refused(tmp_path):
    check(make_world(), tmp_path, lambda w: w["ledgers"]["buy_hold"][0].update(event="order"), "buy_hold: the ledger does not begin with exactly one account_opened", only=1)


def test_a_second_opening_in_the_ledger_is_refused(tmp_path):
    def change(w):
        w["ledgers"]["buy_hold"].append({**opened_row("buy_hold"), "seq": 4})
    check(make_world(), tmp_path, change, "buy_hold: the ledger does not begin with exactly one account_opened", only=1)


def test_an_empty_ledger_and_an_opening_that_is_not_the_first_row_are_refused_in_the_same_words(tmp_path):
    words = "buy_hold: the ledger does not begin with exactly one account_opened"
    check(make_world(), tmp_path / "a", lambda w: w["ledgers"]["buy_hold"].clear(), words, only=1)

    def swap(w):
        rows = w["ledgers"]["buy_hold"]
        rows[0], rows[1] = rows[1], rows[0]                                                                                    # one opening, but after the order
    check(make_world(), tmp_path / "b", swap, words, only=1)


def test_an_account_whose_ledger_cannot_be_replayed_counts_no_fill_and_no_curve_day(tmp_path):
    w = make_world()
    w["ledgers"]["buy_hold"].append({**opened_row("buy_hold"), "seq": 4})
    r = A.audit(write(w, tmp_path))
    assert r["problems"] == ["buy_hold: the ledger does not begin with exactly one account_opened"]
    assert (r["accounts"], r["fills"], r["curve_days"]) == (3, 2, 10)                                                          # the other two are replayed: 2 fills (stopped) and 10 days (5 each)


def test_the_account_file_and_its_meta_carry_the_id_of_the_file_and_every_ledger_row_names_the_account(tmp_path):
    found = check(make_world(), tmp_path / "a", lambda w: w["accounts"]["buy_hold"]["account"].update(id=STOPPED), f"buy_hold: the account file says it is {STOPPED}")
    assert f"{STOPPED}: its meta says it is buy_hold" in found and f"{STOPPED}: 3 row(s) of its ledger name another account (the first, row 1, names buy_hold)" in found      # the rest of the account is then judged by the id it claims
    check(make_world(), tmp_path / "b", lambda w: w["accounts"]["buy_hold"]["meta"].update(id="cash"), "buy_hold: its meta says it is cash", only=1)
    check(make_world(), tmp_path / "c", lambda w: w["accounts"]["buy_hold"]["meta"].pop("id"), "buy_hold: its meta says it is None", only=1)

    def two_foreign_rows(w):
        w["ledgers"]["buy_hold"][1]["account"] = STOPPED
        w["ledgers"]["buy_hold"][2]["account"] = "cash"
    check(make_world(), tmp_path / "d", two_foreign_rows, f"buy_hold: 2 row(s) of its ledger name another account (the first, row 2, names {STOPPED})", only=1)
    check(make_world(), tmp_path / "e", lambda w: w["ledgers"]["buy_hold"][1].pop("account"), "buy_hold: 1 row(s) of its ledger name another account (the first, row 2, names None)", only=1)


def test_the_rows_of_a_ledger_are_numbered_without_a_gap(tmp_path):
    check(make_world(), tmp_path, lambda w: w["ledgers"]["buy_hold"][2].update(seq=9), "buy_hold: the ledger's rows are not numbered 1, 2, 3 ...", only=1)


def test_the_start_equity_is_the_same_in_the_ledger_the_account_and_the_meta(tmp_path):
    for place in ("ledger", "account", "meta"):
        w = make_world()
        if place == "ledger":
            w["ledgers"]["cash"][0]["start_equity"] = 10001.0
        elif place == "account":
            w["accounts"]["cash"]["account"]["start_equity"] = 10001.0
        else:
            w["accounts"]["cash"]["meta"]["start_equity"] = 10001.0
        found = problems(w, tmp_path / place)
        assert any(p.startswith("cash: the start equity differs: ledger") for p in found), (place, found)


def test_a_fill_must_have_its_order_and_sit_on_a_stored_candle(tmp_path):
    w = make_world()
    w["ledgers"]["buy_hold"].pop(1)
    for i, r in enumerate(w["ledgers"]["buy_hold"]):
        r["seq"] = i + 1
    found = problems(w, tmp_path / "a")
    assert found == ["buy_hold: the fill of order 1 has no order in the ledger"]
    check(make_world(), tmp_path / "b", lambda w: w["ledgers"]["buy_hold"][2].update(exec_time=bar(1) + 1), f"buy_hold: the fill at {bar(1) + 1} is not on a stored candle")


def test_a_fill_happens_on_the_day_after_its_signal_bar_as_the_order_says(tmp_path):
    day = lambda i: datetime.fromtimestamp(bar(i), timezone.utc).strftime("%Y-%m-%d")
    check(make_world(), tmp_path / "a", lambda w: w["ledgers"]["buy_hold"][1].update(signal_time=bar(2)),
          f"buy_hold: order 1 was signalled on {day(0)} for {day(2)} and filled on {day(1)}, not at the open of the day after its signal bar")
    check(make_world(), tmp_path / "b", lambda w: w["ledgers"]["buy_hold"][1].update(signal_bar=bar(0) - DAY, signal_time=bar(1)),
          f"buy_hold: order 1 was signalled on {day(-1)} for {day(1)} and filled on {day(1)}, not at the open of the day after its signal bar")


def test_the_order_refers_to_the_close_of_its_signal_bar_and_the_fill_to_the_open_of_its_candle(tmp_path):
    check(make_world(), tmp_path / "a", lambda w: w["ledgers"]["buy_hold"][1].update(ref_close=102.01), "buy_hold: order 1: its reference close 102.01 is not the close of its signal bar 102.0", only=1)
    check(make_world(), tmp_path / "b", lambda w: w["ledgers"]["buy_hold"][2].update(ref_price=102.01), "buy_hold: the fill of order 1 refers to 102.01, not the open 102.0 of its candle")


def test_the_price_is_the_reference_moved_against_the_trade_by_the_slippage_for_a_purchase_and_for_a_sale(tmp_path):
    for aid, idx in (("buy_hold", 2), (STOPPED, 4)):
        w = make_world()
        row = w["ledgers"][aid][idx]
        row["price"] = row["ref_price"] * (1 + (1 if row["side"] == "sell" else -1) * SLIP)                               # the move the wrong way round
        found = problems(w, tmp_path / aid)
        assert any("is at" in p and "not the reference moved by 0.05% against the trade" in p for p in found), (aid, found)


def test_the_fee_is_a_tenth_of_a_percent_of_the_notional_and_the_slippage_cost_the_quantity_times_the_move(tmp_path):
    check(make_world(), tmp_path / "a", lambda w: w["ledgers"]["buy_hold"][2].update(fee=9.0), "buy_hold: the fee of the fill on 2026-11-15 is 9.0, not 0.10% of its notional")
    check(make_world(), tmp_path / "b", lambda w: w["ledgers"]["buy_hold"][2].update(slippage_cost=4.0), "buy_hold: the slippage cost of the fill on 2026-11-15 is 4.0, not the quantity times the price move")


def test_the_cash_and_the_quantity_after_a_fill_are_what_the_replay_says(tmp_path):
    check(make_world(), tmp_path / "a", lambda w: w["ledgers"]["buy_hold"][2].update(cash_after=806.0), "buy_hold: after the fill on 2026-11-15 the replay holds")
    check(make_world(), tmp_path / "b", lambda w: w["ledgers"]["buy_hold"][2].update(qty_after=89.0), "buy_hold: after the fill on 2026-11-15 the replay holds")


def test_an_account_may_not_sell_more_than_it_holds_or_spend_more_than_it_has(tmp_path):
    def sell_too_much(w):
        s = w["ledgers"][STOPPED][4]
        s["qty"] = 60.0
        s["qty_after"] = 50.0 - 60.0
    found = check(make_world(), tmp_path / "a", sell_too_much, "would hold -10.0 Bitcoin")
    assert any("(a short or leverage)" in p for p in found)

    def spend_too_much(w):
        b = w["ledgers"]["buy_hold"][2]
        b["qty"] = 200.0
        b["cash_after"] = 10000.0 - 200.0 * b["price"] - b["fee"]
    check(make_world(), tmp_path / "b", spend_too_much, "(a short or leverage)")


def test_the_totals_of_the_account_file_are_those_of_the_ledger(tmp_path):
    for key, new in (("cash", 1.0), ("qty", 1.0)):
        w = make_world()
        w["accounts"]["buy_hold"]["account"][key] += new
        found = problems(w, tmp_path / key)
        assert any(p.startswith("buy_hold: the account file holds") for p in found), (key, found)
    for key, new in (("fees_paid", 1.0), ("slip_paid", 1.0), ("traded", 1.0), ("fills", 5)):
        w = make_world()
        w["accounts"]["buy_hold"]["account"][key] = w["accounts"]["buy_hold"]["account"][key] + new if key != "fills" else new
        found = problems(w, tmp_path / key)
        assert any(p.startswith("buy_hold: fees, slippage, volume or number of fills differ") for p in found), (key, found)


def test_a_stop_out_needs_its_stop_hit_its_stop_a_low_that_reached_it_and_the_right_reference(tmp_path):
    check(make_world(), tmp_path / "a", lambda w: w["ledgers"][STOPPED].pop(3), f"{STOPPED}: the stop-out of 2026-11-17 has no stop_hit row")
    check(make_world(), tmp_path / "b", lambda w: w["ledgers"][STOPPED][4].update(side="buy"), f"{STOPPED}: a fill with no order on 2026-11-17 is not a stop-out sale")
    check(make_world(), tmp_path / "c", lambda w: w["ledgers"][STOPPED][4].update(reason="signal"), f"{STOPPED}: a fill with no order on 2026-11-17 is not a stop-out sale")

    def low_never_reached(w):
        w["candles"][3] = (110.0, 111.0, 96.0, 92.0)
        w["ledgers"][STOPPED][3]["low"] = 96.0
    check(make_world(), tmp_path / "d", low_never_reached, f"{STOPPED}: the stop-out of 2026-11-17: the low 96.0 of that candle never reached the stop 95.0")
    check(make_world(), tmp_path / "e", lambda w: w["ledgers"][STOPPED][3].update(open=111.0), f"{STOPPED}: the stop-out of 2026-11-17: its row has the open 111.0 and low 90.0, the candle has 110.0 and 90.0")
    check(make_world(), tmp_path / "f", lambda w: w["ledgers"][STOPPED][3].update(low=91.0), f"{STOPPED}: the stop-out of 2026-11-17: its row has the open 110.0 and low 91.0, the candle has 110.0 and 90.0")
    check(make_world(), tmp_path / "g", lambda w: w["ledgers"][STOPPED][4].update(ref_price=96.0), f"{STOPPED}: the stop-out of 2026-11-17 refers to 96.0, but the stop is 95.0 and the open 110.0: it should fill at 95.0")
    w = make_world(gap=True)
    w["ledgers"][STOPPED][4]["ref_price"] = 95.0                                                                         # a gap through the stop fills at the open, not at the stop
    found = problems(w, tmp_path / "h")
    assert any("it should fill at 90.0" in p for p in found), found


def test_a_candle_whose_low_is_exactly_the_stop_has_reached_it(tmp_path):
    w = make_world()
    w["candles"][3] = (110.0, 111.0, 95.0, 92.0)
    w["ledgers"][STOPPED][3]["low"] = 95.0
    assert problems(w, tmp_path) == []


def test_the_curve_follows_the_days_and_starts_the_day_after_the_opening_candle(tmp_path):
    check(make_world(), tmp_path / "a", lambda w: w["accounts"]["cash"]["account"]["curve"].pop(1), "cash: the curve jumps from 2026-11-15 to 2026-11-17")
    check(make_world(), tmp_path / "b", lambda w: w["accounts"]["cash"]["account"]["curve"].pop(0), "cash: the curve starts on 2026-11-16, not the day after the candle the account opened after (2026-11-14)")

    def shift(w):
        w["accounts"]["cash"]["account"]["curve"][0][0] += 1
    found = check(make_world(), tmp_path / "c", shift, "cash: the curve day")
    assert any("is not a stored candle" in p for p in found)


def test_every_day_of_the_curve_has_the_stored_close_the_ledgers_cash_and_quantity_and_its_equity_and_exposure(tmp_path):
    for col, new, expected in ((5, 108.5, "curve day 2026-11-15: the close is 108.5, the stored close 108.0"), (3, 806.0, "curve day 2026-11-15: it holds 806.0 cash and 90.0 Bitcoin"),
                               (4, 89.0, "Bitcoin, the ledger says"), (1, 10000.0, "curve day 2026-11-15: the equity is 10000.0, not cash plus quantity times the close"),
                               (2, 0.5, "curve day 2026-11-15: the exposure is 0.5, not the Bitcoin's share of the equity")):
        w = make_world()
        w["accounts"]["buy_hold"]["account"]["curve"][0][col] = new
        found = problems(w, tmp_path / str(col))
        assert any(expected in p for p in found), (col, found)


def test_the_last_bar_is_the_same_in_the_curve_the_account_and_the_meta(tmp_path):
    check(make_world(), tmp_path / "a", lambda w: w["accounts"]["cash"]["account"].update(last_bar=bar(4)), "cash: the last bar differs: the curve ends on")
    check(make_world(), tmp_path / "b", lambda w: w["accounts"]["cash"]["meta"].update(last_bar=bar(4)), "cash: the last bar differs: the curve ends on")
    check(make_world(), tmp_path / "c", lambda w: w["accounts"]["cash"]["account"]["curve"].pop(), "cash: the last bar differs: the curve ends on", only=1)             # a curve that stops a day early, the account and the meta agreeing on the later day


def test_an_account_with_no_curve_yet_has_no_last_bar_and_its_meta_is_the_candle_it_opened_after(tmp_path):
    def fresh(w):
        a = w["accounts"]["cash"]
        a["account"].update(curve=[], last_bar=None, cash=10000.0, qty=0.0)
        a["meta"]["last_bar"] = bar(0)
        w["dashboard"]["accounts"] = [d for d in w["dashboard"]["accounts"]]
    w = make_world()
    fresh(w)
    found = problems(w, tmp_path / "a")
    assert found == ["cash: the account is 5 day(s) behind the newest stored candle (2026-11-19)"]                              # only the world's five later candles make it late
    w = make_world()
    fresh(w)
    w["candles"] = w["candles"][:1]
    for k in ("buy_hold", STOPPED):
        w["accounts"].pop(k)
        w["ledgers"].pop(k)
    w["dashboard"]["accounts"] = [d for d in w["dashboard"]["accounts"] if d["id"] == "cash"]
    assert problems(w, tmp_path / "b") == []                                                                                  # candle 0 only: nothing to step yet, nothing wrong
    w["accounts"]["cash"]["meta"]["last_bar"] = bar(1)
    found = problems(w, tmp_path / "c")
    assert any("an account with no curve should have no last bar" in p for p in found), found
    w["accounts"]["cash"]["meta"]["last_bar"] = bar(0)
    w["accounts"]["cash"]["account"]["last_bar"] = bar(0)
    found = problems(w, tmp_path / "d")
    assert any("an account with no curve should have no last bar" in p for p in found), found


def test_an_account_may_not_be_behind_the_newest_stored_candle(tmp_path):
    w = make_world()
    for k in w["accounts"]:
        a = w["accounts"][k]
        a["account"]["curve"] = a["account"]["curve"][:-2]
        a["account"]["last_bar"] = a["account"]["curve"][-1][0]
        a["meta"]["last_bar"] = a["account"]["curve"][-1][0]
        a["account"]["cash"], a["account"]["qty"] = a["account"]["curve"][-1][3], a["account"]["curve"][-1][4]
    w["dashboard"] = {"accounts": [{"id": k, "equity": w["accounts"][k]["account"]["curve"][-1][1]} for k in w["accounts"]]}
    found = problems(w, tmp_path)
    assert "cash: the account is 2 day(s) behind the newest stored candle (2026-11-19)" in found and "buy_hold: the account is 2 day(s) behind the newest stored candle (2026-11-19)" in found


def test_a_single_day_behind_the_newest_stored_candle_is_already_late(tmp_path):
    w = make_world()
    w["candles"].append((97.0, 98.0, 96.0, 97.5))                                                                                # one more candle than the accounts have stepped through
    assert problems(w, tmp_path) == [f"{k}: the account is 1 day(s) behind the newest stored candle (2026-11-20)" for k in ("buy_hold", "cash", STOPPED)]


def test_a_pending_order_is_in_the_ledger_and_not_yet_filled(tmp_path):
    def pending(w):
        w["accounts"]["cash"]["account"]["pending"] = {"id": 7}
    check(make_world(), tmp_path / "a", pending, "cash: the pending order 7 is not in the ledger or has been filled already", only=1)
    check(make_world(), tmp_path / "b", lambda w: w["accounts"]["buy_hold"]["account"].update(pending={"id": 1}), "buy_hold: the pending order 1 is not in the ledger or has been filled already", only=1)

    def waiting(w):
        w["ledgers"]["cash"].append(order_row("cash", 2, 1, "enter", 102.0, stop=90.0))
        w["accounts"]["cash"]["account"]["pending"] = {"id": 1}
    assert problems((lambda w: (waiting(w), w)[1])(make_world()), tmp_path / "c") == []


def test_the_dashboard_has_every_account_and_the_equity_of_the_curves_last_day(tmp_path):
    def drop(w):
        w["dashboard"]["accounts"] = [d for d in w["dashboard"]["accounts"] if d["id"] != "buy_hold"]
    check(make_world(), tmp_path / "a", drop, "buy_hold: it is not in the dashboard", only=1)
    check(make_world(), tmp_path / "b", lambda w: w["dashboard"]["accounts"][1].update(equity=1.0), f"buy_hold: the dashboard shows the equity 1.0, the curve's last day {make_world()['accounts']['buy_hold']['account']['curve'][-1][1]}", only=1)
    check(make_world(), tmp_path / "c", lambda w: w["dashboard"]["accounts"].append({"id": "ghost", "equity": 1.0}), "ghost: it is in the dashboard but has no account file", only=1)


def test_the_tolerances_sit_where_the_module_says(tmp_path):
    for factor, ok in ((1 + 1e-10, True), (1 + 1e-8, False)):                                                                 # relative 1e-9 for amounts
        w = make_world()
        w["ledgers"]["buy_hold"][2]["cash_after"] *= factor
        found = problems(w, tmp_path / f"cash{ok}")
        assert (not any("the replay holds" in p for p in found)) is ok, (factor, found)
    for factor, ok in ((1 + 1e-14, True), (1 + 1e-10, False)):                                                                # relative 1e-12 for prices
        w = make_world()
        w["ledgers"]["buy_hold"][2]["ref_price"] *= factor
        w["ledgers"]["buy_hold"][2]["price"] = w["ledgers"]["buy_hold"][2]["ref_price"] * (1 + SLIP)
        found = problems(w, tmp_path / f"price{ok}")
        assert (not any("not the open" in p for p in found)) is ok, (factor, found)
    w = make_world()
    w["accounts"]["buy_hold"]["account"]["curve"][0][5] *= 1 + 1e-10
    assert any("the close is" in p for p in problems(w, tmp_path / "close"))


def scale(container, key, factor):
    container[key] *= factor


@pytest.mark.parametrize("name, change, words", [
    ("price", lambda w: scale(w["ledgers"]["buy_hold"][2], "price", 1 + 1e-10), "not the reference moved by 0.05% against the trade"),                      # relative 1e-12 for a price: a ten-billionth is a difference
    ("fee", lambda w: scale(w["ledgers"]["buy_hold"][2], "fee", 1 + 1e-7), "buy_hold: the fee of the fill on 2026-11-15 is"),                                       # relative 1e-9 for an amount
    ("stop reference", lambda w: scale(w["ledgers"][STOPPED][4], "ref_price", 1 + 1e-9), "it should fill at 95.0"),
    ("curve equity", lambda w: scale(w["accounts"]["buy_hold"]["account"]["curve"][0], 1, 1 + 1e-7), "curve day 2026-11-15: the equity is"),
    ("dashboard equity", lambda w: scale(w["dashboard"]["accounts"][1], "equity", 1 + 1e-7), "buy_hold: the dashboard shows the equity"),
])
def test_a_difference_just_beyond_the_tolerance_is_reported_for_every_kind_of_figure(tmp_path, name, change, words):
    w = make_world()
    change(w)
    found = problems(w, tmp_path)
    assert any(words in p for p in found), (name, found)


def test_a_small_negative_cash_is_leverage_too(tmp_path):
    w = make_world()
    b = w["ledgers"]["buy_hold"][2]
    b["qty"] = 98.0                                                                                                              # 98 x 102.051 = 10,000.998 and a fee of 10.000998: eleven dollars more than the account has
    notional = 98.0 * b["price"]
    b["fee"], b["slippage_cost"], b["qty_after"] = notional * FEE, 98.0 * abs(b["price"] - b["ref_price"]), 98.0
    b["cash_after"] = 10000.0 - notional - b["fee"]
    found = problems(w, tmp_path)
    assert any(p.startswith("buy_hold: after the fill on 2026-11-15 the account would hold 98.0 Bitcoin and -10.99") and p.endswith("cash (a short or leverage)") for p in found), found


def test_two_numbers_are_the_same_within_a_tolerance_that_grows_with_the_larger_of_them():
    assert A._same(0.0, 0.125, 0.125) and not A._same(0.0, 0.25, 0.125)                                                          # below 1 the tolerance is absolute, and its edge counts as the same
    assert A._same(15.0, 16.0, 2 ** -4) and A._same(16.0, 15.0, 2 ** -4) and not A._same(15.0, 17.0, 2 ** -4)                  # 1 is exactly a sixteenth of 16, whichever number comes first


def worst_cash(w, big, small):
    w["ledgers"]["buy_hold"][2]["cash_after"] += big
    w["ledgers"][STOPPED][4]["cash_after"] += small


def worst_qty(w, big, small):
    w["ledgers"]["buy_hold"][2]["qty_after"] += big
    w["ledgers"][STOPPED][4]["qty_after"] += small


def worst_price(w, big, small):
    w["ledgers"]["buy_hold"][2]["price"] += big
    w["ledgers"][STOPPED][4]["price"] += small


def worst_fee(w, big, small):
    w["ledgers"]["buy_hold"][2]["fee"] += big
    w["ledgers"][STOPPED][4]["fee"] += small


def worst_equity(w, big, small):
    curve = w["accounts"]["buy_hold"]["account"]["curve"]
    curve[0][1] += big
    curve[1][1] += small


@pytest.mark.parametrize("key, apply", [("cash", worst_cash), ("qty", worst_qty), ("price", worst_price), ("fee", worst_fee), ("equity", worst_equity)])
def test_the_summary_shows_the_largest_difference_of_each_kind_not_the_last_or_the_smallest(tmp_path, key, apply):
    w = make_world()
    apply(w, 0.5, 0.25)                                                                                                          # the larger difference comes first, the smaller after it
    assert A.audit(write(w, tmp_path))["worst"][key] == pytest.approx(0.5)


def test_an_account_worth_nothing_is_audited_without_dividing_by_zero(tmp_path):
    w = make_world()
    w["ledgers"]["cash"][0]["start_equity"] = 0.0
    a = w["accounts"]["cash"]
    a["account"].update(start_equity=0.0, cash=0.0)
    a["meta"]["start_equity"] = 0.0
    for row in a["account"]["curve"]:
        row[1:5] = [0.0, 0.0, 0.0, 0.0]                                                                                          # equity, exposure, cash, quantity
    w["dashboard"]["accounts"][0]["equity"] = 0.0
    assert problems(w, tmp_path) == []


def test_a_file_in_another_layout_is_a_problem_not_a_crash(tmp_path):
    words = "buy_hold: its files are not in the layout the audit reads (a field is missing or has the wrong type)"

    def broken(w):
        del w["accounts"]["buy_hold"]["account"]["fees_paid"]
    check(make_world(), tmp_path / "a", broken, words, only=1)
    check(make_world(), tmp_path / "b", lambda w: w["accounts"]["buy_hold"].pop("meta"), "buy_hold: the account file lacks its account, its meta or its id", only=1)
    check(make_world(), tmp_path / "c", lambda w: w["ledgers"]["buy_hold"][2].pop("qty"), words, only=1)
    w = make_world()
    w["accounts"]["buy_hold"] = []                                                                                                   # an account file whose JSON is a list: a TypeError at the very first look
    assert problems(w, tmp_path / "d") == ["buy_hold: the account file lacks its account, its meta or its id"]


def a_curve_that_is_not_a_list(w):
    w["accounts"]["buy_hold"]["account"]["curve"] = None


def a_curve_row_of_three_values(w):
    w["accounts"]["buy_hold"]["account"]["curve"][0] = [bar(1), 1.0, 0.0]


def a_ledger_row_that_is_a_number(w):
    w["ledgers"]["buy_hold"].append(5)


def a_pending_order_that_is_a_word(w):
    w["accounts"]["buy_hold"]["account"]["pending"] = "soon"


def a_field_that_is_missing(w):
    del w["accounts"]["buy_hold"]["account"]["fees_paid"]


@pytest.mark.parametrize("damage", [a_curve_that_is_not_a_list, a_curve_row_of_three_values, a_ledger_row_that_is_a_number, a_pending_order_that_is_a_word, a_field_that_is_missing])
def test_every_kind_of_damaged_layout_is_one_problem_for_its_account_and_counts_nothing(tmp_path, damage):
    w = make_world()
    damage(w)                                                                                                                    # a TypeError, a ValueError, two AttributeErrors and a KeyError, in that order
    r = A.audit(write(w, tmp_path))
    assert r["problems"] == ["buy_hold: its files are not in the layout the audit reads (a field is missing or has the wrong type)"]
    assert (r["accounts"], r["fills"], r["curve_days"]) == (3, 2, 10)                                                            # the other two accounts are replayed all the same


@pytest.mark.parametrize("damage, words", [
    (lambda root: (root / "data" / "btcusd_1d.csv").unlink(), "the stored candles cannot be read: "),
    (lambda root: (root / "data" / "btcusd_1d.csv").write_text("a,b\n1,2\n"), "the stored candles are not in the expected layout (t, o, h, l, c, v): "),                            # a KeyError: no column t
    (lambda root: (root / "data" / "btcusd_1d.csv").write_text("t,o,h,l,c,v\n1,abc,2,3,4,5\n"), "the stored candles are not in the expected layout (t, o, h, l, c, v): "),                 # a ValueError: a price that is not a number
    (lambda root: (root / "data" / "btcusd_1d.csv").write_text("t,o,h,l,c,v\n1,2\n"), "the stored candles are not in the expected layout (t, o, h, l, c, v): "),                       # a TypeError: a short row
    (lambda root: (root / "data" / "btcusd_1d.csv").write_text("t,o,h,l,c,v\n"), "the stored candle file is empty: "),
    (lambda root: (root / "dashboard.json").unlink(), "the dashboard cannot be read: "),
    (lambda root: (root / "dashboard.json").write_text("not json"), "the dashboard is not valid JSON: "),
    (lambda root: (root / "dashboard.json").write_text("{}"), "the dashboard has no list of accounts"),
    (lambda root: (root / "dashboard.json").write_text("[1]"), "the dashboard has no list of accounts"),
    (lambda root: [p.unlink() for p in (root / "state" / "accounts").glob("*.json")], "there are no account files under "),
    (lambda root: (root / "state" / "ledger" / "buy_hold.jsonl").unlink(), "the ledger of buy_hold cannot be read: "),
    (lambda root: (root / "state" / "ledger" / "buy_hold.jsonl").write_text("not json\n"), "the ledger of buy_hold is not valid JSON lines: "),
    (lambda root: (root / "state" / "accounts" / "buy_hold.json").write_text("not json"), "the account file buy_hold.json is not valid JSON: "),
])
def test_a_file_that_cannot_be_read_stops_the_audit_in_words(tmp_path, damage, words):
    root = write(make_world(), tmp_path)
    damage(root)
    with pytest.raises(A.AuditError) as e:
        A.audit(root)
    assert str(e.value).startswith(words) and str(e.value).count(str(root)) <= 1


def test_the_audit_writes_nothing(tmp_path):
    root = write(make_world(), tmp_path)

    def state():
        return sorted((str(p.relative_to(root)), hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()), sorted(str(p.relative_to(root)) for p in root.rglob("*"))
    before = state()
    A.audit(root)
    A.main(["--root", str(root)])
    assert state() == before                                                                                                   # not a byte, not a file, not a timestamp changed


def test_the_summary_is_plain_and_the_exit_code_says_whether_a_problem_was_found(tmp_path, capsys):
    root = write(make_world(), tmp_path / "ok")
    assert A.main(["--root", str(root)]) == 0
    assert capsys.readouterr().out == "\n".join([
        "Paper-account audit (read-only: nothing is written)", f"Folder: {root}",
        "3 accounts, 3 fills and 15 curve days replayed against 6 stored candles (2026-11-14 to 2026-11-19).",
        "Largest differences between the replay and the files: cash 0, qty 0, equity 0, price 0, fee 0.", "No problems."]) + "\n"
    w = make_world()
    w["accounts"]["buy_hold"]["account"]["cash"] += 1
    w["dashboard"]["accounts"][0]["equity"] = 1.0
    bad = write(w, tmp_path / "bad")
    assert A.main(["--root", str(bad)]) == 1
    lines = capsys.readouterr().out.split("\n")
    assert lines[:4] == ["Paper-account audit (read-only: nothing is written)", f"Folder: {bad}", lines[2], lines[3]] and lines[4] == "2 problem(s):"
    assert lines[5].startswith("  - buy_hold: the account file holds 807.22541") and lines[6] == "  - cash: the dashboard shows the equity 1.0, the curve's last day 10000.0" and lines[7] == ""


def test_an_audit_that_cannot_be_made_exits_with_two_and_says_why(tmp_path, capsys):
    assert A.main(["--root", str(tmp_path / "nothing")]) == 2
    assert capsys.readouterr().out == f"The audit could not be made: the stored candles cannot be read: {tmp_path / 'nothing' / 'data' / 'btcusd_1d.csv'}\n"


def test_an_empty_path_is_a_path_and_not_the_default_folder(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)                                                                                                  # a folder with no data in it: the audit of "" must not quietly audit another folder
    with pytest.raises(A.AuditError) as e:
        A.audit("")
    assert str(e.value).startswith("the stored candles cannot be read: ")
    assert A.main(["--root", ""]) == 2
    assert capsys.readouterr().out.startswith("The audit could not be made: the stored candles cannot be read: ")


@pytest.fixture
def clock_eight_hours_behind_utc():
    old = os.environ.get("TZ")
    os.environ["TZ"] = "UTC+8"                                                                                                   # POSIX writes a zone west of Greenwich with a plus sign
    time.tzset()
    yield
    if old is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = old
    time.tzset()


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="this platform cannot change its time zone")
def test_the_dates_in_the_messages_are_utc_whatever_the_clock_of_the_machine_says(clock_eight_hours_behind_utc):
    assert datetime.fromtimestamp(bar(0)).strftime("%Y-%m-%d") == "2026-11-13"                                                   # on that machine midnight UTC is still the evening before
    assert A._iso(bar(0)) == "2026-11-14"


def test_the_module_runs_as_a_command(tmp_path):
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-m", "atlas_api.btcquant.audit", "--root", str(tmp_path / "nothing")], cwd=Path(__file__).parent.parent, capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and r.stdout.startswith("The audit could not be made: the stored candles cannot be read: ")


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# The specification each account was opened under. Found 2026-11-18: nothing checked that the stored rules of the monitors and the benchmarks were still the ones they opened with
# (the daily run's frozen check reads only the challengers and the champions, and there are none), and the daily run trades from `meta["family"]` and `meta["params"]`, not from the stored specification.

def fingerprint(spec):
    """The first 16 hexadecimal characters of the SHA-256 of the specification as JSON with sorted keys, worked out here with hashlib and not with the module."""
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:16]


def meta_of(w, aid):
    return w["accounts"][aid]["meta"]


def opening_of(w, aid):
    return w["ledgers"][aid][0]


def renamed(w, old, new):
    """The same account under another id: the id that its file name, its account, its meta, every row of its ledger and its line of the dashboard carry."""
    w["accounts"][new] = w["accounts"].pop(old)
    w["accounts"][new]["account"]["id"] = new
    w["accounts"][new]["meta"]["id"] = new
    w["ledgers"][new] = w["ledgers"].pop(old)
    for row in w["ledgers"][new]:
        row["account"] = new
    for line in w["dashboard"]["accounts"]:
        if line["id"] == old:
            line["id"] = new
    return w


def with_stage(w, aid, stage):
    """The stage of an account in its meta and in the row that opened it (so that the two agree)."""
    meta_of(w, aid)["stage"] = opening_of(w, aid)["stage"] = stage
    return w


def test_the_fingerprints_and_the_monitors_id_of_the_world_are_worked_out_again_outside_the_module():
    for aid, (family, params, stage, fp) in WHO.items():
        assert fingerprint(spec_of(family, params)) == fp, aid
    assert STOPPED == "sma_cross-" + WHO[STOPPED][3][:8] == "sma_cross-c0f76650"
    assert [WHO[a][2] for a in ("cash", "buy_hold", STOPPED)] == ["benchmark", "benchmark", "monitor"]


def test_the_module_writes_the_fingerprint_and_the_names_of_the_accounts_the_way_the_engine_does():
    from atlas_api.btcquant import daily, research, strategies
    for aid, (family, params, stage, fp) in WHO.items():
        assert A._fingerprint(spec_of(family, params)) == strategies.hash_spec(spec_of(family, params)) == fp, aid
    assert research.account_id("sma_cross", {"fast": 10, "slow": 50}) == STOPPED
    assert set(A.FIXED) == {b[0] for b in daily.BENCHMARKS} | {daily.PORTFOLIO}
    assert A.FIXED == {"buy_hold": "benchmark", "cash": "benchmark", "portfolio": "portfolio"} and A.REGISTERED == ("monitor", "challenger", "champion")


@pytest.mark.parametrize("damage", [lambda m: m.pop("spec"), lambda m: m.pop("spec_hash"), lambda m: m.update(spec="text"), lambda m: m.update(spec=None), lambda m: m.update(spec_hash=7), lambda m: m.update(spec_hash=None)])
def test_an_account_whose_meta_has_no_frozen_specification_is_one_problem_and_nothing_more(tmp_path, damage):
    for aid in ("buy_hold", STOPPED):                                                                                              # the monitor too: its registry rules wait for a specification to compare
        w = make_world()
        damage(meta_of(w, aid))
        assert problems(w, tmp_path / aid) == [f"{aid}: its meta has no frozen specification (a spec and its spec_hash)"]


def test_a_specification_that_no_longer_hashes_to_its_fingerprint_is_reported(tmp_path):
    w = make_world()
    meta_of(w, "buy_hold")["spec"]["stop_k"] = 2.0
    got = fingerprint(meta_of(w, "buy_hold")["spec"])
    assert got != WHO["buy_hold"][3]
    assert problems(w, tmp_path / "a") == [f"buy_hold: its stored specification hashes to {got}, not to the recorded fingerprint {WHO['buy_hold'][3]}"]
    w = make_world()                                                                                                               # a monitor: the copy of the rules in the registry then differs from the stored one too
    meta_of(w, STOPPED)["spec"]["risk"] = 0.02
    got = fingerprint(meta_of(w, STOPPED)["spec"])
    assert problems(w, tmp_path / "b") == [f"{STOPPED}: its stored specification hashes to {got}, not to the recorded fingerprint c0f76650213f0d13",
                                          f"{STOPPED}: its stored specification is not the one the registry logged under the fingerprint c0f76650213f0d13"]


def test_the_fingerprint_does_not_depend_on_the_order_of_the_keys_of_the_stored_specification(tmp_path):
    w = make_world()
    for aid in w["accounts"]:
        meta_of(w, aid)["spec"] = dict(reversed(list(meta_of(w, aid)["spec"].items())))
    assert problems(w, tmp_path) == []


def test_the_ledger_opened_the_account_under_the_fingerprint_the_meta_records(tmp_path):
    w = make_world()
    opening_of(w, "buy_hold")["spec_hash"] = "0123456789abcdef"
    assert problems(w, tmp_path / "a") == [f"buy_hold: its ledger opened it under the fingerprint 0123456789abcdef, its meta records {WHO['buy_hold'][3]}"]
    w = make_world()
    opening_of(w, "buy_hold").pop("spec_hash")
    assert problems(w, tmp_path / "b") == [f"buy_hold: its ledger opened it under the fingerprint None, its meta records {WHO['buy_hold'][3]}"]
    w = make_world()                                                                                                               # the meta alone changed: the stored rules no longer hash to it either
    meta_of(w, "cash")["spec_hash"] = "0123456789abcdef"
    assert problems(w, tmp_path / "c") == [f"cash: its stored specification hashes to {WHO['cash'][3]}, not to the recorded fingerprint 0123456789abcdef",
                                          f"cash: its ledger opened it under the fingerprint {WHO['cash'][3]}, its meta records 0123456789abcdef"]


def test_the_family_and_the_parameters_that_trade_are_those_of_the_stored_specification(tmp_path):
    def trades(family, params):
        return f"buy_hold: its meta trades family {family} with parameters {params}, but the specification it records says buy_hold with {{}}"
    w = make_world()                                                                                                               # the meta and the ledger changed together: only the specification it records disagrees
    meta_of(w, "buy_hold")["params"] = opening_of(w, "buy_hold")["params"] = {"k": 3}
    assert problems(w, tmp_path / "a") == [trades("buy_hold", {"k": 3})]
    w = make_world()
    meta_of(w, "buy_hold")["family"] = opening_of(w, "buy_hold")["family"] = "cash"
    assert problems(w, tmp_path / "b") == [trades("cash", {})]
    w = make_world()                                                                                                               # the meta alone changed (what the daily run trades from): the ledger disagrees as well
    meta_of(w, "buy_hold")["params"] = {"k": 3}
    assert problems(w, tmp_path / "c") == [trades("buy_hold", {"k": 3}), "buy_hold: its ledger opened it as family buy_hold with parameters {}, its meta says buy_hold with {'k': 3}"]
    w = make_world()
    meta_of(w, "buy_hold")["family"] = "cash"
    assert problems(w, tmp_path / "d") == [trades("cash", {}), "buy_hold: its ledger opened it as family buy_hold with parameters {}, its meta says cash with {}"]


def test_the_family_and_the_parameters_of_the_opening_row_are_those_of_the_meta(tmp_path):
    w = make_world()
    opening_of(w, "buy_hold")["params"] = {"k": 3}
    assert problems(w, tmp_path / "a") == ["buy_hold: its ledger opened it as family buy_hold with parameters {'k': 3}, its meta says buy_hold with {}"]
    w = make_world()
    opening_of(w, "buy_hold")["family"] = "cash"
    assert problems(w, tmp_path / "b") == ["buy_hold: its ledger opened it as family cash with parameters {}, its meta says buy_hold with {}"]
    w = make_world()
    opening_of(w, "buy_hold").pop("params")
    assert problems(w, tmp_path / "c") == ["buy_hold: its ledger opened it as family buy_hold with parameters None, its meta says buy_hold with {}"]


def test_the_stage_in_the_ledger_is_the_stage_in_the_meta(tmp_path):
    w = make_world()
    opening_of(w, "buy_hold")["stage"] = "monitor"
    assert problems(w, tmp_path / "a") == ["buy_hold: its ledger opened it as a monitor account, its meta says benchmark"]
    w = make_world()
    opening_of(w, "buy_hold").pop("stage")
    assert problems(w, tmp_path / "b") == ["buy_hold: its ledger opened it as a None account, its meta says benchmark"]


@pytest.mark.parametrize("key, new", [("fee", 0.002), ("slippage", 0.001)])
def test_the_costs_of_the_stored_specification_are_the_ones_the_replay_checks(tmp_path, key, new):
    w = make_world()
    spec = meta_of(w, "buy_hold")["spec"]
    spec[key] = new
    meta_of(w, "buy_hold")["spec_hash"] = opening_of(w, "buy_hold")["spec_hash"] = fingerprint(spec)                              # the fingerprint follows the change, so that only the costs are wrong
    assert problems(w, tmp_path) == [f"buy_hold: its specification charges a fee of {spec['fee']} and slippage of {spec['slippage']}, but the audit checks 0.001 and 0.0005"]


def test_a_fixed_account_is_the_stage_of_its_name(tmp_path):
    assert problems(with_stage(make_world(), "buy_hold", "monitor"), tmp_path / "a") == ["buy_hold: it is a monitor account, but the account of that name is a benchmark"]
    assert problems(with_stage(make_world(), "cash", "portfolio"), tmp_path / "b") == ["cash: it is a portfolio account, but the account of that name is a benchmark"]
    w = make_world()
    meta_of(w, "cash").pop("stage")
    opening_of(w, "cash").pop("stage")
    assert problems(w, tmp_path / "c") == ["cash: it is a None account, but the account of that name is a benchmark"]


@pytest.mark.parametrize("stage", ["sandbox", "benchmark", "portfolio", None])
def test_any_other_account_is_a_monitor_a_challenger_or_a_champion(tmp_path, stage):
    w = with_stage(make_world(), STOPPED, stage)                                                                                   # "benchmark" is the way round the registry rules: a monitor that calls itself a benchmark
    shown = "None" if stage is None else f"'{stage}'"
    assert problems(w, tmp_path) == [f"{STOPPED}: it is none of the fixed accounts (buy_hold, cash, portfolio) and its stage {shown} is not monitor, challenger or champion"]


@pytest.mark.parametrize("stage", ["challenger", "champion"])
def test_a_challenger_and_a_champion_are_registered_accounts_like_a_monitor(tmp_path, stage):
    w = with_stage(make_world(), STOPPED, stage)
    assert problems(w, tmp_path / "a") == []                                                                                       # the same record in the registry is what they need
    w["registry"] = []
    assert problems(w, tmp_path / "b") == [f"{STOPPED}: its fingerprint c0f76650213f0d13 was never logged in the registry's candidate list"]


def test_the_id_of_a_registered_account_is_its_family_and_the_start_of_its_fingerprint(tmp_path):
    want = f"its id should be {STOPPED} (the family and the first 8 characters of its fingerprint)"
    assert problems(renamed(make_world(), STOPPED, "sma_cross-deadbeef"), tmp_path / "a") == [f"sma_cross-deadbeef: {want}"]
    assert problems(renamed(make_world(), STOPPED, "ema_cross-c0f76650"), tmp_path / "b") == [f"ema_cross-c0f76650: {want}"]
    assert problems(renamed(make_world(), STOPPED, "sma_cross-c0f76650d"), tmp_path / "c") == [f"sma_cross-c0f76650d: {want}"]               # one character more is another id
    assert problems(renamed(make_world(), STOPPED, "sma_cross"), tmp_path / "d") == [f"sma_cross: {want}"]


def test_the_id_of_a_registered_account_names_the_family_that_trades_not_the_one_in_the_specification(tmp_path):
    w = make_world()
    meta_of(w, STOPPED)["family"] = opening_of(w, STOPPED)["family"] = "ema_cross"                                                  # the meta and the ledger say ema_cross, the specification it records still says sma_cross
    assert problems(w, tmp_path) == [f"{STOPPED}: its meta trades family ema_cross with parameters {{'fast': 10, 'slow': 50}}, but the specification it records says sma_cross with {{'fast': 10, 'slow': 50}}",
                                     f"{STOPPED}: its id should be ema_cross-c0f76650 (the family and the first 8 characters of its fingerprint)"]


def test_a_monitor_needs_its_specification_in_the_registry(tmp_path):
    never = f"{STOPPED}: its fingerprint c0f76650213f0d13 was never logged in the registry's candidate list"
    w = make_world()
    w["registry"] = []
    assert problems(w, tmp_path / "a") == [never]
    w = make_world()
    w["registry"][0]["spec_hash"] = "0123456789abcdef"                                                                             # a record of another specification
    assert problems(w, tmp_path / "b") == [never]
    w = make_world()
    w["registry"][0]["spec"]["risk"] = 0.02                                                                                        # the same fingerprint, other rules
    assert problems(w, tmp_path / "c") == [f"{STOPPED}: its stored specification is not the one the registry logged under the fingerprint c0f76650213f0d13"]
    w = make_world()
    w["registry"][0].pop("spec")
    assert problems(w, tmp_path / "d") == [f"{STOPPED}: its stored specification is not the one the registry logged under the fingerprint c0f76650213f0d13"]


def test_the_specification_is_logged_before_the_account_opens_not_after(tmp_path):
    late = lambda logged: f"{STOPPED}: its specification was logged in the registry at {logged}, not before the account opened at {OPENED_AT}"
    w = make_world()
    w["registry"][0]["logged_at"] = "2026-11-15T10:36:09Z"                                                                         # one second after
    assert problems(w, tmp_path / "a") == [late("2026-11-15T10:36:09Z")]
    w = make_world()
    w["registry"][0]["logged_at"] = OPENED_AT                                                                                      # the same second is not later
    assert problems(w, tmp_path / "b") == []
    w = make_world()
    w["registry"][0].pop("logged_at")
    assert problems(w, tmp_path / "c") == [late(None)]
    w = make_world()
    w["registry"][0]["logged_at"] = 5
    assert problems(w, tmp_path / "d") == [late(None)]
    w = make_world()
    meta_of(w, STOPPED).pop("opened_at")
    assert problems(w, tmp_path / "e") == [f"{STOPPED}: its specification was logged in the registry at {LOGGED_AT}, not before the account opened at None"]


def test_a_specification_logged_again_later_is_judged_by_its_first_record(tmp_path):
    w = make_world()
    w["registry"] = [{**registered(STOPPED), "logged_at": "2026-11-17T04:00:00Z"}, registered(STOPPED), {**registered(STOPPED), "logged_at": "2026-11-18T04:00:00Z"}]
    assert problems(w, tmp_path / "a") == []                                                                                       # a repeat of the run is a later record, the first one is before the opening
    w["registry"] = [{**registered(STOPPED), "logged_at": "2026-11-17T04:00:00Z"}, {**registered(STOPPED), "logged_at": "2026-11-16T04:00:00Z"}]
    assert problems(w, tmp_path / "b") == [f"{STOPPED}: its specification was logged in the registry at 2026-11-16T04:00:00Z, not before the account opened at {OPENED_AT}"]
    w["registry"] = [{**registered(STOPPED), "logged_at": "2026-11-16T04:00:00Z", "spec": spec_of("sma_cross", {"fast": 5, "slow": 50})}, {**registered(STOPPED), "logged_at": "2026-11-17T04:00:00Z"}]
    assert problems(w, tmp_path / "c") == [f"{STOPPED}: its specification was logged in the registry at 2026-11-17T04:00:00Z, not before the account opened at {OPENED_AT}"]      # a record of other rules under the same fingerprint does not count


def test_rows_of_the_registry_that_are_not_candidate_records_are_skipped(tmp_path):
    w = make_world()
    w["registry"] = [5, "text", [], {}, {"spec_hash": 7}, {"spec_hash": None, "spec": {}}, registered(STOPPED)]
    assert problems(w, tmp_path) == []


def test_a_registry_that_cannot_be_read_is_one_problem_and_the_rest_is_audited_all_the_same(tmp_path):
    root = write(make_world(), tmp_path / "a")
    (root / "registry" / "candidates.jsonl").unlink()
    r = A.audit(root)
    assert r["problems"] == [f"the registry's candidate list cannot be read, so no specification was compared with it: {root / 'registry' / 'candidates.jsonl'}"]
    assert (r["accounts"], r["fills"], r["curve_days"]) == (3, 3, 15)
    root = write(make_world(), tmp_path / "b")
    (root / "registry" / "candidates.jsonl").write_text("not json\n")
    assert A.audit(root)["problems"] == [f"the registry's candidate list is not valid JSON lines, so no specification was compared with it: {root / 'registry' / 'candidates.jsonl'}"]
    w = make_world()
    w["accounts"]["buy_hold"]["account"]["cash"] += 1
    root = write(w, tmp_path / "c")
    (root / "registry" / "candidates.jsonl").unlink()
    found = A.audit(root)["problems"]
    assert len(found) == 2 and found[0].startswith("the registry's candidate list cannot be read") and found[1].startswith("buy_hold: the account file holds ")        # the registry's problem first, then the accounts'


def test_the_audit_reads_the_registry_and_changes_nothing_in_it(tmp_path):
    root = write(make_world(), tmp_path)
    before = (root / "registry" / "candidates.jsonl").read_bytes()
    A.audit(root)
    assert (root / "registry" / "candidates.jsonl").read_bytes() == before
