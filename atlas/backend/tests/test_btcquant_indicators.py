"""btcquant indicators: hand-worked small cases, a slow straightforward second implementation of Wilder's ATR, RSI and ADX compared on a seeded random walk, the edge cases (flat, all gains), and
the property the whole system depends on: a value at index i never changes when later candles change."""
import numpy as np
import pytest

from atlas_api.btcquant import indicators as I


def nan_eq(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    assert a.shape == b.shape and np.array_equal(np.isnan(a), np.isnan(b)), (a, b)
    assert np.allclose(a[~np.isnan(a)], b[~np.isnan(b)], rtol=1e-12, atol=1e-12), (a, b)


def test_sma_is_the_mean_of_the_last_n_including_the_current_value():
    nan_eq(I.sma([1, 2, 3, 4, 5], 3), [np.nan, np.nan, 2, 3, 4])
    nan_eq(I.sma([1, 2], 3), [np.nan, np.nan])
    nan_eq(I.sma([5.0], 1), [5.0])


def test_rolling_std_uses_the_population_formula_by_default_and_the_sample_one_when_asked():
    nan_eq(I.rolling_std([1, 2, 3], 3), [np.nan, np.nan, np.sqrt(2 / 3)])
    nan_eq(I.rolling_std([1, 2, 3], 3, ddof=1), [np.nan, np.nan, 1.0])
    nan_eq(I.rolling_std([4, 4, 4, 4], 2), [np.nan, 0, 0, 0])


def test_rolling_extremes_prior_and_change():
    nan_eq(I.rolling_max([1, 3, 2, 5, 4], 2), [np.nan, 3, 3, 5, 5])
    nan_eq(I.rolling_min([1, 3, 2, 5, 4], 3), [np.nan, np.nan, 1, 2, 2])
    nan_eq(I.prior([1, 2, 3], 1), [np.nan, 1, 2])
    nan_eq(I.prior([1, 2, 3], 5), [np.nan] * 3)
    nan_eq(I.change([100, 110, 99], 1), [np.nan, 0.10, -0.10])
    nan_eq(I.change([100, 110, 121], 2), [np.nan, np.nan, 0.21])


def test_true_range_covers_gaps_between_candles():
    h, l, c = [10, 12, 11], [8, 9, 7], [9, 11, 8]
    nan_eq(I.true_range(h, l, c), [2, 3, 4])                 # candle 1: max(3, |12-9|, |9-9|) = 3; candle 2: max(4, |11-11|, |7-11|) = 4
    nan_eq(I.true_range([15], [10], [12]), [5])
    assert I.true_range([20, 30], [18, 27], [19, 28])[1] == 11   # a gap up: the previous close 19 to the high 30


def test_wilder_average_and_atr_by_hand():
    nan_eq(I.wilder([2, 3, 4, 5], 2), [np.nan, 2.5, 3.25, 4.125])          # seed (2+3)/2, then (2.5*1+4)/2 and (3.25*1+5)/2
    nan_eq(I.atr([10, 12, 11], [8, 9, 7], [9, 11, 8], 2), [np.nan, 2.5, 3.25])
    nan_eq(I.wilder([1, 2], 3), [np.nan, np.nan])


def test_rsi_by_hand_and_at_the_extremes():
    nan_eq(I.rsi([10, 11, 10.5, 12], 2), [np.nan, np.nan, 100 - 100 / 3, 100 - 100 / 9])     # avg gain .5, avg loss .25 -> RS 2; then 1.0 and .125 -> RS 8
    assert I.rsi([1, 2, 3, 4, 5], 2)[-1] == 100.0                                              # only gains
    assert I.rsi([5, 4, 3, 2, 1], 2)[-1] == 0.0                                                # only losses
    assert I.rsi([3, 3, 3, 3], 2)[-1] == 50.0                                                  # nothing moved
    nan_eq(I.rsi([1, 2], 2), [np.nan, np.nan])


def test_a_steady_trend_has_adx_100_and_a_choppy_market_has_a_low_adx():
    n = 3
    up = np.arange(1.0, 30.0)
    a = I.adx(up + 0.5, up - 0.5, up, n)
    assert np.all(np.isnan(a[:2 * n - 1])) and np.allclose(a[2 * n - 1:], 100.0)              # never a down move: -DI is zero, DX is 100 every day
    rng = np.random.default_rng(3)
    close = 100 + np.cumsum(rng.normal(0, 1, 300))
    a2 = I.adx(close + 1, close - 1, close, 14)
    assert 0 <= np.nanmin(a2) and np.nanmax(a2) <= 100 and np.nanmean(a2) < 40


def reference_wilder_indicators(h, l, c, n):
    """A deliberately slow, plain-loop version of ATR, RSI and ADX straight from Wilder's definitions, to compare with the vectorised code."""
    m = len(c)
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, m)]
    atr = [None] * m
    atr[n - 1] = sum(tr[:n]) / n
    for i in range(n, m):
        atr[i] = (atr[i - 1] * (n - 1) + tr[i]) / n
    rsi = [None] * m
    gains = [max(c[i] - c[i - 1], 0) for i in range(1, m)]
    losses = [max(c[i - 1] - c[i], 0) for i in range(1, m)]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    rsi[n] = 100 - 100 / (1 + ag / al) if al else 100.0
    for i in range(n + 1, m):
        ag, al = (ag * (n - 1) + gains[i - 1]) / n, (al * (n - 1) + losses[i - 1]) / n
        rsi[i] = 100 - 100 / (1 + ag / al) if al else 100.0
    pdm, mdm = [0.0], [0.0]
    for i in range(1, m):
        u, d = h[i] - h[i - 1], l[i - 1] - l[i]
        pdm.append(u if (u > d and u > 0) else 0.0)
        mdm.append(d if (d > u and d > 0) else 0.0)
    sp, sm, st = sum(pdm[1:n + 1]) / n, sum(mdm[1:n + 1]) / n, sum(tr[1:n + 1]) / n
    dx = {n: 100 * abs(100 * sp / st - 100 * sm / st) / (100 * sp / st + 100 * sm / st)}
    for i in range(n + 1, m):
        sp, sm, st = (sp * (n - 1) + pdm[i]) / n, (sm * (n - 1) + mdm[i]) / n, (st * (n - 1) + tr[i]) / n
        dx[i] = 100 * abs(100 * sp / st - 100 * sm / st) / (100 * sp / st + 100 * sm / st)
    adx = [None] * m
    adx[2 * n - 1] = sum(dx[i] for i in range(n, 2 * n)) / n
    for i in range(2 * n, m):
        adx[i] = (adx[i - 1] * (n - 1) + dx[i]) / n
    return atr, rsi, adx


def test_atr_rsi_and_adx_match_a_slow_plain_loop_version_on_a_random_walk():
    rng = np.random.default_rng(11)
    c = 100 + np.cumsum(rng.normal(0, 1.5, 400))
    h, l = c + rng.uniform(0.2, 2, 400), c - rng.uniform(0.2, 2, 400)
    for n in (5, 14):
        atr, rsi, adx = reference_wilder_indicators(list(h), list(l), list(c), n)
        for ours, ref in ((I.atr(h, l, c, n), atr), (I.rsi(c, n), rsi), (I.adx(h, l, c, n), adx)):
            nan_eq(ours, [np.nan if v is None else v for v in ref])


def test_bollinger_bands_and_realised_volatility_by_hand():
    lo, mid, hi = I.bollinger([1, 2, 3, 4], 3, 2.0)
    sd = np.sqrt(2 / 3)
    nan_eq(mid, [np.nan, np.nan, 2, 3]); nan_eq(lo, [np.nan, np.nan, 2 - 2 * sd, 3 - 2 * sd]); nan_eq(hi, [np.nan, np.nan, 2 + 2 * sd, 3 + 2 * sd])
    lo, mid, hi = I.bollinger([5, 5, 5], 3, 2.0)
    assert lo[2] == mid[2] == hi[2] == 5
    c = [100, 110, 99, 108.9]                                  # returns +10%, -10%, +10%
    v = I.realized_vol(c, 3)
    assert np.isnan(v[:3]).all() and v[3] == pytest.approx(np.std([0.10, -0.10, 0.10], ddof=1) * np.sqrt(365))
    assert I.realized_vol([100, 100, 100, 100], 3)[3] == 0.0
    nan_eq(I.realized_vol([1, 2], 3), [np.nan, np.nan])


def test_no_indicator_value_ever_depends_on_later_candles():
    rng = np.random.default_rng(5)
    c = 100 + np.cumsum(rng.normal(0, 1, 300))
    h, l = c + 1, c - 1
    cut = 200
    def build(c_, h_, l_):
        return {"sma": I.sma(c_, 20), "std": I.rolling_std(c_, 20), "max": I.rolling_max(h_, 20), "min": I.rolling_min(l_, 20), "prior": I.prior(c_, 1), "change": I.change(c_, 30),
                "atr": I.atr(h_, l_, c_, 14), "rsi": I.rsi(c_, 14), "adx": I.adx(h_, l_, c_, 14), "bb": I.bollinger(c_, 20, 2.0)[0], "vol": I.realized_vol(c_, 20)}
    full = build(c, h, l)
    c2, h2, l2 = c.copy(), h.copy(), l.copy()
    c2[cut:], h2[cut:], l2[cut:] = c[cut:] * 3 + 50, h[cut:] * 3 + 60, l[cut:] * 3 + 40            # change every candle from `cut` on
    part = build(c2, h2, l2)
    for k in full:
        nan_eq(full[k][:cut], part[k][:cut])
