"""Bank reserves, currency and the monetary base (Federal Reserve Board H.4.1 weekly and H.6 monthly, via FRED): parsed from real responses (fetched 2026-11-15: 411 weekly values of each since 2019-01-02 and 93 monthly values of each
since 2019-01). Hand-worked weekly and monthly figures (recomputed a second way with pandas), the accounting identity base = currency + reserves, every refusal with its boundary and the window it looks at, the real shock of March to
April 2020 that must NOT be refused, a short history, the stale labels, caching, failure, demo, the route and the plain-client rule."""
import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import reserves as R
from atlas_api.app import create_app
from atlas_api.moneysupply import _months_back

F = json.loads((Path(__file__).parent / "fixtures" / "fred_reserves.json").read_text())
TODAY = date(2026, 11, 14)
NOW = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
LAST_W = date(2026, 11, 11)
LAST_M = date(2026, 9, 1)


def _data():
    return {sid: R.parse(F[sid], sid) for sid in R.SERIES}


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(req):
    return httpx.Response(200, text=F[req.url.params["id"]])


def _first(d):
    return date(d.year, d.month, 1)


def _synthetic(cur=lambda m: 2000.0, res=lambda m: 3000.0, n_months=30, n_weeks=70):
    """A clean synthetic set built from one level per month (in billions): the monthly base is currency plus reserves exactly, and every Wednesday's weekly figures (in millions) are the level of its month, so each month's weekly
    average equals its monthly base. `n_months` months end 2026-09 and `n_weeks` Wednesdays end 2026-11-11. For testing one check at a time."""
    months = [_months_back(LAST_M, i) for i in range(n_months - 1, -1, -1)]
    weeks = [LAST_W - timedelta(days=7 * i) for i in range(n_weeks - 1, -1, -1)]
    mc, mr = {m: cur(m) for m in months}, {m: res(m) for m in months}
    return {"BOGMBASE": {m: mc[m] + mr[m] for m in months}, "MBCURRCIR": mc, "BOGMBBM": mr,
            "WCURCIR": {w: cur(_first(w)) * 1000.0 for w in weeks}, "WRESBAL": {w: res(_first(w)) * 1000.0 for w in weeks}}


def test_latest_weekly_and_monthly_figures_and_cross_checks_by_hand():
    s = R.summarize(_data(), TODAY)
    assert (s["date"], s["age_days"], s["freshness"]) == ("2026-11-11", 3, "CURRENT")
    assert s["weekly"] == {"date": "2026-11-11", "reserves_millions": 2960603.0, "currency_millions": 2493365.0,
                           "reserves_change_1w_pct": 1.0, "reserves_change_4w_pct": -2.0, "reserves_change_1y_pct": 3.7, "currency_change_1y_pct": 2.9,    # +1.041%, -2.036%, +3.698%, +2.923%
                           "reserves_year_low_millions": 2855030.0, "reserves_year_high_millions": 3142721.0, "weeks_in_year": 53, "reserves_rank_in_year": 47}   # 2025-11-12 to 2026-11-11; 25 of 53 weeks at or below
    assert s["monthly"] == {"month": "2026-09", "age_days": 74, "freshness": "CURRENT", "base_billions": 5449.8, "currency_billions": 2483.0, "reserves_billions": 2966.8, "gap_billions": 0.0,
                            "base_change_1m_pct": 0.7, "base_change_1y_pct": -0.5}                                                                          # 5449.8 = 2483.0 + 2966.8; +0.706% and -0.515%
    assert s["crosscheck"] == {"newest": {"month": "2026-09", "weeks": 5, "weekly_average_billions": 5438.2, "monthly_base_billions": 5449.8, "diff_pct": -0.21}, "months_compared": 6}   # April to September, each within 0.24%
    assert len(s["history"]) == 53 and s["history"][0] == {"date": "2025-11-12", "reserves_millions": 2855030.0} and s["history"][-1] == {"date": "2026-11-11", "reserves_millions": 2960603.0}
    assert all(s["checks"].values())


def test_a_short_history_says_not_available_for_what_it_cannot_compute():
    d = _data()
    for sid in ("WRESBAL", "WCURCIR"):
        d[sid] = {k: v for k, v in d[sid].items() if k >= LAST_W - timedelta(days=7 * 29)}      # the last 30 weeks
    for sid in ("BOGMBASE", "MBCURRCIR", "BOGMBBM"):
        d[sid] = {k: v for k, v in d[sid].items() if k >= date(2026, 1, 1)}                      # the last 9 months
    s = R.summarize(d, TODAY)
    assert s["weekly"]["reserves_change_1y_pct"] is None and s["weekly"]["currency_change_1y_pct"] is None and s["monthly"]["base_change_1y_pct"] is None
    assert s["weekly"]["weeks_in_year"] == 30 and s["weekly"]["reserves_change_4w_pct"] == -2.0


def test_stale_weekly_and_monthly_figures_are_overdue_with_real_age():
    assert R.summarize(_data(), LAST_W + timedelta(days=14))["freshness"] == "CURRENT"
    s = R.summarize(_data(), LAST_W + timedelta(days=15))
    assert s["freshness"] == "OVERDUE" and s["age_days"] == 15
    assert R.summarize(_data(), LAST_M + timedelta(days=100))["monthly"]["freshness"] == "CURRENT"
    m = R.summarize(_data(), LAST_M + timedelta(days=101))["monthly"]
    assert m["freshness"] == "OVERDUE" and m["age_days"] == 101


# ---- the weekly series ----

def test_the_weekly_dates_must_be_wednesdays_7_days_apart_and_the_same_for_both_series():
    def without(sid, pos):
        d = _synthetic(n_months=4)
        del d[sid][sorted(d[sid])[pos]]
        return d
    with pytest.raises(ValueError, match="not 7 days apart"):
        R.summarize(without("WRESBAL", -10), TODAY)
    with pytest.raises(ValueError, match="not 7 days apart"):
        R.summarize(without("WRESBAL", -52), TODAY)                                  # the gap lands inside the last 52 weeks
    assert R.summarize(without("WRESBAL", -53), TODAY)["available"]                  # the gap sits before them
    with pytest.raises(ValueError, match="do not cover the same weeks"):
        R.summarize(without("WCURCIR", -10), TODAY)
    assert R.summarize(without("WCURCIR", -53), TODAY)["available"]
    d = _synthetic(n_months=4)
    d["WRESBAL"][date(2026, 10, 15)] = d["WRESBAL"].pop(date(2026, 10, 14))           # a Thursday
    with pytest.raises(ValueError, match="not a Wednesday"):
        R.summarize(d, TODAY)


def test_the_weekly_value_ranges_are_inclusive():
    def levels(res=3000.0, cur=2000.0):
        return _synthetic(cur=lambda m: cur, res=lambda m: res)
    assert R.summarize(levels(res=500.0), TODAY)["weekly"]["reserves_millions"] == 500000.0
    assert R.summarize(levels(res=12000.0), TODAY)["weekly"]["reserves_millions"] == 12000000.0
    assert R.summarize(levels(cur=500.0), TODAY)["weekly"]["currency_millions"] == 500000.0
    assert R.summarize(levels(cur=8000.0), TODAY)["weekly"]["currency_millions"] == 8000000.0
    for kw in ({"res": 499.999}, {"res": 12000.001}, {"cur": 499.999}, {"cur": 8000.001}):
        with pytest.raises(ValueError, match="plausible range"):
            R.summarize(levels(**kw), TODAY)


def test_a_one_week_move_outside_the_real_record_is_refused_and_real_shocks_are_not():
    def last_week(sid, f):
        d = _synthetic(n_months=4)
        d[sid][LAST_W] *= f                                                          # the newest week is in a month without a monthly figure, so only the move checks can object
        return d
    assert R.summarize(last_week("WRESBAL", 1.49), TODAY)["weekly"]["reserves_change_1w_pct"] == 49.0
    assert R.summarize(last_week("WRESBAL", 0.71), TODAY)["weekly"]["reserves_change_1w_pct"] == -29.0
    assert R.summarize(last_week("WCURCIR", 1.09), TODAY)["weekly"]["currency_millions"] == 2180000.0
    assert R.summarize(last_week("WCURCIR", 0.96), TODAY)["weekly"]["currency_millions"] == 1920000.0
    with pytest.raises(ValueError, match="reserves changed by 51.0% in the week of 2026-11-11"):
        R.summarize(last_week("WRESBAL", 1.51), TODAY)
    with pytest.raises(ValueError, match="reserves changed by -31.0%"):
        R.summarize(last_week("WRESBAL", 0.69), TODAY)
    with pytest.raises(ValueError, match="currency changed by 11.0%"):
        R.summarize(last_week("WCURCIR", 1.11), TODAY)
    with pytest.raises(ValueError, match="currency changed by -6.0%"):
        R.summarize(last_week("WCURCIR", 0.94), TODAY)


def test_the_weekly_move_check_looks_at_the_last_52_weeks_and_no_further_back():
    def jump_at(pos):
        d = _synthetic(n_months=4)
        d["WRESBAL"][sorted(d["WRESBAL"])[pos]] *= 1.6                               # +60% into that week, then back down 37.5% (both outside the real record)
        return d
    with pytest.raises(ValueError, match="reserves changed by 60.0%"):
        R.summarize(jump_at(-51), TODAY)                                             # the jump lands on the 2nd week of the window: the move into it is inside
    assert R.summarize(jump_at(-53), TODAY)["available"]                             # both of its moves are before the window


# ---- the monthly series and the identity ----

def test_the_monthly_values_must_be_the_1st_in_a_row_and_the_same_months_in_all_three_series():
    def without(sid, pos):
        d = _synthetic()
        del d[sid][sorted(d[sid])[pos]]
        return d
    with pytest.raises(ValueError, match="skip a month"):
        R.summarize(without("BOGMBASE", -10), TODAY)
    with pytest.raises(ValueError, match="skip a month"):
        R.summarize(without("BOGMBASE", -24), TODAY)                                 # the oldest month of the window: the gap sits between its neighbours, inside
    assert R.summarize(without("BOGMBASE", -25), TODAY)["available"]                 # before the window
    with pytest.raises(ValueError, match="do not cover the same months"):
        R.summarize(without("MBCURRCIR", -10), TODAY)
    with pytest.raises(ValueError, match="do not cover the same months"):
        R.summarize(without("BOGMBBM", -10), TODAY)
    assert R.summarize(without("MBCURRCIR", -25), TODAY)["available"]
    d = _synthetic()
    d["BOGMBASE"][date(2026, 8, 15)] = d["BOGMBASE"].pop(date(2026, 8, 1))
    with pytest.raises(ValueError, match="not the 1st"):
        R.summarize(d, TODAY)


def test_a_unit_slip_in_the_monthly_series_is_caught_by_the_weekly_comparison_and_the_identity():
    d = _synthetic()
    for sid in ("BOGMBASE", "MBCURRCIR", "BOGMBBM"):
        d[sid] = {m: v * 1000.0 for m, v in d[sid].items()}                          # billions written as millions: every month x1000
    with pytest.raises(ValueError, match="weekly figures for 2026-09 add up to an average"):
        R.summarize(d, TODAY)
    d = _synthetic()
    d["BOGMBASE"] = {m: v / 10.0 for m, v in d["BOGMBASE"].items()}                  # only the total slips: the identity gives it away
    with pytest.raises(ValueError, match="away from currency plus reserve balances"):
        R.summarize(d, TODAY)


def test_the_base_and_currency_move_limits_by_month_and_the_window_they_look_at():
    def step(months_back, res_f=None, cur_f=None):
        """A permanent step at `months_back` months before 2026-09, older than the weekly figures, so only the monthly checks see it."""
        return _synthetic(cur=lambda m: 2000.0 * (cur_f if cur_f and _months_back(LAST_M, months_back) <= m else 1.0),
                          res=lambda m: 3000.0 * (res_f if res_f and _months_back(LAST_M, months_back) <= m else 1.0))
    # base 5,000 -> 6,950 is +39% (reserves 4,950 are +65%): allowed; 7,050 is +41%: refused
    assert R.summarize(step(20, res_f=4950.0 / 3000.0), TODAY)["available"]
    with pytest.raises(ValueError, match="the monetary base changed by 41.0%"):
        R.summarize(step(20, res_f=5050.0 / 3000.0), TODAY)
    # base 5,000 -> 4,260 is -14.8%: allowed (reserves 2,260 are -24.7%); 4,240 is -15.2%: refused
    assert R.summarize(step(20, res_f=2260.0 / 3000.0), TODAY)["available"]
    with pytest.raises(ValueError, match="the monetary base changed by -15.2%"):
        R.summarize(step(20, res_f=2240.0 / 3000.0), TODAY)
    # currency 2,000 -> 2,198 is +9.9%: allowed; 2,202 is +10.1%: refused; 1,902 is -4.9% allowed; 1,898 is -5.1% refused
    assert R.summarize(step(20, cur_f=1.099), TODAY)["available"]
    with pytest.raises(ValueError, match="currency changed by 10.1%"):
        R.summarize(step(20, cur_f=1.101), TODAY)
    assert R.summarize(step(20, cur_f=0.951), TODAY)["available"]
    with pytest.raises(ValueError, match="currency changed by -5.1%"):
        R.summarize(step(20, cur_f=0.949), TODAY)
    # the window: a step 22 months back puts its move on the 2nd month of the window (inside); 23 months back the move comes from before the window
    with pytest.raises(ValueError, match="the monetary base changed by 41.0%"):
        R.summarize(step(22, res_f=5050.0 / 3000.0), TODAY)
    assert R.summarize(step(23, res_f=5050.0 / 3000.0), TODAY)["available"]


def test_the_base_must_equal_currency_plus_reserves_in_each_of_the_last_12_months():
    def base_off(months_back, by):
        d = _synthetic()
        m = _months_back(LAST_M, months_back)
        d["BOGMBASE"][m] += by
        return d
    assert R.summarize(base_off(0, 0.4), TODAY)["monthly"]["gap_billions"] == 0.4
    assert R.summarize(base_off(0, -0.4), TODAY)["monthly"]["gap_billions"] == -0.4
    with pytest.raises(ValueError, match="0.6 billion away from currency plus reserve balances in 2026-09"):
        R.summarize(base_off(0, 0.6), TODAY)
    with pytest.raises(ValueError, match="-0.6 billion away"):
        R.summarize(base_off(0, -0.6), TODAY)
    with pytest.raises(ValueError, match="in 2025-10"):
        R.summarize(base_off(11, 0.6), TODAY)                                        # the 12th month back: inside
    assert R.summarize(base_off(12, 0.6), TODAY)["available"]                        # the 13th: outside


# ---- weekly against monthly ----

def test_the_weekly_figures_must_average_to_within_10_percent_of_the_monthly_base():
    def september_weeks(f):
        d = _synthetic()
        for w in d["WRESBAL"]:
            if (w.year, w.month) == (2026, 9):
                d["WRESBAL"][w] *= f
        return d
    for f, ok in ((1.15, True), (0.85, True), (1.17, False), (0.83, False)):         # reserves are 60% of the base: x1.15 moves the base by 9%, x1.17 by 10.2%
        if ok:
            assert R.summarize(september_weeks(f), TODAY)["crosscheck"]["newest"]["diff_pct"] == round((f - 1) * 60, 2)
        else:
            with pytest.raises(ValueError, match="weekly figures for 2026-09 add up to an average"):
                R.summarize(september_weeks(f), TODAY)


def test_the_cross_check_covers_the_last_6_comparable_months_and_no_older_one():
    def month_off(months_back):
        target = _months_back(LAST_M, months_back)
        d = _synthetic()
        for w in d["WRESBAL"]:
            if (w.year, w.month) == (target.year, target.month):
                d["WRESBAL"][w] *= 1.3                                               # 18% off the base for that month
        return d
    sixth = _months_back(LAST_M, 5)
    with pytest.raises(ValueError, match=f"weekly figures for {sixth.year}-{sixth.month:02d}"):
        R.summarize(month_off(5), TODAY)
    assert R.summarize(month_off(6), TODAY)["crosscheck"]["months_compared"] == 6    # the 7th month back is never looked at


def test_a_month_with_fewer_than_four_wednesdays_of_weekly_figures_is_not_compared():
    def with_october(last_wednesday):
        d = _synthetic()
        for sid, level in (("MBCURRCIR", 2000.0), ("BOGMBBM", 3000.0), ("BOGMBASE", 5000.0)):
            d[sid][date(2026, 10, 1)] = level
        for w in list(d["WRESBAL"]):
            if w > last_wednesday:
                del d["WRESBAL"][w]
                del d["WCURCIR"][w]
            elif (w.year, w.month) == (2026, 10):
                d["WRESBAL"][w] *= 1.4                                               # 24% off the base, so a comparison would refuse it
        return d
    s = R.summarize(with_october(date(2026, 10, 21)), TODAY)                         # three Wednesdays of October: not a whole month
    assert s["crosscheck"]["newest"]["month"] == "2026-09" and s["crosscheck"]["months_compared"] == 6
    with pytest.raises(ValueError, match="weekly figures for 2026-10 add up to an average"):
        R.summarize(with_october(date(2026, 10, 28)), TODAY)                         # four Wednesdays: compared


def test_fewer_than_3_comparable_months_means_the_check_cannot_be_made_and_the_card_says_so():
    assert R.summarize(_synthetic(n_months=3), TODAY)["crosscheck"]["months_compared"] == 3
    with pytest.raises(ValueError, match="fewer than 3 months"):
        R.summarize(_synthetic(n_months=2), TODAY)


def test_the_real_shock_of_2020_is_not_refused():
    d = _data()
    for sid in ("BOGMBASE", "MBCURRCIR", "BOGMBBM"):
        d[sid] = {k: v for k, v in d[sid].items() if k <= date(2020, 7, 1)}
    for sid in ("WRESBAL", "WCURCIR"):
        d[sid] = {k: v for k, v in d[sid].items() if k <= date(2020, 8, 5)}
    s = R.summarize(d, date(2020, 9, 20))                                            # base +12.4% in March and +24.8% in April, reserves +15.9% in the week of 1 April, March's weekly average 4.5% off its monthly base
    assert s["available"] and s["monthly"]["month"] == "2020-07" and s["crosscheck"]["months_compared"] == 6


# ---- the service ----

def test_missing_values_are_skipped_never_filled():
    s = R.parse("observation_date,WRESBAL\n2026-11-04,2930088\n2026-11-11,.\n2026-11-18,\n", "WRESBAL")
    assert s == {date(2026, 11, 4): 2930088.0}


def test_overview_fetches_five_series_and_caches():
    n = {"n": 0}

    def handler(req):
        n["n"] += 1
        return _handler(req)

    svc = R.BankReserves(client=_client(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["weekly"]["reserves_millions"] == 2960603.0 and n["n"] == 5 and "not a market signal or a forecast" in r["note"]
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 5


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(R.BankReserves(client=_client(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and "HTTP 503" in r["reason"] and "weekly" not in r
    bad = dict(F)
    bad["WRESBAL"] = F["WRESBAL"].replace("2026-11-11,2960603", "2026-11-11,29606030")                              # a decimal slip in the newest reserves: a check failing shows nothing either
    r = asyncio.run(R.BankReserves(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))
    assert r["available"] is False and "plausible range" in r["reason"] and "weekly" not in r


def test_a_dropped_connection_reads_plainly():
    def boom(req):
        raise httpx.ConnectError("")

    r = asyncio.run(R.BankReserves(client=_client(boom)).overview(NOW))
    assert r["available"] is False and r["reason"] == "Bank reserves and currency could not be read right now (the connection could not be made)"


def test_demo_mode_invents_nothing():
    d = asyncio.run(R.BankReserves(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "Demo" in d["reason"] and "weekly" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/bank-reserves")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True


def test_request_has_no_custom_user_agent_and_limits_the_download():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    asyncio.run(R.BankReserves(client=_client(handler)).overview(NOW))
    assert all("atlas" not in req.headers.get("user-agent", "").lower() for req in seen)     # FRED stalls on an unfamiliar one
    assert all("cosd" in req.url.params for req in seen) and {req.url.params["id"] for req in seen} == set(R.SERIES)
