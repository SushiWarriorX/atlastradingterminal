"""NY Fed repo and reverse repo operations: parsed from a real response (120 operations fetched 2026-11-08), sums by date, window statistics, staleness, failures labelled, demo invents nothing."""
import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import fedops as F
from atlas_api.app import create_app

RAW = json.loads((Path(__file__).parent / "fixtures" / "nyfed_repo_ops.json").read_text())
TODAY = date(2026, 11, 8)
NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


def test_the_real_response_is_summed_per_date_oldest_first():
    days = F.parse(RAW)
    assert days[0]["date"] < days[-1]["date"] and days[-1]["date"] == date(2026, 11, 6) and len(days) == 40
    last = days[-1]
    assert last["reverse_repo"] == 150_000_000 and last["repo"] == 0 and last["reverse_ops"] == 1 and last["repo_ops"] == 2          # two repo operations, both zero, one reverse repo of $150M
    assert next(d for d in days if d["date"] == date(2026, 11, 2))["reverse_repo"] == 5_087_000_000


def test_summary_numbers_are_plain_arithmetic_on_the_data():
    s = F.summarize(F.parse(RAW), TODAY)
    rr = s["reverse_repo"]
    assert s["date"] == "2026-11-06" and s["freshness"] == "CURRENT" and rr["billions"] == 0.15 and rr["previous_day_billions"] == 0.125 and rr["change_billions"] == 0.025
    window = F.parse(RAW)[-21:]
    assert rr["average_billions"] == round(sum(d["reverse_repo"] for d in window) / 21 / 1e9, 3) and rr["highest_billions"] >= rr["billions"] and rr["dates_in_window"] == 21
    assert s["repo"]["highest_billions"] == round(max(d["repo"] for d in window) / 1e9, 3) and 0 <= s["repo"]["days_used"] <= 21 and len(s["history"]) == 40
    assert "not market signals or forecasts" in s["note"]


def test_old_data_is_overdue_and_unfinished_or_unknown_operations_are_ignored():
    assert F.summarize(F.parse(RAW), date(2026, 11, 30))["freshness"] == "OVERDUE"
    raw = json.loads(json.dumps(RAW))
    raw["repo"]["operations"].append({"operationDate": "2026-11-09", "operationType": "Reverse Repo", "totalAmtAccepted": 9e12, "auctionStatus": "Scheduled"})       # not finished: no result yet
    raw["repo"]["operations"].append({"operationDate": "2026-11-09", "operationType": "Something New", "totalAmtAccepted": 1e9, "auctionStatus": "Results"})
    assert F.parse(raw)[-1]["date"] == date(2026, 11, 6)


def test_too_little_or_garbled_data_is_refused():
    with pytest.raises(ValueError):
        F.parse({"repo": {"operations": RAW["repo"]["operations"][:6]}})
    with pytest.raises(ValueError):
        F.parse({"repo": {"operations": [{"operationDate": "x", "operationType": "Repo", "totalAmtAccepted": "?", "auctionStatus": "Results"}] * 10}})
    with pytest.raises(ValueError):
        F.parse({})


def go(handler, demo=False):
    return asyncio.run(F.FedOps(httpx.AsyncClient(transport=httpx.MockTransport(handler)), demo).overview(NOW))


def test_service_returns_the_summary_with_source_and_caveat():
    r = go(lambda req: httpx.Response(200, json=RAW))
    assert r["available"] and "official" in r["source"] and r["reverse_repo"]["billions"] == 0.15 and "newyorkfed.org" in r["url"]


def test_failure_says_so_and_shows_no_numbers():
    for h in (lambda req: httpx.Response(503), lambda req: httpx.Response(200, json={}), lambda req: (_ for _ in ()).throw(httpx.ConnectError("x"))):
        r = go(h)
        assert r["available"] is False and "reverse_repo" not in r and "New York Fed" in r["reason"]


def test_demo_mode_invents_nothing(tmp_path):
    assert go(lambda req: httpx.Response(200, json=RAW), demo=True)["available"] is False
    with TestClient(create_app(db_path=str(tmp_path / "f.db"), demo=True, alert_loop=False, news_loop=False)) as c:
        d = c.get("/api/macro/fedops").json()["data"]
        assert d["demo"] is True and d["available"] is False
