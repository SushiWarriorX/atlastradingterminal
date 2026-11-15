"""btcquant daily run: the first run opens the benchmarks and the empty portfolio, a repeat run changes nothing, a new candle steps every account and writes the ledger, a missing candle is reported and does not
stop the others, a failed download falls back on the stored data, and the report and dashboard say what they must (real trading disabled, no champions, stale data, problems)."""
import json

import httpx
import numpy as np
import pytest

from atlas_api.btcquant import config as C
from atlas_api.btcquant import daily as DY
from atlas_api.btcquant import data as D
from atlas_api.btcquant import registry as R
from atlas_api.btcquant import strategies as S

DAY = 86400
T0 = 1_546_300_800


def history(n, seed=1, start=20_000.0, vol=0.03):
    rng = np.random.default_rng(seed)
    c = start * np.exp(np.cumsum(rng.normal(0.0004, vol, n)))
    o = np.concatenate([[start], c[:-1]])
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.01, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.01, n)))
    return [(T0 + i * DAY, float(o[i]), float(h[i]), float(l[i]), float(c[i]), 100.0) for i in range(n)]


def after(cs, minutes=15):
    """The time of a 00:15 UTC run that follows the last candle in cs."""
    return cs[-1][0] + DAY + minutes * 60


def test_the_first_run_opens_the_benchmarks_and_an_empty_portfolio_and_writes_the_report_and_dashboard(tmp_path):
    cs = history(400)
    dash = DY.run_daily(root=tmp_path, now=after(cs), candles=cs)
    assert sorted(a["id"] for a in dash["accounts"]) == ["buy_hold", "cash", "portfolio"] and dash["opened_today"] == ["buy_hold", "cash", "portfolio"]
    port = dash["portfolio"]
    assert port["equity"] == 100_000.0 and port["stage"] == "portfolio" and port["exposure"] == 0.0 and dash["champions"] == [] and dash["status"] == "no champions: the main portfolio is in cash"
    assert dash["data"]["stale"] is False and dash["data"]["last_candle"] == "2020-02-04T00:00:00Z" and dash["data"]["candles"] == 400 and dash["data"]["gaps"] == 0 and dash["real_trading"].startswith("DISABLED")
    day = "2020-02-05"
    for name in (f"reports/{day}.md", "reports/latest.md", "dashboard.json"):
        assert (tmp_path / name).exists()
    text = (tmp_path / "reports/latest.md").read_text()
    assert "Real trading is disabled" in text and "No strategy has been admitted as a challenger" in text and "main portfolio is in cash" in text and "all in cash" in text and "does not show" in text
    assert json.loads((tmp_path / "dashboard.json").read_text())["generated_at"] == "2020-02-05T00:15:00Z"
    bh = next(a for a in dash["accounts"] if a["id"] == "buy_hold")
    assert bh["pending"]["kind"] == "rebalance" and bh["in_position"] is False and bh["equity"] == 10_000.0                  # the purchase happens at the next open, when the next candle completes
    from atlas_api.btcquant import paper as PP
    book = PP.PaperBook(tmp_path / "state")
    assert book.load("portfolio")[1]["cool_off_days"] is None and book.load("portfolio")[1]["start_equity"] == 100_000.0                # only a human resumes the main portfolio
    assert book.load("buy_hold")[1]["cool_off_days"] == 30 and book.load("cash")[1]["stage"] == "benchmark"


def test_a_second_run_with_nothing_new_changes_nothing(tmp_path):
    cs = history(400)
    first = DY.run_daily(root=tmp_path, now=after(cs), candles=cs)
    files = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    second = DY.run_daily(root=tmp_path, now=after(cs), candles=cs)
    again = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    same = [k for k in files if k != "dashboard.json"]
    assert again.keys() == files.keys() and all(again[k] == files[k] for k in same) and first["accounts"] == second["accounts"]
    assert first["opened_today"] == ["buy_hold", "cash", "portfolio"] and second["opened_today"] == []                    # the only difference: nothing is opened the second time
    strip = lambda raw: {k: v for k, v in json.loads(raw).items() if k != "opened_today"}
    assert strip(again["dashboard.json"]) == strip(files["dashboard.json"])


def test_a_new_candle_steps_every_account_and_the_ledger_records_what_happened(tmp_path):
    cs = history(401)
    DY.run_daily(root=tmp_path, now=after(cs[:400]), candles=cs[:400])
    dash = DY.run_daily(root=tmp_path, now=after(cs), candles=cs)
    bh = next(a for a in dash["accounts"] if a["id"] == "buy_hold")
    assert bh["in_position"] is True and bh["days"] == 1 and bh["fills"] == 1 and bh["pending"] is None and bh["equity"] != 10_000.0 and bh["exposure"] > 0.99
    assert all(s.get("processed") == 1 for s in dash["steps"].values()) and dash["opened_today"] == []
    ledger = [json.loads(line) for line in (tmp_path / "state/ledger/buy_hold.jsonl").read_text().splitlines()]
    assert [r["event"] for r in ledger] == ["account_opened", "order", "fill"] and ledger[2]["side"] == "buy" and ledger[2]["exec_time"] == cs[400][0]
    cash = next(a for a in dash["accounts"] if a["id"] == "cash")
    port = next(a for a in dash["accounts"] if a["id"] == "portfolio")
    assert cash["equity"] == 10_000.0 and port["equity"] == 100_000.0 and cash["days"] == 1 and bh["day_pnl"] == pytest.approx(bh["equity"] - 10_000.0)
    assert bh["hold_return"] == pytest.approx(bh["return"], rel=1e-9) and bh["matched_hold_return"] is not None


def test_a_challenger_in_the_registry_gets_a_shadow_account(tmp_path):
    cs = history(400)
    reg = R.Registry(tmp_path / "registry")
    ch = reg.admit({"family": "tsmom", "params": {"L": 30}})
    dash = DY.run_daily(root=tmp_path, now=after(cs), candles=cs)
    aid = f"tsmom-{ch['spec_hash'][:8]}"
    assert aid in dash["opened_today"] and aid in [a["id"] for a in dash["accounts"]] and dash["challengers"] == [ch["spec_hash"]]
    a = next(x for x in dash["accounts"] if x["id"] == aid)
    assert a["stage"] == "challenger" and a["family"] == "tsmom" and a["start_equity"] == 10_000.0
    text = (tmp_path / "reports/latest.md").read_text()
    assert "Challengers against holding" in text and aid in text and "too early to say anything" in text
    again = DY.run_daily(root=tmp_path, now=after(cs), candles=cs)
    assert again["opened_today"] == []


def test_a_missing_candle_stops_the_affected_accounts_and_the_report_says_so(tmp_path):
    cs = history(420)
    DY.run_daily(root=tmp_path, now=after(cs[:400]), candles=cs[:400])
    broken = cs[:410] + cs[411:]
    dash = DY.run_daily(root=tmp_path, now=after(broken), candles=broken)
    assert dash["data"]["gaps"] == 1 and all("error" in s for s in dash["steps"].values())
    text = (tmp_path / "reports/latest.md").read_text()
    assert "could not be stepped" in text and "is missing" in text and "1 gap(s)" in text
    fixed = DY.run_daily(root=tmp_path, now=after(cs), candles=cs)
    assert all(s.get("processed") == 10 for s in fixed["steps"].values())                                                 # the 10 candles after the gap, once it is filled


def test_stale_data_is_flagged(tmp_path):
    cs = history(400)
    dash = DY.run_daily(root=tmp_path, now=after(cs) + 3 * DAY, candles=cs)
    assert dash["data"]["stale"] is True and "The data are stale" in (tmp_path / "reports/latest.md").read_text()
    assert DY.expected_last_candle(T0 + 10 * DAY + 900) == T0 + 9 * DAY and DY.expected_last_candle(T0 + 10 * DAY - 1) == T0 + 8 * DAY


def test_a_failed_download_falls_back_on_the_stored_data_and_says_so(tmp_path):
    cs = history(400)
    (tmp_path / "data").mkdir()
    D.save(tmp_path / "data" / "btcusd_1d.csv", cs)

    class Dead(httpx.Client):
        def get(self, *a, **k):
            raise httpx.ConnectError("boom")
    dash = DY.run_daily(root=tmp_path, now=after(cs), downloader=D.Downloader(client=Dead(), sleep=0))
    assert dash["data"]["update"].startswith("failed (the candle provider could not be reached); the stored data were used") and dash["data"]["candles"] == 400
    assert "stored data were used" in (tmp_path / "reports/latest.md").read_text()


def test_a_successful_update_records_the_manifest_and_counts_the_new_candles(tmp_path):
    cs = history(401)
    (tmp_path / "data").mkdir()
    D.save(tmp_path / "data" / "btcusd_1d.csv", cs[:400])

    class Fake(D.Downloader):
        def fetch(self, interval, start, end):
            return [c for c in cs if start <= c[0] <= end]
    dash = DY.run_daily(root=tmp_path, now=after(cs), downloader=Fake(sleep=0))
    assert dash["data"]["update"] == "1 new candle(s) added" and dash["data"]["candles"] == 401
    man = json.loads((tmp_path / "data" / "manifest.json").read_text())
    assert man["1d"]["count"] == 401 and man["1d"]["sha256"] == dash["data"]["sha256"]


def test_data_that_fail_validation_stop_the_run_before_anything_is_written(tmp_path):
    cs = history(400)
    bad = cs[:100] + [(cs[100][0], cs[100][1], cs[100][2] * 0.5, cs[100][3], cs[100][4], 1.0)] + cs[101:]          # a high below the open
    with pytest.raises(D.DataError, match="failed validation"):
        DY.run_daily(root=tmp_path, now=after(cs), candles=bad)
    with pytest.raises(D.DataError, match="not enough"):
        DY.run_daily(root=tmp_path, now=after(cs), candles=cs[:100])
    assert not list(tmp_path.rglob("*"))


def test_tampering_with_a_frozen_specification_appears_in_the_report(tmp_path):
    cs = history(400)
    reg = R.Registry(tmp_path / "registry")
    ch = reg.admit({"family": "tsmom", "params": {"L": 30}})
    data = json.loads(reg.challengers_path.read_text())
    data[ch["spec_hash"]]["params"] = {"L": 60}
    reg.challengers_path.write_text(json.dumps(data))
    dash = DY.run_daily(root=tmp_path, now=after(cs), candles=cs)
    assert dash["frozen_check"] and "Problems found" in (tmp_path / "reports/latest.md").read_text()


def test_the_report_shows_the_last_research_run_when_there_is_one(tmp_path):
    cs = history(400)
    reg = R.Registry(tmp_path / "registry")
    reg.root.mkdir(parents=True)
    (reg.root / "research_runs.jsonl").write_text(json.dumps({"protocol": "1.2", "ran_at": "2026-11-15T12:00:00Z", "data": {"last": "2026-11-14T00:00:00Z", "sha256": "ab"}, "admitted": [{"family": "tsmom"}],
                                                                "n_trials": 100, "outcomes": {}}) + "\n")
    dash = DY.run_daily(root=tmp_path, now=after(cs), candles=cs)
    text = (tmp_path / "reports/latest.md").read_text()
    assert dash["research"]["protocol"] == "1.2" and "admitted 1 of 12 families" in text and "research_1.2.md" in text


# ---- the report text and the command line ----

def crafted(accounts, **kw):
    base = {"generated_at": "2026-11-16T00:15:00Z", "protocol": "1.2", "real_trading": "DISABLED", "status": "no champions: the main portfolio is in cash", "champions": [], "challengers": [], "research": None,
            "frozen_check": [], "drift": [], "steps": {}, "opened_today": [], "portfolio": {"equity": 100_000.0},
            "data": {"last_candle": "2026-11-15T00:00:00Z", "last_close": 64_000.0, "candles": 2876, "gaps": 0, "sha256": "ab" * 32, "update": "1 new candle(s) added", "stale": False, "notes": []}, "accounts": accounts}
    base.update(kw)
    return base


def acct(aid, stage, **kw):
    a = {"id": aid, "stage": stage, "equity": 10_000.0, "day_pnl": 0.0, "return": 0.0, "exposure": 0.0, "drawdown": 0.0, "trades": 0, "halted": False, "breaker_trips": 0, "pending": None, "days": 0,
         "hold_return": 0.01, "matched_hold_return": 0.005}
    a.update(kw)
    return a


def test_the_verdict_column_follows_the_forward_record_length():
    accts = [acct(f"c{d}", "challenger", days=d) for d in (59, 60, 89, 90)]
    text = DY.build_report(crafted(accts), None, None)
    rows = {line.split("|")[1].strip("` "): line for line in text.splitlines() if line.startswith("| `c")}
    assert "too early to say anything" in rows["c59"] and "not enough days for promotion (needs 90)" in rows["c60"] and "not enough days for promotion (needs 90)" in rows["c89"] and "see the promotion gates" in rows["c90"]


def test_the_account_table_shows_halts_trips_pending_orders_and_the_champion_status():
    accts = [acct("x", "challenger", halted=True, breaker_trips=2, equity=8_300.0, day_pnl=-120.5, **{"return": -0.17}, drawdown=0.17, exposure=0.05, trades=3,
                  pending={"kind": "exit", "reason": "circuit_breaker", "signal_time": 1, "stop": None, "weight": None, "est_qty": None, "id": 4}), acct("y", "challenger", breaker_trips=1)]
    text = DY.build_report(crafted(accts, champions=["abc"], status="1 champion(s)"), None, None)
    row = next(line for line in text.splitlines() if line.startswith("| `x`"))
    assert "HALTED (2 trips)" in row and "$8,300.00" in row and "| -$120.50 |" in row
    assert "-17.00%" in row and "exit (circuit_breaker) at the next open" in row and "ok (1 trip)" in next(line for line in text.splitlines() if line.startswith("| `y`"))
    assert "1 champion(s)." in text and "all in cash" not in text


def test_the_command_line_exit_codes(monkeypatch, capsys):
    ok = crafted([acct("a", "benchmark")], steps={"a": {"processed": 1}})
    monkeypatch.setattr(DY, "run_daily", lambda **kw: ok)
    assert DY.main(["daily"]) == 0 and "no champions" in capsys.readouterr().out
    bad = crafted([acct("a", "benchmark")], steps={"a": {"error": "a: the candle after 2026-11-14T00:00:00Z is missing"}})
    monkeypatch.setattr(DY, "run_daily", lambda **kw: bad)
    assert DY.main(["daily"]) == 1 and "is missing" in capsys.readouterr().out

    def boom(**kw):
        raise D.DataError("not enough stored candles to run")
    monkeypatch.setattr(DY, "run_daily", boom)
    assert DY.main(["daily"]) == 1 and "daily run stopped: not enough stored candles to run" in capsys.readouterr().out


def test_the_largest_drawdown_counts_the_starting_equity_as_the_first_peak(tmp_path):
    base = history(400, seed=7)
    x = base[-1][4]
    closes = [x * 0.90, x * 0.855, x * 0.80]                                                       # the account falls from its very first day
    extra = []
    prev = x
    for i, c in enumerate(closes):
        extra.append((base[-1][0] + (i + 1) * DAY, prev, max(prev, c), min(prev, c), c, 100.0))
        prev = c
    cs = base + extra
    DY.run_daily(root=tmp_path, now=after(base), candles=base)
    dash = DY.run_daily(root=tmp_path, now=after(cs), candles=cs)
    bh = next(a for a in dash["accounts"] if a["id"] == "buy_hold")
    from atlas_api.btcquant import paper as PP
    eq = [r[1] for r in PP.PaperBook(tmp_path / "state").load("buy_hold")[0].curve]
    assert eq[0] < 10_000.0 and bh["max_drawdown"] == pytest.approx(1 - eq[-1] / 10_000.0) and bh["max_drawdown"] > 1 - eq[-1] / eq[0] and bh["drawdown"] == pytest.approx(bh["max_drawdown"])


def test_the_drawdown_and_the_day_result_of_an_account_are_worked_out_from_its_curve(tmp_path):
    cs = history(405, seed=7)
    DY.run_daily(root=tmp_path, now=after(cs[:400]), candles=cs[:400])
    DY.run_daily(root=tmp_path, now=after(cs), candles=cs)
    from atlas_api.btcquant import paper as PP
    a, _ = PP.PaperBook(tmp_path / "state").load("buy_hold")
    eq = [r[1] for r in a.curve]
    s = DY.account_summary(PP.PaperBook(tmp_path / "state"), __import__("atlas_api.btcquant.backtest", fromlist=["x"]).Prepared(cs), "buy_hold")
    peak = max([10_000.0] + eq)
    assert s["equity"] == eq[-1] and s["day_pnl"] == pytest.approx(eq[-1] - eq[-2]) and s["drawdown"] == pytest.approx(1 - eq[-1] / peak) and s["pnl"] == pytest.approx(eq[-1] - 10_000.0)
    worst = max(1 - e / max([10_000.0] + eq[:i + 1]) for i, e in enumerate(eq))
    assert s["max_drawdown"] == pytest.approx(worst) and s["days"] == 5


def test_families_that_were_not_admitted_are_paper_traded_as_monitors_and_challengers_are_not_doubled(tmp_path):
    cs = history(400)
    reg = R.Registry(tmp_path / "registry")
    for fam, params, dec in (("tsmom", {"L": 30}, "admitted"), ("donchian", {"N": 20}, "rejected"), ("rsi_oversold", {"n": 7, "enter": 20, "exit": 50}, "too_thin")):
        reg.log_candidate({"family": fam, "params": params, "decision": dec, "run": "research"})
    reg.admit({"family": "tsmom", "params": {"L": 30}})
    dash = DY.run_daily(root=tmp_path, now=after(cs), candles=cs)
    stages = {a["id"]: a["stage"] for a in dash["accounts"]}
    don, osold, tsm = (f"donchian-{S.spec_hash('donchian', {'N': 20})[:8]}", f"rsi_oversold-{S.spec_hash('rsi_oversold', {'n': 7, 'enter': 20, 'exit': 50})[:8]}", f"tsmom-{S.spec_hash('tsmom', {'L': 30})[:8]}")
    assert stages[don] == "monitor" and stages[osold] == "monitor" and stages[tsm] == "challenger" and len(stages) == 6                              # 3 benchmarks/portfolio + 1 challenger + 2 monitors
    assert sorted(dash["monitors"]) == sorted([don, osold]) and don in dash["opened_today"]
    text = (tmp_path / "reports/latest.md").read_text()
    assert "Monitored strategies (not admitted)" in text and don in text and "cannot be promoted without first passing the admission gates" in text and "2 accounts watched at once will always have a lucky one" in text
    assert dash["status"] == "no champions: the main portfolio is in cash" and DY.run_daily(root=tmp_path, now=after(cs), candles=cs)["opened_today"] == []
