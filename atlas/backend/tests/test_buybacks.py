"""Treasury buyback operations: parsed from a real response (233 rows fetched 2026-11-10, trimmed to 2024 onward); windows added up independently; missing results counted separately, never as zero;
failure, bad data, stale and demo paths."""
import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import buybacks as B
from atlas_api.app import create_app

RAW = json.loads((Path(__file__).parent / "fixtures" / "treasury_buybacks.json").read_text())
TODAY = date(2026, 11, 10)
NOW = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)


def test_only_the_current_program_is_read_newest_first():
    ops = B.parse(RAW)
    assert ops[0]["date"] == date(2026, 11, 5) and ops[-1]["date"] == date(2024, 5, 29) and len(ops) == 171     # three rows before May 2024 belong to no operation of this program
    assert all(a["date"] >= b["date"] for a, b in zip(ops, ops[1:]))


def test_latest_operation_matches_the_source_row():
    s = B.summarize(B.parse(RAW), TODAY)
    assert s["latest"] == {"date": "2026-11-05", "type": "Liquidity support", "security": "Notes and bonds (nominal)", "maturity": "1Mo to 2Y",
                           "offered_billions": 47.32, "accepted_billions": 4.0, "maximum_billions": 4.0, "bought_share_pct": 8.5, "issues_accepted": 4}      # 4.0 / 47.319 = 8.45%
    assert s["freshness"] == "CURRENT" and s["age_days"] == 5


def test_ninety_day_window_equals_an_independent_sum_of_the_raw_rows():
    since = (TODAY - timedelta(days=90)).isoformat()
    rows = [r for r in RAW["data"] if r["operation_date"] > since]
    acc = sum(float(r["total_par_amt_accepted"]) for r in rows) / 1e9
    off = sum(float(r["total_par_amt_offered"]) for r in rows) / 1e9
    w = B.summarize(B.parse(RAW), TODAY)["last_90_days"]
    assert w["operations"] == len(rows) == 18 and w["no_result"] == 0
    assert w["accepted_billions"] == round(acc, 2) == 78.88 and w["offered_billions"] == round(off, 2) and w["bought_share_pct"] == round(acc / off * 100, 1)


def test_groups_add_up_to_the_window_total():
    s = B.summarize(B.parse(RAW), TODAY)
    tot = s["last_365_days"]["accepted_billions"]
    for key in ("by_security", "by_type", "by_maturity"):
        assert abs(sum(r["accepted_billions"] for r in s[key]) - tot) < 0.05, key                           # every operation lands in exactly one group of each kind
    assert [r["key"] for r in s["by_security"]] == ["Nominal Coupons", "TIPS"]                                  # biggest first


def test_no_source_row_buys_more_than_was_offered_or_announced():
    assert B.summarize(B.parse(RAW), TODAY)["anomalies"] == 0
    bad = {"data": [dict(r) for r in RAW["data"]]}
    bad["data"][0]["total_par_amt_accepted"] = "99000000000.00"                                              # more than offered and more than the maximum
    assert B.summarize(B.parse(bad), TODAY)["anomalies"] == 1


def test_a_missing_result_is_counted_apart_and_never_treated_as_zero():
    rows = [dict(r) for r in RAW["data"]]
    first = rows[0]
    first["total_par_amt_accepted"] = "null"
    w = B.summarize(B.parse({"data": rows}), TODAY)
    assert w["last_90_days"]["no_result"] == 1 and w["last_90_days"]["with_result"] == 17 and w["last_90_days"]["operations"] == 18
    assert w["last_90_days"]["accepted_billions"] == round(78.88 - 4.0, 2)                                    # the 4.0B operation is not in the sum, not counted as 0 either
    assert w["latest"]["accepted_billions"] is None and w["latest"]["bought_share_pct"] is None


def test_overdue_when_no_operation_for_a_long_time():
    assert B.summarize(B.parse(RAW), date(2027, 1, 20))["freshness"] == "OVERDUE"


def test_a_row_without_a_date_is_refused_and_too_few_rows_are_refused():
    with pytest.raises(ValueError):
        B.parse({"data": [{"operation_date": "soon"}, *RAW["data"][:5]]})
    with pytest.raises(ValueError):
        B.parse({"data": RAW["data"][:1]})
    with pytest.raises(ValueError):
        B.parse({"data": []})


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_failure_then_recovery_and_caching():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] == 1 else httpx.Response(200, json=RAW)

    svc = B.Buybacks(client=_client(handler))
    bad = asyncio.run(svc.overview(NOW))
    assert bad["available"] is False and "HTTP 503" in bad["reason"] and "latest" not in bad
    svc._cache = None
    good = asyncio.run(svc.overview(NOW))
    assert good["available"] and good["latest"]["date"] == "2026-11-05"
    asyncio.run(svc.overview(NOW))
    assert calls["n"] == 2


def test_demo_mode_invents_nothing():
    d = asyncio.run(B.Buybacks(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "Demo" in d["reason"] and "latest" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/buybacks")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True
