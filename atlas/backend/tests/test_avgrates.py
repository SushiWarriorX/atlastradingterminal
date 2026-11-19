"""Average interest rates on Treasury debt: parsed from a real response (260 rows, 15 full months for the headline series, fetched 2026-11-08); changes are plain subtraction on the source's own figures."""
import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import avgrates as R
from atlas_api.app import create_app

RAW = json.loads((Path(__file__).parent / "fixtures" / "treasury_avg_rates.json").read_text())
TODAY = date(2026, 11, 8)
NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


def raw_value(security: str, record_date: str) -> float:
    """Read straight from the raw rows, independent of the module under test."""
    return float(next(r["avg_interest_rate_amt"] for r in RAW["data"] if r["security_desc"] == security and r["record_date"] == record_date))


def test_only_the_securities_we_show_are_read_and_all_months_are_kept():
    d = R.parse(RAW)
    assert set(d) == {k for k, _ in R.ROWS} and len(d[R.HEADLINE]) == 15 and max(d[R.HEADLINE]) == date(2026, 10, 31)
    assert d[R.HEADLINE][date(2026, 10, 31)] == 3.58


def test_summary_changes_are_plain_subtraction_on_the_source_numbers():
    s = R.summarize(R.parse(RAW), TODAY)
    assert s["date"] == "2026-10-31" and s["freshness"] == "CURRENT" and [r["name"] for r in s["rows"]][0] == "Bills" and len(s["rows"]) == 7
    total = next(r for r in s["rows"] if r["name"] == "All interest-bearing debt")
    assert total["rate"] == 3.58 and total["change_month"] == round(raw_value(R.HEADLINE, "2026-10-31") - raw_value(R.HEADLINE, "2026-09-30"), 3)
    assert total["change_year"] == round(raw_value(R.HEADLINE, "2026-10-31") - raw_value(R.HEADLINE, "2025-10-31"), 3)
    bills = s["rows"][0]
    assert bills["rate"] == 4.014 and bills["change_month"] == round(4.014 - raw_value("Treasury Bills", "2026-09-30"), 3)
    assert len(s["history"]) == 15 and s["history"][-1] == {"date": "2026-10-31", "rate": 3.58} and "not a market signal or a forecast" in s["note"]


def test_a_missing_comparison_month_gives_none_not_a_guess():
    d = R.parse(RAW)
    for sec in d:
        d[sec].pop(date(2025, 10, 31), None)                                  # no month twelve months back
    s = R.summarize(d, TODAY)
    assert all(r["change_year"] is None for r in s["rows"]) and all(r["change_month"] is not None for r in s["rows"])


def test_month_arithmetic_crosses_year_ends():
    assert R._month_back(date(2026, 1, 31), 1) == (2025, 12) and R._month_back(date(2026, 10, 31), 12) == (2025, 10) and R._month_back(date(2026, 3, 31), 15) == (2024, 12)


def test_old_data_is_overdue():
    assert R.summarize(R.parse(RAW), date(2026, 12, 31))["freshness"] == "OVERDUE"


def test_too_little_or_garbled_data_is_refused():
    for bad in ({}, {"data": RAW["data"][:5]}, {"data": [{"security_desc": "Treasury Bills", "record_date": "x", "avg_interest_rate_amt": "?"}] * 20}):
        with pytest.raises(ValueError):
            R.parse(bad)


def go(handler, demo=False):
    return asyncio.run(R.AvgRates(httpx.AsyncClient(transport=httpx.MockTransport(handler)), demo).overview(NOW))


def test_service_returns_the_summary_with_source():
    r = go(lambda req: httpx.Response(200, json=RAW))
    assert r["available"] and "official" in r["source"] and r["rows"][-1]["rate"] == 3.58 and "fiscaldata" in r["url"]


def test_failure_says_so_and_shows_no_numbers():
    for h in (lambda req: httpx.Response(503), lambda req: httpx.Response(200, json={}), lambda req: (_ for _ in ()).throw(httpx.ConnectError("x"))):
        r = go(h)
        assert r["available"] is False and "rows" not in r and "FiscalData" in r["reason"]


def test_demo_mode_invents_nothing(tmp_path):
    assert go(lambda req: httpx.Response(200, json=RAW), demo=True)["available"] is False
    with TestClient(create_app(db_path=str(tmp_path / "r.db"), demo=True, alert_loop=False, news_loop=False)) as c:
        d = c.get("/api/macro/debtrates").json()["data"]
        assert d["demo"] is True and d["available"] is False
