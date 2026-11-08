"""Newly listed companies: parsed from three real months of the Nasdaq IPO calendar (fetched 2026-11-08); statuses are explicit, upcoming and trading are never mixed, empty days say so."""
import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest

from atlas_api.db import DB
from atlas_api.discover import listings as L
from atlas_api.discover.store import DiscoveryStore

FIX = Path(__file__).parent / "fixtures"
MONTHS = {m: json.loads((FIX / f"nasdaq_ipo_{m}.json").read_text()) for m in ("2026-09", "2026-10", "2026-11")}
ROWS = [r for m in ("2026-09", "2026-10", "2026-11") for r in L.parse_calendar(MONTHS[m])]
TODAY = date(2026, 11, 8)


def test_real_calendar_rows_are_parsed_with_iso_dates_and_exchange_labels():
    nov = L.parse_calendar(MONTHS["2026-11"])
    nara = next(r for r in nov if r["symbol"] == "NARA")
    assert nara["stage"] == "priced" and nara["priced_date"] == "2026-11-02" and nara["exchange"] == "Nasdaq" and nara["exchange_text"] == "NASDAQ Capital" and nara["offer_amount"] == 90988000.0 and nara["shares_offered"] == 9098800
    up = next(r for r in nov if r["symbol"] == "RZRA")
    assert up["stage"] == "upcoming" and up["expected_date"] == "2026-11-12" and up["price"] == "11.00-13.00"
    assert {r["stage"] for r in ROWS} == {"priced", "upcoming", "filed", "withdrawn"}
    assert all(r["name"] for r in ROWS)


def test_exchange_names_are_normalised_and_other_venues_are_excluded_from_the_feed():
    assert L.exchange_of("NASDAQ Global Select")[0] == "Nasdaq" and L.exchange_of("NYSE American")[0] == "NYSE American" and L.exchange_of("NYSE")[0] == "NYSE"
    assert L.exchange_of("OTC Markets")[0] is None and L.exchange_of(None) == (None, None)
    feed = L.build_feed([{**ROWS[0], "exchange": None, "stage": "priced", "priced_date": "2026-11-05", "deal_id": "x"}], TODAY)
    assert feed["recent"] == []


def test_status_rules_keep_upcoming_priced_and_confirmed_trading_apart():
    base = {"deal_id": "d", "symbol": "ZZZ", "name": "Z", "exchange": "Nasdaq", "priced_date": None, "expected_date": None}
    up = L.classify({**base, "stage": "upcoming", "expected_date": "2026-11-12"}, TODAY)
    assert up["status"] == "upcoming" and "not trading yet" in up["status_text"]
    late = L.classify({**base, "stage": "upcoming", "expected_date": "2026-10-20"}, TODAY)
    assert late["status"] == "upcoming_date_passed" and "postponed" in late["status_text"]
    priced = L.classify({**base, "stage": "priced", "priced_date": "2026-11-06"}, TODAY)                    # Friday: first trade expected Monday the 9th
    assert priced["status"] == "priced" and priced["expected_first_trade"] == "2026-11-09" and "Not yet trading" in priced["status_text"]
    old = L.classify({**base, "stage": "priced", "priced_date": "2026-11-02"}, TODAY)
    assert old["status"] == "priced" and "not independently confirmed" in old["status_text"]
    trading = L.classify({**base, "stage": "priced", "priced_date": "2026-11-02"}, TODAY, confirmed_first_trade="2026-11-03")
    assert trading["status"] == "trading" and trading["first_trade_date"] == "2026-11-03" and "independent price history" in trading["status_text"]
    assert L.classify({**base, "stage": "withdrawn"}, TODAY)["status"] == "withdrawn" and L.classify({**base, "stage": "filed"}, TODAY)["status"] == "filed"
    assert up["listing_type"] == "IPO" and "direct listings" in up["listing_type_note"]


def test_next_trading_day_skips_weekends():
    assert L.next_trading_day(date(2026, 11, 6)) == date(2026, 11, 9) and L.next_trading_day(date(2026, 11, 4)) == date(2026, 11, 5) and L.next_trading_day(date(2026, 11, 7)) == date(2026, 11, 9)


def test_the_feed_separates_upcoming_from_recent_and_filters_the_rolling_window():
    f = L.build_feed(ROWS, TODAY, days=30)
    assert all(x["status"] in ("upcoming", "upcoming_date_passed") for x in f["upcoming"]) and all(x["status"] in ("priced", "trading") for x in f["recent"])
    assert f["recent"][0]["priced_date"] >= f["recent"][-1]["priced_date"] and all(x["priced_date"] >= "2026-10-09" for x in f["recent"])
    wide = L.build_feed(ROWS, TODAY, days=75)
    assert len(wide["recent"]) > len(f["recent"]) and f["counts"]["recent"] == len(f["recent"]) and "IPOs only" in f["coverage"]
    assert len({x["deal_id"] for x in f["recent"]}) == len(f["recent"])                                      # no duplicates
    assert any(x["symbol"] == "RZRA" for x in f["upcoming"])


def test_an_empty_day_says_so_and_never_invents_candidates():
    f = L.build_feed(ROWS, date(2026, 11, 14), days=30)                                                       # a Saturday: nothing priced, nothing starting
    assert f["today"]["text"] == "No new listings are reported for today." and f["today"]["priced"] == 0
    none = L.build_feed([], TODAY)
    assert none["recent"] == [] and none["upcoming"] == [] and none["today"]["text"] == "No new listings are reported for today."


def test_today_summary_counts_pricings_and_expected_first_trades():
    rows = [{"deal_id": "a", "symbol": "AAA", "name": "A", "exchange": "NYSE", "stage": "priced", "priced_date": "2026-11-06", "expected_date": None},
            {"deal_id": "b", "symbol": "BBB", "name": "B", "exchange": "Nasdaq", "stage": "priced", "priced_date": "2026-11-09", "expected_date": None}]
    f = L.build_feed(rows, date(2026, 11, 9), days=30)
    assert f["today"]["priced"] == 1 and f["today"]["expected_first_trade"] == 1 and "confirmed: 0" in f["today"]["text"]
    g = L.build_feed(rows, date(2026, 11, 9), days=30, confirmations={"AAA": "2026-11-09"})
    assert g["counts"]["confirmed_trading"] == 1 and "confirmed: 1" in g["today"]["text"]


def test_a_transfer_or_ticker_change_is_not_a_new_company():
    assert L.is_genuinely_new("2026-11-03", earliest_price_date="2019-05-01")["new"] is False
    assert "transfer, ticker change or relisting" in L.is_genuinely_new("2026-11-03", earliest_price_date="2019-05-01")["reason"]
    assert L.is_genuinely_new("2026-11-03", earliest_filing_date="2020-03-01")["new"] is False
    new = L.is_genuinely_new("2026-11-03", earliest_price_date="2026-11-03", earliest_filing_date="2026-08-14")
    assert new["new"] is True and "Genuinely new" in new["reason"]
    assert L.is_genuinely_new("2026-11-03")["new"] is None                                                    # no history to check: cannot tell, says so


def test_sec_verification_needs_a_final_prospectus_near_the_pricing_date():
    filings = [{"form": "8-K", "filed": "2026-11-03"}, {"form": "424B4", "filed": "2026-11-04", "link": "https://www.sec.gov/Archives/edgar/data/1/x/y.htm"}]
    v = L.verify_with_sec(filings, "2026-11-02")
    assert v["verified"] is True and v["evidence"]["form"] == "424B4" and v["evidence"]["link"].startswith("https://www.sec.gov/")
    assert L.verify_with_sec([{"form": "424B4", "filed": "2026-09-01"}], "2026-11-02")["verified"] is False
    assert L.verify_with_sec([], "2026-11-02")["verified"] is False and L.verify_with_sec(filings, None)["verified"] is False
    f = L.build_feed(ROWS, TODAY, days=30, verifications={"NARA": v})
    assert next(x for x in f["recent"] if x["symbol"] == "NARA")["verification"]["verified"] is True and f["counts"]["verified_by_sec"] == 1


# ---------- the network side ----------

def handler_for(months):
    def h(req):
        m = req.url.params["date"]
        return httpx.Response(200, json=months[m]) if m in months else httpx.Response(503)
    return h


def run_rows(client, db=None, now=datetime(2026, 11, 8, 12, tzinfo=timezone.utc)):
    return asyncio.run(L.NasdaqIpoFeed(db, client).rows(TODAY, now))


def test_the_feed_reads_current_previous_and_next_months():
    seen = []

    def h(req):
        seen.append(req.url.params["date"])
        return httpx.Response(200, json=MONTHS.get(req.url.params["date"], {"status": {"rCode": 200}, "data": {}}))
    rows, errors = run_rows(httpx.AsyncClient(transport=httpx.MockTransport(h)))
    assert seen == ["2026-09", "2026-10", "2026-11", "2026-12"] and errors == [] and len(rows) > 20


def test_a_failed_month_is_said_and_a_saved_copy_is_used_when_one_exists(tmp_path):
    db = DB(str(tmp_path / "l.db"))
    good = httpx.AsyncClient(transport=httpx.MockTransport(handler_for(MONTHS)))
    run_rows(good, db, now=datetime(2026, 11, 7, 0, tzinfo=timezone.utc))
    bad = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(503)))
    rows, errors = run_rows(bad, db, now=datetime(2026, 11, 8, 12, tzinfo=timezone.utc))                      # the saved copies are older than 6 hours
    assert len(rows) > 20 and any("showing the copy saved 2026-11-07" in e for e in errors)
    rows2, errors2 = run_rows(bad)                                                                              # no database, nothing saved
    assert rows2 == [] and len(errors2) == 4 and all("could not be read" in e for e in errors2)


def test_a_feed_that_reports_an_error_code_is_not_trusted():
    h = lambda req: httpx.Response(200, json={"status": {"rCode": 500}, "data": {"priced": {"rows": [{"companyName": "X"}]}}})
    rows, errors = run_rows(httpx.AsyncClient(transport=httpx.MockTransport(h)))
    assert rows == [] and all("reported an error" in e for e in errors)


# ---------- my own records ----------

def test_dismissed_saved_and_researched_companies_are_never_offered_again_and_cooldown_applies(tmp_path):
    s = DiscoveryStore(DB(str(tmp_path / "s.db")))
    now = datetime(2026, 11, 8, tzinfo=timezone.utc)
    assert s.eligible("AAA", "m1", now) == (True, "never shown")
    s.mark_shown("AAA", "m1", 70.0, now)
    ok, why = s.eligible("AAA", "m1", now)
    assert ok is False and "cooldown" in why
    assert s.eligible("AAA", "m2", now) == (True, "material change since it was last shown")                  # a new quarter was filed: worth showing again
    later = datetime(2026, 12, 20, tzinfo=timezone.utc)
    assert s.eligible("AAA", "m1", later) == (True, "cooldown over")
    for state, word in (("dismissed", "dismissed"), ("saved", "already saved"), ("researched", "already researched")):
        t = DiscoveryStore(DB(str(tmp_path / f"{state}.db")))
        t.set_state("BBB", state)
        assert t.eligible("BBB", "x", later) == (False, word)
    s.set_state("AAA", "dismissed")
    assert s.eligible("AAA", "m2", later) == (False, "dismissed")                                              # even a material change does not override a dismissal
    s.set_state("AAA", "saved")
    assert s.get("AAA")["dismissed_at"] is None and s.get("AAA")["saved_at"]                                    # saving replaces an earlier dismissal
    s.set_state("AAA", "saved", False)
    assert s.get("AAA")["saved_at"] is None
    with pytest.raises(ValueError):
        s.set_state("AAA", "loved")


def test_notes_are_kept_per_company_and_bounded(tmp_path):
    s = DiscoveryStore(DB(str(tmp_path / "n.db")))
    n = s.add_note("aaa", "  Check segment margins in the 10-K.  ")
    s.add_note("AAA", "Second thought")
    assert n["body"] == "Check segment margins in the 10-K." and [x["body"] for x in s.notes("AAA")][0] == "Second thought" and s.notes("BBB") == []
    for bad in ("", "   ", "x" * 4001):
        with pytest.raises(ValueError):
            s.add_note("AAA", bad)
    assert s.delete_note(n["id"]) is True and len(s.notes("AAA")) == 1 and s.delete_note(9999) is False


def test_changes_since_my_last_review_list_only_what_changed(tmp_path):
    s = DiscoveryStore(DB(str(tmp_path / "c.db")))
    r1 = {"revenue": {"ttm": {"value": 500.0, "period_end": "2025-12-31"}, "ttm_growth_pct": 25.0, "trend": {"label": "steady"}, "latest_period_end": "2025-12-31"},
          "rule_of_40": {"current": {"score": 43.0}}, "valuation": {"label_key": "within", "price": 40.0, "fair_value_range": {"base": 42.0}, "evidence": {"level": "moderate"}}}
    assert s.changes_since_review("AAA", r1)["has_review"] is False
    s.record_review("AAA", r1)
    assert s.get("AAA")["researched_at"]
    same = s.changes_since_review("AAA", r1)
    assert same["has_review"] and same["changed"] == [] and same["unchanged_count"] == 9
    r2 = {**r1, "revenue": {**r1["revenue"], "ttm": {"value": 540.0, "period_end": "2026-03-31"}, "latest_period_end": "2026-03-31"}, "valuation": {**r1["valuation"], "price": 48.0, "label_key": "over"}}
    ch = {c["key"]: c for c in s.changes_since_review("AAA", r2)["changed"]}
    assert set(ch) == {"ttm_revenue", "price", "valuation_label", "latest_filing_period"} and ch["ttm_revenue"]["before"] == 500.0 and ch["ttm_revenue"]["after"] == 540.0 and ch["valuation_label"]["after"] == "over"
