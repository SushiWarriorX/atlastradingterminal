"""US retail gasoline price (weekly, EIA via FRED) with a cross-check against WTI crude: parsed from real responses (fetched 2026-11-14: 80 weekly gasoline prices and 400 daily WTI prices since 2025-05). Hand-worked changes, rank and the per-barrel gap to crude,
every refusal with the windows it looks at (12 weeks spacing, 60 weeks range and move, 8 weeks cross-check), the stale label, caching, failure, demo, the route and the plain-client rule."""
import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import gasoline as G
from atlas_api.app import create_app

F = json.loads((Path(__file__).parent / "fixtures" / "fred_gasoline.json").read_text())
TODAY = date(2026, 11, 14)
NOW = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
LAST = date(2026, 11, 9)


def _data():
    return {sid: G.parse(F[sid], sid) for sid in G.SERIES}


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(req):
    return httpx.Response(200, text=F[req.url.params["id"]])


def _with_margin(week_offsets, margin):
    """The data with WTI replaced, for the gasoline weeks `week_offsets` from the end (-1 is the newest), by (gasoline per barrel - margin), so the cross-check sees exactly that margin there."""
    d = _data()
    weeks = sorted(d["GASREGW"])
    for off in week_offsets:
        day = weeks[off]
        d["DCOILWTICO"][day] = d["GASREGW"][day] * 42.0 - margin
    return d


def test_latest_week_changes_rank_and_the_gap_to_crude_by_hand():
    s = G.summarize(_data(), TODAY)
    assert (s["date"], s["age_days"], s["freshness"]) == ("2026-11-09", 5, "CURRENT")
    assert s["price"] == 3.995 and s["change_1w"] == -0.158                       # 3.995 - 4.153 on 2026-11-02
    assert s["change_4w_pct"] == -7.8                                              # (3.995 - 4.331 on 2026-10-12) / 4.331
    assert s["change_1y_pct"] == 30.7                                              # (3.995 - 3.056 on 2025-11-10) / 3.056
    assert (s["year_low"], s["year_high"], s["weeks_in_year"], s["rank_in_year"]) == (2.779, 4.5, 53, 49)
    assert s["reading"] == "in the middle of the past year's range"
    assert s["crude"] == {"wti": 90.4, "per_barrel": 167.79, "gap": 77.39}         # 3.995 x 42 = 167.79 a barrel against WTI at 90.40: 77.39 for refining, distribution, marketing and taxes
    assert len(s["history"]) == 52 and s["history"][-1] == {"date": "2026-11-09", "price": 3.995}
    assert all(s["checks"].values())


def test_a_missing_earlier_week_is_not_available_never_guessed():
    d = _data()
    del d["GASREGW"][LAST - timedelta(days=52 * 7)]
    s = G.summarize(d, TODAY)
    assert s["change_1y_pct"] is None and s["change_4w_pct"] == -7.8


def test_stale_is_overdue_with_real_age():
    assert G.summarize(_data(), LAST + timedelta(days=14))["freshness"] == "CURRENT"
    s = G.summarize(_data(), LAST + timedelta(days=15))
    assert s["freshness"] == "OVERDUE" and s["age_days"] == 15


def test_a_date_that_is_not_a_monday_is_refused():
    d = _data()
    d["GASREGW"][date(2026, 11, 10)] = 3.99
    with pytest.raises(ValueError, match="not a Monday"):
        G.summarize(d, TODAY)


def test_the_spacing_check_looks_at_the_last_12_weeks_and_no_further_back():
    d = _data()
    del d["GASREGW"][sorted(d["GASREGW"])[-5]]                                     # a missing week 5 from the end
    with pytest.raises(ValueError, match="one week apart"):
        G.summarize(d, TODAY)
    d = _data()
    del d["GASREGW"][sorted(d["GASREGW"])[-15]]                                    # 15 from the end: outside the 12 weeks, so this check does not care
    assert G.summarize(d, TODAY)["available"]


@pytest.mark.parametrize("bad", [0.4, 11.0])
def test_a_price_outside_the_plausible_range_is_refused(bad):
    d = _data()
    d["GASREGW"][max(d["GASREGW"])] = bad
    with pytest.raises(ValueError, match="plausible range"):
        G.summarize(d, TODAY)


def test_the_range_and_move_checks_look_at_the_last_60_weeks_and_no_further_back():
    def with_bad(off, value):
        d = _data()
        d["GASREGW"][sorted(d["GASREGW"])[off]] = value
        return d
    with pytest.raises(ValueError, match="plausible range"):
        G.summarize(with_bad(-30, 20.0), TODAY)                                    # 30 weeks back: inside the last 60
    assert G.summarize(with_bad(-70, 20.0), TODAY)["available"]                    # 70 weeks back: outside every window
    d = _data()
    weeks = sorted(d["GASREGW"])
    d["GASREGW"][weeks[-30]] = d["GASREGW"][weeks[-31]] * 0.5                      # half of the week before: inside the price range, but a 50% weekly move, 30 weeks back
    with pytest.raises(ValueError, match="moved more than 25%"):
        G.summarize(d, TODAY)
    d = _data()
    d["GASREGW"][weeks[-70]] = d["GASREGW"][weeks[-71]] * 0.5                      # the same thing 70 weeks back: outside the window
    assert G.summarize(d, TODAY)["available"]


def test_a_weekly_move_over_25_percent_is_refused_and_24_is_allowed():
    def last_scaled(f):
        d = _data()
        last = max(d["GASREGW"])
        d["GASREGW"][last] = d["GASREGW"][last - timedelta(days=7)] * f
        return d
    with pytest.raises(ValueError, match="moved more than 25%"):
        G.summarize(last_scaled(1.26), TODAY)
    with pytest.raises(ValueError, match="moved more than 25%"):
        G.summarize(last_scaled(0.74), TODAY)
    assert G.summarize(last_scaled(1.24), TODAY)["price"] == pytest.approx(4.153 * 1.24, abs=0.001)
    assert G.summarize(last_scaled(0.76), TODAY)["price"] == pytest.approx(4.153 * 0.76, abs=0.001)


def test_the_gap_to_crude_must_be_between_10_and_130_dollars_a_barrel():
    assert G.summarize(_with_margin([-1], 10.5), TODAY)["crude"]["gap"] == pytest.approx(10.5)
    assert G.summarize(_with_margin([-1], 129.5), TODAY)["crude"]["gap"] == pytest.approx(129.5)
    with pytest.raises(ValueError, match="outside 10 to 130"):
        G.summarize(_with_margin([-1], 9.5), TODAY)
    with pytest.raises(ValueError, match="outside 10 to 130"):
        G.summarize(_with_margin([-1], 130.5), TODAY)
    # a /10 slip in WTI (the case a wider band would miss) and a x10 slip in gasoline are both caught
    d = _data()
    for day in sorted(d["DCOILWTICO"]):
        d["DCOILWTICO"][day] /= 10.0
    with pytest.raises(ValueError, match="outside 10 to 130"):
        G.summarize(d, TODAY)
    d = _data()
    for day in sorted(d["GASREGW"])[-60:]:
        d["GASREGW"][day] *= 10.0
    with pytest.raises(ValueError):
        G.summarize(d, TODAY)


def test_the_cross_check_looks_at_the_last_8_weeks_and_no_further_back():
    with pytest.raises(ValueError, match="outside 10 to 130"):
        G.summarize(_with_margin([-8], 200.0), TODAY)                              # 8 weeks back: inside
    assert G.summarize(_with_margin([-9], 200.0), TODAY)["available"]              # 9 weeks back: outside


def test_when_the_newest_monday_has_no_crude_price_the_latest_one_before_it_is_used_up_to_five_days_back():
    d = _data()
    for day in (date(2026, 11, 7), date(2026, 11, 8), date(2026, 11, 9)):
        d["DCOILWTICO"].pop(day, None)                                             # a Monday holiday: the latest price is Friday 2026-11-06, 3 days earlier
    assert G.summarize(d, TODAY)["crude"]["wti"] == d["DCOILWTICO"][date(2026, 11, 6)]
    for day in (date(2026, 11, 5), date(2026, 11, 6)):
        d["DCOILWTICO"].pop(day, None)                                             # now the latest is 2026-11-04, exactly 5 days earlier: still allowed
    assert G.summarize(d, TODAY)["crude"]["wti"] == d["DCOILWTICO"][date(2026, 11, 4)]


def test_a_missing_crude_price_means_the_check_cannot_be_made_and_the_card_says_so():
    d = _data()
    for day in list(d["DCOILWTICO"]):
        if day >= date(2026, 11, 4):
            del d["DCOILWTICO"][day]                                               # no WTI within 5 days of the newest Monday
    with pytest.raises(ValueError, match="no WTI crude price"):
        G.summarize(d, TODAY)


def test_missing_values_are_skipped_never_filled():
    s = G.parse("observation_date,GASREGW\n2026-11-02,4.153\n2026-11-09,.\n2026-11-16,\n", "GASREGW")
    assert s == {date(2026, 11, 2): 4.153}


def test_overview_fetches_two_series_and_caches():
    n = {"n": 0}

    def handler(req):
        n["n"] += 1
        return _handler(req)

    svc = G.GasolinePrices(client=_client(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["price"] == 3.995 and n["n"] == 2 and "not a market signal or a forecast" in r["note"]
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 2


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(G.GasolinePrices(client=_client(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and "HTTP 503" in r["reason"] and "price" not in r
    bad = dict(F)
    bad["GASREGW"] = F["GASREGW"].replace("2026-11-09,3.995", "2026-11-09,39.95")                                   # a decimal slip: a check failing shows nothing either
    r = asyncio.run(G.GasolinePrices(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))
    assert r["available"] is False and "plausible range" in r["reason"] and "price" not in r


def test_demo_mode_invents_nothing():
    d = asyncio.run(G.GasolinePrices(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "Demo" in d["reason"] and "price" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/gasoline-prices")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True


def test_request_has_no_custom_user_agent_and_limits_the_download():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    asyncio.run(G.GasolinePrices(client=_client(handler)).overview(NOW))
    assert all("atlas" not in req.headers.get("user-agent", "").lower() for req in seen)     # FRED stalls on an unfamiliar one
    assert all("cosd" in req.url.params for req in seen) and {req.url.params["id"] for req in seen} == set(G.SERIES)
