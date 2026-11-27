"""Natural gas (Henry Hub daily spot price, EIA via FRED) with a cross-check against EIA's own monthly average: parsed from real responses (fetched 2026-11-15: 464 daily prices since 2025-01-01 and 23 monthly figures).
Hand-worked changes, rank and month comparisons (recomputed a second way with pandas), every refusal with its exact boundary and the window it looks at (range and one-day moves over the last 60 prices, spacing over the last 20,
the monthly average over the last 3 finished months), a real cold snap that must NOT be refused, the stale label, caching, failure, demo, the route and the plain-client rule."""
import asyncio
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import naturalgas as N
from atlas_api.app import create_app

F = json.loads((Path(__file__).parent / "fixtures" / "fred_natgas.json").read_text())
TODAY = date(2026, 11, 14)
NOW = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
LAST = date(2026, 11, 11)


def _data():
    return {sid: N.parse(F[sid], sid) for sid in N.SERIES}


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(req):
    return httpx.Response(200, text=F[req.url.params["id"]])


def _consistent(daily):
    """Daily prices with each month's published figure set to that month's exact average, so only the range, spacing and move checks can object."""
    by = defaultdict(list)
    for x, v in daily.items():
        by[(x.year, x.month)].append(v)
    return {"DHHNGSP": daily, "MHHNGSP": {date(y, m, 1): sum(v) / len(v) for (y, m), v in by.items()}}


def _flat(price, n=150, pair=None, width=None, end=LAST):
    """A clean synthetic series, one price every calendar day for `n` days ending `end` (2026-11-11 unless said), for testing one check at a time. With `pair` and `width`, the two prices that make up pair number `pair`
    counted from the end (pair 0 is the last two prices) are `width` days apart instead of 1."""
    days = [end]
    for i in range(n - 1):
        days.append(days[-1] - timedelta(days=width if i == pair else 1))
    return _consistent({x: float(price) for x in days})


def test_latest_price_changes_rank_and_months_by_hand():
    s = N.summarize(_data(), TODAY)
    assert (s["date"], s["age_days"], s["freshness"]) == ("2026-11-11", 3, "CURRENT")
    assert s["price"] == 3.0 and s["change_1d"] == 0.0                              # 3.00 on 2026-11-10 and again on 2026-11-11
    assert s["change_1m_pct"] == -3.2                                               # 3.00 against 3.10 on 2026-10-12
    assert s["change_1y_pct"] == -21.1                                              # 3.00 against 3.80 on 2025-11-10 (2025-11-11, Veterans Day, has no price, so the latest earlier one is used)
    assert (s["year_low"], s["year_high"], s["days_in_year"], s["rank_in_year"]) == (2.42, 30.72, 248, 50)   # 2025-11-12 to 2026-11-11; the high is 2026-01-23; 125 of 248 prices are at or below 3.00
    assert s["reading"] == "in the middle of the past year's range"
    assert s["monthly"] == {"month": "2026-10", "average_of_daily": 2.99, "published": 2.99, "days": 22}   # 22 prices averaging 2.9877 against EIA's 2.99
    assert [x["month"] for x in s["months_checked"]] == ["2026-10", "2026-09", "2026-08"]
    assert [(x["average_of_daily"], x["published"]) for x in s["months_checked"]] == [(2.99, 2.99), (2.95, 2.95), (2.79, 2.78)]   # August: 2.7852 against 2.78, inside the 5 cents
    assert len(s["history"]) == 60 and s["history"][0] == {"date": "2026-08-19", "price": 2.94} and s["history"][-1] == {"date": "2026-11-11", "price": 3.0}
    assert all(s["checks"].values())


def test_a_missing_earlier_price_is_not_available_never_guessed():
    d = _data()
    for day in (date(2026, 10, 12), date(2026, 10, 9), date(2026, 10, 8), date(2026, 10, 7)):
        d["DHHNGSP"].pop(day)                                                       # nothing on or within 5 days before 2026-10-12 any more (the next one back is 2026-10-06, 6 days earlier)
    for day in (date(2025, 11, 10), date(2025, 11, 7), date(2025, 11, 6)):
        d["DHHNGSP"].pop(day)                                                       # nothing within 5 days before 2025-11-11 any more (the next one back is 2025-11-05, 6 days earlier)
    s = N.summarize(d, TODAY)
    assert s["change_1m_pct"] is None and s["change_1y_pct"] is None and s["price"] == 3.0


def test_the_earlier_price_is_taken_from_up_to_5_days_before_and_no_further():
    d = _data()
    for day in (date(2026, 10, 12), date(2026, 10, 9), date(2026, 10, 8)):
        d["DHHNGSP"].pop(day)                                                       # the latest on or before 2026-10-12 is now 2026-10-07 (3.16), exactly 5 days earlier: still used
    for day in (date(2025, 11, 10), date(2025, 11, 7)):
        d["DHHNGSP"].pop(day)                                                       # the latest on or before 2025-11-11 is now 2025-11-06 (3.71), exactly 5 days earlier: still used
    s = N.summarize(d, TODAY)
    assert s["change_1m_pct"] == -5.1 and s["change_1y_pct"] == -19.1               # 3.00 / 3.16 - 1 and 3.00 / 3.71 - 1


def test_stale_is_overdue_with_real_age():
    assert N.summarize(_data(), LAST + timedelta(days=14))["freshness"] == "CURRENT"
    s = N.summarize(_data(), LAST + timedelta(days=15))
    assert s["freshness"] == "OVERDUE" and s["age_days"] == 15


def test_the_price_range_is_half_a_dollar_to_sixty_inclusive():
    assert N.summarize(_flat(0.5), TODAY)["price"] == 0.5
    assert N.summarize(_flat(60.0), TODAY)["price"] == 60.0
    with pytest.raises(ValueError, match="plausible range"):
        N.summarize(_flat(0.49), TODAY)
    with pytest.raises(ValueError, match="plausible range"):
        N.summarize(_flat(60.01), TODAY)


def test_a_unit_slip_in_every_recent_price_is_caught_whichever_way_it_goes():
    d = _data()
    for x in sorted(d["DHHNGSP"])[-60:]:
        d["DHHNGSP"][x] /= 10.0
    with pytest.raises(ValueError, match="plausible range"):                       # /10: about 0.30, under the floor
        N.summarize(d, TODAY)
    d = _data()
    for x in sorted(d["DHHNGSP"])[-60:]:
        d["DHHNGSP"][x] *= 10.0
    with pytest.raises(ValueError, match="2026-10 average"):                       # x10: still under $60 and no one-day move, so only the monthly figure gives it away
        N.summarize(d, TODAY)


def test_the_range_and_move_checks_look_at_the_last_60_prices_and_no_further_back():
    def with_value(pos, value):
        daily = _flat(3.0)["DHHNGSP"]
        daily[sorted(daily)[pos]] = value
        return _consistent(daily)
    with pytest.raises(ValueError, match="plausible range"):
        N.summarize(with_value(-60, 100.0), TODAY)                                  # the 60th price from the end: inside
    assert N.summarize(with_value(-61, 100.0), TODAY)["available"]                  # the 61st: outside every window
    with pytest.raises(ValueError, match="factor of 6"):
        N.summarize(with_value(-60, 18.03), TODAY)                                  # a one-day jump of 6.01 times, inside the window
    assert N.summarize(with_value(-61, 18.03), TODAY)["available"]


def test_a_one_day_move_to_more_than_6_times_or_under_a_sixth_is_refused_and_exactly_6_is_allowed():
    def last_value(price, value):
        daily = _flat(price)["DHHNGSP"]
        daily[LAST] = value
        return _consistent(daily)
    assert N.summarize(last_value(3.0, 18.0), TODAY)["price"] == 18.0               # exactly 6 times
    assert N.summarize(last_value(12.0, 2.0), TODAY)["price"] == 2.0                # exactly a sixth
    with pytest.raises(ValueError, match="factor of 6"):
        N.summarize(last_value(3.0, 18.03), TODAY)
    with pytest.raises(ValueError, match="factor of 6"):
        N.summarize(last_value(12.0, 1.99), TODAY)
    with pytest.raises(ValueError, match="factor of 6"):                            # a x10 slip of one price
        N.summarize(last_value(3.0, 30.0), TODAY)


def test_a_real_cold_snap_is_not_refused():
    d = _data()
    cut = date(2026, 2, 12)
    d["DHHNGSP"] = {x: v for x, v in d["DHHNGSP"].items() if x <= cut}              # ends two weeks after the real spike: 8.42 on 2026-01-22, 30.72 on 2026-01-23 (3.65 times), 25.01, 17.19, 9.34, ... down to 4.40 on 2026-02-02
    d["MHHNGSP"] = {x: v for x, v in d["MHHNGSP"].items() if x <= date(2026, 1, 1)}
    s = N.summarize(d, date(2026, 2, 14))
    assert s["available"] and s["year_high"] == 30.72
    assert s["months_checked"][0] == {"month": "2026-01", "average_of_daily": 7.72, "published": 7.72, "days": 19}   # even in the spike month the daily prices average out to EIA's monthly figure


def test_the_gap_between_prices_may_be_7_days_but_not_8_in_the_last_20_values():
    assert N.summarize(_flat(3.0, pair=5, width=7), TODAY)["available"]
    with pytest.raises(ValueError, match="gap of more than 7 days"):
        N.summarize(_flat(3.0, pair=5, width=8), TODAY)


def test_the_gap_check_looks_at_the_last_20_values_and_no_further_back():
    with pytest.raises(ValueError, match="gap of more than 7 days"):
        N.summarize(_flat(3.0, pair=18, width=8), TODAY)                            # the pair (20th from the end, 19th from the end): inside
    assert N.summarize(_flat(3.0, pair=19, width=8), TODAY)["available"]            # the pair (21st, 20th): outside


def test_the_monthly_average_must_match_within_5_cents():
    def with_published(month, value):
        d = _flat(2.0)
        d["MHHNGSP"][month] = value
        return d
    assert N.summarize(with_published(date(2026, 10, 1), 2.045), TODAY)["available"]
    with pytest.raises(ValueError, match="2026-10 average 2.00 but the monthly figure is"):
        N.summarize(with_published(date(2026, 10, 1), 2.055), TODAY)
    with pytest.raises(ValueError, match="2026-10 average 2.00 but the monthly figure is"):
        N.summarize(with_published(date(2026, 10, 1), 1.945), TODAY)


def test_all_of_the_last_3_finished_months_are_checked_and_no_older_one():
    def with_published(month, value):
        d = _flat(2.0)
        d["MHHNGSP"][month] = value
        return d
    for month in (date(2026, 9, 1), date(2026, 8, 1)):                              # the second and the third month back
        with pytest.raises(ValueError, match=f"{month.year}-{month.month:02d} average"):
            N.summarize(with_published(month, 2.06), TODAY)
    s = N.summarize(with_published(date(2026, 7, 1), 9.99), TODAY)                  # the fourth month back is never looked at
    assert [x["month"] for x in s["months_checked"]] == ["2026-10", "2026-09", "2026-08"]


def test_a_unit_slip_in_a_few_days_of_one_month_is_caught_by_the_monthly_figure():
    d = _data()
    for day in (date(2026, 8, 3), date(2026, 8, 4)):
        d["DHHNGSP"][day] *= 10.0                                                   # outside the last 60 prices, so the range and move checks never see it
    with pytest.raises(ValueError, match="2026-08 average"):
        N.summarize(d, TODAY)


def test_this_month_never_counts_and_a_missing_monthly_figure_falls_back_to_an_earlier_month():
    d = _flat(2.0, end=date(2026, 11, 20))                                          # 20 November prices already: enough to be compared if the month counted
    d["MHHNGSP"][date(2026, 11, 1)] = 99.0                                          # November is not finished: its figure, however odd, is not compared
    assert N.summarize(d, date(2026, 11, 22))["available"]
    d = _data()
    del d["MHHNGSP"][date(2026, 10, 1)]                                             # October's monthly figure is not published yet
    s = N.summarize(d, TODAY)
    assert [x["month"] for x in s["months_checked"]] == ["2026-09", "2026-08", "2026-07"] and s["monthly"]["month"] == "2026-09"


def test_a_month_with_fewer_than_15_daily_prices_is_not_compared():
    def keep_last_days_of_october(n):
        d = _flat(2.0)
        for x in list(d["DHHNGSP"]):
            if x.month == 10 and x.day <= 31 - n:
                del d["DHHNGSP"][x]
        d["MHHNGSP"][date(2026, 10, 1)] = 7.77                                      # a figure that would fail if it were compared
        return d
    s = N.summarize(keep_last_days_of_october(14), TODAY)
    assert [x["month"] for x in s["months_checked"]] == ["2026-09", "2026-08", "2026-07"]
    with pytest.raises(ValueError, match="2026-10 average"):
        N.summarize(keep_last_days_of_october(15), TODAY)                           # exactly 15: compared


def test_fewer_than_2_comparable_months_means_the_check_cannot_be_made_and_the_card_says_so():
    d = _flat(2.0)
    for x in list(d["MHHNGSP"]):
        if x != date(2026, 10, 1):
            del d["MHHNGSP"][x]
    with pytest.raises(ValueError, match="fewer than 2 finished months"):
        N.summarize(d, TODAY)
    d["MHHNGSP"][date(2026, 9, 1)] = 2.0
    assert [x["month"] for x in N.summarize(d, TODAY)["months_checked"]] == ["2026-10", "2026-09"]


def test_missing_values_are_skipped_never_filled():
    s = N.parse("observation_date,DHHNGSP\n2026-11-09,2.89\n2026-11-10,.\n2026-11-11,\n", "DHHNGSP")
    assert s == {date(2026, 11, 9): 2.89}


def test_overview_fetches_two_series_and_caches():
    n = {"n": 0}

    def handler(req):
        n["n"] += 1
        return _handler(req)

    svc = N.NaturalGas(client=_client(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["price"] == 3.0 and n["n"] == 2 and "not a market signal or a forecast" in r["note"]
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 2


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(N.NaturalGas(client=_client(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and "HTTP 503" in r["reason"] and "price" not in r
    bad = dict(F)
    bad["DHHNGSP"] = F["DHHNGSP"].replace("2026-11-11,3.00", "2026-11-11,30.00")                                 # a decimal slip in the newest price: a check failing shows nothing either
    r = asyncio.run(N.NaturalGas(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))
    assert r["available"] is False and "factor of 6" in r["reason"] and "price" not in r


def test_a_dropped_connection_reads_plainly():
    def boom(req):
        raise httpx.ConnectError("")

    r = asyncio.run(N.NaturalGas(client=_client(boom)).overview(NOW))
    assert r["available"] is False and r["reason"] == "Natural gas prices could not be read right now (the connection could not be made)"


def test_demo_mode_invents_nothing():
    d = asyncio.run(N.NaturalGas(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "Demo" in d["reason"] and "price" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/natural-gas")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True


def test_request_has_no_custom_user_agent_and_limits_the_download():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    asyncio.run(N.NaturalGas(client=_client(handler)).overview(NOW))
    assert all("atlas" not in req.headers.get("user-agent", "").lower() for req in seen)     # FRED stalls on an unfamiliar one
    assert all("cosd" in req.url.params for req in seen) and {req.url.params["id"] for req in seen} == set(N.SERIES)
