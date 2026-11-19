"""Where US federal money goes (Monthly Treasury Statement Table 9): a real response (fetched 2026-11-12; newest month Sept 2026, an older month is ignored); hand-worked numbers; the purposes adding up to total outlays and the receipts lines to total
receipts as self-checks, the receipts total agreeing with the receipts panel's fixture (Table 4); tampered, missing, stale, failure and demo paths."""
import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from atlas_api import outlays as O
from atlas_api import receipts as R
from atlas_api.app import create_app

FX = Path(__file__).parent / "fixtures"
RAW = json.loads((FX / "treasury_outlays_by_function.json").read_text())
TODAY = date(2026, 11, 12)
NOW = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)


def _s(raw=None, today=TODAY):
    newest, t = O.parse(raw or RAW)
    return O.summarize(newest, t, today)


def _f(s, name):
    return next(f for f in s["functions"] if f["name"] == name)


def test_newest_month_used_and_all_nineteen_purposes_present():
    newest, t = O.parse(RAW)
    s = _s()
    assert newest == date(2026, 9, 30) and s["fiscal_year"] == 2026 and s["months_in_year"] == 12 and s["age_days"] == 43 and s["freshness"] == "CURRENT"
    assert {n for n, _ in t["functions"]} == set(O.WHAT) and len(s["functions"]) == 19


def test_totals_receipts_and_deficit_by_hand():
    s = _s()
    assert (s["outlays"]["month_billions"], s["outlays"]["year_so_far_billions"], s["outlays"]["same_point_last_year_billions"]) == (584.8, 7395.8, 7010.0)
    assert s["outlays"]["change_vs_last_year_pct"] == round((7395799983313.23 / 7009985661849.26 - 1) * 100, 1) == 5.5
    assert (s["receipts"]["year_so_far_billions"], s["receipts"]["same_point_last_year_billions"], s["receipts"]["change_vs_last_year_pct"]) == (5403.3, 5234.6, 3.2)
    d = s["deficit"]
    assert d["year_so_far_billions"] == round((7395799983313.23 - 5403326758960.81) / 1e9, 1) == 1992.5                      # outlays minus receipts
    assert d["same_point_last_year_billions"] == round((7009985661849.26 - 5234616472030.91) / 1e9, 1) == 1775.4
    assert d["change_vs_last_year_pct"] == round(((7395799983313.23 - 5403326758960.81) / (7009985661849.26 - 5234616472030.91) - 1) * 100, 1) == 12.2
    assert d["month_billions"] == round((584774866340.26 - 557874519238.24) / 1e9, 1) == 26.9


def test_purposes_by_hand_and_sorted_by_size():
    s = _s()
    assert [f["name"] for f in s["functions"]][:4] == ["Social Security", "Medicare", "Net Interest", "Health"]                   # 1,667.1 > 1,072.6 > 1,051.8 > 1,025.6
    ni, ss, nd, inc = _f(s, "Net Interest"), _f(s, "Social Security"), _f(s, "National Defense"), _f(s, "Income Security")
    assert ni["year_so_far_billions"] == 1051.8 and ni["share_of_outlays_pct"] == round(1051753969311.11 / 7395799983313.23 * 100, 1) == 14.2
    assert ni["change_vs_last_year_pct"] == round((1051753969311.11 / 970358886994.32 - 1) * 100, 1) == 8.4
    assert ss["year_so_far_billions"] == 1667.1 and ss["change_vs_last_year_pct"] == round((1667097265194.46 / 1580685783033.83 - 1) * 100, 1) == 5.5
    assert nd["year_so_far_billions"] == 965.2 and nd["change_vs_last_year_pct"] == 5.3
    assert inc["change_vs_last_year_pct"] == round((694224470394.36 / 701583598129.63 - 1) * 100, 1) == -1.0
    assert s["functions"][-1]["year_so_far_billions"] < 0 and s["functions"][-1]["change_vs_last_year_pct"] is None           # a negative line is shown, and no percentage is made up for it


def test_purposes_add_up_to_total_outlays_and_receipts_lines_to_total_receipts_to_the_cent():
    _, t = O.parse(RAW)
    for k in ("m", "y", "p"):
        assert abs(sum(v[k] for _, v in t["functions"]) - t["outlays_total"][k]) < 0.01
        assert abs(sum(v[k] for v in t["receipts_leaves"]) - t["receipts_total"][k]) < 0.01                                # computed here independently of the module
    assert O.checks(t)["ok"]


def test_the_receipts_total_agrees_with_the_receipts_panels_own_table_4_figure():
    t4 = json.loads((FX / "treasury_receipts_by_source.json").read_text())
    _, lines = R.parse(t4)
    _, t9 = O.parse(RAW)
    for k in ("m", "y", "p"):
        assert abs(lines[R.TOTAL][k] - t9["receipts_total"][k]) < 0.01                                                    # two different tables, same number


def test_a_tampered_purpose_or_receipts_line_is_refused_not_shown():
    bad = json.loads(json.dumps(RAW))
    for r in bad["data"]:
        if r["classification_desc"] == "National Defense" and r["record_date"] == "2026-09-30":
            r["current_fytd_rcpt_outly_amt"] = str(float(r["current_fytd_rcpt_outly_amt"]) + 2_000_000_000)
    try:
        _s(bad)
        assert False, "should refuse"
    except ValueError as e:
        assert "did not add up" in str(e) and "purposes" in str(e) and "year so far" in str(e)
    bad2 = json.loads(json.dumps(RAW))
    for r in bad2["data"]:
        if r["classification_desc"] == "Customs Duties" and r["record_date"] == "2026-09-30":
            r["current_month_rcpt_outly_amt"] = str(float(r["current_month_rcpt_outly_amt"]) + 10_000_000)
    try:
        _s(bad2)
        assert False, "should refuse"
    except ValueError as e:
        assert "receipts lines" in str(e)


def test_missing_lines_unreadable_amounts_and_empty_responses_are_refused():
    miss = json.loads(json.dumps(RAW))
    miss["data"] = [r for r in miss["data"] if r["classification_desc"] != "Medicare"]
    unread = json.loads(json.dumps(RAW))
    for r in unread["data"]:
        if r["classification_desc"] == "Net Interest" and r["record_date"] == "2026-09-30":
            r["current_fytd_rcpt_outly_amt"] = "null"
    nohdr = json.loads(json.dumps(RAW))
    nohdr["data"] = [r for r in nohdr["data"] if r["classification_desc"] != "Net Outlays"]
    for payload in (miss, unread, nohdr, {"data": []}):
        try:
            O.parse(payload)
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

    svc = O.Outlays(client=_client(handler))
    bad = asyncio.run(svc.overview(NOW))
    assert bad["available"] is False and "HTTP 503" in bad["reason"] and "functions" not in bad
    svc._cache = None
    good = asyncio.run(svc.overview(NOW))
    assert good["available"] and good["deficit"]["year_so_far_billions"] == 1992.5 and "not a market signal or a forecast" in good["note"]
    n = calls["n"]
    asyncio.run(svc.overview(NOW))
    assert calls["n"] == n


def test_demo_mode_invents_nothing():
    d = asyncio.run(O.Outlays(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "Demo" in d["reason"] and "functions" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/outlays")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True
