"""Interest expense on debt held by the public: parsed from a real response (1000 rows fetched 2026-11-09, trimmed to 14 months); buckets add up to the total; own arithmetic checked against the
source's own year-to-date figure; failure, bad data, stale and demo paths."""
import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import intexp as X
from atlas_api.app import create_app

RAW = json.loads((Path(__file__).parent / "fixtures" / "treasury_interest_expense.json").read_text())
NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)


def test_only_debt_held_by_the_public_is_counted_and_months_are_grouped():
    m = X.parse(RAW)
    assert max(m) == date(2026, 10, 31) and len(m) == 14
    assert all(v["rows"] == 29 for v in m.values())                                                      # 29 public-issue lines every month; the 8 government-account lines are left out
    assert abs(m[date(2026, 10, 31)]["total"] - 98616179670.83) < 1                                      # the sum of that month's 29 rows, added by hand from the source


def test_every_row_lands_in_exactly_one_bucket_so_the_buckets_add_up_to_the_total():
    for d, v in X.parse(RAW).items():
        assert abs(sum(v["buckets"].values()) - v["total"]) < 1, d


def test_bucket_rules_keep_look_alike_securities_apart():
    f = X.bucket
    assert f("AMORTIZED DISCOUNT", "Treasury Bills") == "bills" and f("ACCRUED INTEREST EXPENSE", "Treasury Notes") == "notes" and f("AMORTIZED PREMIUM", "Treasury Bonds") == "bonds"
    assert f("ACCRUED INTEREST EXPENSE", "Int. Expense Inflation Compensation") == "tips"
    assert f("AMORTIZED DISCOUNT", "Treasury Inflation Protected Securities") == "tips"               # a TIPS row must not fall into "bonds" or "notes"
    assert f("ACCRUED INTEREST EXPENSE", "Treasury Floating Rate Notes") == "frn"                       # nor a floating rate note into "notes"
    assert f("AMORTIZED DISCOUNT", "Domestic Series Bonds") == "other" and f("AMORTIZED DISCOUNT", "Foreign Series Notes & Bonds") == "other"   # series that only look like bonds
    assert f("SAVINGS BONDS", "Series I") == "savings"


def test_october_notes_line_is_the_sum_of_its_three_source_rows():
    notes = {(r["expense_group_desc"], r["expense_type_desc"]): float(r["month_expense_amt"]) for r in RAW["data"] if r["record_date"] == "2026-10-31" and r["expense_catg_desc"] == X.PUBLIC and r["expense_type_desc"] == "Treasury Notes"}
    assert len(notes) == 3 and abs(sum(notes.values()) - 46_590_000_000) < 5e6                          # 45.766 accrued + 0.962 discount - 0.139 premium, billions
    assert abs(X.parse(RAW)[date(2026, 10, 31)]["buckets"]["notes"] - sum(notes.values())) < 1


def test_summary_compares_with_the_same_month_a_year_earlier_and_checks_itself():
    s = X.summarize(X.parse(RAW), NOW.date())
    assert s["available"] and s["fiscal_year"] == 2027 and s["freshness"] == "CURRENT" and s["age_days"] == 9
    assert s["month_total_billions"] == 98.6 and s["year_ago_month_total_billions"] == 87.8 and s["month_change_pct"] == 12.3      # 98.616 / 87.836 - 1
    assert s["ytd_months"] == 1 and s["ytd_total_billions"] == 98.6 and s["ytd_check"] == {"ours_billions": 98.6, "source_billions": 98.6, "match": True}
    assert [b["key"] for b in s["breakdown"]] == [k for k, _ in X.BUCKETS] and abs(sum(b["share_pct"] for b in s["breakdown"]) - 100) < 0.5
    assert s["history"][-1] == {"date": "2026-10-31", "total_billions": 98.6} and len(s["history"]) == 14


def test_a_full_fiscal_year_matches_the_sources_own_year_to_date_figure():
    older = {"data": [r for r in RAW["data"] if r["record_date"] <= "2026-09-30"]}
    s = X.summarize(X.parse(older), date(2026, 10, 15))
    assert s["fiscal_year"] == 2026 and s["ytd_months"] == 12 and s["ytd_total_billions"] == 1068.5
    assert s["ytd_check"] == {"ours_billions": 1068.5, "source_billions": 1068.5, "match": True}          # twelve monthly totals add up to the published year-to-date total


def test_a_partial_fiscal_year_in_the_response_gives_no_check_instead_of_a_wrong_one():
    short = {"data": [r for r in RAW["data"] if r["record_date"] in ("2026-09-30", "2026-08-31", "2025-09-30", "2025-08-31")]}
    s = X.summarize(X.parse(short), date(2026, 10, 15))
    assert s["ytd_months"] == 12 and s["ytd_check"] is None                                              # only two of the twelve months were fetched


def test_a_missing_year_ago_month_gives_no_comparison():
    s = X.summarize(X.parse({"data": [r for r in RAW["data"] if r["record_date"] >= "2026-08-31"]}), NOW.date())
    assert s["year_ago_month_total_billions"] is None and s["month_change_pct"] is None and s["year_ago_ytd_billions"] is None


def test_old_data_is_marked_overdue():
    assert X.summarize(X.parse(RAW), date(2026, 12, 31))["freshness"] == "OVERDUE"


@pytest.mark.parametrize("bad", ["null", "", "n/a"])
def test_unreadable_amounts_are_refused_not_skipped(bad):
    rows = [dict(r) for r in RAW["data"]]
    rows[0]["month_expense_amt"] = bad
    assert rows[0]["expense_catg_desc"] == X.PUBLIC
    with pytest.raises(ValueError):
        X.parse({"data": rows})


def test_too_little_data_is_refused():
    with pytest.raises(ValueError):
        X.parse({"data": [r for r in RAW["data"] if r["record_date"] == "2026-10-31"]})
    with pytest.raises(ValueError):
        X.parse({"data": []})


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_failure_then_recovery_and_caching():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(500) if calls["n"] == 1 else httpx.Response(200, json=RAW)

    svc = X.InterestExpense(client=_client(handler))
    bad = asyncio.run(svc.overview(NOW))
    assert bad["available"] is False and "HTTP 500" in bad["reason"] and "month_total_billions" not in bad                 # says so, shows nothing
    svc._cache = None
    good = asyncio.run(svc.overview(NOW))
    assert good["available"] and good["month_total_billions"] == 98.6
    asyncio.run(svc.overview(NOW))
    assert calls["n"] == 2                                                                                  # the good answer is cached


def test_demo_mode_invents_nothing():
    d = asyncio.run(X.InterestExpense(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "Demo" in d["reason"] and "month_total_billions" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/interest")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True
