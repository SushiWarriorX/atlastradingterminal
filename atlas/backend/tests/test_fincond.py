"""Chicago Fed financial conditions index via FRED: parsed from real responses (fetched 2026-11-12: the last 80 weeks of NFCI, ANFCI and the risk, credit and leverage pieces). Hand-worked changes, same-week
alignment, range guard, spacing guard, missing values, failure, stale and demo paths."""
import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import fincond as N
from atlas_api.app import create_app

F = json.loads((Path(__file__).parent / "fixtures" / "fred_nfci.json").read_text())
TODAY = date(2026, 11, 12)
NOW = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)


def _data():
    return {sid: N.parse(F[sid], sid) for sid in N.SERIES}


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(req):
    return httpx.Response(200, text=F[req.url.params["id"]])


def test_latest_week_and_changes_by_hand():
    s = N.summarize(_data(), TODAY)
    assert s["date"] == "2026-11-06" and s["age_days"] == 6 and s["freshness"] == "CURRENT"
    assert s["nfci"] == -0.462 and s["adjusted"] == -0.477 and s["reading"] == "looser than average"
    assert s["pieces"] == {"risk": -0.516, "credit": -0.005, "leverage": 0.086}
    assert s["change_1w"] == 0.003          # -0.462 - (-0.465)
    assert s["change_4w"] == 0.026          # -0.462 - (-0.488) on 2026-10-09
    assert s["change_1y"] == 0.049          # -0.462 - (-0.511) on 2025-11-07
    assert (s["year_low"], s["year_high"], s["weeks_in_year"]) == (-0.571, -0.46, 53)


def test_pieces_are_not_claimed_to_sum_to_the_headline():
    s = N.summarize(_data(), TODAY)
    assert round(sum(s["pieces"].values()), 3) != s["nfci"]                      # -0.435 against -0.462: the real data does not reconcile
    assert "not claimed" in s["checks"]["pieces_sum_to_headline"] and "not added up" in s["note"]


def test_stale_is_overdue_with_real_age():
    s = N.summarize(_data(), TODAY + timedelta(days=30))
    assert s["freshness"] == "OVERDUE" and s["age_days"] == 36


def test_series_for_different_weeks_are_refused():
    d = _data()
    last = max(d["ANFCI"])
    del d["ANFCI"][last]
    with pytest.raises(ValueError, match="same week"):
        N.summarize(d, TODAY)


def test_out_of_range_value_is_refused():
    d = _data()
    d["NFCI"][max(d["NFCI"])] = 40.0
    with pytest.raises(ValueError, match="plausible range"):
        N.summarize(d, TODAY)


def test_a_gap_in_recent_weeks_is_refused():
    d = _data()
    for sid in d:
        del d[sid][sorted(d[sid])[-4]]
    with pytest.raises(ValueError, match="one week apart"):
        N.summarize(d, TODAY)


def test_missing_values_are_skipped_never_filled_and_bad_rows_raise():
    s = N.parse("observation_date,NFCI\n2026-10-30,-0.465\n2026-11-06,.\n", "NFCI")
    assert s == {date(2026, 10, 30): -0.465}
    with pytest.raises(ValueError):
        N.parse("observation_date,NFCI\n2026-10-30,abc\n", "NFCI")
    with pytest.raises(ValueError):
        N.parse("observation_date,OTHER\n2026-10-30,1\n", "NFCI")
    with pytest.raises(ValueError):
        N.parse("observation_date,NFCI\n", "NFCI")


def test_overview_fetches_five_series_and_caches():
    n = {"n": 0}

    def handler(req):
        n["n"] += 1
        return _handler(req)

    svc = N.FinConditions(client=_client(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["nfci"] == -0.462 and n["n"] == 5 and "not a market signal or a forecast" in r["note"] and len(r["history"]) == 52
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 5


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(N.FinConditions(client=_client(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and "HTTP 503" in r["reason"] and "nfci" not in r


def test_demo_mode_invents_nothing():
    d = asyncio.run(N.FinConditions(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "Demo" in d["reason"] and "nfci" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/financial-conditions")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True


def test_request_has_no_custom_user_agent_and_limits_the_download():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    asyncio.run(N.FinConditions(client=_client(handler)).overview(NOW))
    assert all("atlas" not in req.headers.get("user-agent", "").lower() for req in seen)     # FRED stalls on an unfamiliar one
    assert all("cosd" in req.url.params for req in seen)
