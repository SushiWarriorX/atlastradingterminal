"""Valuation engine: DCF arithmetic checked by hand, multiples with their not-meaningful rules, scenarios, reverse DCF, evidence quality, label policy and missing-data handling."""
from datetime import date, datetime, timezone

import pytest

from atlas_api.research import valuation as V

NOW = datetime(2026, 3, 1, 12, tzinfo=timezone.utc)


def inp(**kw):
    base = {"price": 50.0, "price_time": NOW.isoformat(), "price_source": "test quote", "shares": 100.0, "shares_reliable": True, "cash": 400.0, "debt": 100.0, "ttm_revenue": 1000.0,
            "ttm_gross_profit": 700.0, "ttm_ebitda": 150.0, "ttm_net_income": 80.0, "ttm_fcf": 120.0, "ttm_growth_pct": 15.0, "fcf_margin_pct": 12.0, "annual_dilution_pct": 1.0,
            "financials_end": date(2025, 12, 31), "annual_years": 4, "sic": 7372}
    return {**base, **kw}


# ---------- the DCF arithmetic, by hand ----------

def test_a_flat_perpetuity_is_worth_cash_flow_over_the_discount_rate():
    d = V.dcf(rev0=100, m0_pct=10, g_start_pct=0, g_term_pct=0, m_target_pct=10, r_pct=10, years=2, debt=20, cash=50, shares=10, dilution_pct=0)
    assert d["ev"] == pytest.approx(100.0)                                            # 10 a year forever at 10%
    assert d["equity"] == pytest.approx(130.0) and d["per_share"] == pytest.approx(13.0)
    assert [p["fcf"] for p in d["path"]] == [10.0, 10.0]


def test_dilution_divides_the_equity_value_over_a_larger_share_count():
    d = V.dcf(100, 10, 0, 0, 10, 10, 2, 20, 50, 10, dilution_pct=10)
    assert d["shares_end"] == pytest.approx(10 * 1.21) and d["per_share"] == pytest.approx(130.0 / 12.1)


def test_growth_fades_linearly_and_margin_moves_linearly():
    d = V.dcf(100, 10, 20, 2.0, 14, 10, 5, 0, 0, 1, 0)
    assert [round(p["growth_pct"], 6) for p in d["path"]] == [20.0, 15.5, 11.0, 6.5, 2.0]
    assert [round(p["fcf_margin_pct"], 6) for p in d["path"]] == [10.8, 11.6, 12.4, 13.2, 14.0]
    assert d["path"][0]["revenue"] == pytest.approx(120.0)


def test_a_discount_rate_too_close_to_terminal_growth_is_refused():
    assert V.dcf(100, 10, 5, 4.8, 10, 5.0, 5, 0, 0, 1, 0) is None and V.dcf(0, 10, 5, 2, 10, 10, 5, 0, 0, 1, 0) is None and V.dcf(100, 10, 5, 2, 10, 10, 5, 0, 0, 0, 0) is None


# ---------- multiples ----------

def test_multiples_are_plain_arithmetic_with_enterprise_value_from_diluted_shares():
    m = {r["key"]: r for r in V.multiples(inp(price=50.0, shares=10.0, debt=100.0, cash=200.0, ttm_revenue=200.0, ttm_gross_profit=100.0, ttm_ebitda=50.0, ttm_net_income=25.0, ttm_fcf=20.0))}
    assert m["market_value"]["value"] == 500.0 and m["enterprise_value"]["value"] == 400.0
    assert m["ev_revenue"]["value"] == 2.0 and m["ev_gross_profit"]["value"] == 4.0 and m["ev_ebitda"]["value"] == 8.0
    assert m["pe"]["value"] == pytest.approx(20.0) and m["fcf_yield_pct"]["value"] == pytest.approx(4.0)


def test_earnings_multiples_are_never_applied_to_negative_earnings():
    m = {r["key"]: r for r in V.multiples(inp(ttm_net_income=-10.0, ttm_ebitda=-5.0, ttm_gross_profit=None, ttm_fcf=-30.0))}
    assert m["pe"]["value"] is None and "not meaningful" in m["pe"]["note"]
    assert m["ev_ebitda"]["value"] is None and "not meaningful" in m["ev_ebitda"]["note"] and m["ev_gross_profit"]["value"] is None
    assert m["fcf_yield_pct"]["value"] < 0 and "consumes cash" in m["fcf_yield_pct"]["note"]


def test_missing_debt_or_cash_leaves_enterprise_value_missing_not_zero():
    m = {r["key"]: r for r in V.multiples(inp(debt=None))}
    assert m["enterprise_value"]["value"] is None and m["ev_revenue"]["value"] is None and "missing" in m["enterprise_value"]["note"]
    assert {r["key"]: r for r in V.multiples(inp(ttm_fcf=None))}["fcf_yield_pct"]["note"] == "free cash flow is missing"


# ---------- the assessment ----------

def base_value():
    return V.assess(inp(), now=NOW)["scenarios"][1]["fair_value_per_share"]


def test_scenarios_are_ordered_and_every_assumption_is_shown():
    a = V.assess(inp(), now=NOW)
    bear, base, bull = a["scenarios"]
    assert [s["name"] for s in a["scenarios"]] == ["bear", "base", "bull"]
    assert bear["fair_value_per_share"] < base["fair_value_per_share"] < bull["fair_value_per_share"]
    assert base["assumptions"]["start_growth_pct"] == pytest.approx(15.0) and bear["assumptions"]["start_growth_pct"] == pytest.approx(7.5) and bull["assumptions"]["start_growth_pct"] == pytest.approx(19.5)
    assert bear["assumptions"]["fcf_margin_end_pct"] == pytest.approx(8.0) and bull["assumptions"]["fcf_margin_end_pct"] == pytest.approx(15.0)
    assert base["assumptions"]["annual_dilution_pct"] == 1.0 and bear["assumptions"]["annual_dilution_pct"] == 2.0 and base["assumptions"]["discount_rate_pct"] == 10.0
    assert a["fair_value_range"]["low"] == bear["fair_value_per_share"] and a["fair_value_range"]["high"] == bull["fair_value_per_share"]
    assert base["upside_pct"] == pytest.approx((base["fair_value_per_share"] / 50.0 - 1) * 100) and "not a forecast" in a["caveat"]


def test_each_scenario_equals_the_dcf_function_with_its_own_assumptions():
    a = V.assess(inp(), now=NOW)
    s = a["scenarios"][1]["assumptions"]
    d = V.dcf(1000.0, 12.0, s["start_growth_pct"], s["terminal_growth_pct"], s["fcf_margin_end_pct"], s["discount_rate_pct"], s["years"], 100.0, 400.0, 100.0, s["annual_dilution_pct"])
    assert a["scenarios"][1]["fair_value_per_share"] == pytest.approx(d["per_share"])


def test_the_label_follows_the_visible_policy():
    b = base_value()
    assert V.assess(inp(price=b * 0.6), now=NOW)["label"] == "Potentially undervalued under these assumptions"
    assert V.assess(inp(price=b), now=NOW)["label"] == "Within estimated fair-value range"
    assert V.assess(inp(price=b * 1.6), now=NOW)["label"] == "Potentially overvalued under these assumptions"
    a = V.assess(inp(price=b), now=NOW)
    assert "undervalued if the price is below the bear case" in a["classification_rule"] and a["policy"]["band_pct"] == 20.0


def test_the_classification_band_is_configurable_and_changes_the_label():
    b = base_value()
    price = b * 0.88                                                                   # 12% below the base case, but above the bear case
    assert V.assess(inp(price=price), now=NOW)["label"] == "Within estimated fair-value range"
    assert V.assess(inp(price=price), policy={"band_pct": 5.0}, now=NOW)["label"] == "Potentially undervalued under these assumptions"


def test_the_reverse_dcf_growth_reproduces_the_price():
    a = V.assess(inp(price=60.0), now=NOW)
    r = a["reverse_dcf"]
    assert r["available"]
    d = V.dcf(1000.0, 12.0, r["implied_growth_pct"], 2.5, 12.0, 10.0, 5, 100.0, 400.0, 100.0, 1.0)
    assert d["per_share"] == pytest.approx(60.0, rel=1e-6) and r["difference_pp"] == pytest.approx(r["implied_growth_pct"] - 15.0)


def test_a_price_no_growth_rate_can_justify_says_so():
    r = V.assess(inp(price=100000.0), now=NOW)["reverse_dcf"]
    assert r["available"] is False and "between -20% and 100%" in r["reason"]


def test_the_margin_invalidator_is_the_margin_at_which_the_base_case_equals_the_price():
    a = V.assess(inp(price=60.0), now=NOW)
    text = next(t for t in a["invalidators"] if "free-cash-flow margin stayed near" in t)
    m_even = float(text.split("near ")[1].split("%")[0])
    s = a["scenarios"][1]["assumptions"]
    d = V.dcf(1000.0, m_even, s["start_growth_pct"], 2.5, m_even, 10.0, 5, 100.0, 400.0, 100.0, 1.0)
    assert d["per_share"] == pytest.approx(60.0, rel=2e-2)                              # printed to one decimal, so a small tolerance


def test_sensitivity_centre_is_the_base_case_and_inputs_are_ranked_by_their_effect():
    a = V.assess(inp(), now=NOW)
    s = a["sensitivity"]
    assert s["values"][2][2] == pytest.approx(a["scenarios"][1]["fair_value_per_share"]) and len(s["values"]) == 5 and len(s["values"][0]) == 5
    assert s["values"][0][2] > s["values"][4][2]                                         # a lower discount rate is worth more
    swings = [i["swing"] for i in a["influence"]]
    assert swings == sorted(swings, reverse=True) and len(swings) == 4


def test_more_dilution_lowers_the_value_per_share():
    assert V.assess(inp(annual_dilution_pct=6.0), now=NOW)["scenarios"][1]["fair_value_per_share"] < V.assess(inp(annual_dilution_pct=0.0), now=NOW)["scenarios"][1]["fair_value_per_share"]
    assert V.assess(inp(annual_dilution_pct=-5.0), now=NOW)["scenarios"][1]["assumptions"]["annual_dilution_pct"] == 0.0         # buybacks are not credited


# ---------- no forced verdicts ----------

def test_negative_free_cash_flow_gives_no_dcf_and_no_verdict():
    a = V.assess(inp(fcf_margin_pct=-10.0, ttm_fcf=-100.0), now=NOW)
    assert a["label"] == "Insufficient evidence" and a["methods"]["dcf"]["available"] is False and "not positive" in a["reason"] and a["scenarios"] == []
    assert next(m for m in a["multiples"] if m["key"] == "ev_revenue")["value"] is not None                       # descriptive multiples still show


def test_a_stale_price_or_stale_financials_remove_the_verdict():
    old = datetime(2026, 2, 1, tzinfo=timezone.utc).isoformat()
    a = V.assess(inp(price_time=old), now=NOW)
    assert a["label"] == "Insufficient evidence" and a["evidence"]["level"] in ("weak", "insufficient") and "price" in a["reason"].lower()
    b = V.assess(inp(financials_end=date(2025, 6, 30)), now=NOW)
    assert b["label"] == "Insufficient evidence" and "quarter is older" in b["reason"]


def test_missing_growth_or_balance_sheet_or_shares_each_block_a_verdict():
    assert V.assess(inp(ttm_growth_pct=None), now=NOW)["label"] == "Insufficient evidence"
    assert V.assess(inp(debt=None), now=NOW)["label"] == "Insufficient evidence"
    assert V.assess(inp(shares=None), now=NOW)["label"] == "Insufficient evidence"
    assert V.assess(inp(price=None), now=NOW)["label"] == "Insufficient evidence"


def test_a_recent_listing_with_an_unreliable_share_count_gets_no_verdict_and_says_why():
    a = V.assess(inp(shares_reliable=False, shares_note="The weighted-average share count lags the post-listing count; the cover-page count is needed.", annual_years=0), now=NOW)
    assert a["label"] == "Insufficient evidence" and "post-listing" in a["reason"]


def test_a_range_too_wide_to_call_is_not_forced_into_a_verdict():
    a = V.assess(inp(), policy={"max_bull_to_bear": 1.05}, now=NOW)
    assert a["label"] == "Insufficient evidence" and "too wide" in a["reason"]


def test_banks_insurers_and_reits_get_no_company_style_verdict():
    for sic, word in ((6022, "bank"), (6311, "insurer"), (6798, "real-estate")):
        a = V.assess(inp(sic=sic), now=NOW)
        assert a["label"] == "Insufficient evidence" and word in a["reason"] and "not built yet" in a["reason"]


def test_evidence_never_reaches_strong_while_only_one_method_exists_and_the_limits_are_listed():
    a = V.assess(inp(), now=NOW)
    assert a["evidence"]["level"] == "moderate" and any("Peer multiples" in x for x in a["evidence"]["limits"])
    assert a["methods"]["peers"]["available"] is False and a["methods"]["own_history"]["available"] is False


def test_discount_rate_must_exceed_terminal_growth():
    a = V.assess(inp(), policy={"discount_rate_pct": 3.0, "terminal_growth_pct": 2.8}, now=NOW)
    assert a["label"] == "Insufficient evidence" and "0.5 points" in a["reason"]


def test_a_short_history_company_carries_a_visible_share_count_warning_and_normal_ones_do_not():
    note = "The weighted-average share count lags the post-listing count; the cover-page count is needed."
    a = V.assess(inp(shares_reliable=False, shares_note=note), now=NOW)
    assert a["warnings"] == [note]
    assert V.assess(inp(), now=NOW)["warnings"] == [] and V.assess(inp(sic=6022), now=NOW)["warnings"] == []
    assert V.assess(inp(fcf_margin_pct=-5.0, shares_reliable=False, shares_note=note), now=NOW)["warnings"] == [note]          # also on the no-DCF path
