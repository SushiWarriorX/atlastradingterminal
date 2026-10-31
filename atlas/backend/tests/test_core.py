from datetime import datetime, timezone

import numpy as np
import pytest

from atlas_api import indicators as ind
from atlas_api.models import Candle, DataStatus
from atlas_api.resample import resample
from atlas_api.sessions import session_state
from atlas_api.status import classify

# Wilder's classic RSI(14) example prices, rounded to 2dp. The published RSI (70.53, ...) was computed
# from unrounded prices, so it differs by ~0.07 here; we assert hand-derived values for THESE prices.
WILDER = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61,
          46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64, 46.21, 46.25, 45.71, 46.45, 45.78, 45.35,
          44.03, 44.18, 44.22, 44.57, 43.42, 42.66, 43.13]


def test_rsi_matches_reference():
    r = ind.rsi(WILDER, 14)
    assert np.isnan(r[:14]).all()
    # Hand arithmetic, independent of the implementation: first avg gain = 3.34/14, avg loss = 1.40/14.
    ag, al = 3.34 / 14, 1.40 / 14
    assert ag == pytest.approx(0.2386, abs=1e-4) and al == pytest.approx(0.1, abs=1e-4)
    assert r[14] == pytest.approx(100 - 100 / (1 + ag / al))
    # One Wilder smoothing step: 46.28 -> 46.00 is a 0.28 loss and no gain.
    ag, al = ag * 13 / 14, (al * 13 + 0.28) / 14
    assert r[15] == pytest.approx(100 - 100 / (1 + ag / al))
    assert r[14] == pytest.approx(70.46, abs=0.01)


def test_sma_ema_known_values():
    x = [1, 2, 3, 4, 5, 6]
    assert ind.sma(x, 3)[2:].tolist() == [2, 3, 4, 5]
    e = ind.ema(x, 3)  # seed = mean(1,2,3)=2; k=0.5
    assert e[2:].tolist() == [2.0, 3.0, 4.0, 5.0]
    assert np.isnan(ind.sma([1, 2], 5)).all()  # insufficient history -> NaN, never a guess


def test_atr_constant_range_and_wilder_seed():
    h, l, c = [11] * 20, [9] * 20, [10] * 20
    a = ind.atr(h, l, c, 14)
    assert np.isnan(a[:13]).all() and a[13:] == pytest.approx([2.0] * 7)


def test_bollinger_population_std():
    lo, mid, up = ind.bollinger([1, 2, 3, 4, 5], 5, 2)
    assert mid[-1] == 3 and up[-1] == pytest.approx(3 + 2 * np.sqrt(2))


def test_macd_shapes_and_warmup():
    c = list(np.linspace(100, 130, 80))
    line, sig, hist = ind.macd(c)
    assert np.isnan(line[:25]).all() and not np.isnan(line[25])
    assert np.isnan(sig[:33]).all() and not np.isnan(sig[33])
    assert hist[-1] == pytest.approx(line[-1] - sig[-1])


def test_vwap_resets_each_utc_day_and_rvol_excludes_current():
    day = 86400
    cs = [Candle(time=0, open=1, high=3, low=1, close=2, volume=10), Candle(time=60, open=2, high=4, low=2, close=3, volume=10),
          Candle(time=day, open=9, high=9, low=9, close=9, volume=5)]
    v = ind.vwap(cs)
    assert v[0] == pytest.approx(2.0) and v[1] == pytest.approx(2.5) and v[2] == pytest.approx(9.0)
    r = ind.rvol([10, 10, 30], 2)
    assert np.isnan(r[:2]).all() and r[2] == pytest.approx(3.0)


def test_compute_rejects_unknown():
    with pytest.raises(ValueError):
        ind.compute([Candle(time=0, open=1, high=1, low=1, close=1)], ["nope:1"])


def test_resample_4h_aligned_and_ohlcv():
    h = 3600
    cs = [Candle(time=i * h, open=i, high=i + 1, low=i - 1, close=i + .5, volume=1) for i in range(5)]
    r = resample(cs, 4 * h)
    assert [c.time for c in r] == [0, 4 * h]
    assert (r[0].open, r[0].high, r[0].low, r[0].close, r[0].volume) == (0, 4, -1, 3.5, 4)


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def test_sessions_dst_and_calendar():
    # EST (before DST): regular open 14:30 UTC. EDT (after 8 Mar 2026): 13:30 UTC.
    assert session_state(utc(2026, 3, 6, 14, 29))["state"] == "PREMARKET"
    assert session_state(utc(2026, 3, 6, 14, 30))["state"] == "REGULAR"
    assert session_state(utc(2026, 3, 9, 13, 29))["state"] == "PREMARKET"
    assert session_state(utc(2026, 3, 9, 13, 30))["state"] == "REGULAR"
    assert session_state(utc(2026, 3, 9, 20, 0))["state"] == "AFTER_HOURS"
    assert session_state(utc(2026, 3, 10, 1, 0))["state"] == "CLOSED"
    assert session_state(utc(2026, 3, 7, 15, 0))["state"] == "CLOSED"           # Saturday
    assert session_state(utc(2026, 11, 26, 15, 0))["state"] == "HOLIDAY"        # Thanksgiving
    early = session_state(utc(2026, 11, 27, 17, 59))                            # 12:59 ET
    assert early["early_close"] and early["state"] == "REGULAR"
    assert session_state(utc(2026, 11, 27, 18, 1))["state"] == "AFTER_HOURS"    # 13:01 ET


def test_classify_rules():
    now = utc(2026, 3, 9, 15, 0)
    f = lambda **k: classify(**{"provider": "yahoo", "asset_class": "equity", "event_time": now, "now": now,
                                "delay_seconds": 900, "session": "REGULAR", **k})[0]
    assert f() == DataStatus.DELAYED
    assert f(delay_seconds=0) == DataStatus.LIVE
    assert f(event_time=utc(2026, 3, 9, 13, 0)) == DataStatus.STALE
    assert f(session="CLOSED") == DataStatus.HISTORICAL
    assert f(provider="demo") == DataStatus.DEMO
    assert f(asset_class="macro") == DataStatus.HISTORICAL
    assert f(event_time=None) == DataStatus.STALE
    assert f(asset_class="crypto", delay_seconds=0, session=None) == DataStatus.LIVE
    assert f(asset_class="crypto", event_time=utc(2026, 3, 9, 14, 58), session=None) == DataStatus.STALE
