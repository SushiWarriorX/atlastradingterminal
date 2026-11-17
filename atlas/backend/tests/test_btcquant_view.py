"""btcquant view: what the phone app shows of the paper lab, in plain words, built only from the dashboard and the ledgers the daily run writes."""
import json
import os

import numpy as np
import pytest
from fastapi.testclient import TestClient

from atlas_api.app import create_app
from atlas_api.btcquant import daily as DY
from atlas_api.btcquant import registry as R
from atlas_api.btcquant import view as V

DAY = 86400
T0 = 1_546_300_800


def history(n, seed=1, start=20_000.0, vol=0.03):
    rng = np.random.default_rng(seed)
    c = start * np.exp(np.cumsum(rng.normal(0.0004, vol, n)))
    o = np.concatenate([[start], c[:-1]])
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.01, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.01, n)))
    return [(T0 + i * DAY, float(o[i]), float(h[i]), float(l[i]), float(c[i]), 100.0) for i in range(n)]


@pytest.fixture()
def root(tmp_path):
    cs = history(420, seed=3, vol=0.035)
    reg = R.Registry(tmp_path / "registry")
    reg.log_candidate({"family": "tsmom", "params": {"L": 30}, "decision": "rejected", "run": "research"})
    reg.log_candidate({"family": "donchian", "params": {"N": 20}, "decision": "rejected", "run": "research"})
    reg.root.mkdir(parents=True, exist_ok=True)
    (reg.root / "research_runs.jsonl").write_text(json.dumps({"protocol": "1.2", "ran_at": "2026-11-15T10:34:08Z", "data": {"last": "2026-11-14T00:00:00Z", "sha256": "ab"}, "admitted": [], "n_trials": 100,
                                                                "outcomes": {"tsmom": "rejected", "donchian": "rejected"}}) + "\n")
    DY.run_daily(root=tmp_path, now=cs[395][0] + DAY + 900, candles=cs[:396])
    for i in range(396, 420):
        DY.run_daily(root=tmp_path, now=cs[i][0] + DAY + 900, candles=cs[:i + 1])
    return tmp_path


def test_the_view_has_the_headline_the_accounts_and_the_trades_in_plain_words(root):
    v = V.paper_view(root)
    json.dumps(v)
    assert v["available"] is True and v["protocol"] == C.PROTOCOL_VERSION and v["real_trading"].startswith("DISABLED") and v["status"] == "no champions: the main portfolio is in cash"
    assert v["headline"].startswith("None of the 2 strategies passed the admission bar in the research run of 2026-11-15") and "stays in cash" in v["headline"] and "All 2 are paper-traded anyway" in v["headline"]
    assert v["counts"] == {"champions": 0, "challengers": 0, "monitors": 2, "research_admitted": 0, "research_ran_at": "2026-11-15T10:34:08Z"}
    by_id = {a["id"]: a for a in v["accounts"]}
    assert set(by_id) == {"buy_hold", "cash", "portfolio"} | {a["id"] for a in v["accounts"] if a["stage"] == "monitor"} and len(v["accounts"]) == 5
    assert by_id["portfolio"]["label"] == "Main portfolio ($100,000, champions only)" and by_id["buy_hold"]["label"] == "Buy and hold Bitcoin" and by_id["cash"]["label"] == "Cash only"
    mon = [a for a in v["accounts"] if a["stage"] == "monitor"]
    assert sorted(a["label"] for a in mon) == ["Donchian breakout (N 20)", "Time-series momentum (L 30)"] and all(a["days"] == 24 for a in mon)
    assert "simulations" in v["note"] and "no real order is ever placed" in v["note"] and v["data"]["stale"] is False and v["problems"] == []
    dash = {a["id"]: a for a in json.loads((root / "dashboard.json").read_text())["accounts"]}
    assert all(a["opened_after"] == dash[a["id"]]["opened_after_candle"] and a["opened_after"] == "2020-01-31T00:00:00Z" for a in v["accounts"])


def test_the_recent_trades_are_the_ledger_rows_newest_first_with_plain_text(root):
    v = V.paper_view(root, recent=500)
    rows = v["recent"]
    assert rows and [r["when"] for r in rows] == sorted((r["when"] for r in rows), reverse=True)
    kinds = {r["kind"] for r in rows}
    assert {"order", "fill"} <= kinds and "account_opened" not in kinds                    # an account opening is not a trade
    bh = [r for r in rows if r["account"] == "buy_hold"]
    fill = next(r for r in bh if r["kind"] == "fill")
    assert fill["text"].startswith("BOUGHT ") and " BTC at $" in fill["text"] and "fee $" in fill["text"] and fill["label"] == "Buy and hold Bitcoin"
    order = next(r for r in bh if r["kind"] == "order")
    assert order["text"].startswith("Change to 100% in Bitcoin at the next open") and "buy and hold" in order["text"]
    assert all(set(r) == {"when", "recorded_at", "seq", "account", "label", "kind", "text"} for r in rows)
    assert len(V.paper_view(root, recent=3)["recent"]) == 3 and V.paper_view(root, recent=3)["recent"] == rows[:3]


def test_without_a_daily_run_the_view_says_so(tmp_path):
    v = V.paper_view(tmp_path)
    assert v == {"available": False, "reason": "The paper lab's daily run has not been made yet."}


def test_every_kind_of_ledger_row_is_worded_for_a_beginner():
    t = lambda row: V.describe(row)
    assert t({"event": "order", "kind": "enter", "signal_time": T0, "ref_close": 64118.79, "stop": 56222.68, "est_qty": 0.01266, "reason": "signal"}) == (
        "2019-01-01T00:00:00Z", "BUY signal at the close ($64,118.79); protective stop $56,222.68, about 0.0127 BTC, to be filled at the next open")
    assert t({"event": "order", "kind": "exit", "signal_time": T0, "reason": "signal"})[1] == "SELL signal (the rule turned off); to be filled at the next open"
    assert t({"event": "order", "kind": "exit", "signal_time": T0, "reason": "circuit_breaker"})[1] == "SELL signal (the 15% circuit breaker); to be filled at the next open"
    assert t({"event": "order", "kind": "rebalance", "signal_time": T0, "weight": 0.45, "reason": "signal"})[1] == "Change to 45% in Bitcoin at the next open (the rule changed its target)"
    assert t({"event": "fill", "exec_time": T0 + DAY, "side": "buy", "qty": 0.0127, "price": 64150.0, "fee": 0.81, "slippage_cost": 0.4, "reason": "signal"}) == (
        "2019-01-02T00:00:00Z", "BOUGHT 0.0127 BTC at $64,150.00; fee $0.81, slippage cost $0.40")
    assert t({"event": "fill", "exec_time": T0, "side": "sell", "qty": 1.0, "price": 100.0, "fee": 0.1, "slippage_cost": 0.05, "reason": "stop"})[1].endswith("(stopped out); fee $0.10, slippage cost $0.05") and "SOLD 1.0000 BTC" in t({"event": "fill", "exec_time": T0, "side": "sell", "qty": 1.0, "price": 100.0, "fee": 0.1, "slippage_cost": 0.05, "reason": "stop"})[1]
    assert t({"event": "stop_hit", "exec_time": T0, "stop": 56222.68, "gap": False})[1] == "STOP hit at $56,222.68" and t({"event": "stop_hit", "exec_time": T0, "stop": 5.0, "gap": True})[1].endswith("(the price gapped through it)")
    assert t({"event": "breaker", "signal_bar": T0, "drawdown": -0.163}) == ("2019-01-02T00:00:00Z", "CIRCUIT BREAKER: equity 16.3% below its peak; everything is sold at the next open and trading halts")
    assert t({"event": "breaker_reset", "how": "cool_off"})[1] == "Trading resumed (30-day cool-off)" and t({"event": "breaker_reset", "how": "human"})[1] == "Trading resumed (reset by a person)"
    assert t({"event": "reject", "signal_bar": T0, "reason": "the open is at or below the protective stop"}) == ("2019-01-02T00:00:00Z", "Order rejected: the open is at or below the protective stop")
    assert t({"event": "account_opened", "start_equity": 10000.0}) == ("", "Account opened with $10,000.00")
    assert V.money(-5.5) == "-$5.50" and V.money(None) == "n/a"


def test_the_headline_changes_with_the_state_of_the_lab():
    base = {"challengers": [], "monitors": ["a", "b"], "champions": [], "research": None}
    assert V.headline(base).startswith("The research run has not been made yet")
    assert V.headline({**base, "research": {"ran_at": "2026-11-15T10:34:08Z", "outcomes": {"x": 1} }}).startswith("None of the 1 strategies passed")
    assert V.headline({**base, "challengers": ["c"]}) .startswith("1 strategy(ies) passed the admission bar") and "stays in cash" in V.headline({**base, "challengers": ["c"]})
    assert V.headline({**base, "champions": ["c"]}) == "1 champion(s) are in the main portfolio. That is a paper result, not a promise."


def test_the_route_serves_the_view_and_makes_no_promise(root, tmp_path, monkeypatch):
    from atlas_api.btcquant import config as C
    monkeypatch.setattr(C, "ROOT", root)
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/btcquant/paper")
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["available"] is True and len(d["accounts"]) == 5 and d["real_trading"].startswith("DISABLED")
        text = json.dumps(d).lower()
        assert "guaranteed" not in text and "will make money" not in text and "buy now" not in text
    monkeypatch.setattr(C, "ROOT", tmp_path / "nowhere")
    with TestClient(app) as c:
        assert c.get("/api/btcquant/paper").json()["data"]["available"] is False


def crafted_root(tmp_path, pendings, frozen=()):
    acc = lambda i, pend: {"id": i, "family": "tsmom", "params": {"L": 30}, "stage": "monitor", "equity": 10_000.0, "start_equity": 10_000.0, "return": 0.0, "day_pnl": 0.0, "exposure": 0.0, "drawdown": 0.0, "trades": 0, "days": 0,
                           "halted": False, "breaker_trips": 0, "pending": pend}
    dash = {"generated_at": "2026-11-16T00:15:00Z", "protocol": "1.2", "real_trading": "DISABLED", "status": "no champions: the main portfolio is in cash", "champions": [], "challengers": [], "monitors": [],
            "research": None, "data": {"last_candle": "2026-11-15T00:00:00Z", "last_close": 1.0, "stale": False, "update": "ok"}, "frozen_check": list(frozen),
            "accounts": [acc(f"a{i}", pend) for i, pend in enumerate(pendings)]}
    (tmp_path / "dashboard.json").write_text(json.dumps(dash))
    return tmp_path


def test_a_waiting_order_is_worded_by_its_kind(tmp_path):
    root = crafted_root(tmp_path, [None, {"kind": "enter", "weight": None}, {"kind": "exit", "weight": None}, {"kind": "rebalance", "weight": 0.45}, {"kind": "rebalance", "weight": 0.0}])
    got = [a["pending"] for a in V.paper_view(root)["accounts"]]
    assert got == [None, "BUY at the next open", "SELL at the next open", "move to 45% in Bitcoin at the next open", "move to 0% in Bitcoin at the next open"]


def test_a_problem_found_in_the_frozen_specifications_reaches_the_phone(tmp_path):
    root = crafted_root(tmp_path, [None], frozen=["challenger abc: the stored specification does not hash to the recorded hash"])
    assert V.paper_view(root)["problems"] == ["challenger abc: the stored specification does not hash to the recorded hash"]


# ---- the backtest side of the Journey page: each rule's verdict, its continuous replay on the stored candles, and its forward paper series ----
from atlas_api.btcquant import backtest as B  # noqa: E402
from atlas_api.btcquant import config as C  # noqa: E402
from atlas_api.btcquant import data as D  # noqa: E402
from atlas_api.btcquant import strategies as S  # noqa: E402


def period(r, h, m, dd, sh, n, ex):
    return {"total_return": r, "hold_return": h, "matched_hold_return": m, "max_drawdown": dd, "sharpe": sh, "trades": n, "exposure": ex, "days": 731}


def write_report(root, text=None):
    rep = {"protocol": "1.2", "evaluation": {"families": {
        "tsmom": {"outcome": "rejected", "admission": {"failed": ["A3"]}, "train": period(0.41, 1.30, 0.13, 0.12, 1.41, 69, 0.08), "validation": period(0.25, 4.64, 0.19, 0.04, 1.93, 20, 0.09), "validation_timing": {"p": 0.12}},
        "donchian": {"outcome": "rejected", "admission": {"failed": ["A2", "A9"]}, "train": period(0.2, 1.30, 0.1, 0.1, 0.95, 33, 0.05), "validation": None, "validation_timing": {"p": 0.17}},
        "not_in_the_dashboard": {"outcome": "rejected", "admission": {"failed": ["A1"]}}}}}
    (root / "reports").mkdir(exist_ok=True)
    (root / "reports" / "research_1.2.json").write_text(text if text is not None else json.dumps(rep))


@pytest.fixture()
def root_with_data(root):
    D.save(root / "data" / "btcusd_1d.csv", history(420, seed=3, vol=0.035))
    return root


def monitors(v):
    return {a["family"]: a for a in v["accounts"] if a["stage"] == "monitor"}


def test_each_rules_verdict_reaches_the_phone_with_the_reasons_in_plain_words(root):
    write_report(root)
    by = monitors(V.paper_view(root))
    t, d = by["tsmom"]["backtest"], by["donchian"]["backtest"]
    assert (t["outcome"], t["outcome_text"], t["why"], t["timing_p"]) == ("rejected", "Rejected", [V.GATE_WORDS["A3"]], 0.12)
    assert t["train"] == {"return": 0.41, "hold_return": 1.30, "matched_hold_return": 0.13, "max_drawdown": 0.12, "sharpe": 1.41, "trades": 69, "exposure": 0.08}
    assert t["validation"] == {"return": 0.25, "hold_return": 4.64, "matched_hold_return": 0.19, "max_drawdown": 0.04, "sharpe": 1.93, "trades": 20, "exposure": 0.09}
    assert d["why"] == [V.GATE_WORDS["A2"], "A9"] and d["validation"] is None and d["train"]["trades"] == 33     # a gate the words do not know is shown as it is; a missing period stays missing
    assert set(V.GATE_WORDS) == {"A1", "A2", "A3", "A4", "A5"} and all(not w[0].isupper() for w in V.GATE_WORDS.values())
    for gate, phrase in (("A1", "too few trades"), ("A2", "holding the same average amount of Bitcoin"), ("A3", "random timing"), ("A4", "settings were nudged"), ("A5", "costs were doubled")):
        assert phrase in V.GATE_WORDS[gate]
    assert V.OUTCOME_WORDS == {"admitted": "Admitted", "rejected": "Rejected", "too_thin": "Too few trades to judge"}


def test_the_stability_gate_of_a_family_with_one_setting_is_worded_as_what_it_asks(tmp_path):
    (tmp_path / "reports").mkdir()
    rep = {"evaluation": {"families": {"monday": {"outcome": "rejected", "admission": {"failed": ["A4", "A5"]}, "stability": {"single": True, "passes": False}, "validation_timing": {"p": 0.4}},
                                       "tsmom": {"outcome": "rejected", "admission": {"failed": ["A4"]}, "stability": {"passes": False}}}}}
    (tmp_path / "reports" / "research_1.3.json").write_text(json.dumps(rep))
    dash = {"protocol": "1.3", "research": {"outcomes": {"monday": "rejected", "tsmom": "rejected"}, "runs": [{"protocol": "1.3"}]}}
    out = V.verdicts(tmp_path, dash)
    assert out["monday"]["why"] == [V.GATE_WORDS_ONE_SETTING["A4"], V.GATE_WORDS["A5"]] and out["tsmom"]["why"] == [V.GATE_WORDS["A4"]]
    assert "2020-2022" in V.GATE_WORDS_ONE_SETTING["A4"] and "one setting" in V.GATE_WORDS_ONE_SETTING["A4"] and not V.GATE_WORDS_ONE_SETTING["A4"][0].isupper()


def test_a_weekday_setting_is_shown_as_the_name_of_the_day_and_the_family_has_its_logo():
    assert V.params_text({"params": {"day": 0}}) == "Monday" and V.params_text({"params": {"day": 6}}) == "Sunday" and V.params_text({"params": {"L": 30}}) == "L 30"
    assert V.label({"id": "monday-abcd1234", "family": "monday", "params": {"day": 0}}) == "Day-of-week holding (Monday)"
    assert V.short({"id": "monday-abcd1234", "family": "monday"}) == "MON" and V.family_name({"id": "monday-abcd1234", "family": "monday"}) == "Day-of-week holding"


def test_the_reversal_setting_is_shown_in_words_and_the_family_has_its_logo():
    assert V.params_text({"params": {"streak": 3}}) == "3 lower closes in a row" and V.params_text({"params": {"streak": 2}}) == "2 lower closes in a row"
    assert V.params_text({"params": {"streak": 1}}) == "1 lower close in a row" and V.params_text({"params": {"streak": 0}}) == "streak 0" and V.params_text({"params": {"streak": 4.5}}) == "streak 4.5"      # one lower close; zero and a fraction are not a run
    assert V.params_text({"params": {"day": 6}}) == "Sunday" and V.params_text({"params": {"L": 30}}) == "L 30"                                                                          # the other words are unchanged
    assert V.label({"id": "three_down-abcd1234", "family": "three_down", "params": {"streak": 3}}) == "Reversal after a losing streak (3 lower closes in a row)"
    assert V.short({"id": "three_down-abcd1234", "family": "three_down"}) == "REV" and V.family_name({"id": "three_down-abcd1234", "family": "three_down"}) == "Reversal after a losing streak"


def test_without_the_research_report_only_the_reasons_and_the_period_figures_are_lost(root):
    for text in (None, "{not json", "[]", json.dumps({"evaluation": {}})):
        if text is not None:
            write_report(root, text)
        t = monitors(V.paper_view(root))["tsmom"]["backtest"]
        assert (t["outcome"], t["outcome_text"], t["why"], t["train"], t["validation"], t["timing_p"]) == ("rejected", "Rejected", [], None, None, None)


def test_the_benchmarks_and_the_main_portfolio_have_no_verdict(root_with_data):
    by = {a["id"]: a for a in V.paper_view(root_with_data)["accounts"]}
    assert by["buy_hold"]["backtest"]["outcome"] is None and by["buy_hold"]["backtest"]["outcome_text"] == "Benchmark" and by["buy_hold"]["backtest"]["why"] == []
    assert by["cash"]["backtest"]["outcome_text"] == "Benchmark" and by["portfolio"]["backtest"] is None
    assert by["portfolio"]["name"] == "Main portfolio" and by["portfolio"]["short"] == "MP" and by["buy_hold"]["short"] == "BTC" and by["cash"]["short"] == "USD"


def test_the_replay_is_one_continuous_run_sampled_weekly_and_matches_the_engine(root_with_data):
    v = V.paper_view(root_with_data)
    bt = v["backtest"]
    cs = history(420, seed=3, vol=0.035)
    prep = B.Prepared(cs)
    i0, i1 = prep.span(C.EVAL_START, None)
    assert (bt["from"], bt["to"], bt["step_days"]) == ("2020-01-01", "2020-02-24", 7) and i1 - i0 + 1 == 55
    assert bt["times"] == ["2020-01-01", "2020-01-08", "2020-01-15", "2020-01-22", "2020-01-29", "2020-02-05", "2020-02-12", "2020-02-19", "2020-02-24"]
    assert bt["periods"] == [{"name": "TRAIN", "from": 0, "to": 8}]                  # TRAIN is cut where the data end; VALIDATION and TEST have not started in this data
    assert "looks better than anything that can be expected" in bt["note"] and "2025 onward is not a clean test" in bt["note"]
    params = {a["id"]: a["params"] for a in json.loads((root_with_data / "dashboard.json").read_text())["accounts"]}
    for a in v["accounts"]:
        if a["id"] == "portfolio":
            continue
        b = a["backtest"]
        r = B.run(prep, a["family"], params[a["id"]], i0, i1, keep_account=True)
        want = [round(r.account.curve[i - i0][1] / 10_000.0, 4) for i in [i0 + 7 * k for k in range(8)] + [i1]]
        assert b["curve"] == want and len(b["curve"]) == len(bt["times"])
        assert b["run"] == {"return": r.metrics["total_return"], "max_drawdown": r.metrics["max_drawdown"], "trades": r.metrics["trades"], "breaker_trips": r.metrics["breaker_trips"], "sharpe": r.metrics["sharpe"]}
    by = {a["id"]: a for a in v["accounts"]}
    assert by["cash"]["backtest"]["curve"] == [1.0] * 9 and by["buy_hold"]["backtest"]["run"]["return"] == pytest.approx(B.hold_return(prep, i0, i1))
    json.dumps(v)


def test_each_period_is_marked_by_the_samples_that_fall_inside_it(tmp_path):
    cs = history(1400, seed=5, vol=0.02)                                       # 2019-01-01 to 2022-10-31: TRAIN is still running at the end of the data
    D.save(tmp_path / "data" / "btcusd_1d.csv", cs)
    acc = {"id": "buy_hold", "family": "buy_hold", "params": {}}
    bt = V.backtest_curves(tmp_path, [acc])
    n = len(bt["times"])
    assert bt["periods"] == [{"name": "TRAIN", "from": 0, "to": n - 1}] and bt["times"][0] == "2020-01-01" and bt["times"][-1] == "2022-10-31"
    cs = history(2300, seed=5, vol=0.02)                                       # to 2025-04-12: TRAIN and VALIDATION are complete and TEST has begun
    D.save(tmp_path / "data" / "btcusd_1d.csv", cs)
    bt = V.backtest_curves(tmp_path, [acc])
    t = bt["times"]
    p = {x["name"]: x for x in bt["periods"]}
    assert t[p["TRAIN"]["from"]] == "2020-01-01" and t[p["TRAIN"]["to"]] <= "2022-12-31" < t[p["TRAIN"]["to"] + 1]
    assert p["VALIDATION"]["from"] == p["TRAIN"]["to"] + 1 and "2023-01-01" <= t[p["VALIDATION"]["from"]] and t[p["VALIDATION"]["from"] - 1] < "2023-01-01"
    assert t[p["VALIDATION"]["to"]] <= "2024-12-31" < t[p["VALIDATION"]["to"] + 1]
    assert p["TEST"]["from"] == p["VALIDATION"]["to"] + 1 and p["TEST"]["to"] == len(t) - 1 and t[p["TEST"]["from"] - 1] < "2025-01-01" <= t[p["TEST"]["from"]] and [x["name"] for x in bt["periods"]] == ["TRAIN", "VALIDATION", "TEST"]


def test_without_a_usable_candle_file_only_the_replay_is_lost(root, root_with_data):
    v = V.paper_view(root)
    (root / "data" / "btcusd_1d.csv").unlink()
    v = V.paper_view(root)
    assert v["backtest"] is None and len(v["accounts"]) == 5 and all(a["backtest"] is None or a["backtest"]["curve"] is None for a in v["accounts"])
    for junk in (b"not a candle file", b"t,o,h,l,c,v\n1,2,3\n", b"t,o,h,l,c,v\nx,2,3,4,5,6\n", b"t,o,h,l,c,v\n1,2,3,4,5,6\n"):      # a wrong header, a short row, a word for a number, a single candle
        (root / "data" / "btcusd_1d.csv").write_bytes(junk)
        v = V.paper_view(root)
        assert v["backtest"] is None and len(v["accounts"]) == 5 and v["available"] is True
    D.save(root / "data" / "btcusd_1d.csv", history(100, seed=3))                # candles that do not reach the first evaluation day
    assert V.paper_view(root)["backtest"] is None


def test_the_replay_is_cached_until_the_candle_file_or_the_rules_change(root_with_data):
    raw = json.loads((root_with_data / "dashboard.json").read_text())["accounts"]
    first = V.backtest_curves(root_with_data, raw)
    assert V.backtest_curves(root_with_data, raw) is first
    assert V.backtest_curves(root_with_data, raw[:2]) is not first and V.backtest_curves(root_with_data, raw) is not first          # a different set of rules replaces the entry
    again = V.backtest_curves(root_with_data, raw)
    f = root_with_data / "data" / "btcusd_1d.csv"
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))           # the file's time alone changed: not the same replay
    settled = V.backtest_curves(root_with_data, raw)
    assert settled is not again and V.backtest_curves(root_with_data, raw) is settled
    t1 = f.stat().st_mtime_ns
    D.save(f, history(421, seed=3, vol=0.035))
    os.utime(f, ns=(st.st_atime_ns, t1))                                       # one more candle but the same time as before: not the same replay either
    later = V.backtest_curves(root_with_data, raw)
    assert later is not settled and later["to"] == "2020-02-25" and again["to"] == "2020-02-24"


def test_the_forward_series_is_the_paper_accounts_equity_as_a_ratio_of_its_start(root):
    v = V.paper_view(root)
    for a in v["accounts"]:
        assert len(a["forward"]) == a["days"] == 24 and a["forward"][-1] == pytest.approx(a["equity"] / a["start_equity"], abs=1e-4)
    assert V.forward_series(root, "buy_hold", keep=5) == [a for a in v["accounts"] if a["id"] == "buy_hold"][0]["forward"][-5:]
    assert V.forward_series(root, "nobody") == [] and V.forward_series(root / "nowhere", "buy_hold") == []
    (root / "state" / "accounts" / "buy_hold.json").write_text("{broken")
    assert V.forward_series(root, "buy_hold") == []


def test_every_family_has_its_own_letters_for_the_logo():
    codes = [V.SHORT[f] for f in list(S.FAMILIES) + ["portfolio"]]
    assert len(set(codes)) == len(codes) and all(c.isupper() and 2 <= len(c) <= 3 for c in codes)
    assert V.short({"id": "x-1", "family": "newfamily"}) == "NEW" and V.short({"id": "sma_cross-ab", "family": "sma_cross"}) == "SMA"


def test_the_view_built_from_the_committed_artifacts_is_complete_and_makes_no_promise():
    if not (C.ROOT / "dashboard.json").exists():
        pytest.skip("no daily run has been committed")
    v = V.paper_view()
    mons = [a for a in v["accounts"] if a["stage"] == "monitor"]
    assert len(mons) >= 12 and len({a["family"] for a in mons}) == len(mons) and v["backtest"] is not None and v["backtest"]["to"] >= "2026-11-14"        # twelve from the first run, one more for each family a later run did not admit; one monitor a family
    for a in v["accounts"]:
        if a["id"] == "portfolio":
            assert a["backtest"] is None
            continue
        assert len(a["backtest"]["curve"]) == len(v["backtest"]["times"]) and 0.9 < a["backtest"]["curve"][0] < 1.1
    for a in mons:
        b = a["backtest"]
        assert b["outcome"] in ("rejected", "too_thin", "admitted") and b["why"] and b["train"]["trades"] is not None and b["validation"]["return"] is not None
    text = json.dumps(v).lower()
    assert "guaranteed" not in text and "will make money" not in text and "buy now" not in text
