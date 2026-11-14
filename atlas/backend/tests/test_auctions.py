"""Treasury note and bond auctions: parsed from a real response (150 auctions fetched 2026-11-08); TIPS, floating-rate and bills excluded; reopenings grouped; arithmetic checked."""
import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import auctions as A
from atlas_api.app import create_app

RAW = json.loads((Path(__file__).parent / "fixtures" / "treasury_auctions.json").read_text())
TODAY = date(2026, 11, 8)
NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


def test_reopened_terms_are_grouped_with_their_original_tenor():
    assert [A.tenor_of(t) for t in ("10-Year", "9-Year 10-Month", "9-Year 11-Month", "20-Year", "19-Year 11-Month", "30-Year", "29-Year 10-Month", "2-Year", "7-Year")] == [10, 10, 10, 20, 20, 30, 30, 2, 7]
    assert A.tenor_of("1-Year 10-Month") is None and A.tenor_of("4-Year 10-Month") is None and A.tenor_of("13-Week") is None and A.tenor_of("") is None


def test_only_finished_fixed_rate_notes_and_bonds_are_used():
    done, pending = A.parse(RAW)
    assert len(done) == 27 and done[0]["auction_date"] == date(2026, 10, 8) and done == sorted(done, key=lambda r: r["auction_date"], reverse=True)
    assert all(r["yield"] is not None and r["btc"] is not None for r in done)
    assert {r["cusip"] for r in done}.isdisjoint({"91282CRD5"})                    # a floating-rate note: excluded
    assert [(r["tenor"], r["auction_date"]) for r in pending] == [(20, date(2026, 10, 21))]       # held, but its results are not in the source yet (the 10-22 "5-Year" was a TIPS: excluded)


def test_summary_is_plain_arithmetic_on_the_auctions():
    done, pending = A.parse(RAW)
    s = A.summarize(done, pending, TODAY)
    ten = {t["tenor"]: t for t in s["tenors"]}
    assert list(ten) == ["2-year", "3-year", "5-year", "7-year", "10-year", "20-year", "30-year"] and s["date"] == "2026-10-08" and s["freshness"] == "CURRENT"
    t10 = ten["10-year"]                                                          # 2026-10-07 (a reopening, 9-Year 10-Month) vs 2026-09-09 and earlier
    assert t10["term"] == "9-Year 10-Month" and t10["reopening"] and t10["high_yield"] == 5.3 and t10["previous_yield"] == 4.834 and t10["yield_change"] == round(5.3 - 4.834, 3)
    assert t10["bid_to_cover"] == 2.77 and t10["compared_with"] == 3 and t10["average_bid_to_cover"] == round((2.71 + 2.53 + 2.59) / 3, 2)
    assert t10["offering_billions"] == 39.0
    assert ten["2-year"]["high_yield"] == 4.787 and ten["2-year"]["previous_yield"] == 4.204
    assert s["pending_results"] == [{"tenor": "20-year", "auction_date": "2026-10-21"}]
    assert "not market signals or forecasts" in s["note"]


def test_old_data_is_overdue():
    done, pending = A.parse(RAW)
    assert A.summarize(done, pending, date(2026, 12, 15))["freshness"] == "OVERDUE"


def test_too_little_or_garbled_data_is_refused():
    with pytest.raises(ValueError):
        A.parse({"data": RAW["data"][:5]})
    with pytest.raises(ValueError):
        A.parse({"data": [{"security_type": "Note"}] * 20})
    with pytest.raises(ValueError):
        A.parse({})


def go(handler, demo=False):
    return asyncio.run(A.Auctions(httpx.AsyncClient(transport=httpx.MockTransport(handler)), demo).overview(NOW))


def test_service_returns_the_summary_with_source():
    r = go(lambda req: httpx.Response(200, json=RAW))
    assert r["available"] and "official" in r["source"] and len(r["tenors"]) == 7 and "fiscaldata" in r["url"]


def test_failure_says_so_and_shows_no_numbers():
    for h in (lambda req: httpx.Response(503), lambda req: httpx.Response(200, json={}), lambda req: (_ for _ in ()).throw(httpx.ConnectError("x"))):
        r = go(h)
        assert r["available"] is False and "tenors" not in r and "FiscalData" in r["reason"]


def test_demo_mode_invents_nothing(tmp_path):
    assert go(lambda req: httpx.Response(200, json=RAW), demo=True)["available"] is False
    with TestClient(create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)) as c:
        d = c.get("/api/macro/auctions").json()["data"]
        assert d["demo"] is True and d["available"] is False
