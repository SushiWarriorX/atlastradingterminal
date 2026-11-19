"""Treasury borrowing (Daily Treasury Statement, Public Debt Transactions): parsed from real responses (fetched 2026-11-10: the newest day, the month so far, and the same days a year earlier); the month's days
added up independently against the source's own month-to-date figure; buckets, year-ago comparison, stale, bad-data, failure and demo paths."""
import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import borrowing as B
from atlas_api.app import create_app

RAW = json.loads((Path(__file__).parent / "fixtures" / "treasury_borrowing.json").read_text())
TODAY = date(2026, 11, 9)
NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)


def _summary(today=TODAY, month=None):
    latest = B.parse(RAW["latest"])
    d = max(latest)
    return B.summarize({d: latest[d]}, B.parse(month or RAW["month"]), B.parse(RAW["year_ago"]), today)


def test_only_marketable_rows_are_read():
    rows = B.parse(RAW["latest"])
    assert max(rows) == date(2026, 11, 6) and all(r["bucket"] in dict(B.BUCKETS) for rs in rows.values() for r in rs)
    assert not any(r["bucket"] == "other" and r["mtd"] > 0 for r in rows[date(2026, 11, 6)])         # Government Account Series (trillions) is not in here


def test_bucket_rules():
    assert B.bucket("Bills") == "bills" and B.bucket("Notes") == "notes" and B.bucket("Bonds") == "bonds"
    assert B.bucket("Inflation-Protected Securities Increment") == "tips" and B.bucket("Federal Financing Bank") == "other"


def test_month_to_date_equals_an_independent_sum_of_the_raw_rows():
    raw = [r for r in RAW["latest"]["data"] if r["record_date"] == "2026-11-06" and r["security_market"] == "Marketable"]
    iss = sum(float(r["transaction_mtd_amt"]) for r in raw if r["transaction_type"] == "Issues") / 1000
    red = sum(float(r["transaction_mtd_amt"]) for r in raw if r["transaction_type"] == "Redemptions") / 1000
    m = _summary()["month_to_date"]
    assert m["issues_billions"] == round(iss, 1) == 848.7 and m["redemptions_billions"] == round(red, 1) == 820.2 and m["net_billions"] == round(iss - red, 1) == 28.5


def test_the_days_of_the_month_add_up_to_the_sources_own_month_to_date():
    c = _summary()["mtd_check"]
    assert c["days"] == 5 and c["match"] is True and c["issues_billions"] == c["source_issues_billions"] and c["redemptions_billions"] == c["source_redemptions_billions"]
    broken = json.loads(json.dumps(RAW["month"]))
    one = next(r for r in broken["data"] if r["record_date"] == "2026-11-04" and r["transaction_type"] == "Issues" and r["security_type"] == "Bills" and r["security_type_desc"] == "Regular Series")
    one["transaction_today_amt"] = str(float(one["transaction_today_amt"]) + 50000)                       # a day that is $50B off
    assert _summary(month=broken)["mtd_check"]["match"] is False


def test_the_buckets_add_up_to_the_totals():
    s = _summary()
    assert abs(sum(r["mtd_net_billions"] for r in s["by_security"]) - s["month_to_date"]["net_billions"]) < 0.15
    assert abs(sum(r["fytd_net_billions"] for r in s["by_security"]) - s["fiscal_year_to_date"]["net_billions"]) < 0.15
    bills = next(r for r in s["by_security"] if r["key"] == "bills")
    assert bills["mtd_issues_billions"] == 609.5 and bills["mtd_redemptions_billions"] == 556.1 and bills["mtd_net_billions"] == 53.4


def test_cash_management_and_regular_bills_are_one_line():
    raw = [r for r in RAW["latest"]["data"] if r["record_date"] == "2026-11-06" and r["security_type"] == "Bills" and r["transaction_type"] == "Issues"]
    assert {r["security_type_desc"] for r in raw} == {"Regular Series", "Cash Management Series"}
    assert next(r for r in _summary()["by_security"] if r["key"] == "bills")["fytd_net_billions"] == 316.9      # 3,425.65 issued in the fiscal year (incl. 25 of cash management) minus 3,108.71 redeemed


def test_the_comparison_is_with_the_same_day_a_year_earlier():
    s = _summary()
    assert s["year_ago_date"] == "2025-11-06" and s["month_to_date"]["year_ago_net_billions"] == 41.1 and s["fiscal_year_to_date"]["year_ago_net_billions"] == 325.0
    assert s["fiscal_year"] == 2027 and s["freshness"] == "CURRENT" and s["age_days"] == 3


def test_no_year_ago_data_gives_no_comparison_not_a_guess():
    latest = B.parse(RAW["latest"])
    d = max(latest)
    s = B.summarize({d: latest[d]}, B.parse(RAW["month"]), {}, TODAY)
    assert s["year_ago_date"] is None and s["month_to_date"]["year_ago_net_billions"] is None and s["fiscal_year_to_date"]["year_ago_net_billions"] is None


def test_old_data_is_overdue():
    s = _summary(today=date(2026, 11, 30))
    assert s["freshness"] == "OVERDUE" and s["age_days"] == 24


def test_an_unreadable_marketable_amount_is_refused():
    bad = json.loads(json.dumps(RAW["latest"]))
    row = next(r for r in bad["data"] if r["security_market"] == "Marketable")
    row["transaction_mtd_amt"] = "null"
    with pytest.raises(ValueError):
        B.parse(bad)
    with pytest.raises(ValueError):
        B.parse({"data": [{"record_date": "soon", "security_market": "Marketable"}]})


def _handler(calls):
    def handler(req):
        calls.append(str(req.url))
        q = str(req.url)
        if "gte" in q:
            return httpx.Response(200, json=RAW["month"])
        if "lte" in q:
            return httpx.Response(200, json=RAW["year_ago"])
        return httpx.Response(200, json=RAW["latest"])
    return handler


def test_the_service_reads_three_slices_then_serves_from_cache():
    calls = []
    svc = B.Borrowing(client=httpx.AsyncClient(transport=httpx.MockTransport(_handler(calls))))
    a = asyncio.run(svc.overview(NOW))
    assert a["available"] and a["month_to_date"]["net_billions"] == 28.5 and a["mtd_check"]["match"] and len(calls) == 3
    asyncio.run(svc.overview(NOW))
    assert len(calls) == 3


def test_failure_says_so_and_shows_nothing():
    svc = B.Borrowing(client=httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(500))))
    bad = asyncio.run(svc.overview(NOW))
    assert bad["available"] is False and "HTTP 500" in bad["reason"] and "month_to_date" not in bad


def test_demo_mode_invents_nothing():
    d = asyncio.run(B.Borrowing(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "Demo" in d["reason"] and "month_to_date" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/borrowing")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True
