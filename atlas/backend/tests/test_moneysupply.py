"""M2 money supply (monthly adjusted level, Federal Reserve Board via FRED) with cross-checks against the unadjusted monthly series and the weekly series: parsed from real responses (fetched 2026-11-15: 153 monthly values of each
since 2014-01 and 614 weekly values since 2015-01). Hand-worked level, changes, ten-year growth range and cross-check figures (recomputed a second way with pandas), every refusal with its boundary and the window it looks at, real shocks
(March to May 2020) that must NOT be refused, a short history, the stale label, caching, failure, demo, the route and the plain-client rule."""
import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import moneysupply as M
from atlas_api.app import create_app

F = json.loads((Path(__file__).parent / "fixtures" / "fred_m2.json").read_text())
TODAY = date(2026, 11, 14)
NOW = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
LAST = date(2026, 9, 1)
NEWEST_WEEK = date(2026, 10, 5)


def _data():
    return {sid: M.parse(F[sid], sid) for sid in M.SERIES}


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(req):
    return httpx.Response(200, text=F[req.url.params["id"]])


def _idx(d):
    """Months from LAST: 0 for the newest month, -1 for the one before."""
    return (d.year * 12 + d.month) - (LAST.year * 12 + LAST.month)


def _synthetic(level=lambda d: 20000.0, ns_level=None, week_scale=lambda d: 1.0, n_months=40):
    """A clean synthetic M2: `n_months` months ending 2026-09, adjusted = unadjusted = level(month), and every Monday from the first month to 2026-10-05 at the unadjusted level of its month times week_scale(month),
    so each month's weekly average equals its monthly figure exactly. For testing one check at a time."""
    ns_level = ns_level or level
    months = [M._months_back(LAST, i) for i in range(n_months - 1, -1, -1)]
    sa = {d: level(d) for d in months}
    ns = {d: ns_level(d) for d in months}
    wk = {}
    d = months[0] + timedelta(days=(7 - months[0].weekday()) % 7)
    while d <= NEWEST_WEEK:
        key = date(d.year, d.month, 1)
        wk[d] = ns_level(key if key in ns else LAST) * week_scale(key)
        d += timedelta(days=7)
    return {"M2SL": sa, "M2NS": ns, "WM2NS": wk}


def test_latest_level_changes_growth_and_cross_checks_by_hand():
    s = M.summarize(_data(), TODAY)
    assert (s["date"], s["month"], s["age_days"], s["freshness"]) == ("2026-09-01", "2026-09", 74, "CURRENT")
    assert s["level_billions"] == 23413.9
    assert s["change_1m_pct"] == 0.5 and s["change_3m_pct"] == 1.5 and s["change_1y_pct"] == 5.7      # against 23,300.9 (Aug), 23,077.7 (Jun) and 22,149.2 (Sep 2025): +0.485%, +1.457%, +5.710%
    assert s["growth"] == {"months": 120, "slowest": {"pct": -4.7, "month": "2023-04"}, "fastest": {"pct": 26.8, "month": "2021-02"}, "share_slower_pct": 66}    # 2016-10 to 2026-09; 79 of the 120 months grew slower than +5.71%
    assert s["seasonal"] == {"month": "2026-09", "adjusted": 23413.9, "unadjusted": 23339.6, "pct": 0.3}
    assert s["weekly"] == {"newest": {"month": "2026-09", "weeks": 4, "average": 23327.5, "unadjusted": 23339.6, "diff_pct": -0.05}, "months_compared": 6}   # Apr to Sep 2026, each 0.01 to 0.13% from the monthly figure
    assert len(s["history"]) == 36 and s["history"][0] == {"date": "2023-10-01", "level": 20712.3} and s["history"][-1] == {"date": "2026-09-01", "level": 23413.9}
    assert all(s["checks"].values())


def test_a_short_history_says_not_available_for_what_it_cannot_compute():
    d = _data()
    keep = LAST - timedelta(days=300)                                                # about 10 months
    d["M2SL"] = {k: v for k, v in d["M2SL"].items() if k >= keep}
    d["M2NS"] = {k: v for k, v in d["M2NS"].items() if k >= keep}
    s = M.summarize(d, TODAY)
    assert s["change_1y_pct"] is None and s["growth"] is None and s["change_3m_pct"] == 1.5 and s["level_billions"] == 23413.9


def test_the_ten_year_growth_comparison_needs_at_least_60_months_of_yearly_growth():
    assert M.summarize(_synthetic(n_months=71), TODAY)["growth"] is None             # 71 months give 59 yearly growth figures
    g = M.summarize(_synthetic(n_months=72), TODAY)["growth"]                        # 72 give 60
    assert g == {"months": 60, "slowest": {"pct": 0.0, "month": g["slowest"]["month"]}, "fastest": {"pct": 0.0, "month": g["fastest"]["month"]}, "share_slower_pct": 0}


def test_stale_is_overdue_with_real_age():
    assert M.summarize(_data(), LAST + timedelta(days=100))["freshness"] == "CURRENT"
    s = M.summarize(_data(), LAST + timedelta(days=101))
    assert s["freshness"] == "OVERDUE" and s["age_days"] == 101


def test_the_level_range_is_5000_to_60000_billion_inclusive():
    assert M.summarize(_synthetic(lambda d: 5000.0), TODAY)["level_billions"] == 5000.0
    assert M.summarize(_synthetic(lambda d: 60000.0), TODAY)["level_billions"] == 60000.0
    with pytest.raises(ValueError, match="plausible range"):
        M.summarize(_synthetic(lambda d: 4999.9), TODAY)
    with pytest.raises(ValueError, match="plausible range"):
        M.summarize(_synthetic(lambda d: 60000.1), TODAY)
    d = _data()
    for k in d["M2SL"]:
        d["M2SL"][k] *= 10.0
    with pytest.raises(ValueError, match="plausible range"):                         # a x10 slip in the whole series
        M.summarize(d, TODAY)


def test_the_range_check_looks_at_the_last_24_months_and_no_further_back():
    def low_until(cut):
        """Every month up to `cut` months back from 2026-09 is under the floor (4,900); the later ones are in range (5,300): a step of 8.2% that the move and year-on-year checks allow."""
        return _synthetic(lambda d: 4900.0 if _idx(d) <= -cut else 5300.0)
    with pytest.raises(ValueError, match="plausible range"):
        M.summarize(low_until(23), TODAY)                                            # the oldest month of the window (23 months before 2026-09) is under the floor: inside
    assert M.summarize(low_until(24), TODAY)["available"]                            # only the month before the window and older are under the floor: outside every window


def test_the_months_must_follow_each_other_in_the_last_24_and_start_on_the_1st():
    def without(pos):
        d = _synthetic()
        del d["M2SL"][sorted(d["M2SL"])[pos]]
        return d
    with pytest.raises(ValueError, match="skip a month"):
        M.summarize(without(-10), TODAY)
    with pytest.raises(ValueError, match="skip a month"):
        M.summarize(without(-24), TODAY)                                             # the oldest month of the window: the gap sits between it and the next one
    assert M.summarize(without(-25), TODAY)["available"]                             # the gap sits before the oldest month of the window: not looked at
    d = _synthetic()
    d["M2SL"][date(2026, 8, 15)] = d["M2SL"].pop(date(2026, 8, 1))
    with pytest.raises(ValueError, match="not the 1st"):
        M.summarize(d, TODAY)


def test_a_one_month_move_under_minus_5_or_over_plus_10_percent_is_refused():
    def last_month(level_last):
        return _synthetic(lambda d: level_last if d == LAST else 20000.0)
    assert M.summarize(last_month(21980.0), TODAY)["change_1m_pct"] == 9.9           # +9.9%
    assert M.summarize(last_month(19020.0), TODAY)["change_1m_pct"] == -4.9          # -4.9%
    with pytest.raises(ValueError, match="changed by 10.1% in 2026-09"):
        M.summarize(last_month(22020.0), TODAY)
    with pytest.raises(ValueError, match="changed by -5.1% in 2026-09"):
        M.summarize(last_month(18980.0), TODAY)


def test_the_month_move_check_looks_at_the_last_24_months_and_no_further_back():
    def step_up_at(months_back, f):
        return _synthetic(lambda d: 20000.0 * f if _idx(d) >= -months_back else 20000.0)
    with pytest.raises(ValueError, match="changed by 12.0%"):
        M.summarize(step_up_at(22, 1.12), TODAY)                                     # the step lands on the 2nd month of the window (22 months before 2026-09): the move into it is inside
    assert M.summarize(step_up_at(23, 1.12), TODAY)["available"]                     # the step lands on the first month of the window: the move into it comes from before the window


def test_year_on_year_growth_over_30_percent_or_under_minus_10_is_refused_and_real_shocks_are_not():
    def ramp(rate, k):
        return _synthetic(lambda d: 10000.0 * (1 + rate) ** max(0, k + _idx(d)))
    assert M.summarize(ramp(0.08, 3), TODAY)["change_1y_pct"] == 26.0                # +26%: like the real +26.8% of February 2021
    with pytest.raises(ValueError, match="over the year to 2026-09"):
        M.summarize(ramp(0.075, 4), TODAY)                                           # +33.6%: just over the 30% limit
    with pytest.raises(ValueError, match="over the year to 2026-09"):
        M.summarize(ramp(0.08, 4), TODAY)                                            # +36%
    assert M.summarize(ramp(-0.045, 2), TODAY)["change_1y_pct"] == -8.8              # -8.8%: like the real -4.7% of April 2023
    with pytest.raises(ValueError, match="over the year to 2026-09"):
        M.summarize(ramp(-0.045, 3), TODAY)                                          # -12.9%


def test_the_real_shock_of_2020_is_not_refused():
    d = _data()
    d["M2SL"] = {k: v for k, v in d["M2SL"].items() if k <= date(2020, 7, 1)}
    d["M2NS"] = {k: v for k, v in d["M2NS"].items() if k <= date(2020, 7, 1)}
    d["WM2NS"] = {k: v for k, v in d["WM2NS"].items() if k <= date(2020, 8, 3)}
    s = M.summarize(d, date(2020, 9, 20))                                            # +3.5%, +6.42%, +5.09% in three months; March's weekly figures average 0.64% under its monthly one
    assert s["available"] and s["month"] == "2020-07" and s["weekly"]["months_compared"] == 6 and s["growth"] is not None   # the six compared months are February to July, March among them


def test_adjusted_and_unadjusted_may_differ_by_up_to_2_percent_in_each_of_the_last_12_months():
    def off_in(month, pct):
        return _synthetic(lambda d: 20000.0, ns_level=lambda d: 20000.0 / (1 + pct) if d == month else 20000.0)
    assert M.summarize(off_in(LAST, 0.019), TODAY)["seasonal"]["pct"] == 1.9
    with pytest.raises(ValueError, match="differ by 2.1% in 2026-09"):
        M.summarize(off_in(LAST, 0.021), TODAY)
    with pytest.raises(ValueError, match="differ by -2.1% in 2026-09"):
        M.summarize(off_in(LAST, -0.021), TODAY)
    oldest = M._months_back(LAST, 11)
    with pytest.raises(ValueError, match="in 2025-10"):
        M.summarize(off_in(oldest, 0.03), TODAY)                                     # the 12th month back: inside
    assert M.summarize(off_in(M._months_back(LAST, 12), 0.03), TODAY)["available"]   # the 13th: outside


def test_fewer_than_6_months_with_both_series_means_the_seasonal_check_cannot_be_made():
    d = _synthetic()
    for k in sorted(d["M2NS"])[:-5]:
        del d["M2NS"][k]
    with pytest.raises(ValueError, match="cannot be compared"):
        M.summarize(d, TODAY)
    d = _synthetic()
    for k in sorted(d["M2NS"])[:-6]:
        del d["M2NS"][k]
    assert M.summarize(d, TODAY)["available"]


def test_the_weekly_dates_must_be_7_days_apart_in_the_last_26_weeks():
    def without_week(pos):
        d = _synthetic()
        del d["WM2NS"][sorted(d["WM2NS"])[pos]]
        return d
    with pytest.raises(ValueError, match="not 7 days apart"):
        M.summarize(without_week(-5), TODAY)
    with pytest.raises(ValueError, match="not 7 days apart"):
        M.summarize(without_week(-26), TODAY)                                        # the gap lands inside the last 26 weeks
    assert M.summarize(without_week(-27), TODAY)["available"]                        # the gap sits before them


def test_weekly_figures_must_average_to_within_1_percent_of_the_monthly_one():
    def scaled(month, f):
        return _synthetic(week_scale=lambda d: f if d == month else 1.0)
    assert M.summarize(scaled(LAST, 1.009), TODAY)["weekly"]["newest"]["diff_pct"] == 0.9
    with pytest.raises(ValueError, match="weekly figures for 2026-09 average"):
        M.summarize(scaled(LAST, 1.011), TODAY)
    with pytest.raises(ValueError, match="weekly figures for 2026-09 average"):
        M.summarize(scaled(LAST, 0.989), TODAY)


def test_the_weekly_check_covers_the_last_6_comparable_months_and_no_older_one():
    sixth = M._months_back(LAST, 5)
    seventh = M._months_back(LAST, 6)
    with pytest.raises(ValueError, match=f"weekly figures for {sixth.year}-{sixth.month:02d}"):
        M.summarize(_synthetic(week_scale=lambda d: 1.05 if d == sixth else 1.0), TODAY)
    assert M.summarize(_synthetic(week_scale=lambda d: 1.05 if d == seventh else 1.0), TODAY)["weekly"]["months_compared"] == 6


def test_a_month_whose_weekly_figures_stop_inside_it_is_not_compared():
    d = _synthetic()
    d["M2NS"][date(2026, 10, 1)] = 99999.0                                           # October has one weekly figure (Oct 5) so far: its monthly figure, however odd, is not compared (it is not in the adjusted series either)
    w = M.summarize(d, TODAY)["weekly"]
    assert w["newest"]["month"] == "2026-09" and w["months_compared"] == 6          # October is passed over and the sixth comparable month is still found (September back to April)
    for monday in (date(2026, 10, 12), date(2026, 10, 19)):
        d["WM2NS"][monday] = 20000.0
    assert M.summarize(d, TODAY)["weekly"]["newest"]["month"] == "2026-09"          # three Mondays of October: still not a whole month
    d["WM2NS"][date(2026, 10, 26)] = 20000.0
    with pytest.raises(ValueError, match="weekly figures for 2026-10 average"):     # four Mondays: compared, and the odd monthly figure shows
        M.summarize(d, TODAY)


def test_fewer_than_3_comparable_months_means_the_check_cannot_be_made_and_the_card_says_so():
    d = _synthetic()
    d["WM2NS"] = {k: v for k, v in d["WM2NS"].items() if k >= date(2026, 7, 6)}      # Jul 6 on: July 4 Mondays, August 5, September 4: three months
    assert M.summarize(d, TODAY)["weekly"]["months_compared"] == 3
    d["WM2NS"] = {k: v for k, v in d["WM2NS"].items() if k >= date(2026, 8, 3)}      # now August and September only
    with pytest.raises(ValueError, match="fewer than 3 months"):
        M.summarize(d, TODAY)


def test_missing_values_are_skipped_never_filled():
    s = M.parse("observation_date,M2SL\n2026-07-01,23177.4\n2026-08-01,.\n2026-09-01,\n", "M2SL")
    assert s == {date(2026, 7, 1): 23177.4}


def test_overview_fetches_three_series_and_caches():
    n = {"n": 0}

    def handler(req):
        n["n"] += 1
        return _handler(req)

    svc = M.MoneySupply(client=_client(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["level_billions"] == 23413.9 and n["n"] == 3 and "not a market signal or a forecast" in r["note"]
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 3


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(M.MoneySupply(client=_client(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and "HTTP 503" in r["reason"] and "level_billions" not in r
    bad = dict(F)
    bad["M2SL"] = F["M2SL"].replace("2026-09-01,23413.9", "2026-09-01,234139.0")                                   # a decimal slip in the newest value: a check failing shows nothing either
    r = asyncio.run(M.MoneySupply(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))
    assert r["available"] is False and "plausible range" in r["reason"] and "level_billions" not in r


def test_a_dropped_connection_reads_plainly():
    def boom(req):
        raise httpx.ConnectError("")

    r = asyncio.run(M.MoneySupply(client=_client(boom)).overview(NOW))
    assert r["available"] is False and r["reason"] == "The money supply could not be read right now (the connection could not be made)"


def test_demo_mode_invents_nothing():
    d = asyncio.run(M.MoneySupply(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "Demo" in d["reason"] and "level_billions" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/money-supply")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True


def test_request_has_no_custom_user_agent_and_limits_the_download():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    asyncio.run(M.MoneySupply(client=_client(handler)).overview(NOW))
    assert all("atlas" not in req.headers.get("user-agent", "").lower() for req in seen)     # FRED stalls on an unfamiliar one
    assert all("cosd" in req.url.params for req in seen) and {req.url.params["id"] for req in seen} == set(M.SERIES)
