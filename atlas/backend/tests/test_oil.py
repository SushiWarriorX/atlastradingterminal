"""Oil prices (WTI and Brent spot, EIA via FRED): parsed from real responses (fetched 2026-11-14: 400 daily values of each since 2025-05-01). Hand-worked changes, ranks and the Brent minus WTI spread, the as-of lookup across holidays, the stale label,
every refusal with its boundaries (range, gap, one-day move, date skew, spread), caching, failure, demo, the route and the plain-client rule."""
import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import oil as O
from atlas_api.app import create_app

F = json.loads((Path(__file__).parent / "fixtures" / "fred_oil.json").read_text())
TODAY = date(2026, 11, 14)
NOW = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
LAST = date(2026, 11, 11)


def _data():
    return {sid: O.parse(F[sid], sid) for sid in O.SERIES}


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(req):
    return httpx.Response(200, text=F[req.url.params["id"]])


def _with_spread(delta):
    """The data with Brent's last 80 values replaced by (the latest WTI price on or before that day) + delta, so the spread is `delta` every day and no daily move is odd. Nothing is deleted."""
    d = _data()
    for day in sorted(d["DCOILBRENTEU"])[-80:]:
        d["DCOILBRENTEU"][day] = O._on_or_before(d["DCOILWTICO"], day) + delta
    return d


def test_latest_values_changes_ranks_and_spread_by_hand():
    s = O.summarize(_data(), TODAY)
    w, b = s["wti"], s["brent"]
    assert (w["value"], w["date"], w["age_days"], w["freshness"]) == (89.62, "2026-11-11", 3, "CURRENT")
    assert w["change_1d"] == 0.0                                                   # 89.62 on 2026-11-10 as well
    assert w["change_1m_pct"] == -5.7                                              # (89.62 - 94.99 on 2026-10-12) / 94.99
    assert w["change_1y_pct"] == 47.1                                              # 2025-11-11 has no WTI price, so the latest one before it counts: (89.62 - 60.94 on 2025-11-10) / 60.94
    assert (w["year_low"], w["year_high"], w["days_in_year"], w["rank_in_year"]) == (55.44, 114.58, 251, 54)
    assert w["reading"] == "in the middle of the past year's range"
    assert (b["value"], b["change_1d"]) == (92.14, 1.98)                           # 92.14 - 90.16 on 2026-11-10
    assert b["change_1m_pct"] == -29.1                                             # (92.14 - 129.95 on 2026-10-12) / 129.95: the real October spike
    assert b["change_1y_pct"] == 44.3                                              # (92.14 - 63.86 on 2025-11-11) / 63.86
    assert (b["year_low"], b["year_high"], b["days_in_year"], b["rank_in_year"]) == (59.93, 138.21, 254, 50)
    assert s["spread"] == {"value": 2.52, "date": "2026-11-11"}                    # 92.14 - 89.62
    assert len(s["history"]) == 60 and s["history"][-1] == {"date": "2026-11-11", "wti": 89.62}
    assert all(s["checks"].values())


def test_the_lookup_takes_the_latest_price_on_or_before_a_day_within_five_days():
    s = {date(2026, 10, 9): 98.73, date(2026, 10, 12): 94.99}
    assert O._on_or_before(s, date(2026, 10, 12)) == 94.99
    assert O._on_or_before(s, date(2026, 10, 11)) == 98.73                         # a Sunday: Friday's price
    assert O._on_or_before(s, date(2026, 10, 14)) == 94.99
    assert O._on_or_before(s, date(2026, 10, 17)) == 94.99                         # exactly 5 days later still counts
    assert O._on_or_before(s, date(2026, 10, 18)) is None                          # 6 days: nothing is made up
    assert O._on_or_before(s, date(2026, 10, 1)) is None


def test_stale_is_overdue_with_real_age():
    assert O.summarize(_data(), LAST + timedelta(days=14))["wti"]["freshness"] == "CURRENT"
    s = O.summarize(_data(), LAST + timedelta(days=15))
    assert s["wti"]["freshness"] == "OVERDUE" and s["wti"]["age_days"] == 15 and s["brent"]["freshness"] == "OVERDUE"


@pytest.mark.parametrize("sid,bad", [("DCOILWTICO", 300.0), ("DCOILWTICO", 0.0), ("DCOILWTICO", -60.0), ("DCOILBRENTEU", 260.0), ("DCOILBRENTEU", 250.01)])
def test_out_of_range_value_is_refused(sid, bad):
    d = _data()
    last = max(d[sid])
    d[sid][last] = bad
    with pytest.raises(ValueError, match="plausible range"):
        O.summarize(d, TODAY)


def test_exactly_250_dollars_is_allowed():
    d = _data()
    for sid in d:
        for day in sorted(d[sid])[-60:]:
            d[sid][day] = 249.0                                                       # a smooth path (no big daily move, spread zero), ending exactly on the limit
        d[sid][max(d[sid])] = 250.0
    assert O.summarize(d, TODAY)["wti"]["value"] == 250.0                              # 250.01 and anything at or below zero are refused in the test above


def test_a_gap_of_more_than_five_days_in_the_last_twenty_values_is_refused():
    d = _data()
    for sid in d:
        for day in (date(2026, 11, 5), date(2026, 11, 6), date(2026, 11, 9)):        # 2026-11-04 to 2026-11-10 is now 6 days
            d[sid].pop(day, None)
    with pytest.raises(ValueError, match="gap of more than 5 days"):
        O.summarize(d, TODAY)
    d = _data()
    for sid in d:
        for day in (date(2026, 11, 5), date(2026, 11, 6)):                           # 2026-11-04 to 2026-11-09 is exactly 5 days: allowed
            d[sid].pop(day, None)
    assert O.summarize(d, TODAY)["available"]


def test_a_one_day_move_over_forty_percent_is_refused():
    def scaled(factor):
        d = _data()
        last = max(d["DCOILWTICO"])
        for sid in d:
            d[sid][last] = d[sid][last - timedelta(days=1)] * factor                  # both series together, so the spread stays small
        return d
    with pytest.raises(ValueError, match="moved more than 40%"):
        O.summarize(scaled(1.45), TODAY)
    with pytest.raises(ValueError, match="moved more than 40%"):
        O.summarize(scaled(0.55), TODAY)
    assert O.summarize(scaled(1.39), TODAY)["wti"]["value"] == pytest.approx(89.62 * 1.39, abs=0.01)             # 39% is allowed
    assert O.summarize(scaled(0.61), TODAY)["wti"]["value"] == pytest.approx(89.62 * 0.61, abs=0.01)


def test_series_for_different_weeks_are_refused():
    d = _data()
    for day in sorted(d["DCOILBRENTEU"])[-6:]:
        del d["DCOILBRENTEU"][day]                                                   # Brent now ends 8 days before WTI
    with pytest.raises(ValueError, match="same week"):
        O.summarize(d, TODAY)


def test_the_date_skew_limit_is_exactly_seven_days():
    d = _data()
    for day in [x for x in d["DCOILBRENTEU"] if x > date(2026, 11, 4)]:
        del d["DCOILBRENTEU"][day]                                                    # Brent now ends 2026-11-04, exactly 7 days before WTI: allowed
    s = O.summarize(d, TODAY)
    assert s["brent"]["date"] == "2026-11-04" and s["wti"]["date"] == "2026-11-11" and s["spread"]["date"] == "2026-11-04"      # the spread is taken on the newest day both have
    del d["DCOILBRENTEU"][date(2026, 11, 4)]                                           # now it ends 2026-11-03: 8 days
    with pytest.raises(ValueError, match="same week"):
        O.summarize(d, TODAY)


def test_the_gap_check_looks_at_the_last_20_values_and_no_further_back():
    def without(offset_from_end):
        d = _data()
        for sid in d:
            ks = sorted(d[sid])
            for day in ks[offset_from_end + 1:offset_from_end + 5]:                    # four trading days missing: the gap between the neighbours is more than 5 days
                if day in d[sid] and day != ks[-1]:
                    del d[sid][day]
        return d
    with pytest.raises(ValueError, match="gap of more than 5 days"):
        O.summarize(without(-15), TODAY)                                               # inside the last 20 values
    assert O.summarize(without(-30), TODAY)["available"]                               # further back than that: not this check's business


def test_the_range_and_move_checks_look_at_the_last_60_values_and_no_further_back():
    def with_bad(offset_from_end, sid="DCOILWTICO"):
        d = _data()
        ks = sorted(d[sid])
        d[sid][ks[offset_from_end]] = 400.0                                            # one absurd value
        return d
    with pytest.raises(ValueError, match="plausible range"):
        O.summarize(with_bad(-30), TODAY)                                              # 30 values back: inside the last 60
    assert O.summarize(with_bad(-70), TODAY)["available"]                              # 70 values back: outside every window


def test_the_spread_must_be_between_minus_20_and_plus_80_dollars():
    assert O.summarize(_with_spread(79.0), TODAY)["spread"]["value"] == pytest.approx(79.0)
    assert O.summarize(_with_spread(-19.0), TODAY)["spread"]["value"] == pytest.approx(-19.0)
    with pytest.raises(ValueError, match="outside -20 to 80"):
        O.summarize(_with_spread(81.0), TODAY)
    with pytest.raises(ValueError, match="outside -20 to 80"):
        O.summarize(_with_spread(-21.0), TODAY)


def test_missing_values_are_skipped_never_filled():
    s = O.parse("observation_date,DCOILWTICO\n2026-11-10,89.62\n2026-11-11,.\n2026-11-12,\n", "DCOILWTICO")
    assert s == {date(2026, 11, 10): 89.62}


def test_overview_fetches_two_series_and_caches():
    n = {"n": 0}

    def handler(req):
        n["n"] += 1
        return _handler(req)

    svc = O.OilPrices(client=_client(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["wti"]["value"] == 89.62 and n["n"] == 2 and "not a market signal or a forecast" in r["note"]
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 2


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(O.OilPrices(client=_client(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and "HTTP 503" in r["reason"] and "wti" not in r and "brent" not in r
    bad = dict(F)
    bad["DCOILBRENTEU"] = F["DCOILBRENTEU"].replace("2026-11-11,92.14", "2026-11-11,921.4")                          # a unit slip in one value: a check failing shows nothing either
    r = asyncio.run(O.OilPrices(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))
    assert r["available"] is False and "plausible range" in r["reason"] and "wti" not in r


def test_demo_mode_invents_nothing():
    d = asyncio.run(O.OilPrices(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "Demo" in d["reason"] and "wti" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/oil-prices")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True


def test_request_has_no_custom_user_agent_and_limits_the_download():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    asyncio.run(O.OilPrices(client=_client(handler)).overview(NOW))
    assert all("atlas" not in req.headers.get("user-agent", "").lower() for req in seen)     # FRED stalls on an unfamiliar one
    assert all("cosd" in req.url.params for req in seen) and {req.url.params["id"] for req in seen} == set(O.SERIES)
