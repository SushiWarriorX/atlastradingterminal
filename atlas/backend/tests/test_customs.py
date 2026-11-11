"""US customs duties (tariff revenue) from the Monthly Treasury Statement, Table 4: parsed from a real response (fetched 2026-11-11, 40 months to Sept 2026); hand-worked numbers; gross - refunds = net and fiscal-year-so-far =
sum of monthly nets as self-checks; tampered, missing-month, stale, failure and demo paths."""
import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from atlas_api import customs as C
from atlas_api.app import create_app

RAW = json.loads((Path(__file__).parent / "fixtures" / "treasury_customs_duties.json").read_text())
TODAY = date(2026, 11, 11)
NOW = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)


def _s(raw=None, today=TODAY):
    return C.summarize(C.parse(raw or RAW), today)


def test_latest_month_matches_the_report_by_hand():
    s = _s()
    la = s["latest"]
    assert s["date"] == "2026-09-30" and s["fiscal_year"] == 2026 and s["age_days"] == 42 and s["freshness"] == "CURRENT"
    assert (la["gross_billions"], la["refunds_billions"], la["net_billions"]) == (25.3, 19.4, 5.9)               # 25,271,564,478 - 19,361,162,228 = 5,910,402,250
    assert la["refunds_share_of_gross_pct"] == round(19361162228.45 / 25271564478.23 * 100, 1) == 76.6


def test_year_so_far_and_change_against_last_year_by_hand():
    ys = _s()["year_so_far"]
    assert (ys["gross_billions"], ys["refunds_billions"], ys["net_billions"]) == (317.8, 144.6, 173.2) and ys["months"] == 12
    assert ys["same_point_last_year_net_billions"] == 194.9 and ys["change_vs_last_year_pct"] == round((173218614643.40 / 194865739872.82 - 1) * 100, 1) == -11.1


def test_a_month_with_refunds_larger_than_collections_shows_a_negative_net():
    july = next(m for m in _s()["months"] if m["date"] == "2026-07-31")
    assert july["net_billions"] == -8.5 and july["refunds_billions"] > july["gross_billions"]


def test_the_fiscal_year_total_equals_the_sum_of_its_monthly_nets_for_every_checkable_month():
    rows = C.parse(RAW)
    ck = C.checks(rows)
    assert ck["ok"] and ck["identity_failures"] == 0 and ck["fytd_sum_mismatches"] == 0 and ck["fytd_sum_checks"] >= 12
    by = {r["date"]: r for r in rows}
    fy26 = [by[d] for d in by if C._fy(d) == 2026]
    assert len(fy26) == 12 and abs(sum(r["m_net"] for r in fy26) - by[date(2026, 9, 30)]["y_net"]) < 2           # computed here independently of the module


def test_tampered_arithmetic_is_refused_not_shown():
    bad = json.loads(json.dumps(RAW))
    bad["data"][0]["current_month_net_rcpt_amt"] = str(float(bad["data"][0]["current_month_net_rcpt_amt"]) + 1_000_000)   # a million dollars off
    try:
        _s(bad)
        assert False, "should refuse"
    except ValueError as e:
        assert "did not add up" in str(e)
    bad2 = json.loads(json.dumps(RAW))
    bad2["data"][3]["current_month_net_rcpt_amt"] = str(float(bad2["data"][3]["current_month_net_rcpt_amt"]) + 5_000_000)
    bad2["data"][3]["current_month_gross_rcpt_amt"] = str(float(bad2["data"][3]["current_month_gross_rcpt_amt"]) + 5_000_000)   # month still balances, but the year-so-far sum no longer does
    try:
        _s(bad2)
        assert False, "should refuse"
    except ValueError as e:
        assert "did not add up" in str(e)


def test_parse_refuses_unreadable_amounts_and_conflicting_duplicates():
    bad = json.loads(json.dumps(RAW))
    bad["data"][0]["current_month_gross_rcpt_amt"] = "n/a"
    for payload in (bad, {"data": []}):
        try:
            C.parse(payload)
            assert False
        except ValueError:
            pass
    dup = json.loads(json.dumps(RAW))
    other = json.loads(json.dumps(dup["data"][0]))
    other["current_month_net_rcpt_amt"] = "1.00"
    dup["data"].append(other)
    try:
        C.parse(dup)
        assert False
    except ValueError as e:
        assert "same month" in str(e)


def test_stale_data_is_marked_overdue_with_the_real_age():
    s = _s(today=date(2026, 12, 15))
    assert s["freshness"] == "OVERDUE" and s["age_days"] == 76


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_failure_then_recovery_and_caching():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] == 1 else httpx.Response(200, json=RAW)

    svc = C.Customs(client=_client(handler))
    bad = asyncio.run(svc.overview(NOW))
    assert bad["available"] is False and "HTTP 503" in bad["reason"] and "latest" not in bad
    svc._cache = None
    good = asyncio.run(svc.overview(NOW))
    assert good["available"] and good["latest"]["net_billions"] == 5.9 and "not a market signal or a forecast" in good["note"]
    n = calls["n"]
    asyncio.run(svc.overview(NOW))
    assert calls["n"] == n


def test_demo_mode_invents_nothing():
    d = asyncio.run(C.Customs(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "Demo" in d["reason"] and "latest" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/customs")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True
