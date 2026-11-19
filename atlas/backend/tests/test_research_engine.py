"""Revenue analysis, TTM, quality measures and the Rule of 40, on SYNTHETIC fixtures in the SEC schema (see research_fixtures.py): five company types and the edge cases that must stay missing."""
from datetime import date

import pytest

from atlas_api.research import facts as F
from atlas_api.research import revenue as R
from atlas_api.research import rule40 as K

import research_fixtures as X

TODAY = date(2026, 2, 1)


def rf(raw):
    return F.condense(raw, TODAY)


# ---------- facts: reported versus derived quarters, restatements, gaps ----------

def test_condense_keeps_only_annual_and_quarterly_reports_and_the_latest_restatement():
    raw = X.software()
    raw["facts"]["us-gaap"]["Revenues"] = {"units": {"USD": [{"start": "2025-01-01", "end": "2025-03-31", "val": 1.0, "accn": "x", "fy": 2025, "fp": "Q1", "form": "8-K", "filed": "2025-05-01"}]}}
    c = rf(raw)
    assert all(row[3] in F.FORMS_OK for row in c["flows"]["revenue"])
    restated = rf(X.build("R", 1, 2024, {"revenue": [100.0] * 4}, restate={("revenue", "2024-03-31"): 90.0}))
    q1 = [r for r in restated["flows"]["revenue"] if r[1] == "2024-03-31" and r[0] == "2024-01-01"]
    assert len(q1) == 1 and q1[0][2] == 90.0                                       # the later filing replaced the original


def test_a_fallback_concept_only_fills_periods_the_main_one_lacks():
    raw = X.build("F", 2, 2024, {"revenue": [10.0] * 4})
    gaap = raw["facts"]["us-gaap"]
    gaap["Revenues"] = {"units": {"USD": [{"start": "2024-01-01", "end": "2024-03-31", "val": 999.0, "accn": "a", "fy": 2024, "fp": "Q1", "form": "10-Q", "filed": "2024-05-02"},
                                          {"start": "2023-01-01", "end": "2023-03-31", "val": 7.0, "accn": "b", "fy": 2023, "fp": "Q1", "form": "10-Q", "filed": "2023-05-02"}]}}
    rows = {(r[0], r[1]): r[2] for r in rf(raw)["flows"]["revenue"]}
    assert rows[("2024-01-01", "2024-03-31")] == 10.0 and rows[("2023-01-01", "2023-03-31")] == 7.0


def test_quarters_are_reported_when_filed_and_derived_from_cumulative_figures_otherwise():
    q = F.discrete_quarters(F.flow_facts(rf(X.build("D", 3, 2024, {"revenue": [10.0, 20.0, 30.0, 40.0], "operating_cash_flow": [1.0, 2.0, 3.0, 4.0]})), "revenue"))
    ends = sorted(q)
    assert [q[e]["value"] for e in ends] == [10.0, 20.0, 30.0, 40.0]
    assert q[ends[1]]["basis"].startswith("reported") and q[ends[3]]["basis"] == "derived: 12-month total minus 9-month total"           # the fourth quarter is never filed on its own
    cf = F.discrete_quarters(F.flow_facts(rf(X.build("D", 3, 2024, {"operating_cash_flow": [1.0, 2.0, 3.0, 4.0]})), "operating_cash_flow"))
    e = sorted(cf)
    assert [cf[x]["value"] for x in e] == [1.0, 2.0, 3.0, 4.0] and cf[e[1]]["basis"] == "derived: 6-month total minus 3-month total"       # cash flow is filed year-to-date only


def test_a_missing_quarter_breaks_the_run_and_no_ttm_is_made_from_it():
    q = F.discrete_quarters(F.flow_facts(rf(X.build("G", 4, 2024, {"revenue": [10.0] * 8})), "revenue"))
    assert F.ttm(q)["value"] == 40.0 and len(F.run(q, 8)) == 8
    q.pop(date(2025, 3, 31))
    assert F.ttm(q) is None and F.run(q, 4) is None                                  # the latest stretch is only 3 quarters long
    assert F.ttm(q, date(2024, 12, 31))["value"] == 40.0                             # but the earlier four are intact


def test_filing_links_are_built_only_from_a_valid_accession_number():
    assert F.filing_link(320193, "0000320193-25-000079") == "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/0000320193-25-000079-index.htm"
    assert F.filing_link(320193, "../../x") is None and F.filing_link("abc", "0000320193-25-000079") is None and F.filing_link(1, "") is None


# ---------- revenue analysis ----------

def test_mature_company_revenue_analysis_is_plain_arithmetic():
    raw = X.mature()
    rev = [round(1000 * 1.0075 ** i, 2) for i in range(20)]
    a = R.analyze_revenue(rf(raw), TODAY)
    assert a["available"] and len(a["annual"]) == 5 and len(a["quarterly"]) == 8 and a["missing"] == []
    assert a["annual"][0]["value"] == pytest.approx(sum(rev[0:4]))
    assert a["annual"][0]["growth_pct"] is None and a["annual"][0]["growth_note"] == "a comparable earlier period is missing"        # the first year has no year before it
    assert a["annual"][1]["growth_pct"] == pytest.approx((sum(rev[4:8]) / sum(rev[0:4]) - 1) * 100)
    assert a["ttm"]["value"] == pytest.approx(sum(rev[-4:])) and a["ttm_previous"]["value"] == pytest.approx(sum(rev[-8:-4]))
    assert a["ttm_growth_pct"] == pytest.approx((sum(rev[-4:]) / sum(rev[-8:-4]) - 1) * 100)
    first, last = sum(rev[0:4]), sum(rev[16:20])
    assert a["cagr"]["value_pct"] == pytest.approx(((last / first) ** (1 / a["cagr"]["years"]) - 1) * 100) and a["cagr"]["years"] == 4.0
    assert a["quarterly"][-1]["yoy_pct"] == pytest.approx((rev[19] / rev[15] - 1) * 100) and a["quarterly"][-1]["period_end"] == "2025-12-31"
    assert a["trend"]["label"] == "steady" and "rule" in a["trend"]
    assert a["per_share"][0]["revenue_per_diluted_share"] == pytest.approx(sum(rev[0:4]) / 100.0) and a["share_count_change"]["change_pct"] == pytest.approx(-4.0)
    assert a["quarterly"][-1]["source"]["link"].startswith("https://www.sec.gov/Archives/edgar/data/1001/")
    assert a["stale"] is False and "management guidance" in a["not_in_structured_data"]


def test_growth_that_speeds_up_or_slows_down_is_labelled_by_a_stated_rule():
    # year-over-year growth only keeps changing while the newest quarters are still compared with the old regime, so the change of pace is placed in the last four quarters
    fast = X.build("A", 7, 2022, {"revenue": [100.0 * 1.02 ** i if i < 12 else 100.0 * 1.02 ** 11 * 1.10 ** (i - 11) for i in range(16)]})
    slow = X.build("S", 8, 2022, {"revenue": [100.0 * 1.08 ** i if i < 12 else 100.0 * 1.08 ** 11 * 1.01 ** (i - 11) for i in range(16)]})
    f, s_ = R.analyze_revenue(rf(fast), TODAY)["trend"], R.analyze_revenue(rf(slow), TODAY)["trend"]
    assert f["label"] == "accelerating" and f["latest_yoy_pct"] == pytest.approx((1.10 ** 4 - 1) * 100) and f["change_pp"] > 1.0
    assert s_["label"] == "decelerating" and s_["latest_yoy_pct"] == pytest.approx((1.01 ** 4 - 1) * 100) and s_["change_pp"] < -1.0


def test_a_recent_listing_has_what_it_has_and_says_what_is_missing():
    a = R.analyze_revenue(rf(X.recent_ipo()), date(2026, 11, 8))
    assert a["available"] and a["annual"] == [] and len(a["quarterly"]) == 3 and a["ttm"] is None and a["ttm_growth_pct"] is None and a["cagr"] is None
    assert all(r["yoy_pct"] is None and r["yoy_note"] for r in a["quarterly"])                 # no year-earlier quarter: growth stays missing, never zero
    assert any("four consecutive quarters" in m for m in a["missing"]) and any("fiscal years" in m for m in a["missing"])
    assert a["share_count_change"] is None


def test_growth_from_a_zero_or_negative_base_is_not_a_number():
    assert R.growth_pct(10, 0) == (None, "not meaningful: the earlier figure is zero or negative")
    assert R.growth_pct(10, -5)[0] is None and R.growth_pct(None, 5)[0] is None and R.growth_pct(5, None)[0] is None
    assert R.growth_pct(110, 100)[0] == pytest.approx(10.0)


def test_no_revenue_line_means_unavailable_not_zero():
    a = R.analyze_revenue(rf(X.bank()), TODAY)
    assert a["available"] is False and "revenue" in a["reason"]


def test_stale_data_is_flagged_by_the_age_of_the_latest_period():
    a = R.analyze_revenue(rf(X.mature()), date(2026, 9, 1))
    assert a["stale"] is True and a["age_days"] > 135


# ---------- revenue quality ----------

def test_quality_measures_use_the_same_four_quarters_and_label_their_limits():
    q = R.quality(rf(X.software()))
    rows = {r["key"]: r for r in q["rows"]}
    assert q["available"] and q["ttm_period_end"] == "2025-12-31"
    assert rows["gross_margin"]["value"] == pytest.approx(75.0) and rows["operating_margin"]["value"] == pytest.approx(5.0) and rows["fcf_margin"]["value"] == pytest.approx(18.0)
    assert rows["cash_conversion"]["value"] == pytest.approx(5.0) and rows["sbc_pct_revenue"]["value"] == pytest.approx(15.0)
    assert q["balance"]["net_cash"] == pytest.approx(400.0) and "may be excluded" in q["balance"]["note"]
    assert rows["pretax_return_on_capital"]["value"] == pytest.approx(25.0 / (900.0 + 0.0 - 400.0) * 100)


def test_cash_conversion_is_not_meaningful_when_net_income_is_negative():
    rows = {r["key"]: r for r in R.quality(rf(X.loss_making_software()))["rows"]}
    assert rows["cash_conversion"]["value"] is None and "not meaningful" in rows["cash_conversion"]["note"]
    assert rows["fcf_margin"]["value"] == pytest.approx(-30.0)


def test_quality_needs_four_consecutive_quarters():
    q = R.quality(rf(X.recent_ipo()))
    assert q["available"] is False and "four consecutive" in q["reason"]


# ---------- Rule of 40 ----------

def test_rule_of_40_matches_the_worked_example_25_plus_18_is_43():
    r = K.rule_of_40(rf(X.software()), 7372)
    c = r["current"]
    assert r["applicable"] and r["available"] and c["basis"] == "FCF basis"
    assert c["growth_pct"] == pytest.approx(25.0) and c["margin_pct"] == pytest.approx(18.0) and c["score"] == pytest.approx(43.0) and c["reaches_40"] is True
    assert c["ttm_revenue"] == 500.0 and c["ttm_revenue_previous"] == 400.0 and c["ttm_operating_cash_flow"] == 100.0 and c["ttm_capital_expenditures"] == 10.0 and c["ttm_free_cash_flow"] == 90.0
    assert r["label"] == "Reaches 40" and "does not mean a stock is undervalued" in r["caveat"] and r["definition"].startswith("Rule of 40 (FCF basis)")


def test_the_ebitda_variant_is_separate_and_never_replaces_the_default():
    r = K.rule_of_40(rf(X.software()), 7372)
    e = r["ebitda_variant"]
    assert e["basis"] == "EBITDA basis" and e["growth_pct"] == pytest.approx(25.0) and e["margin_pct"] == pytest.approx((25.0 + 12.0) / 500.0 * 100) and e["score"] == pytest.approx(25.0 + 7.4)
    assert r["current"]["score"] == pytest.approx(43.0) and "not the default" in e["label"]


def test_a_fast_growing_cash_burning_software_company_scores_below_40_and_shows_why():
    r = K.rule_of_40(rf(X.loss_making_software()), 7372)
    c = r["current"]
    assert c["growth_pct"] == pytest.approx(60.0) and c["margin_pct"] == pytest.approx(-30.0) and c["score"] == pytest.approx(30.0) and c["reaches_40"] is False and r["label"] == "Below 40"


def test_missing_capital_expenditures_are_not_treated_as_zero():
    raw = X.software()
    del raw["facts"]["us-gaap"][X.CONCEPT["capex"]]
    r = K.rule_of_40(rf(raw), 7372)
    assert r["available"] is False and r["label"] == "N/A" and "capital expenditures are missing" in r["reason"] and "not treated as zero" in r["reason"]


def test_not_enough_history_gives_na_with_the_reason():
    r = K.rule_of_40(rf(X.recent_ipo()), 7372)
    assert r["available"] is False and r["label"] == "N/A" and "eight consecutive quarters" in r["reason"]


def test_a_zero_revenue_base_makes_the_growth_not_meaningful():
    raw = X.build("Z", 9, 2024, {"revenue": [0.0] * 4 + [10.0] * 4, "operating_cash_flow": [1.0] * 8, "capex": [0.1] * 8})
    r = K.rule_of_40(rf(raw), 7372)
    assert r["available"] is False and "not meaningful" in r["reason"]


def test_outside_software_the_measure_is_not_applicable_and_points_elsewhere():
    mature = K.rule_of_40(rf(X.mature()), 3490)
    assert mature["applicable"] is False and mature["label"] == "Not applicable" and "software" in mature["reason"] and "revenue quality" in mature["reason"]
    bank = K.rule_of_40(rf(X.bank()), 6022)
    assert bank["applicable"] is False and bank["sector"] == "bank" and "net interest margin" in bank["reason"]
    reit = K.rule_of_40(rf(X.mature()), 6798)
    assert reit["sector"] == "reit" and "funds from operations" in reit["reason"]


def test_history_has_one_point_per_quarter_end_with_enough_data_and_a_peer_placeholder_that_says_so():
    r = K.rule_of_40(rf(X.software()), 7372)
    assert len(r["history"]) == 1 and r["history"][0]["score"] == pytest.approx(43.0)
    longer = X.build("L", 11, 2023, {"revenue": [100.0] * 4 + [110.0] * 4 + [125.0] * 4, "operating_cash_flow": [20.0] * 12, "capex": [2.0] * 12})
    h = K.rule_of_40(rf(longer), 7372)["history"]
    assert len(h) == 5 and h[-1]["end"] == "2025-12-31" and r["peers"]["available"] is False


def test_capitalised_software_is_shown_beside_the_score_not_silently_included():
    raw = X.build("C", 12, 2024, {"revenue": [100.0] * 4 + [125.0] * 4, "operating_cash_flow": [25.0] * 8, "capex": [2.5] * 8, "cap_software": [5.0] * 8})
    r = K.rule_of_40(rf(raw), 7372)
    assert r["capitalised_software_ttm"] == 20.0 and "not subtracted" in r["capitalised_software_note"] and r["current"]["ttm_free_cash_flow"] == pytest.approx(90.0)


def test_sector_kinds_from_sic_codes():
    assert [R.sector_kind(x) for x in (7372, 6022, 6311, 6798, 6770, 3571, None, "x")] == ["software", "bank", "insurer", "reit", "other_financial", "standard", "unknown", "unknown"]
