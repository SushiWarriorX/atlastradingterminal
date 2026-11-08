"""The network wrapper with fake SEC and price services: every failure is said in words, a missing price keeps the filing analysis, demo shows no company figures, policy input is bounded."""
import asyncio
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from atlas_api.app import create_app
from atlas_api.models import ProviderUnavailable
from atlas_api.research import facts as F
from atlas_api.research.live import FundamentalResearch, clean_policy

import research_fixtures as X

NOW = datetime(2026, 2, 1, 12, tzinfo=timezone.utc)


class Inst:
    symbol, id = "ZZZ", "stock:ZZZ"


class FakeEdgar:
    def __init__(self, enabled=True, hit=(2002, "Cloud Software Inc"), facts_error=None, subs_error=None, sic=7372):
        self.enabled, self.hit, self.facts_error, self.subs_error, self.sic = enabled, hit, facts_error, subs_error, sic

    async def cik(self, t):
        return self.hit

    async def research_facts(self, cik):
        if self.facts_error:
            raise ProviderUnavailable("edgar", self.facts_error)
        return F.condense(X.software(), NOW.date()), "live", NOW

    async def filings(self, cik):
        if self.subs_error:
            raise ProviderUnavailable("edgar", self.subs_error)
        return {"sic": self.sic, "sic_description": "Services-Prepackaged Software", "fiscal_year_end": "1231", "exchanges": ["Nasdaq"]}, "live", NOW


class FakePrices:
    def __init__(self, price=40.0, fail=False):
        self.price, self.fail = price, fail

    async def get(self, inst):
        if self.fail:
            raise ProviderUnavailable("yahoo", "unreachable")
        return {"price": self.price, "prov": {"fetched_at": NOW.isoformat(), "provider": "yahoo", "status": "DELAYED"}}


def go(edgar, prices, demo=False, policy=None):
    return asyncio.run(FundamentalResearch(edgar, prices, demo).research(Inst(), policy, NOW))


def test_full_path_returns_filing_analysis_and_a_valuation_with_sources():
    o = go(FakeEdgar(), FakePrices())
    assert o["available"] and o["rule_of_40"]["current"]["score"] > 42.9 and o["valuation"]["label_key"] in ("under", "within", "over") and o["sources"]["filings"]["origin"] == "live"
    assert o["valuation"]["price_source"] == "yahoo (DELAYED)" and o["company"]["name"] == "Cloud Software Inc" and o["sources"]["submissions"]["exchanges"] == ["Nasdaq"]


def test_demo_mode_shows_no_company_figures():
    o = go(FakeEdgar(), FakePrices(), demo=True)
    assert o["available"] is False and "made-up company figures" in o["reason"] and "revenue" not in o


def test_missing_sec_contact_is_said_without_putting_one_in_the_repo():
    o = go(FakeEdgar(enabled=False), FakePrices())
    assert o["available"] is False and "ATLAS_SEC_CONTACT" in o["reason"] and "never in the repository" in o["reason"]


def test_unknown_ticker_and_sec_failure_are_said_in_words():
    assert "No SEC company" in go(FakeEdgar(hit=None), FakePrices())["reason"]
    o = go(FakeEdgar(facts_error="SEC EDGAR returned HTTP 503"), FakePrices())
    assert o["available"] is False and "HTTP 503" in o["reason"]


def test_a_failed_price_keeps_the_filing_analysis_and_removes_only_the_verdict():
    o = go(FakeEdgar(), FakePrices(fail=True))
    assert o["available"] and o["rule_of_40"]["label"] == "Reaches 40" and o["valuation"]["label"] == "Insufficient evidence" and any("Price" in e for e in o["errors"])


def test_a_failed_industry_lookup_is_warned_about_and_does_not_block():
    o = go(FakeEdgar(subs_error="SEC EDGAR returned HTTP 503"), FakePrices())
    assert o["available"] and any("Industry code" in e for e in o["errors"]) and o["company"]["sic"] is None


def test_policy_values_are_bounded_and_unknown_keys_ignored():
    assert clean_policy({"discount_rate_pct": 12, "terminal_growth_pct": 99, "band_pct": "x", "evil": 1, "years": 7}) == {"discount_rate_pct": 12.0, "years": 7}
    assert clean_policy(None) == {} and clean_policy({"band_pct": 4.9}) == {} and clean_policy({"band_pct": 5}) == {"band_pct": 5.0}
    o = go(FakeEdgar(), FakePrices(), policy={"discount_rate_pct": 14.0, "terminal_growth_pct": 1.0})
    assert o["valuation"]["policy"]["discount_rate_pct"] == 14.0 and o["valuation"]["policy"]["terminal_growth_pct"] == 1.0


def test_the_route_exists_and_refuses_non_stocks(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "r.db"), demo=True, alert_loop=False, news_loop=False)) as c:
        d = c.get("/api/research/AAPL").json()
        assert d["ok"] and d["data"]["available"] is False and d["data"]["demo"] is True
        assert c.get("/api/research/NOT-A-THING-123").status_code == 404
        r = c.get("/api/research/BTC")
        assert r.status_code in (404, 422)
