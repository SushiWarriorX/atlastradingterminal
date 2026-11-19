"""Monthly Statement of the Public Debt: parsed from a real response (140 rows, 10 month-ends, fetched 2026-11-08); shares and changes are plain arithmetic on the source's own figures."""
import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import mspd as P
from atlas_api.app import create_app

RAW = json.loads((Path(__file__).parent / "fixtures" / "treasury_mspd.json").read_text())
TODAY = date(2026, 11, 8)
NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


def raw(kind: str, cls: str, record_date: str, field: str = "total_mil_amt") -> float:
    """Straight from the raw rows, independent of the module under test."""
    return float(next(r[field] for r in RAW["data"] if r["security_type_desc"] == kind and r["security_class_desc"] == cls and r["record_date"] == record_date))


def test_only_the_rows_we_show_are_read_across_all_months():
    d = P.parse(RAW)
    assert set(d) == {k for k, _ in P.ROWS} and len(d[P.TOTAL]) == 10 and max(d[P.TOTAL]) == date(2026, 10, 31)
    assert d[P.TOTAL][date(2026, 10, 31)]["total"] == raw("Total Public Debt Outstanding", "_", "2026-10-31")


def test_summary_shares_and_changes_are_plain_arithmetic():
    s = P.summarize(P.parse(RAW), TODAY)
    tot, prev_tot = raw("Total Public Debt Outstanding", "_", "2026-10-31"), raw("Total Public Debt Outstanding", "_", "2026-09-30")
    assert s["date"] == "2026-10-31" and s["freshness"] == "CURRENT" and s["total_billions"] == round(tot / 1000, 1) and len(s["rows"]) == 8
    bills = next(r for r in s["rows"] if r["name"].startswith("Bills"))
    b, bp = raw("Marketable", "Bills", "2026-10-31"), raw("Marketable", "Bills", "2026-09-30")
    assert bills["billions"] == round(b / 1000, 1) and bills["share_of_total_pct"] == round(b / tot * 100, 1) and bills["change_month_billions"] == round((b - bp) / 1000, 1)
    mk = raw("Total Marketable", "_", "2026-10-31")
    assert s["bills_share_of_marketable_pct"] == round(b / mk * 100, 1)
    assert s["held_by_public_billions"] == round(raw("Total Public Debt Outstanding", "_", "2026-10-31", "debt_held_public_mil_amt") / 1000, 1)
    assert abs(s["held_by_public_billions"] + s["held_by_government_accounts_billions"] - s["total_billions"]) < 0.2                # the two holders add up to the total
    assert s["since"] == "2026-01-31" and s["change_since_billions"] == round((tot - raw("Total Public Debt Outstanding", "_", "2026-01-31")) / 1000, 1) and s["months_covered"] == 10
    assert len(s["history"]) == 10 and "not a market signal or a forecast" in s["note"]


def test_the_listed_parts_add_up_to_the_total_in_the_source():
    s = P.summarize(P.parse(RAW), TODAY)
    by = {r["name"].split(" (")[0]: r["billions"] for r in s["rows"]}
    marketable = by["Bills"] + by["Notes"] + by["Bonds"] + by["Inflation-protected"] + by["Floating-rate notes"]
    assert abs(marketable - by["All marketable debt"]) < 5.0                                   # the small remainder is the Federal Financing Bank line (about $3.6B)
    assert abs(by["All marketable debt"] + by["All non-marketable debt"] - by["Total public debt outstanding"]) < 0.3


def test_old_data_is_overdue_and_missing_previous_month_gives_none():
    d = P.parse(RAW)
    assert P.summarize(d, date(2026, 12, 31))["freshness"] == "OVERDUE"
    d[("Marketable", "Bills")].pop(date(2026, 9, 30))
    bills = next(r for r in P.summarize(d, TODAY)["rows"] if r["name"].startswith("Bills"))
    assert bills["change_month_billions"] is None


def test_too_little_or_garbled_data_is_refused():
    for bad in ({}, {"data": RAW["data"][:5]}, {"data": [{"security_type_desc": "Marketable", "security_class_desc": "Bills", "record_date": "x", "debt_held_public_mil_amt": "?"}] * 20}):
        with pytest.raises(ValueError):
            P.parse(bad)


def go(handler, demo=False):
    return asyncio.run(P.Mspd(httpx.AsyncClient(transport=httpx.MockTransport(handler)), demo).overview(NOW))


def test_service_returns_the_summary_with_source():
    r = go(lambda req: httpx.Response(200, json=RAW))
    assert r["available"] and "official" in r["source"] and r["total_billions"] > 40000 and "fiscaldata" in r["url"]


def test_failure_says_so_and_shows_no_numbers():
    for h in (lambda req: httpx.Response(503), lambda req: httpx.Response(200, json={}), lambda req: (_ for _ in ()).throw(httpx.ConnectError("x"))):
        r = go(h)
        assert r["available"] is False and "rows" not in r and "FiscalData" in r["reason"]


def test_demo_mode_invents_nothing(tmp_path):
    assert go(lambda req: httpx.Response(200, json=RAW), demo=True)["available"] is False
    with TestClient(create_app(db_path=str(tmp_path / "d.db"), demo=True, alert_loop=False, news_loop=False)) as c:
        d = c.get("/api/macro/debtmix").json()["data"]
        assert d["demo"] is True and d["available"] is False
