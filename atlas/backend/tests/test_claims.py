"""US weekly jobless claims via FRED: parsed from real responses (fetched 2026-11-14: the last 80 weeks of initial claims, continuing claims and the Labor Department's own four-week average). Hand-worked changes and ranks, the cross-check against the official
average, every refusal (not a Saturday, range, spacing, missing official average, stale continuing claims), the stale label, caching, failure, demo, the route and the plain-client rule."""
import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import claims as C
from atlas_api.app import create_app

F = json.loads((Path(__file__).parent / "fixtures" / "fred_claims.json").read_text())
TODAY = date(2026, 11, 14)
NOW = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
LAST = date(2026, 11, 7)


def _data():
    return {sid: C.parse(F[sid], sid) for sid in C.SERIES}


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(req):
    return httpx.Response(200, text=F[req.url.params["id"]])


def _with_latest(value):
    """The data with the latest initial-claims value replaced and the official four-week average made consistent with it."""
    d = _data()
    d["ICSA"][LAST] = float(value)
    wk = sorted(d["ICSA"])[-4:]
    d["IC4WSA"][LAST] = sum(d["ICSA"][w] for w in wk) / 4
    return d


def test_latest_week_changes_and_range_by_hand():
    s = C.summarize(_data(), TODAY)
    assert s["date"] == "2026-11-07" and s["age_days"] == 7 and s["freshness"] == "CURRENT"
    i = s["initial"]
    assert i["value"] == 200000 and i["change_1w"] == 9000                      # 200,000 - 191,000 on 2026-10-31
    assert i["avg4"] == 195250 and i["avg4_official"] == 195250                  # (195,000 + 195,000 + 191,000 + 200,000) / 4, and the Labor Department says the same
    assert i["change_1y_pct"] == -12.3                                            # (200,000 - 228,000) / 228,000 on 2025-11-08
    assert (i["year_low"], i["year_high"], i["weeks_in_year"], i["rank_in_year"]) == (189000, 235000, 53, 26)
    assert s["reading"] == "in the middle of the past year's range"
    c = s["continuing"]
    assert c["value"] == 1697000 and c["date"] == "2026-10-31"                    # one week behind the initial claims
    assert c["change_1w"] == -20000 and c["change_1y_pct"] == -12.8               # 1,697,000 - 1,717,000; (1,697,000 - 1,946,000) / 1,946,000
    assert len(s["history"]) == 52 and s["history"][-1] == {"date": "2026-11-07", "initial": 200000}


def test_reading_follows_the_rank_in_the_past_years_range():
    assert C.summarize(_with_latest(189000), TODAY)["reading"] == "toward the low end of the past year's range"            # the year's low
    assert C.summarize(_with_latest(235000), TODAY)["reading"] == "toward the high end of the past year's range"          # the year's high
    assert C.summarize(_with_latest(240000), TODAY)["initial"]["rank_in_year"] == 100


def test_reading_boundaries_are_exact():
    assert C.reading(0) == C.reading(25) == "toward the low end of the past year's range"
    assert C.reading(26) == C.reading(50) == C.reading(74) == "in the middle of the past year's range"
    assert C.reading(75) == C.reading(100) == "toward the high end of the past year's range"


def test_stale_is_overdue_with_real_age():
    s = C.summarize(_data(), TODAY + timedelta(days=30))
    assert s["freshness"] == "OVERDUE" and s["age_days"] == 37
    assert C.summarize(_data(), LAST + timedelta(days=14))["freshness"] == "CURRENT" and C.summarize(_data(), LAST + timedelta(days=15))["freshness"] == "OVERDUE"


def test_our_four_week_average_must_match_the_labor_departments():
    d = _data()
    d["IC4WSA"][LAST] = 205000.0                                                  # 5% off
    with pytest.raises(ValueError, match="does not match"):
        C.summarize(d, TODAY)
    d["IC4WSA"][LAST] = 195250.0 * 1.009                                          # inside 1%: accepted
    assert C.summarize(d, TODAY)["available"]
    d = _data()
    del d["IC4WSA"][LAST]
    with pytest.raises(ValueError, match="average is missing"):
        C.summarize(d, TODAY)


def test_a_date_that_is_not_a_saturday_is_refused():
    d = _data()
    d["ICSA"][date(2026, 11, 6)] = 200000.0
    with pytest.raises(ValueError, match="not a Saturday"):
        C.summarize(d, TODAY)


@pytest.mark.parametrize("sid,bad", [("ICSA", 50_000.0), ("ICSA", 40_000_000.0), ("CCSA", 100_000.0), ("CCSA", 90_000_000.0)])
def test_out_of_range_value_is_refused(sid, bad):
    d = _data()
    d[sid][max(d[sid])] = bad
    with pytest.raises(ValueError, match="plausible range"):
        C.summarize(d, TODAY)


def test_a_gap_in_recent_weeks_is_refused():
    d = _data()
    del d["ICSA"][sorted(d["ICSA"])[-5]]
    with pytest.raises(ValueError, match="one week apart"):
        C.summarize(d, TODAY)


def test_continuing_claims_must_be_for_a_recent_week():
    d = _data()
    for w in sorted(d["CCSA"])[-3:]:
        del d["CCSA"][w]                                                          # newest continuing week is now 3 weeks behind the initial claims
    with pytest.raises(ValueError, match="not for a recent week"):
        C.summarize(d, TODAY)


def test_missing_values_are_skipped_never_filled():
    s = C.parse("observation_date,ICSA\n2026-10-31,191000\n2026-11-07,.\n", "ICSA")
    assert s == {date(2026, 10, 31): 191000.0}


def test_overview_fetches_three_series_and_caches():
    n = {"n": 0}

    def handler(req):
        n["n"] += 1
        return _handler(req)

    svc = C.JoblessClaims(client=_client(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["initial"]["value"] == 200000 and n["n"] == 3 and "not a market signal or a forecast" in r["note"] and len(r["history"]) == 52
    assert all(r["checks"].values())
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 3


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(C.JoblessClaims(client=_client(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and "HTTP 503" in r["reason"] and "initial" not in r and "continuing" not in r
    bad = dict(F)
    bad["IC4WSA"] = F["IC4WSA"].replace("2026-11-07,195250", "2026-11-07,300000")                                  # a check failing shows nothing either
    r = asyncio.run(C.JoblessClaims(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))
    assert r["available"] is False and "does not match" in r["reason"] and "initial" not in r


def test_demo_mode_invents_nothing():
    d = asyncio.run(C.JoblessClaims(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "Demo" in d["reason"] and "initial" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/jobless-claims")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True


def test_request_has_no_custom_user_agent_and_limits_the_download():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    asyncio.run(C.JoblessClaims(client=_client(handler)).overview(NOW))
    assert all("atlas" not in req.headers.get("user-agent", "").lower() for req in seen)     # FRED stalls on an unfamiliar one
    assert all("cosd" in req.url.params for req in seen) and {req.url.params["id"] for req in seen} == set(C.SERIES)
