"""Monthly Treasury Statement: parsed from a real response (60 rows fetched 2026-11-08); fiscal-year grouping by parent row, own arithmetic cross-checked against the source's deficit field."""
import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import mts as M
from atlas_api.app import create_app

RAW = json.loads((Path(__file__).parent / "fixtures" / "treasury_mts.json").read_text())
TODAY = date(2026, 11, 8)
NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


def test_newest_statement_is_grouped_into_fiscal_years_by_parent_row():
    newest, years = M.parse(RAW)
    assert newest == date(2026, 9, 30) and set(years) == {2025, 2026} and len(years[2026]) == 12 and len(years[2025]) == 12
    assert years[2026]["October"]["receipts"] == 404371348973.33 or abs(years[2026]["October"]["receipts"] - 404371348973) < 1000     # October opens FY2026
    assert abs(years[2025]["October"]["receipts"] - 326770236058) < 1000                                                         # and FY2025 has its own October


def test_our_deficit_arithmetic_matches_the_sources_own_figure_for_every_month():
    _, years = M.parse(RAW)
    for fy in years.values():
        for v in fy.values():
            assert abs((v["outlays"] - v["receipts"]) - v["source_deficit"]) < 1.0


def test_summary_year_to_date_is_the_sum_of_the_months_and_matches_the_sources_total():
    newest, years = M.parse(RAW)
    s = M.summarize(newest, years, TODAY)
    assert s["fiscal_year"] == 2026 and s["month"] == "September" and s["ytd_months"] == 12 and s["freshness"] == "CURRENT"
    assert s["month_receipts_billions"] == 557.9 and s["month_outlays_billions"] == 584.8 and s["month_deficit_billions"] == 26.9
    assert s["ytd_receipts_billions"] == round(sum(v["receipts"] for v in years[2026].values()) / 1e9, 1)
    assert s["ytd_receipts_billions"] == 5403.3 and s["ytd_outlays_billions"] == 7395.8 and s["ytd_deficit_billions"] == 1992.5              # the source's own "Year-to-Date" row
    assert s["prior_ytd_deficit_billions"] == 1775.4 and len(s["history"]) == 24 and "not market signals or forecasts" in s["note"]


def test_a_partial_fiscal_year_is_compared_with_the_same_months_only():
    newest, years = M.parse(RAW)
    years = {2026: {m: v for m, v in years[2026].items() if m in ("October", "November", "December")}, 2025: years[2025]}
    s = M.summarize(newest, years, TODAY)
    assert s["month"] == "December" and s["ytd_months"] == 3
    assert s["prior_ytd_receipts_billions"] == round(sum(years[2025][m]["receipts"] for m in ("October", "November", "December")) / 1e9, 1)
    years[2025].pop("November")                                                                # prior year incomplete: no comparison rather than a wrong one
    assert M.summarize(newest, years, TODAY)["prior_ytd_deficit_billions"] is None


def test_old_statement_is_overdue():
    newest, years = M.parse(RAW)
    assert M.summarize(newest, years, date(2026, 12, 31))["freshness"] == "OVERDUE"


def test_garbled_or_thin_responses_are_refused():
    for bad in ({}, {"data": [{"record_date": "x"}]}, {"data": [r for r in RAW["data"] if r["classification_desc"] == "FY 2026"]}):
        with pytest.raises(ValueError):
            M.parse(bad)


def go(handler, demo=False):
    return asyncio.run(M.Mts(httpx.AsyncClient(transport=httpx.MockTransport(handler)), demo).overview(NOW))


def test_service_returns_the_summary_with_source():
    r = go(lambda req: httpx.Response(200, json=RAW))
    assert r["available"] and "official" in r["source"] and r["ytd_deficit_billions"] == 1992.5 and "fiscaldata" in r["url"]


def test_failure_says_so_and_shows_no_numbers():
    for h in (lambda req: httpx.Response(503), lambda req: httpx.Response(200, json={}), lambda req: (_ for _ in ()).throw(httpx.ConnectError("x"))):
        r = go(h)
        assert r["available"] is False and "ytd_deficit_billions" not in r and "FiscalData" in r["reason"]


def test_demo_mode_invents_nothing(tmp_path):
    assert go(lambda req: httpx.Response(200, json=RAW), demo=True)["available"] is False
    with TestClient(create_app(db_path=str(tmp_path / "m.db"), demo=True, alert_loop=False, news_loop=False)) as c:
        d = c.get("/api/macro/budget").json()["data"]
        assert d["demo"] is True and d["available"] is False
