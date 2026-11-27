"""Event calendar: parsing real-shaped samples, filters, per-source failure, caps, dates, honest labels, routes."""
import asyncio
import json
from datetime import date, datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api.app import create_app
from atlas_api.db import DB
from atlas_api.eventcal import sources as S
from atlas_api.eventcal.service import EventCalendar

NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
EARN = {"data": {"rows": [
    {"lastYearRptDt": "11/06/2025", "lastYearEPS": "$0.82", "time": "time-after-hours", "symbol": "PBR", "name": "Petroleo Brasileiro S.A.- Petrobras", "marketCap": "$121,154,085,000", "fiscalQuarterEnding": "Sep/2026", "epsForecast": "$1.38", "noOfEsts": "2"},
    {"lastYearRptDt": "N/A", "lastYearEPS": "($0.12)", "time": "time-pre-market", "symbol": "AAPL", "name": "Apple Inc.", "marketCap": "$3,900,000,000,000", "fiscalQuarterEnding": "Sep/2026", "epsForecast": "", "noOfEsts": "30"},
    {"lastYearRptDt": "N/A", "lastYearEPS": "N/A", "time": "time-not-supplied", "symbol": "TINY", "name": "Tiny Co", "marketCap": "N/A", "fiscalQuarterEnding": "Sep/2026", "epsForecast": "$0.01", "noOfEsts": ""},
    {"symbol": "bad symbol!", "name": "x", "marketCap": "$1"}]}}
DIV = {"data": {"calendar": {"rows": [{"companyName": "American Electric Power Company, Inc. Common Stock", "symbol": "AEP", "dividend_Ex_Date": "11/10/2026", "payment_Date": "12/10/2026", "record_Date": "11/10/2026", "dividend_Rate": 0.97, "indicated_Annual_Dividend": 3.8, "announcement_Date": "10/20/2026"}]}}}
ICS = "BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART;TZID=US-Eastern:20261110T083000\nSUMMARY:Consumer Price Index\nEND:VEVENT\nBEGIN:VEVENT\nDTSTART;TZID=US-Eastern:20261113T083000\nSUMMARY:Producer Price Index\nEND:VEVENT\nBEGIN:VEVENT\nDTSTART;TZID=US-Eastern:20261112T083000\nSUMMARY:Union Membership\nEND:VEVENT\nEND:VCALENDAR\n"
BEA = '''<tr class="scheduled-releases-type-press"><td class="scheduled-date no-wrap"><div class="release-date">November 25</div>
<small class="text-muted">8:30 AM</small></td><td class="views-field"><div class="icon-letter"></div></td><td class="release-title views-field" headers="x">GDP (Second Estimate) and Corporate Profits, 3rd Quarter 2026        </td></tr>
<tr class="scheduled-releases-type-press"><td class="scheduled-date no-wrap"><div class="release-date">December 2</div>
<small class="text-muted">8:30 AM</small></td><td class="views-field"><div class="icon-letter"></div></td><td class="release-title views-field" headers="x">Personal Income and Outlays, October 2026        </td></tr>
<tr class="scheduled-releases-type-press"><td class="scheduled-date no-wrap"><div class="release-date">December 3</div>
<small class="text-muted">8:30 AM</small></td><td class="views-field"><div class="icon-letter"></div></td><td class="release-title views-field" headers="x">Something Unimportant        </td></tr>'''
TSY = {"data": [{"security_type": "Note", "security_term": "10-Year", "reopening": "Yes", "cusip": "X", "auction_date": "2026-11-12", "issue_date": "2026-11-16"}, {"security_type": "Bill", "security_term": "4-Week", "reopening": "No", "cusip": "Y", "auction_date": "2026-10-01", "issue_date": "2026-10-03"}]}


def test_money_and_dates_parse_the_provider_formats():
    assert S.money("$1,234.5") == 1234.5 and S.money("($0.12)") == -0.12 and S.money("") is None and S.money("N/A") is None and S.money(None) is None
    assert S.us_date("11/10/2026") == "2026-11-10" and S.us_date("N/A") is None


def test_earnings_rows_keep_only_what_the_source_says_and_reject_bad_symbols():
    ev = S.parse_nasdaq_earnings(EARN, "2026-11-10")
    assert [e["symbol"] for e in ev] == ["PBR", "AAPL", "TINY"]                      # the bad symbol is dropped
    pbr, aapl, tiny = ev
    assert pbr["details"]["eps_estimate"] == 1.38 and pbr["time_label"] == "After the market closes" and pbr["importance"] == "medium" and pbr["official"] is False
    assert aapl["importance"] == "high" and aapl["details"]["eps_estimate"] is None and aapl["details"]["last_year_eps"] == -0.12
    assert tiny["importance"] == "low" and tiny["time_label"] is None and tiny["market_cap"] is None and tiny["details"]["analysts"] is None


def test_dividends_use_the_ex_date_and_carry_pay_and_record_dates():
    d = S.parse_nasdaq_dividends(DIV, "2026-11-10")[0]
    assert d["date"] == "2026-11-10" and d["details"]["pay_date"] == "2026-12-10" and d["details"]["amount"] == 0.97 and d["name"] == "American Electric Power Company, Inc."


def test_official_sources_parse_and_unwanted_releases_are_left_out():
    bls = S.parse_bls(ICS)
    assert [(e["date"], e["title"], e["importance"]) for e in bls] == [("2026-11-10", "CPI (inflation)", "high"), ("2026-11-13", "PPI (producer prices)", "medium")]
    assert all(e["official"] for e in bls)
    bea = S.parse_bea(BEA, date(2026, 11, 8))
    assert [e["date"] for e in bea] == ["2026-11-25", "2026-12-02"] and bea[0]["title"].startswith("GDP") and bea[0]["importance"] == "high"
    t = S.parse_treasury(TSY, date(2026, 11, 8))
    assert len(t) == 1 and t[0]["title"] == "Treasury 10-Year note auction (reopening)" and t[0]["importance"] == "medium"       # past auctions are dropped


def test_bea_dates_without_a_year_roll_into_next_year():
    html = BEA.replace("December 2", "January 6")
    assert S.parse_bea(html, date(2026, 12, 20))[-1]["date"] == "2027-01-06"


def fake_client(fail=()):
    def handler(req: httpx.Request):
        u = str(req.url)
        if any(f in u for f in fail):
            return httpx.Response(503)
        if "calendar/earnings" in u:
            d = u.split("date=")[1]
            return httpx.Response(200, json=EARN if d == "2026-11-10" else {"data": {"rows": []}})
        if "calendar/dividends" in u:
            return httpx.Response(200, json=DIV if u.endswith("2026-11-10") else {"data": {"calendar": {"rows": []}}})
        if "bls.ics" in u:
            return httpx.Response(200, text=ICS)
        if "bea.gov" in u:
            return httpx.Response(200, text=BEA)
        if "fiscaldata" in u:
            return httpx.Response(200, json=TSY)
        return httpx.Response(404)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def cal(tmp_path, **kw):
    return EventCalendar(DB(str(tmp_path / "c.db")), client=fake_client(**kw) if "client" not in kw else kw["client"], contact="me@example.com")


def run(c, **kw):
    return asyncio.run(c.overview(start=date(2026, 11, 9), days=10, now=NOW, **kw))


def test_all_five_kinds_arrive_sorted_with_sources_labelled_official_or_not(tmp_path):
    out = run(cal(tmp_path), scope="all")
    assert out["counts"]["earnings"] == 3 and out["counts"]["dividend"] == 1 and out["counts"]["economy"] == 2 and out["counts"]["auction"] == 1 and out["counts"]["rates"] >= 1
    dates = [e["date"] for e in out["items"]]
    assert dates == sorted(dates)
    by = {s["id"]: s for s in out["sources"]}
    assert by["bls"]["official"] and by["treasury"]["official"] and not by["nasdaq_earnings"]["official"] and all(s["ok"] for s in out["sources"])
    assert "not a prediction" in out["importance_note"] and "unofficial" in out["labels"] or "Nasdaq" in out["labels"]["unofficial"]


def test_one_failing_source_is_reported_and_the_rest_still_show(tmp_path):
    out = run(cal(tmp_path, fail=("fiscaldata", "bls.ics")), scope="all")
    by = {s["id"]: s for s in out["sources"]}
    assert not by["treasury"]["ok"] and "503" in by["treasury"]["error"] and not by["bls"]["ok"]
    assert by["nasdaq_earnings"]["ok"] and out["counts"]["earnings"] == 3 and out["counts"]["auction"] == 0


def test_scopes_filter_company_events_but_keep_economy_and_rates(tmp_path):
    c = cal(tmp_path)
    maj = run(c, scope="major")
    assert {e["symbol"] for e in maj["items"] if e["kind"] == "earnings"} == {"PBR", "AAPL"}          # TINY (small cap, not in the big list) is dropped
    assert maj["counts"]["economy"] == 2
    wl = run(c, scope="watchlist", symbols=["TINY"])
    assert {e["symbol"] for e in wl["items"] if e["kind"] == "earnings"} == {"TINY"}
    assert next(e for e in wl["items"] if e["symbol"] == "TINY")["watch"] is True and next(e for e in wl["items"] if e["symbol"] == "TINY")["instrument_id"] is None
    assert next(e for e in maj["items"] if e["symbol"] == "AAPL")["instrument_id"].endswith(":AAPL") and wl["counts"]["economy"] == 2


def test_watchlist_symbols_come_from_the_saved_watchlist(tmp_path):
    c = cal(tmp_path)
    c.db.x("INSERT INTO signal_watchlist(asset_id,position,symbol,name,asset_type,venue,added_at) VALUES('EQUITY:NASDAQ:TINY',1,'TINY','Tiny','stock','NASDAQ','2026-11-01')")
    out = run(c, scope="watchlist")
    assert [e["symbol"] for e in out["items"] if e["kind"] == "earnings"] == ["TINY"]


def test_kinds_filter_and_window_limits(tmp_path):
    out = run(cal(tmp_path), scope="all", kinds=["dividend"])
    assert out["kinds"] == ["dividend"] and out["counts"]["earnings"] == 0 and {s["id"] for s in out["sources"]} == {"nasdaq_dividends"}
    long = asyncio.run(cal(tmp_path).overview(start=date(2026, 11, 9), days=90, now=NOW, scope="all"))
    assert long["to"] == "2026-11-29"                                                                   # capped at 21 days


def test_days_with_hundreds_of_small_events_are_capped_and_the_cap_is_said(tmp_path):
    rows = [{"lastYearRptDt": "N/A", "lastYearEPS": "N/A", "time": "time-pre-market", "symbol": f"S{i}", "name": "x", "marketCap": f"${1000 + i}", "fiscalQuarterEnding": "Sep/2026", "epsForecast": "", "noOfEsts": ""} for i in range(120)]

    def handler(req):
        u = str(req.url)
        if "calendar/earnings" in u:
            return httpx.Response(200, json={"data": {"rows": rows}} if u.endswith("2026-11-10") else {"data": {"rows": []}})
        return httpx.Response(200, json={"data": {"calendar": {"rows": []}}}) if "dividends" in u else httpx.Response(404)
    out = run(cal(tmp_path, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))), scope="all", kinds=["earnings"])
    assert out["counts"]["earnings"] == 40 and any("120" not in n and "80 smaller" in n for n in out["notes"])
    assert out["items"][0]["market_cap"] > out["items"][-1]["market_cap"]                               # the biggest are kept


def test_every_source_down_says_so_plainly(tmp_path):
    out = run(cal(tmp_path, fail=("nasdaq", "bls", "bea", "fiscaldata")), scope="all")
    assert all(not s["ok"] for s in out["sources"] if s["id"] != "fomc") and any("None of the online sources" in n for n in out["notes"])


def test_demo_mode_is_labelled_synthetic_and_needs_no_network(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "d.db"), demo=True, alert_loop=False, news_loop=False)) as c:
        r = c.get("/api/calendar?days=10&scope=all")
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["demo"] is True and any("synthetic" in n for n in d["notes"]) and any(e["source"].startswith("DEMO") for e in d["items"])
        assert c.get("/api/calendar?start=nope").status_code == 422
        assert c.get("/api/calendar?kinds=earnings&days=7").json()["data"]["kinds"] == ["earnings"]
