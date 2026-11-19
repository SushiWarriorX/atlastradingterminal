"""US retail and food services sales (Census Bureau Advance Monthly Retail Trade Survey via FRED): parsed from real responses (fetched 2026-11-17 05:18 UTC: 153 monthly values per series since 2014-01, newest 2026-09). Hand-worked level, changes, parts, shares,
ten-year growth range and sum check (recomputed a second way in plain Python before the module was written), every refusal with its boundary and the window it looks at, the real shock of 2020 that must NOT be refused, a short history, the overdue label,
caching, failure, demo, the route and the plain-client rule."""
import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import retailsales as R
from atlas_api.app import create_app

F = json.loads((Path(__file__).parent / "fixtures" / "fred_retail.json").read_text())
TODAY = date(2026, 11, 17)
NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
LAST = date(2026, 9, 1)


def _data():
    return {sid: R.parse(F[sid], sid) for sid in R.SERIES}


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(req):
    return httpx.Response(200, text=F[req.url.params["id"]])


def _idx(d):
    """Months from LAST: 0 for the newest month, -1 for the one before."""
    return (d.year * 12 + d.month) - (LAST.year * 12 + LAST.month)


def _synthetic(total=lambda d: 700_000, food=None, n_months=40):
    """A clean synthetic set: `n_months` months ending 2026-09, a total of `total(month)` million dollars, food services 12% of it (whole dollars, so retail trade plus food services is the total exactly) or `food(month)`. For testing one check at a time."""
    months = [R._months_back(LAST, i) for i in range(n_months - 1, -1, -1)]
    sa = {d: float(total(d)) for d in months}
    fs = {d: float(food(d)) if food else float(int(sa[d]) * 12 // 100) for d in months}
    rx = {d: sa[d] - fs[d] for d in months}
    return {"RSAFS": sa, "RSXFS": rx, "RSFSDP": fs}


def test_latest_level_changes_parts_growth_and_sums_by_hand():
    s = R.summarize(_data(), TODAY)
    assert (s["date"], s["month"], s["age_days"], s["freshness"]) == ("2026-09-01", "2026-09", 77, "CURRENT")
    assert s["level_billions"] == 745.0
    assert s["change_1m_pct"] == 0.8 and s["change_3m_pct"] == 1.7 and s["change_1y_pct"] == 6.3          # against 739,322 (Aug), 732,898 (Jun) and 700,948 (Sep 2025): +0.771%, +1.654%, +6.288%
    assert s["retail"] == {"level_billions": 652.1, "share_pct": 87.5, "change_1m_pct": 0.7, "change_1y_pct": 6.2}     # 652,115 against 647,440 (+0.722%) and 614,111 (+6.189%); 87.530% of the total
    assert s["food"] == {"level_billions": 92.9, "share_pct": 12.5, "change_1m_pct": 1.1, "change_1y_pct": 7.0}       # 92,906 against 91,882 (+1.115%) and 86,837 (+6.989%); 12.470% of the total
    assert s["growth"] == {"months": 120, "slowest": {"pct": -19.5, "month": "2020-04"}, "fastest": {"pct": 51.5, "month": "2021-04"}, "share_slower_pct": 79}    # 2016-10 to 2026-09; 95 of the 120 months grew slower than +6.29%
    assert s["sums"] == {"months_checked": 24, "max_difference_millions": 0.0,
                         "newest": {"month": "2026-09", "retail_millions": 652115.0, "food_millions": 92906.0, "total_millions": 745021.0, "difference_millions": 0.0}}
    assert all(s["checks"].values()) and "not a market signal or a forecast" in s["note"] and "NOT adjusted for price changes" in s["note"] and "advance estimate" in s["note"]


def test_the_history_is_the_last_36_months_in_billions_oldest_first():
    s = R.summarize(_data(), TODAY)
    assert len(s["history"]) == 36 and s["history"][0] == {"date": "2023-10-01", "level": 667.8} and s["history"][-1] == {"date": "2026-09-01", "level": 745.0}
    assert [h["date"] for h in s["history"]] == sorted(h["date"] for h in s["history"])


def test_a_short_history_says_not_available_for_what_it_cannot_compute():
    d = _data()
    keep = LAST - timedelta(days=300)                                                # about 10 months
    d = {sid: {k: v for k, v in s.items() if k >= keep} for sid, s in d.items()}
    s = R.summarize(d, TODAY)
    assert s["change_1y_pct"] is None and s["growth"] is None and s["change_3m_pct"] == 1.7 and s["level_billions"] == 745.0
    assert s["retail"]["change_1y_pct"] is None and s["food"]["change_1y_pct"] is None and s["retail"]["change_1m_pct"] == 0.7


def test_the_ten_year_growth_comparison_needs_at_least_60_months_of_yearly_growth():
    assert R.summarize(_synthetic(n_months=71), TODAY)["growth"] is None             # 71 months give 59 yearly growth figures
    g = R.summarize(_synthetic(n_months=72), TODAY)["growth"]                        # 72 give 60
    assert g == {"months": 60, "slowest": {"pct": 0.0, "month": g["slowest"]["month"]}, "fastest": {"pct": 0.0, "month": g["fastest"]["month"]}, "share_slower_pct": 0}


def test_overdue_after_90_days_from_the_first_of_the_month():
    assert R.summarize(_data(), LAST + timedelta(days=90))["freshness"] == "CURRENT"
    s = R.summarize(_data(), LAST + timedelta(days=91))
    assert s["freshness"] == "OVERDUE" and s["age_days"] == 91


def test_the_level_range_is_100000_to_2000000_million_dollars_inclusive():
    assert R.summarize(_synthetic(lambda d: 100_000), TODAY)["level_billions"] == 100.0
    assert R.summarize(_synthetic(lambda d: 2_000_000), TODAY)["level_billions"] == 2000.0
    with pytest.raises(ValueError, match="plausible range"):
        R.summarize(_synthetic(lambda d: 99_999), TODAY)
    with pytest.raises(ValueError, match="plausible range"):
        R.summarize(_synthetic(lambda d: 2_000_001), TODAY)
    d = _data()
    for sid in d:
        for k in d[sid]:
            d[sid][k] *= 10.0
    with pytest.raises(ValueError, match="plausible range"):                         # a x10 slip in every series
        R.summarize(d, TODAY)


def test_the_range_check_looks_at_the_last_24_months_and_no_further_back():
    def low_until(cut):
        """Every month up to `cut` months back from 2026-09 is under the floor (99,000); the later ones are in range (105,000): a step of 6.1% that the move and year-on-year checks allow."""
        return _synthetic(lambda d: 99_000 if _idx(d) <= -cut else 105_000)
    with pytest.raises(ValueError, match="plausible range"):
        R.summarize(low_until(23), TODAY)                                            # the oldest month of the window (23 months before 2026-09) is under the floor: inside
    assert R.summarize(low_until(24), TODAY)["available"]                            # only the month before the window and older are under the floor: outside every window


def test_the_months_must_follow_each_other_in_the_last_24_and_start_on_the_1st():
    def without(pos):
        d = _synthetic()
        del d["RSAFS"][sorted(d["RSAFS"])[pos]]
        return d
    with pytest.raises(ValueError, match="skip a month"):
        R.summarize(without(-10), TODAY)
    with pytest.raises(ValueError, match="skip a month"):
        R.summarize(without(-24), TODAY)                                             # the oldest month of the window: the gap sits between it and the next one
    assert R.summarize(without(-25), TODAY)["available"]                             # the gap sits before the oldest month of the window: not looked at
    d = _synthetic()
    d["RSAFS"][date(2026, 8, 15)] = d["RSAFS"].pop(date(2026, 8, 1))
    with pytest.raises(ValueError, match="not the 1st"):
        R.summarize(d, TODAY)


def test_a_one_month_move_under_minus_25_or_over_plus_30_percent_is_refused():
    def last_month(level_last):
        return _synthetic(lambda d: level_last if d == LAST else 700_000)
    assert R.summarize(last_month(909_000), TODAY)["change_1m_pct"] == 29.9          # +29.9%
    assert R.summarize(last_month(525_700), TODAY)["change_1m_pct"] == -24.9         # -24.9%
    with pytest.raises(ValueError, match="changed by 30.1% in 2026-09"):
        R.summarize(last_month(910_700), TODAY)
    with pytest.raises(ValueError, match="changed by -25.1% in 2026-09"):
        R.summarize(last_month(524_300), TODAY)


def test_the_month_move_check_looks_at_the_last_24_months_and_no_further_back():
    def step_up_at(months_back, f):
        return _synthetic(lambda d: 700_000 * f if _idx(d) >= -months_back else 700_000)
    with pytest.raises(ValueError, match="changed by 40.0%"):
        R.summarize(step_up_at(22, 1.4), TODAY)                                      # the step lands on the 2nd month of the window (22 months before 2026-09): the move into it is inside
    assert R.summarize(step_up_at(23, 1.4), TODAY)["available"]                      # the step lands on the first month of the window: the move into it comes from before the window


def test_year_on_year_growth_over_60_percent_or_under_minus_30_is_refused_and_real_shocks_are_not():
    def ramp(rate):
        return _synthetic(lambda d: 500_000 * (1 + rate) ** max(0, 12 + _idx(d)))    # flat, then twelve months of steady growth ending in 2026-09
    def yearly(rate):
        return round(100 * ((1 + rate) ** 12 - 1), 1)                                # the year-on-year growth of twelve steady months, worked outside the module
    assert yearly(0.0399) == 59.9 and R.summarize(ramp(0.0399), TODAY)["change_1y_pct"] == 59.9      # +59.9%: just under the 60% limit, like the real +51.5% of April 2021
    with pytest.raises(ValueError, match="grew 60.1% over the year to 2026-09"):
        R.summarize(ramp(0.04), TODAY)                                               # +60.1%: just over it
    assert yearly(-0.0292) == -29.9 and R.summarize(ramp(-0.0292), TODAY)["change_1y_pct"] == -29.9  # -29.9%: like the real -19.5% of April 2020
    with pytest.raises(ValueError, match="grew -30.1% over the year to 2026-09"):
        R.summarize(ramp(-0.0294), TODAY)                                            # -30.1%


def test_the_real_shock_of_2020_and_its_rebound_are_not_refused():
    for cut, today, month in ((date(2020, 7, 1), date(2020, 9, 20), "2020-07"), (date(2021, 6, 1), date(2021, 8, 20), "2021-06")):
        d = {sid: {k: v for k, v in s.items() if k <= cut} for sid, s in _data().items()}
        s = R.summarize(d, today)                                                    # April 2020 is -14.18% on the month and -19.51% on the year, May +19.42%; April 2021 is +51.49% on the year
        assert s["available"] and s["month"] == month and s["growth"] is not None


def test_the_parts_must_add_up_to_the_total_within_one_million_dollars_in_each_of_the_last_24_months():
    def off(month, by, part="RSXFS"):
        d = _synthetic()
        d[part][month] += by
        return d
    assert R.summarize(off(LAST, 1.0), TODAY)["sums"]["newest"]["difference_millions"] == 1.0          # rounding-sized: allowed
    assert R.summarize(off(LAST, -1.0), TODAY)["sums"]["max_difference_millions"] == 1.0
    with pytest.raises(ValueError, match=r"is \+1.1 million dollars away from the total in 2026-09"):
        R.summarize(off(LAST, 1.1), TODAY)
    with pytest.raises(ValueError, match=r"is -1.1 million dollars away from the total in 2026-09"):
        R.summarize(off(LAST, -1.1), TODAY)
    with pytest.raises(ValueError, match="away from the total in 2026-09"):
        R.summarize(off(LAST, 2000.0, part="RSFSDP"), TODAY)                         # the other part too
    oldest = R._months_back(LAST, 23)
    with pytest.raises(ValueError, match="away from the total in 2024-10"):
        R.summarize(off(oldest, 500.0), TODAY)                                       # the 24th month back: inside
    assert R.summarize(off(R._months_back(LAST, 24), 500.0), TODAY)["available"]      # the 25th: outside


def test_the_largest_difference_over_the_window_is_reported_not_the_first_or_the_last_one():
    d = _synthetic()
    d["RSXFS"][R._months_back(LAST, 10)] += 0.5
    d["RSXFS"][R._months_back(LAST, 5)] += 1.0
    d["RSXFS"][R._months_back(LAST, 2)] -= 0.25
    s = R.summarize(d, TODAY)["sums"]
    assert s["max_difference_millions"] == 1.0 and s["newest"]["difference_millions"] == 0.0 and s["months_checked"] == 24


def test_a_part_missing_from_any_one_month_of_the_window_is_refused_for_either_part():
    for part in ("RSXFS", "RSFSDP"):
        d = _synthetic()
        del d[part][R._months_back(LAST, 5)]
        with pytest.raises(ValueError, match="retail trade or food services is missing for 2026-04"):
            R.summarize(d, TODAY)


def test_a_date_that_is_not_the_1st_matters_only_inside_the_window():
    d = _synthetic()
    old = R._months_back(LAST, 30)
    d["RSAFS"][date(old.year, old.month, 15)] = d["RSAFS"].pop(old)                  # 30 months back: outside the 24-month window
    assert R.summarize(d, TODAY)["available"]


def test_a_one_month_fall_of_exactly_25_percent_is_allowed():
    s = R.summarize(_synthetic(lambda d: 525_000 if d == LAST else 700_000), TODAY)  # 0.75 is exact in floating point, so this sits exactly on the limit (+30%, +60% and -30% have no exact ratio, so their edges cannot be hit)
    assert s["change_1m_pct"] == -25.0


def test_food_services_must_be_between_5_and_20_percent_of_the_total():
    assert R.summarize(_synthetic(food=lambda d: 35_000), TODAY)["food"]["share_pct"] == 5.0               # exactly 5% in every month
    assert R.summarize(_synthetic(food=lambda d: 140_000), TODAY)["food"]["share_pct"] == 20.0             # exactly 20% in every month
    with pytest.raises(ValueError, match="food services are 4.9% of retail sales in 2026-09, outside 5% to 20%"):
        R.summarize(_synthetic(food=lambda d: 34_300 if d == LAST else 84_000), TODAY)
    with pytest.raises(ValueError, match="food services are 20.1% of retail sales in 2026-09, outside 5% to 20%"):
        R.summarize(_synthetic(food=lambda d: 140_700 if d == LAST else 84_000), TODAY)
    oldest = R._months_back(LAST, 23)
    with pytest.raises(ValueError, match="food services are 3.0% of retail sales in 2024-10"):
        R.summarize(_synthetic(food=lambda d: 21_000 if d == oldest else 84_000), TODAY)                   # the 24th month back: inside
    assert R.summarize(_synthetic(food=lambda d: 21_000 if d == R._months_back(LAST, 24) else 84_000), TODAY)["available"]      # the 25th: outside
    d = _data()
    d["RSXFS"], d["RSFSDP"] = d["RSFSDP"], d["RSXFS"]                                # the two parts swapped: they still add up to the total, but food services would be about 88% of it
    with pytest.raises(ValueError, match="food services are 87.8% of retail sales in 2024-10, outside 5% to 20%"):      # the oldest month of the window is the first one named
        R.summarize(d, TODAY)


def test_a_part_missing_a_month_or_a_series_ending_in_another_month_is_refused():
    d = _synthetic()
    del d["RSXFS"][LAST]
    with pytest.raises(ValueError, match="end in different months"):
        R.summarize(d, TODAY)
    d = _synthetic()
    d["RSFSDP"][date(2026, 10, 1)] = 84_000.0                                        # a part that is a month AHEAD of the total
    with pytest.raises(ValueError, match="end in different months"):
        R.summarize(d, TODAY)
    d = _synthetic()
    del d["RSFSDP"][R._months_back(LAST, 5)]
    with pytest.raises(ValueError, match="retail trade or food services is missing for 2026-04"):
        R.summarize(d, TODAY)
    d = _synthetic()
    del d["RSXFS"][R._months_back(LAST, 24)]                                         # a hole before the window: not looked at
    assert R.summarize(d, TODAY)["sums"]["months_checked"] == 24


def test_missing_values_are_skipped_never_filled():
    s = R.parse("observation_date,RSAFS\n2026-07-01,729915\n2026-08-01,.\n2026-09-01,\n", "RSAFS")
    assert s == {date(2026, 7, 1): 729915.0}


def test_overview_fetches_three_series_and_caches():
    n = {"n": 0}

    def handler(req):
        n["n"] += 1
        return _handler(req)

    svc = R.RetailSales(client=_client(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["level_billions"] == 745.0 and n["n"] == 3 and r["source"].startswith("U.S. Census Bureau") and r["url"] == "https://fred.stlouisfed.org/series/RSAFS"
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 3


def test_a_success_is_kept_for_six_hours_and_a_failure_for_two_minutes(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(R.time, "monotonic", lambda: clock["t"])
    n = {"n": 0, "ok": False}

    def handler(req):
        n["n"] += 1
        return _handler(req) if n["ok"] else httpx.Response(503)

    svc = R.RetailSales(client=_client(handler))
    assert asyncio.run(svc.overview(NOW))["available"] is False and n["n"] == 3
    clock["t"] += R.FAIL_TTL - 1
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 3                                                               # still the failure from the cache
    clock["t"] += 2
    n["ok"] = True
    assert asyncio.run(svc.overview(NOW))["available"] is True and n["n"] == 6       # two minutes on it asks again
    clock["t"] += R.TTL - 1
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 6
    clock["t"] += 2
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 9 and (R.FAIL_TTL, R.TTL) == (120.0, 21600.0)


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(R.RetailSales(client=_client(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and "HTTP 503" in r["reason"] and "level_billions" not in r
    bad = dict(F)
    bad["RSAFS"] = F["RSAFS"].replace("2026-09-01,745021", "2026-09-01,7450210")                                   # a decimal slip in the newest value: a check failing shows nothing either
    r = asyncio.run(R.RetailSales(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))
    assert r["available"] is False and "plausible range" in r["reason"] and "level_billions" not in r


def test_a_dropped_connection_reads_plainly():
    def boom(req):
        raise httpx.ConnectError("")

    r = asyncio.run(R.RetailSales(client=_client(boom)).overview(NOW))
    assert r["available"] is False and r["reason"] == "Retail sales could not be read right now (the connection could not be made)"


def test_demo_mode_invents_nothing():
    d = asyncio.run(R.RetailSales(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "Demo" in d["reason"] and "level_billions" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/retail-sales")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True


def test_request_has_no_custom_user_agent_and_limits_the_download():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    asyncio.run(R.RetailSales(client=_client(handler)).overview(NOW))
    assert all("atlas" not in req.headers.get("user-agent", "").lower() for req in seen)     # FRED stalls on an unfamiliar one
    assert all("cosd" in req.url.params for req in seen) and {req.url.params["id"] for req in seen} == set(R.SERIES) == {"RSAFS", "RSXFS", "RSFSDP"}
    start = date.fromisoformat(seen[0].url.params["cosd"])
    assert 4100 <= (date.today() - start).days <= 4300                                       # about 11.5 years, enough for ten years of yearly growth
