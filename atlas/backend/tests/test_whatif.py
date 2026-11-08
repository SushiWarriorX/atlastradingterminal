"""What-if simulator: exact arithmetic on known price paths, correct bars-per-year for stocks and crypto, honest limits."""
import math

import numpy as np
import pytest

from atlas_api.signal import whatif as W

DAY = 86400


def bars(prices, step=DAY):
    return [(1_600_000_000 + i * step, float(p)) for i, p in enumerate(prices)]


def test_lump_sum_is_exact_and_reports_the_dip_after_buying():
    # 3 trading years (~756 bars): flat 100, dip to 80, finish at 150
    p = [100.0] * 300 + [80.0] * 100 + [150.0] * 400
    r = W.simulate(bars(p, step=int(365.25 * DAY / 252)), 1000, "x")
    one = r["lump_sum"][0]
    assert one["return_pct"] == pytest.approx(0.0) and one["value_now"] == pytest.approx(1000.0)      # a year ago it was already 150 and flat since
    three = next(x for x in r["lump_sum"] if x["label"] == "3 years ago")
    assert three["value_now"] == pytest.approx(1000 * 150 / three["buy_price"])
    assert three["lowest_vs_cost_pct"] == pytest.approx((80 / three["buy_price"] - 1) * 100)


def test_years_follow_the_calendar_for_both_stocks_and_crypto():
    for per_year in (252, 365):
        n = per_year * 3 + 5
        step = 365.25 * DAY / per_year
        r = W.simulate([(1_600_000_000 + i * step, 100 + i * 0.01) for i in range(n)], 500, "k")
        assert abs(r["bars_per_year"] - per_year) <= 1
        labels = [x["label"] for x in r["lump_sum"]]
        assert labels[:2] == ["1 year ago", "3 years ago"]          # three years of bars plus a few days: 1 and 3 years fit, 5 does not
        assert abs(r["lump_sum"][0]["days"] - per_year) <= 1


def test_steady_growth_gives_the_same_answer_every_start():
    c = [100 * 1.0004 ** i for i in range(1000)]
    r = W.simulate(bars(c, step=int(365.25 * DAY / 252)), 100, "s")
    e = r["every_start"][0]
    assert e["worst_pct"] == pytest.approx(e["best_pct"], rel=1e-6) and e["share_positive"] == 1.0
    assert all(x["result_pct"] > 0 for blk in r["exit_rules"] for x in blk["rules"] if x["rule"] in ("hold", "stop"))


def test_stop_and_target_trigger_on_closes():
    c = np.array([100, 105, 90, 79, 60, 120], float)
    assert W._exit(c, 0, "stop")["result_pct"] == pytest.approx(-21.0) and W._exit(c, 0, "stop")["sold_on_idx"] == 3
    assert not W._exit(c, 0, "target")["sold"]                       # never reached +30% before the end... it did reach 120 (+20%) only
    t = W._exit(np.array([100, 110, 131, 90], float), 0, "target")
    assert t["sold"] and t["result_pct"] == pytest.approx(31.0)
    tr = W._exit(np.array([100, 150, 119, 200], float), 0, "trail")
    assert tr["sold_on_idx"] == 2 and tr["result_pct"] == pytest.approx(19.0)


def test_bootstrap_is_repeatable_and_sane():
    rng = np.random.default_rng(1)
    c = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, 900)))
    a, b = W.bootstrap(c, 7, 252), W.bootstrap(c, 7, 252)
    assert a == b and a["p5_pct"] < a["median_pct"] < a["p95_pct"] and 0 <= a["share_positive"] <= 1
    assert W.bootstrap(c[:100], 7, 252) is None


def test_short_history_is_refused_plainly():
    with pytest.raises(ValueError, match="at least"):
        W.simulate(bars([100] * 50), 1000, "x")


def test_monthly_buying_counts_months_and_compares_with_lump_sum():
    c = [100.0 + (i % 40) for i in range(800)]
    r = W.simulate(bars(c, step=int(365.25 * DAY / 252)), 100, "m")
    m = r["monthly"][0]
    assert 11 <= m["buys"] <= 13 and m["invested"] == pytest.approx(100 * m["buys"])
    assert math.isfinite(m["same_money_lump_sum_return_pct"])


def test_whatif_api_in_demo_mode_is_labelled_and_validated(tmp_path):
    from fastapi.testclient import TestClient
    from atlas_api.app import create_app
    with TestClient(create_app(db_path=str(tmp_path / "w.db"), demo=True, alert_loop=False)) as c:
        r = c.get("/api/signal/whatif/EQUITY:NASDAQ:AAPL?amount=2500")
        assert r.status_code == 200, r.text
        d = r.json()["data"]
        assert d["prov"]["status"] == "DEMO" and d["amount"] == 2500 and d["lump_sum"] and d["bootstrap"]
        assert any("Research only" in x for x in d["caveats"])
        assert c.get("/api/signal/whatif/EQUITY:NASDAQ:AAPL?amount=0").status_code == 422
        assert c.get("/api/signal/whatif/EQUITY:NASDAQ:AAPL?amount=99999999999").status_code == 422
