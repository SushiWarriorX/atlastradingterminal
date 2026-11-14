"""Primary dealer net Treasury positions (New York Fed): parsed from real responses (fetched 2026-11-10, trimmed to Sept 2024 onward); the week-on-week change checked against the source's own change series;
year-ago, 52-week range, stale, missing-week, failure and demo paths."""
import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import dealers as D
from atlas_api.app import create_app

RAW = json.loads((Path(__file__).parent / "fixtures" / "nyfed_pd_treasury.json").read_text())
TODAY = date(2026, 11, 10)
NOW = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)


def _s(today=TODAY, level=None):
    return D.summarize(D.parse(level or RAW["level"]), D.parse(RAW["change"]), today)


def test_the_latest_week_matches_the_source():
    s = _s()
    assert s["date"] == "2026-10-28" and s["net_position_billions"] == 452.8 and s["previous_date"] == "2026-10-21"        # 452,759 million
    assert s["week_change_billions"] == 27.1 and s["freshness"] == "CURRENT" and s["age_days"] == 13                       # 452,759 - 425,643 = 27,116


def test_our_weekly_change_equals_the_sources_own_change_series_for_26_weeks():
    c = _s()["check"]
    assert c == {"weeks": 26, "mismatches": 0, "match": True, "latest_ours_billions": 27.1, "latest_source_billions": 27.1}
    broken = json.loads(json.dumps(RAW["level"]))
    broken["pd"]["timeseries"][-3]["value"] = str(float(broken["pd"]["timeseries"][-3]["value"]) + 20000)                 # one week 20 billion off
    c2 = _s(level=broken)["check"]
    assert c2["match"] is False and c2["mismatches"] >= 1


def test_year_ago_and_52_week_range_equal_an_independent_calculation():
    rows = {r["asofdate"]: float(r["value"]) for r in RAW["level"]["pd"]["timeseries"] if r["value"] not in ("*", "N/A")}
    last = max(rows)
    window = {d: v for d, v in rows.items() if (date.fromisoformat(last) - date.fromisoformat(d)).days < 365}
    s = _s()
    assert s["year_ago_date"] == "2025-10-29" and s["year_ago_billions"] == round(rows["2025-10-29"] / 1000, 1) == 413.3
    r = s["range_52w"]
    assert r["low_billions"] == round(min(window.values()) / 1000, 1) == 382.9 and r["high_billions"] == round(max(window.values()) / 1000, 1) == 557.1
    assert r["weeks"] == len(window) and r["weeks_lower_than_now"] == sum(1 for v in window.values() if v < rows[last])


def test_weeks_the_source_does_not_report_are_left_out_not_zero():
    lv = json.loads(json.dumps(RAW["level"]))
    lv["pd"]["timeseries"].append({"asofdate": "2026-11-04", "keyid": "PDPOSGST-TOT", "value": "*"})
    s = _s(level=lv)
    assert s["date"] == "2026-10-28"                                                                                          # the "*" week is not the newest week and not a zero
    lv["pd"]["timeseries"][-3]["value"] = "N/A"                                                                              # and 2026-10-21 is not reported either
    parsed = D.parse(lv)
    assert date(2026, 10, 21) not in parsed and date(2026, 11, 4) not in parsed and parsed[date(2026, 10, 28)] == 452759.0


def test_a_gap_in_the_weeks_gives_no_week_change_instead_of_a_two_week_change():
    lv = json.loads(json.dumps(RAW["level"]))
    del lv["pd"]["timeseries"][-2]                                                                                           # drop 2026-10-21
    s = _s(level=lv)
    assert s["week_change_billions"] is None and s["check"] is None


def test_old_data_is_overdue():
    s = _s(today=date(2026, 12, 15))
    assert s["freshness"] == "OVERDUE" and s["age_days"] == 48


def test_bad_data_is_refused():
    with pytest.raises(ValueError):
        D.parse({"pd": {"timeseries": [{"asofdate": "soon", "value": "1"}]}})
    with pytest.raises(ValueError):
        D.parse({"pd": {"timeseries": RAW["level"]["pd"]["timeseries"][:5]}})
    with pytest.raises(ValueError):
        D.parse({})


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_failure_then_recovery_and_caching():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(503)
        return httpx.Response(200, json=RAW["change"] if str(req.url).endswith("TOTC.json") else RAW["level"])

    svc = D.Dealers(client=_client(handler))
    bad = asyncio.run(svc.overview(NOW))
    assert bad["available"] is False and "HTTP 503" in bad["reason"] and "net_position_billions" not in bad
    svc._cache = None
    good = asyncio.run(svc.overview(NOW))
    assert good["available"] and good["net_position_billions"] == 452.8 and good["check"]["match"]
    n = calls["n"]
    asyncio.run(svc.overview(NOW))
    assert calls["n"] == n


def test_the_change_series_failing_to_parse_still_shows_the_level_but_no_check():
    def handler(req):
        return httpx.Response(200, json={"pd": {"timeseries": []}} if str(req.url).endswith("TOTC.json") else RAW["level"])
    r = asyncio.run(D.Dealers(client=_client(handler)).overview(NOW))
    assert r["available"] and r["net_position_billions"] == 452.8 and r["check"] is None


def test_demo_mode_invents_nothing():
    d = asyncio.run(D.Dealers(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "Demo" in d["reason"] and "net_position_billions" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/dealers")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True
