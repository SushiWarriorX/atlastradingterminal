"""CFTC Traders in Financial Futures for S&P 500, Nasdaq-100, 2-year and 10-year Treasury and dollar index futures: real responses (fetched 2026-11-11, 30 weeks each); hand-worked numbers; the report's own
totals as a self-check (groups add up to the reportable total, reportable plus small traders equal open interest, reported change in open interest equals the difference of weeks); failure, stale, demo."""
import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from atlas_api import cftc_futures as C
from atlas_api.app import create_app

RAW = json.loads((Path(__file__).parent / "fixtures" / "cftc_tff_macro.json").read_text())
TODAY = date(2026, 11, 10)
NOW = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)


def _s(raw=None, today=TODAY):
    raw = raw or RAW
    return C.summarize({k: C.parse(v) for k, v in raw.items()}, today)


def _contract(s, code):
    return next(x for x in s["contracts"] if x["code"] == code)


def test_sp500_latest_week_matches_the_report_by_hand():
    s = _s()
    sp = _contract(s, "13874A")
    g = {x["key"]: x for x in sp["groups"]}
    assert s["date"] == "2026-11-03" and sp["open_interest"] == 1986532 and sp["open_interest_change"] == 30821
    assert g["lev_money"]["net"] == 125269 - 497587 == -372318                                       # leveraged funds: 125,269 long, 497,587 short
    assert g["asset_mgr"]["net"] == 1111721 - 183137 == 928584 and g["dealer"]["net"] == 182419 - 870993 == -688574 and g["other_rept"]["net"] == 70819 - 62730 == 8089
    assert g["lev_money"]["net_change"] == -372318 - (102079 - 502683) == 28286                      # the week before: 102,079 long, 502,683 short
    assert g["lev_money"]["long_pct_oi"] == 6.3 and g["lev_money"]["short_pct_oi"] == 25.0           # 125,269 / 1,986,532 and 497,587 / 1,986,532


def test_all_five_contracts_pass_the_report_own_totals_over_26_weeks():
    s = _s()
    assert [x["code"] for x in s["contracts"]] == ["13874A", "209742", "042601", "043602", "098662"]
    for x in s["contracts"]:
        assert x["available"] and x["checks"] == {"weeks_checked": 26, "groups_add_up": True, "oi_change_pairs": 25, "oi_change_mismatches": 0, "ok": True}


def test_rank_equals_an_independent_calculation():
    sp = _contract(_s(), "13874A")
    nets = [int(r["lev_money_positions_long"]) - int(r["lev_money_positions_short"]) for r in RAW["13874A"]]      # all 30 weeks, newest first
    expected = round(sum(1 for n in nets if n <= nets[0]) / len(nets) * 100)
    assert {x["key"]: x for x in sp["groups"]}["lev_money"]["net_rank_1y"] == expected


def test_a_week_that_does_not_add_up_removes_only_that_contract():
    bad = json.loads(json.dumps(RAW))
    bad["043602"][0]["tot_rept_positions_long_all"] = str(int(bad["043602"][0]["tot_rept_positions_long_all"]) + 1)       # one contract too many
    s = _s(bad)
    t = _contract(s, "043602")
    assert t["available"] is False and "did not add up" in t["reason"] and "groups" not in t
    assert _contract(s, "13874A")["available"] and s["available"]


def test_a_wrong_reported_change_in_open_interest_is_caught():
    bad = json.loads(json.dumps(RAW))
    bad["098662"][3]["change_in_open_interest_all"] = str(int(bad["098662"][3]["change_in_open_interest_all"]) + 5)
    d = _contract(_s(bad), "098662")
    assert d["available"] is False and d["checks"]["oi_change_mismatches"] == 1


def test_stale_data_is_marked_overdue_with_the_real_age():
    s = _s(today=date(2026, 12, 1))
    assert s["freshness"] == "OVERDUE" and s["age_days"] == 28
    assert _s()["freshness"] == "CURRENT" and _s()["age_days"] == 7


def test_missing_contract_and_unreadable_rows():
    part = {k: v for k, v in RAW.items() if k != "042601"}
    s = _s(part)
    assert _contract(s, "042601")["available"] is False and "no readable reports" in _contract(s, "042601")["reason"] and s["available"]
    try:
        C.parse([{"report_date_as_yyyy_mm_dd": "not a date"}])
        assert False, "should refuse"
    except ValueError:
        pass
    assert C.summarize({}, TODAY)["available"] is False


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(req):
    code = str(req.url.params["$where"]).split("'")[1]
    return httpx.Response(200, json=RAW[code])


def test_overview_fetches_all_five_and_caches():
    n = {"n": 0}

    def handler(req):
        n["n"] += 1
        return _handler(req)

    svc = C.CftcFutures(client=_client(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and len(r["contracts"]) == 5 and "not a market signal or a forecast" in r["note"] and n["n"] == 5
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 5


def test_failure_says_so_and_shows_no_numbers():
    svc = C.CftcFutures(client=_client(lambda req: httpx.Response(503)))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] is False and "could not be read" in r["reason"] and all(not x.get("groups") for x in r["contracts"])


def test_one_contract_failing_leaves_the_others():
    def handler(req):
        return httpx.Response(500) if "'209742'" in str(req.url.params["$where"]) else _handler(req)
    r = asyncio.run(C.CftcFutures(client=_client(handler)).overview(NOW))
    assert r["available"] and [x["available"] for x in r["contracts"]] == [True, False, True, True, True]


def test_demo_mode_invents_nothing():
    d = asyncio.run(C.CftcFutures(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "Demo" in d["reason"] and "contracts" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/futures-positioning")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True


# ---- the commodity family (Disaggregated report): gold, crude oil, copper, natural gas; real responses fetched 2026-11-11, 30 weeks each
RAWC = json.loads((Path(__file__).parent / "fixtures" / "cftc_disagg_commodities.json").read_text())


def _sc(raw=None, today=TODAY):
    return C.summarize({k: C.parse(v, C.COMMODITY.groups) for k, v in (raw or RAWC).items()}, today, C.COMMODITY)


def test_commodity_gold_latest_week_matches_the_report_by_hand():
    s = _sc()
    g = {x["key"]: x for x in _contract(s, "088691")["groups"]}
    gold = _contract(s, "088691")
    assert [x["code"] for x in s["contracts"]] == ["088691", "067651", "085692", "023651"] and s["date"] == "2026-11-03" and "Disaggregated" in s["source"]
    assert gold["open_interest"] == 399169 and gold["open_interest_change"] == 2359
    assert g["m_money"]["net"] == 122283 - 18669 == 103614 and g["m_money"]["net_change"] == 103614 - (122508 - 16946) == -1948        # managed money, then the week before
    assert g["prod_merc"]["net"] == 18914 - 27826 == -8912 and g["swap"]["net"] == 19301 - 215291 == -195990
    assert g["prod_merc"]["spread"] == 0                                                                                                # producers have no spreading column: counted as zero, not missing


def test_commodity_totals_reconcile_for_all_four_contracts_over_26_weeks():
    for x in _sc()["contracts"]:
        assert x["available"] and x["checks"] == {"weeks_checked": 26, "groups_add_up": True, "oi_change_pairs": 25, "oi_change_mismatches": 0, "ok": True}


def test_commodity_week_that_does_not_add_up_removes_only_that_contract():
    bad = json.loads(json.dumps(RAWC))
    bad["067651"][0]["swap_positions_long_all"] = str(int(bad["067651"][0]["swap_positions_long_all"]) + 1)
    s = _sc(bad)
    assert _contract(s, "067651")["available"] is False and "did not add up" in _contract(s, "067651")["reason"] and _contract(s, "088691")["available"]


def test_commodity_overview_uses_its_own_dataset_and_wording():
    seen = []

    def handler(req):
        seen.append(str(req.url).split("?")[0])
        code = str(req.url.params["$where"]).split("'")[1]
        return httpx.Response(200, json=RAWC[code])

    r = asyncio.run(C.CftcCommodities(client=_client(handler)).overview(NOW))
    assert r["available"] and len(r["contracts"]) == 4 and set(seen) == {"https://publicreporting.cftc.gov/resource/72hh-3qpy.json"} and "producers and merchants" in r["note"]
    assert "not a market signal or a forecast" in r["note"]
    d = asyncio.run(C.CftcCommodities(demo=True).overview(NOW))
    assert d["available"] is False and "Demo" in d["reason"] and "contracts" not in d


def test_commodity_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/commodity-positioning")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True
