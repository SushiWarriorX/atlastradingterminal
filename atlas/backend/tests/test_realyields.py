"""US Treasury real yields (TIPS) and breakeven inflation: parsed from real responses (fetched 2026-11-11: Nov 2026, Oct 2026, Nov 2025 for both the regular and the real curve); hand-worked breakevens and changes;
same-day alignment, range guard, missing maturity, reference days on weekends, failure, stale and demo paths."""
import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from atlas_api import realyields as R
from atlas_api.app import create_app

F = json.loads((Path(__file__).parent / "fixtures" / "treasury_real_yields.json").read_text())
TODAY = date(2026, 11, 11)
NOW = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)


def _data():
    nom, real = {}, {}
    for ym in ("202611", "202610", "202511"):
        nom.update(R.parse(F["nominal_" + ym], "BC_"))
        real.update(R.parse(F["real_" + ym], "TC_"))
    return nom, real


def _row(s, t):
    return next(x for x in s["rows"] if x["tenor"] == t)


def test_latest_day_breakeven_is_nominal_minus_real_by_hand():
    nom, real = _data()
    s = R.summarize(nom, real, TODAY)
    assert s["date"] == "2026-11-10" and s["freshness"] == "CURRENT" and s["age_days"] == 1
    assert [x["tenor"] for x in s["rows"]] == ["5Y", "7Y", "10Y", "20Y", "30Y"]
    r5, r10, r30 = _row(s, "5Y"), _row(s, "10Y"), _row(s, "30Y")
    assert (r5["nominal_pct"], r5["real_pct"], r5["breakeven_pct"]) == (4.81, 2.56, 2.25)       # 4.81 - 2.56
    assert (r10["nominal_pct"], r10["real_pct"], r10["breakeven_pct"]) == (4.98, 2.78, 2.20)    # 4.98 - 2.78
    assert r30["breakeven_pct"] == 2.18                                                          # 5.35 - 3.17


def test_changes_against_a_month_and_a_year_earlier_by_hand():
    nom, real = _data()
    s = R.summarize(nom, real, TODAY)
    # a month back from Nov 10 is Oct 10, a Saturday: the latest earlier day, Fri Oct 9, is used. Oct 9: 10Y 5.24 - 2.91 = 2.33; 5Y 5.02 - 2.68 = 2.34; 30Y 5.60 - 3.32 = 2.28
    assert s["month_ago_date"] == "2026-10-09" and s["year_ago_date"] == "2025-11-10"
    assert _row(s, "10Y")["breakeven_change_1m_bp"] == -13 and _row(s, "5Y")["breakeven_change_1m_bp"] == -9 and _row(s, "30Y")["breakeven_change_1m_bp"] == -10
    # a year ago, Nov 10 2025: 10Y 4.13 - 1.84 = 2.29; 5Y 3.72 - 1.34 = 2.38; 30Y 4.71 - 2.48 = 2.23
    assert _row(s, "10Y")["breakeven_change_1y_bp"] == -9 and _row(s, "5Y")["breakeven_change_1y_bp"] == -13 and _row(s, "30Y")["breakeven_change_1y_bp"] == -5
    assert _row(s, "10Y")["real_change_1y_bp"] == 94                                             # real 10Y: 2.78 now, 1.84 a year ago


def test_only_days_present_in_both_curves_are_used():
    nom, real = _data()
    nom[date(2026, 11, 11)] = {t: 5.0 for t in R.TENORS}                    # the regular curve has a day the real one does not
    s = R.summarize(nom, real, TODAY)
    assert s["date"] == "2026-11-10" and s["checks"]["latest_dates_differ"] is True
    only_real = {d: v for d, v in real.items() if d != date(2026, 11, 10)}
    assert R.summarize(nom, only_real, TODAY)["date"] == "2026-11-09"


def test_a_missing_or_implausible_value_leaves_that_maturity_out_and_says_so():
    nom, real = _data()
    real[date(2026, 11, 10)] = {**real[date(2026, 11, 10)], "20Y": None, "7Y": 99.0}
    s = R.summarize(nom, real, TODAY)
    assert [x["tenor"] for x in s["rows"]] == ["5Y", "10Y", "30Y"] and s["checks"]["maturities_left_out"] == ["7Y", "20Y"]


def test_a_comparison_day_too_far_away_is_left_out_not_guessed():
    nom, real = _data()
    nom = {d: v for d, v in nom.items() if not (date(2026, 9, 25) <= d <= date(2026, 10, 14))}
    s = R.summarize(nom, {d: v for d, v in real.items() if d in nom}, TODAY)
    assert s["month_ago_date"] is None and _row(s, "10Y")["breakeven_change_1m_bp"] is None and _row(s, "10Y")["breakeven_change_1y_bp"] == -9


def test_stale_data_is_marked_overdue_with_the_real_age():
    nom, real = _data()
    s = R.summarize(nom, real, date(2026, 11, 30))
    assert s["freshness"] == "OVERDUE" and s["age_days"] == 20


def test_parse_refuses_doctype_and_junk():
    for bad in ("<!DOCTYPE x><feed/>", "<feed xmlns='http://www.w3.org/2005/Atom'></feed>"):
        try:
            R.parse(bad, "TC_")
            assert False
        except ValueError:
            pass


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(req):
    ym = req.url.params["field_tdr_date_value_month"]
    kind = "real" if "real" in req.url.params["data"] else "nominal"
    return httpx.Response(200, text=F[f"{kind}_{ym}"])


def test_overview_fetches_three_months_of_both_curves_and_caches():
    n = {"n": 0}

    def handler(req):
        n["n"] += 1
        return _handler(req)

    svc = R.RealYields(client=_client(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and _row(r, "10Y")["breakeven_pct"] == 2.2 and n["n"] == 6 and "not a market signal or a forecast" in r["note"] and len(r["history"]) <= 40
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 6


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(R.RealYields(client=_client(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and "HTTP 503" in r["reason"] and "rows" not in r


def test_demo_mode_invents_nothing():
    d = asyncio.run(R.RealYields(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "Demo" in d["reason"] and "rows" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/real-yields")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True
