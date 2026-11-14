"""US Treasury yield curve and debt: parsed from real responses (fetched 2026-11-08), spreads and changes by arithmetic, staleness, failures labelled, demo invents nothing."""
import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import treasury as T
from atlas_api.app import create_app

FX = Path(__file__).parent / "fixtures"
XML = (FX / "treasury_curve_202611.xml").read_text()
DEBT = json.loads((FX / "treasury_debt.json").read_text())
TODAY = date(2026, 11, 8)
NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


def test_the_real_curve_parses_oldest_first_with_every_tenor():
    days = T.parse_curve(XML)
    assert [d["date"] for d in days] == sorted(d["date"] for d in days) and len(days) >= 3
    last = days[-1]
    assert last["date"] == date(2026, 11, 6) and last["rates"]["10Y"] == 4.86 and last["rates"]["2Y"] == 4.51 and set(last["rates"]) == {t for t, _ in T.TENORS}


def test_spreads_changes_and_inversion_flags_are_plain_arithmetic():
    f = T.curve_fact(T.parse_curve(XML), TODAY)
    assert f["spreads"]["2s10s_bp"] == 35 and f["spreads"]["3m10y_bp"] == 67 and f["spreads"]["2s10s_inverted"] is False
    ten = next(p for p in f["points"] if p["tenor"] == "10Y")
    prev = T.parse_curve(XML)[-2]["rates"]["10Y"]
    assert ten["change_1d_bp"] == round((4.86 - prev) * 100) and f["freshness"] == "CURRENT" and f["compared_with"]["previous_day"] < "2026-11-06"


def test_an_inverted_curve_is_flagged_and_an_old_curve_is_overdue():
    days = T.parse_curve(XML)
    days[-1]["rates"]["2Y"], days[-1]["rates"]["3M"] = 5.2, 5.0
    f = T.curve_fact(days, date(2026, 11, 30))
    assert f["spreads"]["2s10s_inverted"] is True and f["spreads"]["3m10y_inverted"] is True and f["freshness"] == "OVERDUE"


def test_documents_with_entities_or_garbage_are_refused():
    for bad in ('<!DOCTYPE x [<!ENTITY a "b">]><feed/>', "<feed/>", "not xml"):
        with pytest.raises((ValueError, Exception)):
            T.parse_curve(bad)


def test_debt_is_parsed_in_trillions_with_changes_from_the_data():
    d = T.parse_debt(DEBT, TODAY)
    assert d["date"] == "2026-11-05" and 40 < d["total_trillions"] < 41 and d["held_by_public_trillions"] + d["intragovernmental_trillions"] == pytest.approx(d["total_trillions"], abs=0.01)
    assert d["change_vs_previous_day_billions"] == pytest.approx((40556120784983.65 - 40550230047609.15) / 1e9, abs=0.1)
    rows = [{"record_date": "2026-11-05", "tot_pub_debt_out_amt": "110", "debt_held_public_amt": "80", "intragov_hold_amt": "30"}, {"record_date": "2025-11-05", "tot_pub_debt_out_amt": "100", "debt_held_public_amt": "70", "intragov_hold_amt": "30"}]
    assert T.parse_debt({"data": rows}, TODAY)["change_vs_a_year_ago_pct"] == 10.0


def go(handler, demo=False):
    return asyncio.run(T.Treasury(httpx.AsyncClient(transport=httpx.MockTransport(handler)), demo).overview(NOW))


def handler(req):
    return httpx.Response(200, text=XML) if "treasury.gov" in req.url.host and "fiscaldata" not in req.url.host else httpx.Response(200, json=DEBT)


def test_service_returns_curve_and_debt_with_sources():
    r = go(handler)
    assert r["curve"]["available"] and r["debt"]["available"] and "official" in r["curve"]["source"] and "official" in r["debt"]["source"]


def test_one_failing_half_does_not_hide_the_other():
    r = go(lambda req: httpx.Response(503) if "fiscaldata" in req.url.host else httpx.Response(200, text=XML))
    assert r["curve"]["available"] and r["debt"]["available"] is False and "Treasury debt" in r["debt"]["reason"] and "points" not in r["debt"]
    r2 = go(lambda req: httpx.Response(200, json=DEBT) if "fiscaldata" in req.url.host else httpx.Response(500))
    assert r2["debt"]["available"] and r2["curve"]["available"] is False


def test_demo_mode_invents_nothing(tmp_path):
    r = go(handler, demo=True)
    assert r["demo"] and not r["curve"]["available"] and not r["debt"]["available"] and "points" not in r["curve"]
    with TestClient(create_app(db_path=str(tmp_path / "t.db"), demo=True, alert_loop=False, news_loop=False)) as c:
        assert c.get("/api/macro/treasury").json()["data"]["demo"] is True
