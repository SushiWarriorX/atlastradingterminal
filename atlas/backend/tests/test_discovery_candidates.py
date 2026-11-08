"""New-to-me discovery: the real screener sample for universe and filters, scoring and the evidence gate on synthetic filings (see research_fixtures.py), and the daily flow with fakes."""
import asyncio
import json
from datetime import date, datetime, timezone
from itertools import product
from pathlib import Path

import httpx
import pytest

from atlas_api.db import DB
from atlas_api.discover import candidates as C
from atlas_api.discover import universe as U
from atlas_api.discover.newtome import NewToMe
from atlas_api.discover.store import DiscoveryStore
from atlas_api.research import facts as F
from atlas_api.research import service as S

import research_fixtures as X

FIX = Path(__file__).parent / "fixtures"
SAMPLE = json.loads((FIX / "nasdaq_screener_sample.json").read_text())
NOW = datetime(2026, 2, 1, 12, tzinfo=timezone.utc)


def companies():
    out = []
    for ex, label in (("nasdaq", "Nasdaq"), ("nyse", "NYSE")):
        out += U.parse_screener({"data": {"rows": SAMPLE["exchanges"][ex]["rows"]}}, label)
    return out


# ---------- universe and filters (real screener rows) ----------

def test_real_rows_are_parsed_with_unknowns_kept_unknown():
    cs = companies()
    assert len(cs) == 232 + 157 and {c["exchange"] for c in cs} == {"Nasdaq", "NYSE"}
    a = next(c for c in cs if c["market_cap"] and c["ipo_year"])
    assert a["price"] > 0 and a["dollar_volume"] == pytest.approx(a["price"] * a["volume"]) and a["sector"]
    assert any(c["market_cap"] is None for c in cs) and any(c["ipo_year"] is None for c in cs) and any(c["sector"] is None for c in cs)


def test_non_operating_securities_are_excluded_and_every_exclusion_is_counted():
    def row(sym, name):
        return {"symbol": sym, "name": name, "exchange": "Nasdaq", "price": 10.0, "market_cap": 1e9, "volume": 1000000, "dollar_volume": 1e7, "country": "United States", "ipo_year": 2015, "sector": "Technology", "industry": "x"}
    rows = [row("GOOD", "Good Software Inc. Common Stock"), row("WARR", "Good Software Inc. Warrants"), row("UNIT", "Some Co Units"), row("RGHT", "Some Co Rights"), row("PREF", "Some Co Preferred Stock"),
            row("FUND", "Some Income Fund"), row("SPAC", "Big Acquisition Corp Class A"), row("BIL", "Bilibili Inc. American Depositary Shares"), row("AB^C", "Weird Symbol Inc"),
            {**row("NOCAP", "No Market Value Inc. Common Stock"), "market_cap": None}, {**row("THIN", "Thinly Traded Inc. Common Stock"), "dollar_volume": None}]
    kept, why = U.apply_filters(rows, None, 2026)
    assert [c["symbol"] for c in kept] == ["GOOD"]
    assert why["not an operating company"] == 7 and why["foreign depositary shares (foreign filers are not covered)"] == 1
    assert why["unknown market value"] == 1 and why["low trading volume or unknown"] == 1                                    # unknown is never treated as passing
    cs = companies()
    kept, why = U.apply_filters(cs, None, 2026)
    assert all(U.operating_company(c) and 300e6 <= c["market_cap"] <= 50e9 and c["dollar_volume"] >= 1e6 for c in kept)
    assert sum(why.values()) + len(kept) == len(cs)                                                                    # every company is either kept or counted under a reason


def test_filters_for_sector_country_exchange_size_and_listing_age_are_configurable():
    cs = companies()
    kept, _ = U.apply_filters(cs, {"sectors": ["Technology"]}, 2026)
    assert kept and {c["sector"] for c in kept} == {"Technology"}
    kept, _ = U.apply_filters(cs, {"exchanges": ["NYSE"], "countries": ["United States"]}, 2026)
    assert kept and {c["exchange"] for c in kept} == {"NYSE"} and {c["country"] for c in kept} == {"United States"}
    kept, why = U.apply_filters(cs, {"max_listing_age_years": 10}, 2026)
    assert kept and all(2026 - c["ipo_year"] <= 10 for c in kept) and why["unknown listing year"] > 0                  # a blank IPO year cannot pass an age filter, and is counted
    kept, _ = U.apply_filters(cs, {"min_market_cap": 5e9, "max_market_cap": 20e9}, 2026)
    assert kept and all(5e9 <= c["market_cap"] <= 20e9 for c in kept)
    everything, _ = U.apply_filters(cs, {"max_market_cap": float("inf"), "min_market_cap": 0, "min_dollar_volume": 0}, 2026)
    assert len(everything) >= len(U.apply_filters(cs, None, 2026)[0])


def test_size_buckets_have_clear_edges():
    assert [U.size_bucket(x) for x in (None, 1e8, 3e8, 1.99e9, 2e9, 9.9e9, 1e10, 199e9, 200e9)] == [None, "micro", "small", "small", "mid", "mid", "large", "large", "mega"]


def test_the_daily_sample_is_varied_reproducible_and_changes_by_day():
    kept, _ = U.apply_filters(companies(), None, 2026)
    a, b = U.sample_for_study(kept, "2026-11-08", 30), U.sample_for_study(kept, "2026-11-08", 30)
    assert [c["symbol"] for c in a] == [c["symbol"] for c in b] and len(a) == 30
    assert [c["symbol"] for c in U.sample_for_study(kept, "2026-11-09", 30)] != [c["symbol"] for c in a]
    assert len({c["sector"] for c in a}) >= min(8, len({c["sector"] for c in kept}))                              # spread across sectors, not the biggest names
    ex = U.sample_for_study(kept, "2026-11-08", 30, exclude={a[0]["symbol"].lower()})
    assert a[0]["symbol"] not in {c["symbol"] for c in ex}


# ---------- scoring and the evidence gate ----------

def research(raw, sic, price):
    return S.assemble(F.condense(raw, NOW.date()), sic, price, NOW.isoformat(), "test", NOW)


def test_a_growing_profitable_software_company_scores_high_with_reasons_and_a_named_risk():
    r = research(X.software(), 7372, 40.0)
    f = C.factors(r)
    assert f["growth"] == pytest.approx(75.0) and f["resilience"] == pytest.approx(100.0) and f["quality"] == pytest.approx((100 + (60 + 0.8 * 40) + 50) / 3, abs=0.01)
    ev = C.evaluate(r)
    assert ev["eligible"] and ev["score"] >= C.MIN_TOTAL and ev["factors_used"] >= 3
    assert any("Revenue grew 25.0%" in w for w in ev["why_selected"]) and any("Rule of 40" in w for w in ev["why_selected"])
    assert ev["main_opportunity"] and ev["main_risk"] and ev["risks"]


def test_a_recent_listing_is_left_out_for_weak_evidence_not_padded_in():
    ev = C.evaluate(research(X.recent_ipo(), 7372, 20.0))
    assert ev["eligible"] is False and "fewer than eight consecutive quarters" in ev["excluded_because"]


def test_a_cash_burning_grower_does_not_pass_on_growth_alone():
    ev = C.evaluate(research(X.loss_making_software(), 7372, 10.0))
    assert ev["eligible"] is False and "below the minimum" in ev["excluded_because"] and ev["factors"]["growth"] > 90 and ev["factors"]["resilience"] < 30


def test_a_slow_steady_company_is_featured_only_when_the_price_is_clearly_below_its_value_and_a_bank_is_excluded():
    base = research(X.mature(), 3490, 40.0)["valuation"]["fair_value_range"]["base"]
    fair = C.evaluate(research(X.mature(), 3490, base))
    assert fair["eligible"] is False and "below the minimum" in fair["excluded_because"] and fair["factors"]["growth"] < 15                          # slow growth alone is not interesting
    cheap = C.evaluate(research(X.mature(), 3490, base * 0.6))
    assert cheap["eligible"] is True and cheap["factors"]["valuation"] >= 90 and any("Valuation under stated assumptions" in w for w in cheap["why_selected"])
    ev = C.evaluate(research(X.bank(), 6022, 20.0))
    assert ev["eligible"] is False and "no revenue" in ev["excluded_because"]


def test_stale_filings_are_excluded():
    r = S.assemble(F.condense(X.software(), date(2026, 9, 1)), 7372, 40.0, NOW.isoformat(), "test", datetime(2026, 9, 1, tzinfo=timezone.utc))
    assert C.evaluate(r)["eligible"] is False and "stale" in C.evaluate(r)["excluded_because"]


def test_material_key_changes_with_a_new_quarter_or_a_new_valuation_reading():
    a, b = research(X.software(), 7372, 5.0), research(X.software(), 7372, 500.0)
    assert C.material_key(a) != C.material_key(b) and C.material_key(a).startswith("2025-12-31|")


def test_picking_is_best_first_varied_and_may_return_fewer_than_the_target():
    pool = [{"symbol": f"S{i}", "score": 90 - i, "sector": "Tech" if i < 4 else "Health", "size_bucket": "mid"} for i in range(8)]
    chosen, skipped = C.pick(pool, target=5, max_per_sector=2, max_per_size=3)
    assert [c["symbol"] for c in chosen] == ["S0", "S1", "S4"]                                              # two Tech, one Health: the size limit of three then stops it
    assert skipped and all("varied" in s["reason"] for s in skipped)
    assert C.pick([], 5) == ([], [])


# ---------- the daily flow ----------

def fake_screener(rows):
    return {"data": {"rows": rows}}


def make_rows():
    base = [("SOFT", "Cloud Software Inc", "Technology", "40.00"), ("MATU", "Mature Industrial Co", "Industrials", "62.57"), ("BURN", "Burning Cash Software", "Technology", "10.00"),
            ("NEWC", "New Listing Corp", "Technology", "20.00"), ("BANK", "Sample Bank", "Finance", "20.00")]
    rows = [{"symbol": s, "name": n, "lastsale": f"${px}", "marketCap": "2000000000", "volume": "900000", "country": "United States", "ipoyear": "2015", "sector": sec, "industry": "Test industry"}
            for s, n, sec, px in base]
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for a, b, c in product(letters[:5], letters[:5], letters[:5]):
        rows.append({"symbol": f"F{a}{b}{c}", "name": f"Filler {a}{b}{c} Inc", "lastsale": "$10.00", "marketCap": "900000000", "volume": "500000", "country": "China", "ipoyear": "", "sector": "Finance", "industry": "x"})
    return rows


RAW = {"SOFT": (X.software, 7372), "MATU": (X.mature, 3490), "BURN": (X.loss_making_software, 7372), "NEWC": (X.recent_ipo, 7372), "BANK": (X.bank, 6022)}


async def researcher(symbol, price, price_time, price_source, now):
    if symbol not in RAW:
        return {"available": False, "reason": f"No SEC company with ticker {symbol} was found"}
    mk, sic = RAW[symbol]
    return {**S.assemble(F.condense(mk(), NOW.date()), sic, price, price_time, price_source, NOW), "available": True}


def screener_client(fail=False):
    def h(req):
        if fail:
            return httpx.Response(503)
        return httpx.Response(200, json=fake_screener(make_rows()))
    return httpx.AsyncClient(transport=httpx.MockTransport(h))


def build(tmp_path, client=None, demo=False, watch=()):
    db = DB(str(tmp_path / "n.db"))
    store = DiscoveryStore(db)
    return db, store, NewToMe(db, store, researcher, client or screener_client(), demo, watchlist=lambda: list(watch))


def test_a_symbol_listed_twice_by_the_feed_is_studied_once(tmp_path):
    _, _, n = build(tmp_path)                                                                                           # the fake feed serves the same rows for both exchanges
    rows, errors = asyncio.run(n.universe(NOW))
    assert errors == [] and len(rows) == 130 and len({r["symbol"] for r in rows}) == 130


def test_the_daily_study_keeps_only_candidates_that_pass_and_counts_why_others_did_not(tmp_path):
    _, _, n = build(tmp_path)
    run = asyncio.run(n.refresh(NOW, study=300))
    assert run["available"] and [p["symbol"] for p in run["pool"]] == ["SOFT"] and run["passed"] == 1
    assert run["left_out_reasons"] and any("fewer than eight" in k for k in run["left_out_reasons"]) and any("below the minimum" in k for k in run["left_out_reasons"])
    assert sum(run["could_not_study"].values()) == 125 and "No SEC company" in next(iter(run["could_not_study"]))
    p = run["pool"][0]
    assert p["exchange"] in ("Nasdaq", "NYSE") and p["size_bucket"] == "mid" and p["price_source"].startswith("Nasdaq screener") and p["rule_of_40"]["label"] == "Reaches 40" and p["description"]["note"]
    assert n.latest_run()["asof"] == "2026-02-01"


def test_the_page_applies_my_filters_states_cooldown_and_never_repeats_without_news(tmp_path):
    _, store, n = build(tmp_path)
    asyncio.run(n.refresh(NOW, study=300))
    first = n.read(now=NOW)
    assert first["available"] and [i["symbol"] for i in first["items"]] == ["SOFT"] and "fewer are shown" in first["evidence_note"] and first["stale"] is False
    again = n.read(now=NOW)                                                                                       # same day: the cooldown hides it, nothing is padded in
    assert again["items"] == [] and again["hidden_because_seen"][0]["symbol"] == "SOFT" and store.get("SOFT")["shown_count"] == 1
    assert n.read(now=datetime(2026, 3, 5, tzinfo=timezone.utc))["items"][0]["symbol"] == "SOFT"                  # cooldown over
    store.set_state("SOFT", "dismissed")
    assert n.read(now=datetime(2026, 3, 5, tzinfo=timezone.utc))["items"] == []                                   # dismissed stays dismissed


def test_a_material_change_brings_a_seen_company_back_with_the_reason(tmp_path):
    db, store, n = build(tmp_path)
    run = asyncio.run(n.refresh(NOW, study=300))
    n.read(now=NOW)
    run["pool"][0]["material"] = "2026-03-31|within"                                                              # a new quarter was filed since it was shown
    db.x("UPDATE disc_feed_runs SET payload=? WHERE kind='new_to_me'", (json.dumps(run),))
    back = n.read(now=NOW)
    assert [i["symbol"] for i in back["items"]] == ["SOFT"] and "New since you last saw it" in back["items"][0]["why_shown_again"]


def test_my_filters_narrow_the_pool_and_the_exclusions_are_reported(tmp_path):
    _, _, n = build(tmp_path)
    asyncio.run(n.refresh(NOW, study=300))
    out = n.read({"sectors": ["Health Care"], "min_market_cap": 0, "max_market_cap": float("inf"), "min_dollar_volume": 0}, now=NOW, mark=False)
    assert out["items"] == [] and out["excluded_by_my_filters"]["sector"] == 1 and "Showing 0 of a target of 5" in out["evidence_note"]
    ok = n.read({"sectors": ["technology"], "countries": ["United States"], "min_market_cap": 0, "max_market_cap": float("inf"), "min_dollar_volume": 0}, now=NOW, mark=False)
    assert [i["symbol"] for i in ok["items"]] == ["SOFT"]


def test_watchlist_and_researched_companies_are_not_studied_again(tmp_path):
    _, store, n = build(tmp_path, watch=["soft"])
    run = asyncio.run(n.refresh(NOW, study=300))
    assert run["pool"] == [] and run["studied"] == 129                                                                  # 130 companies, SOFT skipped because it is on the watchlist
    store2 = DiscoveryStore(DB(str(tmp_path / "x.db")))
    store2.set_state("SOFT", "researched")
    n2 = NewToMe(DB(str(tmp_path / "x.db")), store2, researcher, screener_client(), False)
    assert asyncio.run(n2.refresh(NOW, study=300))["pool"] == []


def test_demo_no_run_and_universe_failure_say_so_in_words(tmp_path):
    _, _, demo = build(tmp_path, demo=True)
    d = asyncio.run(demo.refresh(NOW))
    assert d["available"] is False and "made-up companies" in d["reason"] and d["pool"] == []
    dbe = DB(str(tmp_path / "e.db"))
    fresh = NewToMe(dbe, DiscoveryStore(dbe), researcher, screener_client(), False)
    assert fresh.read(now=NOW)["available"] is False and "No daily study has run yet" in fresh.read(now=NOW)["reason"]
    dbf = DB(str(tmp_path / "f.db"))
    bad = NewToMe(dbf, DiscoveryStore(dbf), researcher, screener_client(fail=True), False)
    r = asyncio.run(bad.refresh(NOW))
    assert r["available"] is False and "could not be read" in r["reason"]
    assert bad.read(now=NOW)["available"] is False and "No daily study has run yet" in bad.read(now=NOW)["reason"]          # a failed study saves nothing, so there is nothing to show yet


def test_a_stale_universe_copy_is_used_and_said(tmp_path):
    db, _, n = build(tmp_path)
    asyncio.run(n.refresh(NOW, study=10))
    later = datetime(2026, 2, 2, 12, tzinfo=timezone.utc)
    bad = NewToMe(db, DiscoveryStore(db), researcher, screener_client(fail=True), False)
    run = asyncio.run(bad.refresh(later, study=10))
    assert run["available"] and any("using the copy saved 2026-02-01" in e for e in run["errors"])


def test_a_company_that_fails_to_load_does_not_stop_the_others(tmp_path):
    async def flaky(symbol, *a):
        if symbol == "MATU":
            raise RuntimeError("boom")
        return await researcher(symbol, *a)
    db = DB(str(tmp_path / "k.db"))
    n = NewToMe(db, DiscoveryStore(db), flaky, screener_client(), False)
    run = asyncio.run(n.refresh(NOW, study=300))
    assert run["could_not_study"].get("RuntimeError") == 1 and [p["symbol"] for p in run["pool"]] == ["SOFT"]
