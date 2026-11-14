"""Fear & Greed: parsing a real response, bands, staleness, failure labelled (never guessed), demo mode shows nothing invented."""
import asyncio
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api.app import create_app
from atlas_api.sentiment import FearGreed, band, parse

# Shape and values taken from a real response fetched on 2026-11-08 (two most recent days), extended back with older days.
REAL = {"name": "Fear and Greed Index", "data": [
    {"value": "28", "value_classification": "Fear", "timestamp": "1794096000", "time_until_update": "27718"},
    {"value": "25", "value_classification": "Extreme Fear", "timestamp": "1794009600"},
    {"value": "40", "value_classification": "Fear", "timestamp": "1793491200"},
    {"value": "60", "value_classification": "Greed", "timestamp": "1791494400"}], "metadata": {"error": None}}
NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


def test_bands_follow_the_stated_cutoffs():
    assert [band(v) for v in (0, 24, 25, 44, 45, 54, 55, 74, 75, 100)] == ["Extreme fear", "Extreme fear", "Fear", "Fear", "Neutral", "Neutral", "Greed", "Greed", "Extreme greed", "Extreme greed"]


def test_parse_reads_latest_and_comparisons_from_the_data():
    r = parse(REAL, NOW)
    assert r["value"] == 28 and r["label"] == "Fear" and r["date"] == "2026-11-08" and r["yesterday"] == 25
    assert r["freshness"] == "CURRENT" and r["history"][0]["date"] < r["history"][-1]["date"]


def test_old_reading_is_flagged_overdue_not_presented_as_current():
    r = parse(REAL, datetime(2026, 11, 20, tzinfo=timezone.utc))
    assert r["freshness"] == "OVERDUE" and r["age_days"] >= 10


def test_garbage_values_are_dropped_and_empty_raises():
    assert parse({"data": [{"value": "999", "timestamp": "1794096000"}, {"value": "x", "timestamp": "1"}, {"value": "50", "timestamp": "1794009600"}]}, NOW)["value"] == 50
    with pytest.raises(ValueError):
        parse({"data": []}, NOW)


def run(handler, demo=False):
    return asyncio.run(FearGreed(httpx.AsyncClient(transport=httpx.MockTransport(handler)), demo).overview(NOW))


def test_service_returns_the_value_with_source_note_and_no_signal_language():
    r = run(lambda req: httpx.Response(200, json=REAL))
    assert r["available"] and r["value"] == 28 and "alternative.me" in r["source"] and "not a forecast" in r["note"]


def test_failure_is_said_plainly_with_no_value():
    for h in (lambda req: httpx.Response(503), lambda req: httpx.Response(200, json={"data": []}), lambda req: (_ for _ in ()).throw(httpx.ConnectError("down"))):
        r = run(h)
        assert r["available"] is False and "value" not in r and "alternative.me" in r["reason"]


def test_demo_mode_invents_nothing():
    r = run(lambda req: httpx.Response(200, json=REAL), demo=True)
    assert r["available"] is False and r["demo"] is True and "value" not in r


def test_route(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "s.db"), demo=True, alert_loop=False)) as c:
        d = c.get("/api/btc/sentiment").json()["data"]
        assert d["demo"] is True and d["available"] is False
