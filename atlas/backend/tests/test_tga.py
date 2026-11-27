"""Treasury General Account: parsed from a real response (260 days fetched 2026-11-08), plain arithmetic, staleness, failures labelled, demo invents nothing."""
import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import tga as T
from atlas_api.app import create_app

RAW = json.loads((Path(__file__).parent / "fixtures" / "treasury_tga.json").read_text())
TODAY = date(2026, 11, 8)
NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


def test_real_response_is_sorted_oldest_first_and_read_from_the_right_field():
    rows = T.parse(RAW)
    assert rows[0][0] < rows[-1][0] and rows[-1] == (date(2026, 11, 5), 922752.0) and len(rows) == 260
    assert dict(rows)[date(2026, 11, 4)] == 936248.0          # equals the next day's opening balance in the same source


def test_summary_is_plain_arithmetic_on_the_data():
    rows = T.parse(RAW)
    s = T.summarize(rows, TODAY)
    assert s["date"] == "2026-11-05" and s["freshness"] == "CURRENT" and s["balance_billions"] == 922.8 and s["change_1d_billions"] == round((922752 - 936248) / 1000, 1)
    assert s["change_month_billions"] == round((922752 - rows[-22][1]) / 1000, 1)
    assert s["month_average_billions"] == round(sum(v for _, v in rows[-21:]) / 21 / 1000, 1)
    vals = [v for _, v in rows[-250:]]
    assert s["year_low_billions"] == round(min(vals) / 1000, 1) and s["year_high_billions"] == round(max(vals) / 1000, 1) and len(s["history"]) == 60
    assert "not a market signal or a forecast" in s["note"]


def test_old_data_is_overdue_and_bad_rows_are_skipped():
    assert T.summarize(T.parse(RAW), date(2026, 11, 30))["freshness"] == "OVERDUE"
    raw = json.loads(json.dumps(RAW))
    raw["data"] += [{"record_date": "2026-11-06", "account_type": "Treasury General Account (TGA) Closing Balance", "open_today_bal": "null"},
                    {"record_date": "x", "account_type": "Treasury General Account (TGA) Closing Balance", "open_today_bal": "5"},
                    {"record_date": "2026-11-06", "account_type": "Something else", "open_today_bal": "5"}]
    assert T.parse(raw)[-1][0] == date(2026, 11, 5)


def test_too_little_data_is_refused():
    with pytest.raises(ValueError):
        T.parse({"data": RAW["data"][:10]})
    with pytest.raises(ValueError):
        T.parse({})


def go(handler, demo=False):
    return asyncio.run(T.Tga(httpx.AsyncClient(transport=httpx.MockTransport(handler)), demo).overview(NOW))


def test_service_returns_the_summary_with_source():
    r = go(lambda req: httpx.Response(200, json=RAW))
    assert r["available"] and "official" in r["source"] and r["balance_billions"] == 922.8 and "fiscaldata" in r["url"]


def test_failure_says_so_and_shows_no_numbers():
    for h in (lambda req: httpx.Response(503), lambda req: httpx.Response(200, json={}), lambda req: (_ for _ in ()).throw(httpx.ConnectError("x"))):
        r = go(h)
        assert r["available"] is False and "balance_billions" not in r and "FiscalData" in r["reason"]


def test_demo_mode_invents_nothing(tmp_path):
    assert go(lambda req: httpx.Response(200, json=RAW), demo=True)["available"] is False
    with TestClient(create_app(db_path=str(tmp_path / "t.db"), demo=True, alert_loop=False, news_loop=False)) as c:
        d = c.get("/api/macro/tga").json()["data"]
        assert d["demo"] is True and d["available"] is False
