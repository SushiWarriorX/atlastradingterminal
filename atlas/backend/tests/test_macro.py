"""Macro dashboard: calculations, exact date matching, freshness by publication schedule, partial failure, demo, no order language."""
import asyncio
import re
import time
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import macro as M
from atlas_api.app import create_app
from atlas_api.models import ProviderUnavailable
from atlas_api.providers.fred import FredProvider
from atlas_api.providers.http import Http

TODAY = date(2026, 11, 20)
D = date


def run(c):
    return asyncio.run(c)


def days(start, values, step=1):
    return [(start + timedelta(days=i * step), v) for i, v in enumerate(values)]


def months(start, values):
    out, y, m = [], start.year, start.month
    for v in values:
        out.append((D(y, m, 1), v))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


# --- calculations ----------------------------------------------------------------------------------------------------------------------
def test_basis_point_and_percent_math():
    assert M.bps(4.25, 4.00) == pytest.approx(25.0) and M.pct(110, 100) == pytest.approx(10.0) and M.pct(1, 0) is None


def test_spread_uses_only_dates_present_in_both_series():
    a = [(D(2026, 11, 17), 4.5), (D(2026, 11, 18), 4.6), (D(2026, 11, 19), 4.7)]
    b = [(D(2026, 11, 17), 4.0), (D(2026, 11, 19), 4.1)]                      # 18th missing in b
    assert M.spread(a, b) == [(D(2026, 11, 17), pytest.approx(0.5)), (D(2026, 11, 19), pytest.approx(0.6))]


def test_curve_fact_does_not_mix_dates_and_flags_inversion():
    y10 = days(D(2026, 10, 1), [4.0 + 0.01 * i for i in range(50)])                   # ends 2026-11-19
    y2 = days(D(2026, 10, 1), [4.2] * 49)                                         # ends a day earlier
    f = M.curve_fact(y10, y2, TODAY)
    assert f["obs_date"] == "2026-11-18" and "latest date present in both" in f["note"]
    assert f["value"] == pytest.approx((4.0 + 0.01 * 48 - 4.2) * 100) and f["inverted"] == (f["value"] < 0)
    assert f["changes"][0]["unit"] == "bps" and f["changes"][0]["ref_date"] == "2026-11-17"


def test_curve_unavailable_without_common_dates():
    f = M.curve_fact([(D(2026, 11, 1), 4.0)], [(D(2026, 11, 2), 3.0)], TODAY)
    assert "error" in f and "value" not in f


def test_yield_change_in_bps_with_reference_dates():
    pts = days(D(2026, 10, 1), [4.00] * 40 + [4.30])                              # last = Nov 10
    f = M.yield_fact("DGS10", "us10y", pts, TODAY)
    assert f["value"] == 4.30 and f["unit"] == "%"
    assert f["changes"][0]["value"] == pytest.approx(30.0) and f["changes"][1]["ref_date"] == "2026-10-11"


def test_cpi_year_over_year_uses_the_same_calendar_month():
    idx = months(D(2025, 1, 1), [100.0 + i for i in range(17)])                      # Jan 2025 .. May 2026
    f = M.cpi_fact("CPIAUCSL", "cpi", idx, TODAY)
    assert f["obs_date"] == "2026-05-01" and f["value"] == pytest.approx((116.0 / 104.0 - 1) * 100)
    assert f["changes"][0]["unit"] == "percentage points" and f["changes"][0]["value"] == pytest.approx((116 / 104 - 115 / 103) * 100)
    assert f["unit"] == "% year-over-year" and f["index_level"] == 116.0


def test_cpi_missing_month_is_not_approximated():
    idx = [x for x in months(D(2025, 1, 1), [100.0 + i for i in range(17)]) if x[0] != D(2025, 5, 1)]       # May 2025 missing
    ys = dict(M.yoy(idx))
    assert D(2026, 5, 1) not in ys and D(2026, 4, 1) in ys                                  # no neighbouring-month stand-in
    f = M.cpi_fact("CPIAUCSL", "cpi", idx, TODAY)
    assert f["obs_date"] == "2026-04-01"
    short = M.cpi_fact("CPIAUCSL", "cpi", months(D(2026, 1, 1), [100, 101, 102]), TODAY)
    assert "error" in short


def test_cpi_change_omitted_when_previous_month_is_missing():
    idx = [x for x in months(D(2025, 1, 1), [100.0 + i for i in range(17)]) if x[0] != D(2025, 4, 1)]       # Apr 2025 missing -> Apr 2026 yoy missing
    f = M.cpi_fact("CPIAUCSL", "cpi", idx, TODAY)
    assert f["obs_date"] == "2026-05-01" and f["changes"] == [] and "missing" in f["note"]


def test_fed_range_and_unchanged_run():
    lo = days(D(2026, 1, 1), [3.50] * 100 + [3.75] * 200)
    hi = days(D(2026, 1, 1), [3.75] * 100 + [4.00] * 200)
    f = M.fed_fact(lo, hi, D(2026, 10, 27))
    assert (f["lower"], f["upper"]) == (3.75, 4.00) and f["unchanged_since"] == "2026-04-11" and f["unchanged_since_is_lower_bound"] is False
    flat = M.fed_fact(days(D(2026, 1, 1), [3.5] * 5), days(D(2026, 1, 1), [3.75] * 5), D(2026, 1, 6))
    assert flat["unchanged_since_is_lower_bound"] is True


def test_dollar_percent_change_and_not_dxy_label():
    pts = days(D(2026, 10, 1), [120.0] * 40 + [123.6])
    f = M.usd_fact(pts, TODAY)
    assert "NOT DXY" in f["label"] and "NOT the ICE DXY" in f["note"] and f["changes"][1]["value"] == pytest.approx(3.0) and f["changes"][1]["unit"] == "%"


# --- freshness by publication schedule ----------------------------------------------------------------------------------------------------
def test_unchanged_fed_policy_is_current_not_stale():
    fr = M.freshness("DFEDTARU", TODAY - timedelta(days=1), TODAY)
    assert fr["state"] == "CURRENT" and "not stale" in fr["rule"]
    assert M.freshness("DFEDTARU", TODAY - timedelta(days=9), TODAY)["state"] == "OVERDUE"          # the daily series itself stopped updating


def test_monthly_cpi_six_weeks_old_is_current_but_four_months_is_overdue():
    assert M.freshness("CPIAUCSL", TODAY - timedelta(days=50), TODAY)["state"] == "CURRENT"
    assert M.freshness("CPIAUCSL", TODAY - timedelta(days=120), TODAY)["state"] == "OVERDUE"


def test_daily_yields_and_weekly_dollar_have_their_own_limits():
    assert M.freshness("DGS10", TODAY - timedelta(days=4), TODAY)["state"] == "CURRENT"                  # long weekend
    assert M.freshness("DGS10", TODAY - timedelta(days=8), TODAY)["state"] == "OVERDUE"
    assert M.freshness("DTWEXBGS", TODAY - timedelta(days=10), TODAY)["state"] == "CURRENT"              # weekly publication
    assert M.freshness("DTWEXBGS", TODAY - timedelta(days=20), TODAY)["state"] == "OVERDUE"


# --- interpretations: conditional, tied to facts, no order language ---------------------------------------------------------------------------
ORDER = re.compile(r"\b(buy|sell|short(?!-)|go long|enter|exit|stop[- ]loss|take[- ]profit|price target|you should|will (rise|fall|crash|rally))\b", re.I)


def facts_for(**over):
    base = {
        "curve": {"id": "curve", "value": -35.0, "changes": []}, "us10y": {"id": "us10y", "changes": [{"label": "vs ~1 month earlier", "value": 40.0}]},
        "us2y": {"id": "us2y", "changes": [{"label": "vs ~1 month earlier", "value": -30.0}]}, "core_cpi": {"id": "core_cpi", "value": 3.4},
        "fed": {"id": "fed", "lower": 3.75, "upper": 4.0}, "usd": {"id": "usd", "changes": [{"label": "vs ~1 month earlier", "value": 2.5}]},
    }
    base.update(over)
    return base


def test_every_interpretation_has_facts_caveat_and_no_order_language():
    out = M.interpretations(facts_for())
    assert {i["id"] for i in out} >= {"curve", "us10y_move", "us2y_move", "inflation", "fed", "usd"}
    for i in out:
        assert i["based_on"] and i["caveat"] and not ORDER.search(i["text"] + " " + i["caveat"]), i


def test_interpretations_follow_the_conditions_and_skip_missing_facts():
    assert "BELOW" in next(i for i in M.interpretations(facts_for()) if i["id"] == "curve")["text"]
    assert "positively sloped" in next(i for i in M.interpretations(facts_for(curve={"id": "curve", "value": 80.0})) if i["id"] == "curve")["text"]
    quiet = M.interpretations(facts_for(us10y={"id": "us10y", "changes": [{"label": "vs ~1 month earlier", "value": 5.0}]}, usd={"id": "usd", "changes": []}))
    assert not any(i["id"] in ("us10y_move", "usd") for i in quiet)
    assert M.interpretations({}) == []
    assert not any("score" in str(i).lower() for i in M.interpretations(facts_for()))


# --- service: partial failure, caching, demo, API -------------------------------------------------------------------------------------------------
def csv_for(pts):
    return "observation_date,X\n" + "\n".join(f"{d.isoformat()},{v}" for d, v in pts)


def fred_with(handler, calls=None):
    def h(req):
        if calls is not None:
            calls.append(dict(req.url.params))
        return handler(req)
    return FredProvider(Http("https://fred.test", "fred", min_interval=0, retries=1, client=httpx.AsyncClient(transport=httpx.MockTransport(h), base_url="https://fred.test")))


def good(req):
    sid = req.url.params["id"]
    today = datetime.now(timezone.utc).date()
    if sid in ("CPIAUCSL", "CPILFESL"):
        first = (today.replace(day=1) - timedelta(days=60)).replace(day=1)
        start = D(first.year - 1, first.month, 1)
        return httpx.Response(200, text=csv_for(months(start, [100.0 + i * 0.3 for i in range(14)])))
    base = {"DGS10": 4.2, "DGS2": 4.5, "DFEDTARL": 3.75, "DFEDTARU": 4.0, "DTWEXBGS": 120.0}[sid]
    return httpx.Response(200, text=csv_for(days(today - timedelta(days=60), [base] * 59)))


def test_overview_has_all_seven_series_and_requests_a_start_date():
    calls: list[dict] = []
    out = run(M.MacroService(fred_with(good, calls)).overview())
    assert {f["id"] for f in out["facts"]} == {"us10y", "us2y", "curve", "cpi", "core_cpi", "fed", "usd"} and all("error" not in f for f in out["facts"])
    assert {c["id"] for c in calls} == set(M.SERIES) and all("cosd" in c for c in calls)
    assert out["interpretations"] and "not predictions" in out["interpretation_note"]


def test_one_failing_series_does_not_hide_the_others():
    def h(req):
        return httpx.Response(500) if req.url.params["id"] == "CPILFESL" else good(req)
    out = run(M.MacroService(fred_with(h)).overview())
    by = {f["id"]: f for f in out["facts"]}
    assert "error" in by["core_cpi"] and "CPILFESL" in by["core_cpi"]["error"] and "value" in by["cpi"] and "value" in by["curve"]
    assert not any(i["id"] == "inflation" for i in out["interpretations"])


def test_curve_unavailable_when_one_yield_series_fails_but_the_other_still_shows():
    def h(req):
        return httpx.Response(404) if req.url.params["id"] == "DGS2" else good(req)
    by = {f["id"]: f for f in run(M.MacroService(fred_with(h)).overview())["facts"]}
    assert "error" in by["curve"] and "error" in by["us2y"] and "value" in by["us10y"]


def test_success_is_cached_and_a_partial_failure_is_cached_only_briefly():
    calls: list[dict] = []
    svc = M.MacroService(fred_with(good, calls))
    run(svc.overview())
    n = len(calls)
    run(svc.overview())
    assert len(calls) == n and svc._cache[0] - time.monotonic() > M.FAIL_CACHE_SECONDS            # full success: long cache
    def h(req):
        calls.append(dict(req.url.params))
        return httpx.Response(500) if req.url.params["id"] == "CPILFESL" else good(req)
    part = M.MacroService(fred_with(h, None))
    first = run(part.overview())
    m = len(calls)
    second = run(part.overview())
    assert len(calls) == m and any("error" in f for f in second["facts"]) and second is first          # short cache: no refetch, error still visible
    assert part._cache[0] - time.monotonic() <= M.FAIL_CACHE_SECONDS
    part._cache = (0.0, part._cache[1])                                                                # the short cache expires
    run(part.overview())
    assert len(calls) > m


def test_demo_mode_returns_an_empty_labelled_dashboard_without_network():
    class Boom:
        async def series(self, *a, **k):
            raise AssertionError("no network in demo")
    out = run(M.MacroService(Boom(), demo=True).overview())
    assert out["demo"] and out["facts"] == [] and "Demo mode" in out["notice"]


def test_api_route_and_existing_fred_adapter_unchanged(tmp_path):
    fred = fred_with(good)
    with TestClient(create_app(db_path=str(tmp_path / "m.db"), demo=False, providers={"fred": fred}, alert_loop=False, news_loop=False)) as c:
        d = c.get("/api/macro/overview").json()["data"]
        assert len(d["facts"]) == 7
    with TestClient(create_app(db_path=str(tmp_path / "m2.db"), demo=True, alert_loop=False)) as c:
        assert c.get("/api/macro/overview").json()["data"]["demo"] is True
    with TestClient(create_app(db_path=str(tmp_path / "m3.db"), demo=False, providers={}, alert_loop=False)) as c:
        assert c.get("/api/macro/overview").status_code == 503


def test_fred_quote_path_without_start_date_is_unchanged():
    calls: list[dict] = []
    p = fred_with(lambda r: httpx.Response(200, text=csv_for(days(D(2026, 11, 1), [4.0, 4.1]))), calls)
    from atlas_api import instruments as I
    q = run(p.quote(I.get("MACRO:FRED:DGS10")))
    assert q.price == 4.1 and "cosd" not in calls[0]
