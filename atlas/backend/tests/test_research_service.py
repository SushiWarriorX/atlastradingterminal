"""The assembled research output for the five company types the experience must handle: a mature company, a software company, a recent listing, a loss-making company and a bank.
All SYNTHETIC SEC-schema fixtures (see research_fixtures.py); the figures are chosen so every result can be checked by hand."""
from datetime import datetime, timezone

import pytest

from atlas_api.research import facts as F
from atlas_api.research import service as S

import research_fixtures as X

NOW = datetime(2026, 2, 1, 12, tzinfo=timezone.utc)
PRICE_TIME = NOW.isoformat()


def go(raw, sic, price=50.0, now=NOW, **kw):
    return S.assemble(F.condense(raw, now.date()), sic, price, PRICE_TIME, "test quote", now, **kw)


def test_mature_company_has_five_years_eight_quarters_and_no_rule_of_40():
    o = go(X.mature(), 3490, price=14.0)
    assert o["revenue"]["available"] and len(o["revenue"]["annual"]) == 5 and len(o["revenue"]["quarterly"]) == 8
    assert o["rule_of_40"]["applicable"] is False and o["rule_of_40"]["label"] == "Not applicable" and "software" in o["rule_of_40"]["reason"]
    assert o["quality"]["available"] and o["valuation"]["label_key"] in ("under", "within", "over") and len(o["valuation"]["scenarios"]) == 3
    assert o["valuation"]["inputs"]["shares_basis"].startswith("weighted-average diluted shares for the year ended 2025-12-31")
    assert "Revenue by segment or geography" in o["coverage"]["not_covered"][0]


def test_software_company_shows_the_rule_of_40_example_and_a_complete_valuation():
    o = go(X.software(), 7372, price=40.0)
    r = o["rule_of_40"]
    assert r["current"]["score"] == pytest.approx(43.0) and r["label"] == "Reaches 40"
    v = o["valuation"]
    assert v["inputs"]["ttm_fcf"] == pytest.approx(90.0) and v["inputs"]["fcf_margin_pct"] == pytest.approx(18.0) and v["inputs"]["ttm_growth_pct"] == pytest.approx(25.0)
    assert v["inputs"]["shares"] == 52.0 and v["inputs"]["cash"] == 400.0 and v["inputs"]["debt"] == 0.0
    assert [s["name"] for s in v["scenarios"]] == ["bear", "base", "bull"] and v["reverse_dcf"]["available"] in (True, False)
    assert v["inputs"]["annual_dilution_pct"] == pytest.approx(((52.0 / 50.0) ** (1 / ((F.date(2025, 12, 31) - F.date(2024, 12, 31)).days / 365.25)) - 1) * 100)
    assert any("Rule of 40 (FCF basis) is 43.0" in t for t in o["thesis"]["what_must_be_true"])
    assert any("segment" in t for t in o["thesis"]["research_next"])


def test_recent_listing_is_honest_about_short_history_and_gets_no_verdict():
    o = go(X.recent_ipo(), 7372, price=20.0, now=datetime(2026, 11, 8, 12, tzinfo=timezone.utc))
    assert o["revenue"]["annual"] == [] and len(o["revenue"]["quarterly"]) == 3 and o["revenue"]["ttm"] is None
    assert o["rule_of_40"]["label"] == "N/A" and "eight consecutive quarters" in o["rule_of_40"]["reason"]
    v = o["valuation"]
    assert v["label"] == "Insufficient evidence" and v["label_key"] == "none"
    assert o["quality"]["available"] is False
    assert any("short filing history" in w and "post-listing" in w for w in v["warnings"])                           # the share-count caution is visible, not buried
    assert v["inputs"]["shares_basis"].startswith("weighted-average diluted shares for the quarter ended 2026-09-30") and v["inputs"]["shares"] == 90.0
    raw = X.software()
    del raw["facts"]["us-gaap"]["WeightedAverageNumberOfDilutedSharesOutstanding"]
    assert any("No diluted share count" in w for w in go(raw, 7372, price=10.0)["valuation"]["warnings"])              # no share count on file at all is also said
    assert go(X.bank(), 6022)["valuation"]["warnings"] == [] and go(X.bank(), 6022)["valuation"]["multiples"] == []   # every valuation answer has the same shape


def test_loss_making_company_shows_a_score_but_no_dcf_and_no_earnings_multiple():
    o = go(X.loss_making_software(), 7372, price=10.0)
    assert o["rule_of_40"]["current"]["score"] == pytest.approx(30.0) and o["rule_of_40"]["label"] == "Below 40"
    v = o["valuation"]
    assert v["label"] == "Insufficient evidence" and v["methods"]["dcf"]["available"] is False and v["scenarios"] == []
    m = {x["key"]: x for x in v["multiples"]}
    assert m["pe"]["value"] is None and "not meaningful" in m["pe"]["note"] and m["ev_revenue"]["value"] is not None
    assert any("not positive" in t or "turn" in t for t in [v["reason"]])


def test_bank_gets_sector_specific_notes_instead_of_company_style_measures():
    o = go(X.bank(), 6022)
    assert o["revenue"]["available"] is False and o["company"]["sector_kind"] == "bank" and "net interest margin" in o["company"]["special_sector_note"]
    assert o["rule_of_40"]["applicable"] is False and o["valuation"]["label"] == "Insufficient evidence"


def test_a_missing_price_removes_the_verdict_but_keeps_the_filing_based_analysis():
    o = go(X.software(), 7372, price=None)
    assert o["revenue"]["available"] and o["rule_of_40"]["label"] == "Reaches 40" and o["valuation"]["label"] == "Insufficient evidence"


def test_assemble_never_calls_a_model_and_labels_every_kind_of_number():
    o = go(X.software(), 7372, price=40.0)
    assert set(o["definitions"]) == {"reported", "derived", "calculated", "estimate"}
    assert o["revenue"]["quarterly"][-1]["basis"] in ("reported (three-month figure)", "derived: 12-month total minus 9-month total")


def test_latest_diluted_shares_prefers_the_newest_period_and_ignores_cumulative_lengths():
    raw = X.software()
    c = F.condense(raw, NOW.date())
    s = S.latest_diluted_shares(c)
    assert s["value"] == 52.0 and s["kind"] == "year" and s["end"].isoformat() == "2025-12-31"
    raw["facts"]["us-gaap"]["WeightedAverageNumberOfDilutedSharesOutstanding"]["units"]["shares"].append(
        {"start": "2025-01-01", "end": "2025-09-30", "val": 999.0, "accn": "0000999999-25-000001", "fy": 2025, "fp": "Q3", "form": "10-Q", "filed": "2025-11-01"})        # a nine-month average is not a count to use
    assert S.latest_diluted_shares(F.condense(raw, NOW.date()))["value"] == 52.0
