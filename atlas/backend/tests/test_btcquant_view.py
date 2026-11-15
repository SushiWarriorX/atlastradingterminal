"""btcquant view: what the phone app shows of the paper lab, in plain words, built only from the dashboard and the ledgers the daily run writes."""
import json

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
    assert v["available"] is True and v["protocol"] == "1.2" and v["real_trading"].startswith("DISABLED") and v["status"] == "no champions: the main portfolio is in cash"
    assert v["headline"].startswith("None of the 2 strategies passed the admission bar in the research run of 2026-11-15") and "stays in cash" in v["headline"] and "All 2 are paper-traded anyway" in v["headline"]
    assert v["counts"] == {"champions": 0, "challengers": 0, "monitors": 2, "research_admitted": 0, "research_ran_at": "2026-11-15T10:34:08Z"}
    by_id = {a["id"]: a for a in v["accounts"]}
    assert set(by_id) == {"buy_hold", "cash", "portfolio"} | {a["id"] for a in v["accounts"] if a["stage"] == "monitor"} and len(v["accounts"]) == 5
    assert by_id["portfolio"]["label"] == "Main portfolio ($100,000, champions only)" and by_id["buy_hold"]["label"] == "Buy and hold Bitcoin" and by_id["cash"]["label"] == "Cash only"
    mon = [a for a in v["accounts"] if a["stage"] == "monitor"]
    assert sorted(a["label"] for a in mon) == ["Donchian breakout (N 20)", "Time-series momentum (L 30)"] and all(a["days"] == 24 for a in mon)
    assert "simulations" in v["note"] and "no real order is ever placed" in v["note"] and v["data"]["stale"] is False and v["problems"] == []


def test_the_recent_trades_are_the_ledger_rows_newest_first_with_plain_text(root):
    v = V.paper_view(root, recent=500)
    rows = v["recent"]
    assert rows and [r["when"] for r in rows] == sorted((r["when"] for r in rows), reverse=True)
    kinds = {r["kind"] for r in rows}
    assert {"order", "fill", "account_opened"} <= kinds
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
