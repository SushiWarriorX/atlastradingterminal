import time
from datetime import datetime, timezone

import numpy as np
import pytest
from fastapi.testclient import TestClient

from atlas_api import compare as cmp
from atlas_api import mtf
from atlas_api.app import create_app
from atlas_api.models import Candle, OHLCV, Provenance
from atlas_api.resample import MONDAY_OFFSET, resample

DAY = 86400


def ts(y, m, d, h=0):
    return int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp())


def c(t, close, vol=1.0):
    return Candle(time=t, open=close, high=close * 1.001, low=close * 0.999, close=close, volume=vol)


# --- calendar alignment ---------------------------------------------------------
def test_daily_alignment_crypto_24_7_vs_equity_sessions():
    mon = ts(2026, 10, 5)                                   # a Monday
    btc = [c(mon + i * DAY, 100 + i) for i in range(21)]    # every calendar day, stamped 00:00 UTC
    # equities: weekdays only, stamped 00:00 New York = 04:00 UTC (EDT) -- same UTC DATE as the crypto bar
    eq = [c(mon + i * DAY + 4 * 3600, 50 + i) for i in range(21) if (i % 7) < 5]
    times, al = cmp.align({"BTC": btc, "EQ": eq}, "1d")
    assert len(times) == 15 and len(al["BTC"]) == len(al["EQ"]) == 15
    assert times == [b.time for b in al["BTC"]]             # x axis comes from the first series
    assert all(datetime.fromtimestamp(t, timezone.utc).weekday() < 5 for t in times)   # weekends dropped from BOTH
    assert btc[5].time not in times and btc[6].time not in times                        # Sat, Sun


def test_returns_use_the_shared_horizon_friday_to_monday():
    mon = ts(2026, 10, 5)
    btc = [c(mon + i * DAY, 100 * (1 + 0.01 * i)) for i in range(14)]          # drifts every day incl. the weekend
    eq = [c(mon + i * DAY + 4 * 3600, 50.0 + i) for i in range(14) if (i % 7) < 5]
    _, al = cmp.align({"BTC": btc, "EQ": eq}, "1d")
    closes = [x.close for x in al["BTC"]]
    r = cmp.returns(closes)
    fri, nxt_mon = btc[4].close, btc[7].close
    assert r[4] == pytest.approx(nxt_mon / fri - 1)                            # Fri -> Mon spans 3 calendar days for BOTH series
    assert r[4] > 0.025                                                        # clearly not a single-day return


def test_intraday_cross_calendar_refuses_instead_of_faking_alignment():
    h = 3600
    btc = [c(ts(2026, 10, 5) + i * h, 100 + i) for i in range(48)]                    # on the hour
    eq = [c(ts(2026, 10, 5, 13) + 30 * 60 + i * h, 50 + i) for i in range(7)]         # 09:30 ET bars: on the half hour
    with pytest.raises(cmp.NoOverlap) as e:
        cmp.align({"BTC": btc, "EQ": eq}, "1h")
    assert "1d or 1w" in str(e.value)
    same = [c(btc[0].time + i * h, 1 + i) for i in range(48)]
    assert len(cmp.align({"A": btc, "B": same}, "1h")[0]) == 48                        # identical timestamps do align


def test_weekly_bars_start_on_monday():
    mon = ts(2026, 10, 26)
    days = [c(mon - 7 * DAY + i * DAY, 100 + i, 10) for i in range(21)]                # three weeks starting Mon 19 Oct
    wk = resample(days, 7 * DAY, MONDAY_OFFSET)
    assert [datetime.fromtimestamp(x.time, timezone.utc).strftime("%a %d") for x in wk] == ["Mon 19", "Mon 26", "Mon 02"]
    assert wk[0].volume == 70 and wk[0].open == days[0].open and wk[0].close == days[6].close
    wed = [c(ts(2026, 10, 28), 1)]
    assert datetime.fromtimestamp(resample(wed, 7 * DAY, MONDAY_OFFSET)[0].time, timezone.utc).strftime("%a %d") == "Mon 26"


# --- statistics ------------------------------------------------------------------
def prices(rets, start=100.0):
    out = [start]
    for r in rets:
        out.append(out[-1] * (1 + r))
    return out


def test_corr_beta_known_relationships():
    rng = np.random.default_rng(1)
    r = rng.normal(0, 0.01, 200)
    base, twice, inverse = prices(r), prices(2 * r), prices(-r)
    s = cmp.pair_stats(base, twice)
    assert s["observations"] == 200 and s["windows"]["60"]["corr"] == pytest.approx(1.0)
    assert s["windows"]["60"]["beta_of_other_on_base"] == pytest.approx(2.0)
    assert cmp.pair_stats(base, inverse)["windows"]["180"]["corr"] == pytest.approx(-1.0)
    flat = cmp.pair_stats(base, [100.0] * 201)
    assert flat["full_sample_corr"] is None and flat["windows"]["20"]["corr"] is None          # undefined, not 0
    assert s["total_return_pct"]["other"] != s["total_return_pct"]["base"]


def test_short_samples_report_unavailable_windows_with_the_count():
    rng = np.random.default_rng(2)
    r = rng.normal(0, 0.01, 50)
    s = cmp.pair_stats(prices(r), prices(r * 0.5))
    assert s["observations"] == 50 and s["windows"]["20"]["available"] is True
    for w in ("60", "90", "180"):
        assert s["windows"][w] == {"available": False, "observations": 50}                       # never silently shortened
    assert "rolling_60" not in s


def test_rolling_correlation_shows_instability():
    rng = np.random.default_rng(3)
    a = rng.normal(0, 0.01, 240)
    b = np.concatenate([a[:120], -a[120:]]) + rng.normal(0, 0.002, 240)                          # correlation flips sign mid-sample
    s = cmp.pair_stats(prices(a), prices(b))
    r = s["rolling_60"]
    assert r["max"] > 0.9 and r["min"] < -0.9 and r["min"] <= r["latest"] <= r["max"] and "unstable" in r["note"]


def test_rebase_starts_at_100():
    assert cmp.rebase([50.0, 55.0, 25.0]) == [100.0, 110.0, 50.0]


# --- structure rules ---------------------------------------------------------------
def zig(closes):
    t0 = ts(2026, 1, 5)
    return [Candle(time=t0 + i * DAY, open=x, high=x * 1.001, low=x * 0.999, close=x, volume=1) for i, x in enumerate(closes)]


UP = [10, 12, 10.5, 14, 11, 16, 12, 15]       # swing highs 12,14,16 / swing lows 10.5,11,12 -> HH + HL


def test_structure_uptrend_downtrend_range_and_events():
    up = mtf.structure(zig(UP), k=1)
    assert up["label"] == "uptrend" and up["event"] is None and up["prior_swing_high"] == pytest.approx(14 * 1.001) and up["last_swing_high"] == pytest.approx(16 * 1.001)
    assert "swing highs" in up["derivation"]
    assert mtf.structure(zig(UP[:-1] + [17.5]), k=1)["event"] == "BOS bullish"                   # close beyond last swing high, with the trend
    down = mtf.structure(zig([30 - x for x in UP]), k=1)
    assert down["label"] == "downtrend"
    assert mtf.structure(zig([30 - x for x in UP[:-1]] + [30 - 17.5]), k=1)["event"] == "BOS bearish"   # close 12.5 < last swing low ~14: break WITH the trend
    choch = mtf.structure(zig([30 - x for x in UP[:-1]] + [30 - 12.5 + 8]), k=1)
    assert choch["label"] == "downtrend" and choch["event"] == "CHoCH bullish"                   # break against the trend
    rng_ = mtf.structure(zig([10, 12, 10, 14, 10, 12, 10.5, 12]), k=1)                           # equal-ish highs/lows
    assert rng_["label"] == "range"
    assert mtf.structure(zig([1, 2, 3, 4, 5, 6]), k=1)["label"] == "insufficient_data"


def test_analyze_tf_requires_history_and_drops_the_forming_bar():
    now = time.time()
    few = [c(int(now) - 3600 * (20 - i) - 5000, 100 + i) for i in range(20)]
    assert mtf.analyze_tf(few, "1h", 3600, now)["available"] is False
    n = 60
    bars = [c(int(now // 3600) * 3600 - 3600 * (n - 1 - i), 100 + i * 0.1 + (i % 3), 5) for i in range(n)]   # last bar opened this hour = forming
    a = mtf.analyze_tf(bars, "1h", 3600, now)
    assert a["available"] and a["bars"] == n - 1 and a["last_close"] == bars[-2].close
    assert a["trend"] in ("bullish", "bearish", "mixed") and a["structure"]["label"] in ("uptrend", "downtrend", "range", "insufficient_data")


def tf(i, trend="mixed", struct="range", **kw):
    return {"interval": i, "available": True, "trend": trend, "structure": {"label": struct}, "rsi14": kw.get("rsi"), "macd_hist": kw.get("macd"),
            "rvol": kw.get("rvol"), "change_pct": kw.get("chg", 0.0), "atr_pct": kw.get("atr", 2.0)}


def test_alignment_verdicts_including_the_spec_example():
    ex = [tf("1w", "bullish"), tf("1d", "bullish"), tf("4h", "mixed"), tf("1h", "bearish"), tf("15m", "mixed")]
    a = mtf.alignment(ex)
    assert a["verdict"] == "bullish higher timeframes, short-term unconfirmed" and "4h mixed" in a["text"] and a["bullish"] == ["1w", "1d"]
    assert mtf.alignment([tf(i, "bullish") for i in mtf.TIMEFRAMES])["verdict"] == "aligned bullish"
    assert mtf.alignment([tf(i, "bearish") for i in mtf.TIMEFRAMES])["verdict"] == "aligned bearish"
    assert mtf.alignment([tf("1w", "bullish"), tf("1d", "bearish"), tf("4h", "mixed")])["verdict"] == "conflicting"
    assert mtf.alignment([tf("1d", "mixed"), tf("1h", "mixed")])["verdict"] == "mixed"
    off = [{"interval": "1w", "available": False}, {"interval": "1d", "available": False}]
    assert mtf.alignment(off)["verdict"] == "no data"
    part = mtf.alignment([tf("1d", "bullish"), {"interval": "1w", "available": False, "reason": "x"}])
    assert part["available"] == 1 and part["of"] == 2                                            # unavailable timeframes are not counted as agreeing


# --- score ---------------------------------------------------------------------------
def test_score_hand_computed():
    d = tf("1d", "bullish", "uptrend", rsi=75, macd=0.5, rvol=1.5, chg=2.0)
    s = mtf.score([d], rs_pp=8.0)
    f = s["factors"]
    assert f["trend"]["value"] == 1.0 and f["structure"]["value"] == 1.0
    assert f["momentum"]["value"] == pytest.approx(1.0)                  # mean(clip((75-50)/25)=1, macd>0 -> 1)
    assert f["volume"]["value"] == pytest.approx(0.5)                    # +1 * min(1.5-1, 1)
    assert f["relative_strength"]["value"] == pytest.approx(0.4)         # 8pp / 20
    # tilt = .25*1 + .20*1 + .20*1 + .10*.5 + .25*.4 = 0.80  -> score 90
    assert s["tilt"] == pytest.approx(0.8) and s["score"] == 90.0 and s["label"] == "bullish tilt"
    assert sum(x["contribution"] for x in f.values()) == pytest.approx(s["tilt"])
    assert f["volatility"]["weight"] == 0 and f["volatility"]["contribution"] == 0 and f["volatility"]["context_only"]


def test_unavailable_factor_is_excluded_and_weights_renormalised_not_imputed():
    d = tf("1d", "bullish", "uptrend", rsi=75, macd=0.5, rvol=1.5, chg=2.0)
    s = mtf.score([d], rs_pp=None)
    f = s["factors"]
    assert s["unavailable"] == ["relative_strength"] and f["relative_strength"]["effective_weight"] == 0 and not f["relative_strength"]["available"]
    assert sum(x["effective_weight"] for x in f.values()) == pytest.approx(1.0)
    assert s["tilt"] == pytest.approx((0.25 + 0.20 + 0.20 + 0.05) / 0.75) and s["score"] == 96.7


def test_score_with_nothing_available_is_none_and_weights_are_overridable():
    s = mtf.score([{"interval": "1d", "available": False}], None)
    assert s["score"] is None and s["label"] is None
    d = tf("1d", "bearish", "downtrend", rsi=20, macd=-1, rvol=2.0, chg=-3.0)
    heavy = mtf.score([d], rs_pp=-20, weights={"trend": 1, "structure": 0, "momentum": 0, "volume": 0, "relative_strength": 0})
    assert heavy["tilt"] == -1.0 and heavy["score"] == 0.0 and heavy["label"] == "bearish tilt"
    neutral = mtf.score([tf("1d", "mixed", "range", rsi=50, macd=0.0)], None)
    assert neutral["label"] == "neutral" and neutral["score"] == 50.0


# --- API -------------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "m.db"), demo=True, alert_loop=False)) as c:
        yield c


def test_api_compare_demo(client):
    r = client.get("/api/compare", params={"ids": "BTC-USD,QQQ,SPY", "interval": "1d", "limit": 250}).json()["data"]
    assert r["aligned_bars"] > 100 and len(r["times"]) == r["aligned_bars"] and r["base"] == "CRYPTO:COINBASE:BTC-USD:SPOT"
    for s in r["series"].values():
        assert s["rebased"][0] == 100.0 and len(s["rebased"]) == r["aligned_bars"] and s["prov"]["status"] == "DEMO"
    assert set(r["stats"]) == {"ETF:NASDAQ:QQQ", "ETF:ARCA:SPY"}
    w = r["stats"]["ETF:NASDAQ:QQQ"]["windows"]
    assert w["20"]["available"] and w["180"]["available"] and "rolling_60" in r["stats"]["ETF:NASDAQ:QQQ"]
    assert any("calendar-aligned" in n for n in r["notes"])


def test_api_compare_validation(client):
    g = client.get
    assert g("/api/compare", params={"ids": "BTC-USD"}).status_code == 422
    assert g("/api/compare", params={"ids": "BTC-USD,BTC-USD"}).status_code == 422
    assert g("/api/compare", params={"ids": "BTC-USD,QQQ,SPY,IWM,DIA"}).status_code == 422
    assert g("/api/compare", params={"ids": "BTC-USD,NOPE123456"}).status_code == 404
    assert g("/api/compare", params={"ids": "BTC-USD,QQQ", "interval": "1M"}).json()["error"]["code"] == "DATA_UNAVAILABLE"


def test_api_mtf_equity_has_benchmark_and_btc_does_not(client):
    a = client.get("/api/technical/mtf", params={"instrument_id": "AAPL"}).json()["data"]
    assert [t["interval"] for t in a["timeframes"]] == ["1w", "1d", "4h", "1h", "15m"] and all(t["available"] for t in a["timeframes"])
    assert a["benchmark"] == "SPY" and a["score"]["factors"]["relative_strength"]["available"] and "63 aligned daily observations" in a["score"]["factors"]["relative_strength"]["note"]
    assert 0 <= a["score"]["score"] <= 100 and a["alignment"]["verdict"] and set(a["rules"]) >= {"trend", "structure", "momentum"}
    assert a["timeframes"][2]["data"]["derived_from"] == "1h" and all(t["data"]["status"] == "DEMO" for t in a["timeframes"])
    b = client.get("/api/technical/mtf", params={"instrument_id": "BTC-USD"}).json()["data"]
    assert b["benchmark"] is None and "relative_strength" in b["score"]["unavailable"] and b["score"]["factors"]["relative_strength"]["note"] == "no benchmark selected"
    q = client.get("/api/technical/mtf", params={"instrument_id": "BTC-USD", "benchmark": "QQQ"}).json()["data"]
    assert q["benchmark"] == "QQQ" and q["score"]["factors"]["relative_strength"]["available"]
    assert client.get("/api/technical/mtf", params={"instrument_id": "AAPL", "swing_k": 0}).status_code == 422


class Partial:
    """A provider that only has 1h and 1d: 15m must come back unavailable, not invented."""
    name, entitlement, delay_seconds, native_intervals = "coinbase", "test", 0, {"1h", "1d"}

    async def ohlcv(self, inst, interval, limit):
        sec = {"1h": 3600, "1d": 86400}[interval]
        now = int(time.time())
        end = now - now % sec
        cs = [Candle(time=end - (limit - i) * sec, open=100 + i, high=101 + i, low=99 + i, close=100 + i * 0.5 + (i % 4), volume=10) for i in range(limit)]
        return OHLCV(instrument_id=inst.id, interval=interval, candles=cs, prov=Provenance(
            provider="coinbase", instrument_id=inst.id, event_time=datetime.now(timezone.utc), ingested_time=datetime.now(timezone.utc), delay_seconds=0))


def test_api_mtf_missing_timeframe_is_reported_unavailable(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "p.db"), demo=False, providers={"coinbase": Partial()}, alert_loop=False)) as c:
        d = c.get("/api/technical/mtf", params={"instrument_id": "BTC-USD"}).json()["data"]
        by = {t["interval"]: t for t in d["timeframes"]}
        assert by["15m"]["available"] is False and "15m" in by["15m"]["reason"]
        assert by["1h"]["available"] and by["1d"]["available"] and by["4h"]["available"]       # 4h derived from 1h
        assert d["alignment"]["available"] == 4 and d["alignment"]["of"] == 5
