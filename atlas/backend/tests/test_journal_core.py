from datetime import datetime, timedelta, timezone
from decimal import Decimal as Dec

import pytest

from atlas_api.journal import stats
from atlas_api.journal.matching import Exec, Flow, build_trades

T0 = datetime(2026, 3, 9, 15, 0, tzinfo=timezone.utc)


def ex(i, side, qty, price, fee="0", sym="BTC", src="x", minutes=0, kind="trade", **kw):
    return Exec(source=src, ext_id=f"e{i}", ts=T0 + timedelta(minutes=minutes), symbol=sym, asset_class="crypto", side=side, qty=Dec(str(qty)),
                price=Dec(str(price)), fee=Dec(str(fee)), kind=kind, **kw)


def one(evs, flows=None):
    trades, left = build_trades(evs, flows)
    return trades, left


# --- matching ---------------------------------------------------------------------------------------
def test_simple_long_round_trip_with_fees():
    (t,), _ = one([ex(1, "buy", 2, 100, "1", minutes=0), ex(2, "sell", 2, 110, "1.5", minutes=90)])
    assert (t.side, t.status, t.qty_max, t.entry_avg, t.exit_avg) == ("long", "closed", 2, 100, 110)
    assert t.gross_pnl == 20 and t.fees == Dec("2.5") and t.net_pnl == Dec("17.5") and t.holding_seconds == 5400 and t.key == "x|BTC|e1"
    assert t.exec_ids == ["e1", "e2"] and not t.liquidated


def test_short_round_trip_profits_when_price_falls():
    (t,), _ = one([ex(1, "sell", 3, 100), ex(2, "buy", 3, 90, minutes=5)])
    assert t.side == "short" and t.gross_pnl == 30 and t.net_pnl == 30


def test_fifo_matching_with_scaling_in_and_out_is_one_trade():
    evs = [ex(1, "buy", 1, 100, minutes=0), ex(2, "buy", 1, 120, minutes=1), ex(3, "sell", 1, 130, minutes=2), ex(4, "sell", 1, 110, minutes=3)]
    (t,), _ = one(evs)
    # FIFO: first sell closes the 100 lot (+30), second closes the 120 lot (-10)
    assert t.gross_pnl == 20 and t.entry_avg == 110 and t.exit_avg == 120 and t.qty_max == 2 and t.status == "closed"


def test_partial_close_leaves_the_trade_open():
    (t,), _ = one([ex(1, "buy", 4, 100), ex(2, "sell", 1, 110, minutes=1)])
    assert t.status == "open" and t.qty_open == 3 and t.gross_pnl == 10 and t.closed_at is None and t.holding_seconds is None


def test_flip_through_zero_splits_the_fill_and_prorates_the_fee():
    evs = [ex(1, "buy", 2, 100, "0"), ex(2, "sell", 5, 110, "5", minutes=1), ex(3, "buy", 3, 100, "0", minutes=2)]
    t1, t2 = one(evs)[0]
    assert (t1.side, t1.status, t1.gross_pnl, t1.fees) == ("long", "closed", 20, 2)             # closes 2 of the 5: fee 5*2/5
    assert (t2.side, t2.status, t2.gross_pnl, t2.fees) == ("short", "closed", 30, 3)            # remaining 3 sold short at 110, bought back at 100
    assert t2.key == "x|BTC|e2" and t2.entry_avg == 110 and t1.net_pnl + t2.net_pnl == Dec(20 + 30 - 5)


def test_separate_lifecycles_symbols_and_sources_do_not_mix():
    evs = [ex(1, "buy", 1, 100, sym="BTC"), ex(2, "buy", 1, 10, sym="ETH"), ex(3, "sell", 1, 120, sym="BTC", minutes=1), ex(4, "sell", 1, 9, sym="ETH", minutes=1),
           ex(5, "buy", 1, 100, src="y"), ex(6, "buy", 1, 100, sym="BTC", minutes=10), ex(7, "sell", 1, 90, sym="BTC", minutes=11)]
    trades, _ = one(evs)
    by = {(t.source, t.symbol, t.key): t for t in trades}
    assert len(trades) == 4 and by[("x", "BTC", "x|BTC|e1")].net_pnl == 20 and by[("x", "ETH", "x|ETH|e2")].net_pnl == -1
    assert by[("x", "BTC", "x|BTC|e6")].net_pnl == -10 and by[("y", "BTC", "y|BTC|e5")].status == "open"


def test_input_order_does_not_matter_and_ties_are_stable():
    a, b = ex(1, "buy", 1, 100, minutes=0), ex(2, "sell", 1, 110, minutes=1)
    assert one([b, a])[0][0].net_pnl == 10
    same_ts = [ex(1, "buy", 1, 100), ex(2, "sell", 1, 105)]
    assert one(same_ts)[0][0].status == "closed" and one(list(reversed(same_ts)))[0][0].status == "closed"


def test_liquidation_is_flagged_and_decimal_math_is_exact():
    evs = [ex(1, "buy", Dec("0.1"), Dec("0.1")), ex(2, "sell", Dec("0.1"), Dec("0.3"), kind="liquidation", minutes=1)]
    (t,), _ = one(evs)
    assert t.liquidated and t.gross_pnl == Dec("0.1") * Dec("0.2") == Dec("0.02")                    # 0.1*0.2 with no binary float error


def test_multiplier_scales_pnl():
    (t,), _ = one([ex(1, "buy", 2, 100, multiplier=Dec(50)), ex(2, "sell", 2, 101, multiplier=Dec(50), minutes=1)])
    assert t.gross_pnl == 100                                                                     # 2 contracts * $1 * 50


def test_funding_is_attributed_to_the_open_trade_and_the_rest_is_reported():
    evs = [ex(1, "buy", 1, 100, minutes=0), ex(2, "sell", 1, 100, minutes=120)]
    flows = [Flow("x", "f1", T0 + timedelta(minutes=30), "BTC", "funding", Dec("-0.4")), Flow("x", "f2", T0 + timedelta(minutes=60), "BTC", "funding", Dec("0.1")),
             Flow("x", "f3", T0 + timedelta(minutes=500), "BTC", "funding", Dec("-9")),            # after the trade closed
             Flow("x", "f4", T0 + timedelta(minutes=30), "ETH", "funding", Dec("-1")),             # a symbol that was never traded
             Flow("x", "t1", T0 + timedelta(minutes=30), None, "transfer", Dec("500")),
             Flow("x", "fee1", T0 + timedelta(minutes=40), "BTC", "fee", Dec("-0.25"))]
    (t,), left = one(evs, flows)
    assert t.funding == Dec("-0.3") and t.fees == Dec("0.25") and t.net_pnl == Dec("0") - Dec("0.25") + Dec("-0.3")
    assert sorted(f.ext_id for f in left) == ["f3", "f4", "t1"]


def test_open_trade_collects_funding_up_to_now():
    (t,), left = one([ex(1, "buy", 1, 100)], [Flow("x", "f", T0 + timedelta(days=30), "BTC", "funding", Dec("-2"))])
    assert t.funding == -2 and left == []


def test_invalid_executions_are_rejected_not_guessed():
    with pytest.raises(ValueError):
        build_trades([ex(1, "buy", 0, 100)])
    with pytest.raises(ValueError):
        build_trades([ex(1, "buy", 1, -5)])
    assert build_trades([]) == ([], [])


# --- statistics --------------------------------------------------------------------------------------
def tr(pnl, day=0, **kw):
    base = {"net_pnl": pnl, "closed_at": T0 + timedelta(days=day), "opened_at": T0 + timedelta(days=day - 1), "holding_seconds": 86400, "fees": 0, "funding": 0,
            "symbol": "BTC", "source": "x", "side": "long", "asset_class": "crypto", "currency": "USD"}
    return {**base, **kw}


def test_wilson_interval_matches_hand_calculation():
    lo, hi = stats.wilson(6, 10)
    assert lo == pytest.approx(0.3127, abs=1e-3) and hi == pytest.approx(0.8318, abs=1e-3)
    assert stats.wilson(0, 10)[0] == 0.0 and stats.wilson(10, 10)[1] == 1.0 and stats.wilson(0, 0) is None


def test_summary_hand_computed():
    s = stats.summary([tr(100, 0), tr(-50, 1), tr(30, 2), tr(-20, 3), tr(0, 4)])
    assert (s["n"], s["wins"], s["losses"], s["breakeven"]) == (5, 2, 2, 1) and s["win_rate"] == 0.4
    assert s["gross_profit"] == 130 and s["gross_loss"] == -70 and s["net_pnl"] == 60 and s["profit_factor"] == pytest.approx(130 / 70)
    assert s["avg_win"] == 65 and s["avg_loss"] == -35 and s["payoff_ratio"] == pytest.approx(65 / 35) and s["expectancy"] == 12
    assert s["best"] == 100 and s["worst"] == -50 and s["reliable"] is False and "anecdotal" in s["note"]
    # chronological cumulative: 100, 50, 80, 60, 60 -> peak 100, trough 50 -> drawdown 50
    assert s["max_drawdown"] == 50 and s["max_win_streak"] == 1 and s["max_loss_streak"] == 1
    assert s["expectancy_ci95"] is None                                                           # no interval claimed from 5 trades
    assert s["r"]["avg_r"] is None and "R-multiples are unavailable" in s["r"]["note"]


def test_profit_factor_undefined_without_losses_and_empty_input():
    s = stats.summary([tr(10), tr(20)])
    assert s["profit_factor"] is None and "undefined" in s["profit_factor_note"] and s["avg_loss"] is None and s["payoff_ratio"] is None
    assert stats.summary([]) == {"n": 0, "reliable": False, "min_sample": 30, "note": "no closed trades"}


def test_streaks_and_order_by_close_time_not_input_order():
    t = [tr(1, 4), tr(1, 1), tr(-1, 2), tr(-1, 3), tr(-1, 5), tr(1, 6)]
    s = stats.summary(t)
    # chronological by close day: d1 +, d2 -, d3 -, d4 +, d5 -, d6 +  -> longest loss streak 2, longest win streak 1
    assert s["max_win_streak"] == 1 and s["max_loss_streak"] == 2
    assert [x["pnl"] for x in stats.equity_curve(t)] == [1, -1, -1, 1, -1, 1]


def test_r_multiples_enter_the_summary_only_when_present():
    s = stats.summary([tr(100, r_multiple=2.0), tr(-50, 1, r_multiple=-1.0), tr(10, 2)])
    assert s["r"]["n"] == 2 and s["r"]["avg_r"] == 0.5 and s["r"]["total_r"] == 1.0


def test_bootstrap_interval_is_deterministic_and_only_from_30_trades():
    vals = [(-1) ** i * (i % 7 + 1) + 0.5 for i in range(60)]
    a, b = stats.bootstrap_mean_ci(vals), stats.bootstrap_mean_ci(vals)
    assert a == b and a[0] < sum(vals) / 60 < a[1]
    assert stats.bootstrap_mean_ci(vals[:29]) is None
    s = stats.summary([tr(v, i) for i, v in enumerate(vals)])
    assert s["reliable"] and s["note"] is None and s["expectancy_ci95"] == a


def test_groups_flag_small_samples_and_never_rank_them_above_reliable_ones():
    trades = [tr(10, i, setup="breakout") for i in range(35)] + [tr(500, 40 + i, setup="lucky") for i in range(3)]
    rows = stats.group_by(trades, "setup")
    assert [r["key"] for r in rows] == ["breakout", "lucky"] and rows[0]["reliable"] and not rows[1]["reliable"]        # 3 trades of +500 do not outrank 35 reliable ones
    assert rows[1]["net_pnl"] == 1500 and rows[1]["n"] == 3
    assert [r["key"] for r in stats.group_by([tr(1), tr(2, setup="a")], "setup")] and {r["key"] for r in stats.group_by([tr(1)], "setup")} == {"(no setup)"}


def test_time_buckets_use_new_york_time_across_dst():
    # 2026-03-08 06:30 UTC = 01:30 EST (before DST); 2026-03-09 05:30 UTC = 01:30 EDT (after DST): same ET hour bucket
    a = tr(1, opened_at=datetime(2026, 3, 8, 6, 30, tzinfo=timezone.utc))
    b = tr(1, opened_at=datetime(2026, 3, 9, 5, 30, tzinfo=timezone.utc))
    assert stats.GROUPS["hour_et"](a) == stats.GROUPS["hour_et"](b) == ["01:00"]
    assert stats.GROUPS["weekday_et"](tr(1, opened_at=datetime(2026, 3, 9, 3, 0, tzinfo=timezone.utc))) == ["Sun"]    # 23:00 ET on Sunday the 8th


def test_holding_and_r_buckets_boundaries():
    f = stats.GROUPS["holding"]
    assert [f(tr(1, holding_seconds=s))[0] for s in (3599, 3600, 86399, 86400, 7 * 86400 - 1, 7 * 86400, None)] == ["<1h", "1h-1d", "1h-1d", "1d-7d", "1d-7d", ">7d", "n/a"]
    g = stats.GROUPS["r_bucket"]
    assert [g(tr(1, r_multiple=r))[0] for r in (-2, -1, -0.1, 0, 0.9, 1, 1.9, 2, None)] == ["<-1R", "-1R..0", "-1R..0", "0..1R", "0..1R", "1R..2R", "1R..2R", ">=2R", "no stop"]


def test_tags_multiply_membership_and_unknown_group_is_an_error():
    rows = stats.group_by([tr(5, tags=["fomo", "early exit"]), tr(-5, 1, tags=["fomo"]), tr(1, 2)], "tag")
    assert {r["key"]: r["n"] for r in rows} == {"fomo": 2, "early exit": 1, "(untagged)": 1}
    with pytest.raises(ValueError):
        stats.group_by([], "nonsense")


def test_mixed_currencies_are_not_added_together():
    a = stats.analyze([tr(10, i) for i in range(3)] + [tr(5000, 9, currency="EUR")])
    assert a["currency"] == "USD" and a["excluded"] == {"EUR": 1} and a["summary"]["net_pnl"] == 30
    assert stats.analyze([])["currency"] is None
    assert set(a["groups"]) >= {"setup", "symbol", "hour_et", "tag"} and any("Past performance" in c for c in a["caveats"])


def test_expectancy_interval_is_explained_in_words():
    sym = [(-1) ** i * (3 + i % 5) for i in range(60)]                                              # alternating wins/losses, mean ~0
    s = stats.summary([tr(v, i) for i, v in enumerate(sym)])
    lo, hi = s["expectancy_ci95"]
    assert lo <= 0 <= hi and "INCLUDES zero" in s["expectancy_note"] and "reliable edge" in s["expectancy_note"]
    pos = stats.summary([tr(5 + i % 3, i) for i in range(60)])
    assert pos["expectancy_ci95"][0] > 0 and "excludes zero" in pos["expectancy_note"] and "does not guarantee" in pos["expectancy_note"]
    assert stats.summary([tr(5, i) for i in range(10)])["expectancy_note"] is None                  # no claim at all from a small sample
