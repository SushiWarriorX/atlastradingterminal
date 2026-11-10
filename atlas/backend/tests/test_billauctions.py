"""Treasury bill auctions: parsed from a real response (1000 rows fetched 2026-11-10, trimmed to the newest 130); rate changes and mix checked against the raw rows; pending, stale, bad-data, failure and demo paths."""
import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import billauctions as B
from atlas_api.app import create_app

RAW = json.loads((Path(__file__).parent / "fixtures" / "treasury_bill_auctions.json").read_text())
TODAY = date(2026, 10, 21)                    # a day when the newest completed auctions (Oct 15) were current
NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)


def test_completed_and_pending_auctions_are_told_apart():
    done, pending = B.parse(RAW)
    assert len(done) == 127 and len(pending) == 3                                                          # three auctions on Oct 19 and 20 have an offering but no result yet
    assert {p["term"] for p in pending} == {"6-Week", "13-Week", "26-Week"} and max(r["auction_date"] for r in done) == date(2026, 10, 15)


def test_eight_week_row_matches_the_source():
    t = {x["term"]: x for x in B.summarize(*B.parse(RAW), TODAY)["terms"]}["8-Week"]
    assert t["auction_date"] == "2026-10-15" and t["investment_rate"] == 4.132 and t["discount_rate"] == 4.05 and t["bid_to_cover"] == 2.26
    assert t["offering_billions"] == 105.0 and t["accepted_billions"] == 112.1
    assert t["mix"] == {"dealers_pct": 47.4, "direct_pct": 5.7, "indirect_pct": 46.9, "sum_ok": True}      # 48.345 / 102.055, 5.818 / 102.055, 47.892 / 102.055


def test_rate_change_and_average_cover_equal_an_independent_calculation():
    rows = [r for r in RAW["data"] if r["security_term"] == "4-Week" and r["total_accepted"] not in (None, "null")]
    cur, prev = float(rows[0]["high_investment_rate"]), float(rows[1]["high_investment_rate"])
    avg = sum(float(r["bid_to_cover_ratio"]) for r in rows[1:5]) / 4
    t = {x["term"]: x for x in B.summarize(*B.parse(RAW), TODAY)["terms"]}["4-Week"]
    assert t["rate_change_bps"] == round((cur - prev) * 100, 1) == 2.0 and t["average_bid_to_cover"] == round(avg, 2) and t["compared_with"] == 4


def test_the_three_buyer_groups_add_up_to_the_competitive_awards_in_every_auction():
    done, _ = B.parse(RAW)
    assert all(r["mix"] and r["mix"]["sum_ok"] and abs(r["mix"]["dealers_pct"] + r["mix"]["direct_pct"] + r["mix"]["indirect_pct"] - 100) < 0.2 for r in done)


def test_all_seven_standard_terms_are_listed_in_order():
    assert [t["term"] for t in B.summarize(*B.parse(RAW), TODAY)["terms"]] == B.TERMS


def test_pending_results_are_listed_not_guessed():
    s = B.summarize(*B.parse(RAW), TODAY)
    assert [(p["term"], p["auction_date"]) for p in s["pending_results"]] == [("6-Week", "2026-10-20"), ("13-Week", "2026-10-19"), ("26-Week", "2026-10-19")]      # newest first, as the source lists them
    assert all(p["offering_billions"] is not None for p in s["pending_results"]) and s["freshness"] == "CURRENT"


def test_old_results_are_marked_overdue_with_the_real_gap():
    s = B.summarize(*B.parse(RAW), date(2026, 11, 10))                                                     # what the live source looked like on 2026-11-10
    assert s["freshness"] == "OVERDUE" and s["age_days"] == 26 and s["date"] == "2026-10-15"


def test_cash_management_bills_and_odd_terms_are_left_out():
    rows = [dict(r) for r in RAW["data"]]
    extra = dict(rows[3], security_term="27-Day", cash_management_bill_cmb="Yes")
    extra2 = dict(rows[3], cash_management_bill_cmb="Yes")
    done, _ = B.parse({"data": rows + [extra, extra2]})
    assert len(done) == 127


def test_a_completed_auction_with_a_missing_rate_is_refused():
    rows = [dict(r) for r in RAW["data"]]
    i = next(k for k, r in enumerate(rows) if r["total_accepted"] not in (None, "null"))
    rows[i]["high_investment_rate"] = "null"
    with pytest.raises(ValueError):
        B.parse({"data": rows})
    with pytest.raises(ValueError):
        B.parse({"data": []})
    with pytest.raises(ValueError):
        B.parse({"data": [dict(RAW["data"][0], auction_date="soon")]})


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_failure_then_recovery_and_caching():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(502) if calls["n"] == 1 else httpx.Response(200, json=RAW)

    svc = B.BillAuctions(client=_client(handler))
    bad = asyncio.run(svc.overview(NOW))
    assert bad["available"] is False and "HTTP 502" in bad["reason"] and "terms" not in bad
    svc._cache = None
    good = asyncio.run(svc.overview(NOW))
    assert good["available"] and len(good["terms"]) == 7
    asyncio.run(svc.overview(NOW))
    assert calls["n"] == 2


def test_demo_mode_invents_nothing():
    d = asyncio.run(B.BillAuctions(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "Demo" in d["reason"] and "terms" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/bills")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True
