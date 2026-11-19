"""Fed policy rate and overnight reference rates: parsed from real responses fetched 2026-11-08 (latest rates and 260 days of EFFR history); the last target change is found, not typed in."""
import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import fedrates as F
from atlas_api.app import create_app

FIX = Path(__file__).parent / "fixtures"
LATEST = json.loads((FIX / "nyfed_rates_latest.json").read_text())
HIST = json.loads((FIX / "nyfed_effr_history.json").read_text())
TODAY = date(2026, 11, 8)
NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


def test_latest_rates_are_read_with_the_target_range_from_the_effr_row():
    r = F.parse_latest(LATEST)
    assert set(r) == {"EFFR", "OBFR", "TGCR", "BGCR", "SOFR"}                                    # the SOFR index row (SOFRAI) is ignored
    e = r["EFFR"]
    assert e["rate"] == 3.88 and e["date"] == date(2026, 11, 5) and (e["target_from"], e["target_to"]) == (3.75, 4.0) and e["p1"] == 3.85 and e["p99"] == 3.92 and e["volume"] == 111.0
    assert r["SOFR"]["rate"] == 3.92 and r["SOFR"]["target_from"] is None                         # only EFFR carries the target range


def test_history_is_sorted_oldest_first():
    h = F.parse_history(HIST)
    assert len(h) == 260 and h[0]["date"] < h[-1]["date"] and h[-1]["date"] == date(2026, 11, 5)


def test_the_last_target_change_is_found_in_the_data():
    h = F.parse_history(HIST)
    c = F.last_target_change(h, TODAY)
    assert c["date"] == "2026-09-17" and c["from_range"] == [3.5, 3.75] and c["to_range"] == [3.75, 4.0] and c["change_pp"] == 0.25 and c["days_ago"] == 52
    flat = [{"date": date(2026, 1, 1 + i), "rate": 3.88, "target_from": 3.75, "target_to": 4.0} for i in range(30)]
    assert F.last_target_change(flat, TODAY) is None                                              # no change inside the window: say so, do not invent one
    cut = [{"date": date(2026, 1, 1 + i), "rate": 4.0 if i < 15 else 3.88, "target_from": 4.0 if i < 15 else 3.75, "target_to": 4.25 if i < 15 else 4.0} for i in range(30)]
    c2 = F.last_target_change(cut, TODAY)
    assert c2["change_pp"] == -0.25 and c2["date"] == "2026-01-16"                               # a cut shows as negative


def test_summary_is_plain_arithmetic():
    s = F.summarize(F.parse_latest(LATEST), F.parse_history(HIST), TODAY)
    assert s["effr"] == 3.88 and s["target_low"] == 3.75 and s["target_high"] == 4.0 and s["effr_position"] == "inside" and s["effr_above_bottom_pp"] == 0.13
    assert s["sofr_minus_effr_pp"] == round(3.92 - 3.88, 3) and s["freshness"] == "CURRENT" and [r["code"] for r in s["rates"]] == ["EFFR", "OBFR", "TGCR", "BGCR", "SOFR"]
    prev = F.parse_history(HIST)[-2]["rate"]
    assert s["effr_change_pp"] == round(3.88 - prev, 3) and len(s["history"]) == 60 and "not market signals or forecasts" in s["note"]


def test_a_rate_outside_the_range_is_said_to_be_outside():
    latest = F.parse_latest(LATEST)
    latest["EFFR"]["rate"] = 4.1
    assert F.summarize(latest, None, TODAY)["effr_position"] == "above"
    latest["EFFR"]["rate"] = 3.7
    assert F.summarize(latest, None, TODAY)["effr_position"] == "below"


def test_old_data_is_overdue():
    assert F.summarize(F.parse_latest(LATEST), None, date(2026, 11, 30))["freshness"] == "OVERDUE"


def test_garbled_or_thin_responses_are_refused():
    for bad in ({}, {"refRates": [{"type": "SOFR", "effectiveDate": "2026-11-05", "percentRate": 3.9}]}):
        with pytest.raises(ValueError):
            F.parse_latest(bad)
    with pytest.raises(ValueError):
        F.parse_history({"refRates": HIST["refRates"][:5]})


def go(handler, demo=False):
    return asyncio.run(F.FedRates(httpx.AsyncClient(transport=httpx.MockTransport(handler)), demo).overview(NOW))


def both(req):
    return httpx.Response(200, json=HIST if "effr" in req.url.path else LATEST)


def test_service_returns_rates_and_the_last_change():
    r = go(both)
    assert r["available"] and "official" in r["source"] and r["effr"] == 3.88 and r["history_available"] and r["last_change"]["date"] == "2026-09-17" and "newyorkfed.org" in r["url"]


def test_missing_history_still_shows_the_rates_and_says_the_history_is_missing():
    r = go(lambda req: httpx.Response(503) if "effr" in req.url.path else httpx.Response(200, json=LATEST))
    assert r["available"] and r["effr"] == 3.88 and r["history_available"] is False and r["last_change"] is None and "could not be read" in r["history_reason"]


def test_failure_says_so_and_shows_no_numbers():
    for h in (lambda req: httpx.Response(503), lambda req: httpx.Response(200, json={}), lambda req: (_ for _ in ()).throw(httpx.ConnectError("x"))):
        r = go(h)
        assert r["available"] is False and "effr" not in r and "New York Fed" in r["reason"]


def test_demo_mode_invents_nothing(tmp_path):
    assert go(both, demo=True)["available"] is False
    with TestClient(create_app(db_path=str(tmp_path / "f.db"), demo=True, alert_loop=False, news_loop=False)) as c:
        d = c.get("/api/macro/fedrates").json()["data"]
        assert d["demo"] is True and d["available"] is False
