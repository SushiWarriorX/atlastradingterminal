"""Where US federal revenue comes from (Monthly Treasury Statement Table 4): a real response (fetched 2026-11-11; the newest month is Sept 2026, older rows are ignored); hand-worked numbers; the seven categories adding up to the source's own
total and on-budget plus off-budget equalling it as self-checks; tampered, missing line, stale, failure and demo paths."""
import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from atlas_api import receipts as R
from atlas_api.app import create_app

RAW = json.loads((Path(__file__).parent / "fixtures" / "treasury_receipts_by_source.json").read_text())
TODAY = date(2026, 11, 11)
NOW = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)


def _s(raw=None, today=TODAY):
    newest, lines = R.parse(raw or RAW)
    return R.summarize(newest, lines, today)


def _cat(s, name):
    return next(c for c in s["categories"] if c["name"].startswith(name))


def test_the_newest_month_is_used_and_older_rows_are_ignored():
    newest, lines = R.parse(RAW)
    s = _s()
    assert newest == date(2026, 9, 30) and s["fiscal_year"] == 2026 and s["months_in_year"] == 12 and s["age_days"] == 42 and s["freshness"] == "CURRENT"
    assert set(lines) == {c[0] for c in R.CATEGORIES} | {R.TOTAL, R.ON_BUDGET, R.OFF_BUDGET}


def test_totals_and_changes_match_the_report_by_hand():
    t = _s()["total"]
    assert (t["month_billions"], t["year_so_far_billions"], t["same_point_last_year_billions"]) == (557.9, 5403.3, 5234.6)          # 557,874,519,238 / 5,403,326,758,961 / 5,234,616,472,031
    assert t["change_vs_last_year_pct"] == round((5403326758960.81 / 5234616472030.91 - 1) * 100, 1) == 3.2


def test_each_category_by_hand_and_sorted_by_size():
    s = _s()
    assert [c["name"] for c in s["categories"]][:3] == ["Individual income taxes", "Social Security, Medicare and other payroll taxes", "Corporate income taxes"]
    ind, corp, cust = _cat(s, "Individual"), _cat(s, "Corporate"), _cat(s, "Customs")
    assert ind["year_so_far_billions"] == 2845.5 and ind["share_of_year_pct"] == round(2845526866159.55 / 5403326758960.81 * 100, 1) == 52.7
    assert ind["change_vs_last_year_pct"] == round((2845526866159.55 / 2656044447275.63 - 1) * 100, 1) == 7.1
    assert corp["year_so_far_billions"] == 381.4 and corp["same_point_last_year_billions"] == 452.1 and corp["change_vs_last_year_pct"] == -15.6
    assert cust["year_so_far_billions"] == 173.2 and cust["change_vs_last_year_pct"] == -11.1 and cust["month_billions"] == 5.9      # agrees with the customs panel's figures


def test_the_seven_categories_add_up_to_the_total_to_the_cent_for_month_year_and_last_year():
    _, lines = R.parse(RAW)
    for k in ("m", "y", "p"):
        assert abs(sum(lines[c[0]][k] for c in R.CATEGORIES) - lines[R.TOTAL][k]) < 0.01
        assert abs(lines[R.ON_BUDGET][k] + lines[R.OFF_BUDGET][k] - lines[R.TOTAL][k]) < 0.01          # computed here independently of the module
    ck = R.checks(lines)
    assert ck["ok"] and ck["categories_add_up_to_total"] and ck["on_plus_off_budget_equals_total"] and ck["problems"] == []


def test_a_tampered_category_or_budget_split_is_refused_not_shown():
    bad = json.loads(json.dumps(RAW))
    for r in bad["data"]:
        if r["classification_desc"] == "Customs Duties" and r["record_date"] == "2026-09-30":
            r["current_fytd_net_rcpt_amt"] = str(float(r["current_fytd_net_rcpt_amt"]) + 1_000_000_000)           # a billion dollars off
    try:
        _s(bad)
        assert False, "should refuse"
    except ValueError as e:
        assert "did not add up" in str(e) and "year so far" in str(e)
    bad2 = json.loads(json.dumps(RAW))
    for r in bad2["data"]:
        if r["classification_desc"] == "Total -- Off-Budget" and r["record_date"] == "2026-09-30":
            r["current_month_net_rcpt_amt"] = str(float(r["current_month_net_rcpt_amt"]) + 5_000_000)
    try:
        _s(bad2)
        assert False, "should refuse"
    except ValueError as e:
        assert "on-budget plus off-budget" in str(e)


def test_a_missing_or_unreadable_line_and_empty_responses_are_refused():
    miss = json.loads(json.dumps(RAW))
    miss["data"] = [r for r in miss["data"] if r["classification_desc"] != "Corporation Income Taxes"]
    unread = json.loads(json.dumps(RAW))
    for r in unread["data"]:
        if r["classification_desc"] == "Total -- Receipts" and r["record_date"] == "2026-09-30":
            r["current_fytd_net_rcpt_amt"] = "null"
    for payload in (miss, unread, {"data": []}):
        try:
            R.parse(payload)
            assert False, "should refuse"
        except ValueError:
            pass


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

    svc = R.Receipts(client=_client(handler))
    bad = asyncio.run(svc.overview(NOW))
    assert bad["available"] is False and "HTTP 503" in bad["reason"] and "categories" not in bad
    svc._cache = None
    good = asyncio.run(svc.overview(NOW))
    assert good["available"] and good["total"]["year_so_far_billions"] == 5403.3 and "not a market signal or a forecast" in good["note"]
    n = calls["n"]
    asyncio.run(svc.overview(NOW))
    assert calls["n"] == n


def test_demo_mode_invents_nothing():
    d = asyncio.run(R.Receipts(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "Demo" in d["reason"] and "categories" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/receipts")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True
