"""Stock research: EDGAR parsing (tag changes, duplicates, quarters ignored), calculations, rule-based cases, honest gaps, routes, SEC fair-access guard."""
import asyncio
from datetime import date, datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import instruments as I
from atlas_api.app import create_app
from atlas_api.db import DB
from atlas_api.models import ProviderUnavailable
from atlas_api.stocks import edgar as E
from atlas_api.stocks import research as R

NOW = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)


def row(start, end, val, form="10-K", filed=None, **kw):
    r = {"end": end, "val": val, "form": form, "filed": filed or end, **kw}
    if start:
        r["start"] = start
    return r


def facts():
    usd = lambda *rows: {"units": {"USD": list(rows)}}
    return {"entityName": "Acme Corp", "cik": 1, "facts": {"us-gaap": {
        "Revenues": usd(row("2022-01-01", "2022-12-31", 100.0)),                                   # old tag, only the first year
        "RevenueFromContractWithCustomerExcludingAssessedTax": usd(
            row("2023-01-01", "2023-12-31", 120.0), row("2024-01-01", "2024-12-31", 150.0, filed="2025-02-01"),
            row("2024-01-01", "2024-12-31", 149.0, filed="2025-01-01"),                           # an older filing of the same year: the later filing wins
            row("2024-10-01", "2024-12-31", 40.0),                                                # a quarter: ignored
            row("2025-01-01", "2025-12-31", 90.0, form="10-Q"),                                   # not a 10-K: ignored
            row("2025-01-01", "2025-12-31", 140.0)),
        "OperatingIncomeLoss": usd(row("2022-01-01", "2022-12-31", 10.0), row("2023-01-01", "2023-12-31", 12.0), row("2024-01-01", "2024-12-31", 30.0), row("2025-01-01", "2025-12-31", 14.0)),
        "NetIncomeLoss": usd(row("2022-01-01", "2022-12-31", 8.0), row("2023-01-01", "2023-12-31", 9.0), row("2024-01-01", "2024-12-31", 20.0), row("2025-01-01", "2025-12-31", -5.0)),
        "NetCashProvidedByUsedInOperatingActivities": usd(row("2025-01-01", "2025-12-31", 30.0), row("2024-01-01", "2024-12-31", 25.0)),
        "PaymentsToAcquirePropertyPlantAndEquipment": usd(row("2025-01-01", "2025-12-31", 10.0), row("2024-01-01", "2024-12-31", 5.0)),
        "CashAndCashEquivalentsAtCarryingValue": usd(row(None, "2025-12-31", 50.0), row(None, "2024-12-31", 20.0)),
        "LongTermDebt": usd(row(None, "2025-12-31", 400.0), row(None, "2024-12-31", 100.0)),
        "StockholdersEquity": usd(row(None, "2025-12-31", 100.0), row(None, "2024-12-31", 90.0)),
    }}}


def test_parsing_fills_gaps_across_tag_changes_and_ignores_quarters_and_10q():
    c = E.condense_facts(facts())
    assert [y["end"] for y in c["years"]] == ["2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31"]
    assert [y["revenue"] for y in c["years"]] == [100.0, 120.0, 150.0, 140.0]           # latest filing wins; quarter and 10-Q never used
    assert c["years"][0]["gross_profit"] is None and c["years"][3]["cash"] == 50.0


def test_calculations_are_exact_and_missing_inputs_stay_missing():
    ys = R.compute(E.condense_facts(facts())["years"])
    assert ys[0]["revenue_growth_pct"] is None                                          # no previous year
    assert ys[1]["revenue_growth_pct"] == pytest.approx(20.0)
    assert ys[2]["operating_margin_pct"] == pytest.approx(20.0)
    assert ys[3]["free_cash_flow"] == 20.0 and ys[3]["fcf_margin_pct"] == pytest.approx(20 / 140 * 100)
    assert ys[3]["net_cash"] == -350.0 and ys[3]["debt_to_equity"] == pytest.approx(4.0)
    assert ys[2]["free_cash_flow"] == 20.0
    assert ys[1]["free_cash_flow"] is None and ys[1]["gross_margin_pct"] is None
    assert ys[3]["net_income_growth_pct"] is None                                       # a swing into a loss is shown as a loss, not as a percentage
    assert R.cagr(ys)["value_pct"] == pytest.approx(((140 / 100) ** (1 / 3.0) - 1) * 100, rel=0.01)


def test_growth_needs_a_real_one_year_step():
    ys = R.compute([{"end": "2022-12-31", "revenue": 100.0}, {"end": "2024-12-31", "revenue": 150.0}])
    assert ys[1]["revenue_growth_pct"] is None                                          # a skipped year is not a growth rate


def test_cases_cite_figures_use_the_rules_and_make_no_calls():
    ys = R.compute(E.condense_facts(facts())["years"])
    bull, bear = R.cases(ys, {"values": {"pe": 55.0, "ps": 2.0}})
    texts = " ".join(x["text"] for x in bull + bear).lower()
    ids = {x["id"] for x in bear}
    assert {"growth", "margin", "leverage", "loss", "pe"} <= ids and "fcf" in {x["id"] for x in bull}
    assert all(x["kind"].startswith("Interpretation") and x["based_on"] for x in bull + bear)
    assert not any(w in texts for w in ("buy", "sell", "price target", "will rise", "you should"))
    assert R.cases([], None) == ([], [])


def test_filings_condense_with_item_meanings_and_safe_links():
    subs = {"cik": 5, "name": "Acme", "sicDescription": "Widgets", "fiscalYearEnd": "1231", "filings": {"recent": {
        "form": ["8-K", "4", "10-K"], "filingDate": ["2026-02-01", "2026-02-02", "2026-01-01"], "accessionNumber": ["0001-26-000001", "x", "0001-26-000002"],
        "primaryDocument": ["a.htm", "b.xml", "../evil"], "items": ["2.02,9.01", "", ""], "reportDate": ["2026-02-01", "", "2025-12-31"]}}}
    c = E.condense_subs(subs)
    assert [f["form"] for f in c["filings"]] == ["8-K", "10-K"]
    assert c["filings"][0]["items"][0] == {"item": "2.02", "meaning": "Results of operations (earnings release)"}
    assert c["filings"][0]["link"].endswith("/5/000126000001/a.htm") and c["filings"][1]["link"] is None


def test_catalysts_only_list_future_earnings_and_the_latest_release():
    f = [{"form": "8-K", "filed": "2026-02-01", "link": "https://sec.example/x", "items": [{"item": "2.02"}]}]
    c = R.catalysts("2026-12-01", f, date(2026, 11, 5))
    assert [x["title"] for x in c] == ["Next earnings report", "Latest earnings release filed (8-K item 2.02)"]
    assert R.catalysts("2026-01-01", [], date(2026, 11, 5)) == []


def test_edgar_is_off_without_a_valid_contact_and_never_sends_a_request(tmp_path):
    db = DB(str(tmp_path / "e.db"))
    for bad in ("", "not an email", None):
        c = EdgarClientFor(db, bad)
        assert not c.enabled
        with pytest.raises(ProviderUnavailable, match="ATLAS_SEC_CONTACT"):
            asyncio.run(c.cik("AAPL"))


def EdgarClientFor(db, contact):
    return E.EdgarClient(db, contact=contact if contact is not None else "", client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(AssertionError("no request without a contact")))))


def test_edgar_sends_the_contact_in_user_agent_caches_and_serves_stale_on_failure(tmp_path):
    db = DB(str(tmp_path / "e.db"))
    seen, fail = [], {"on": False}

    def handler(req):
        seen.append(req.headers["user-agent"])
        if fail["on"]:
            return httpx.Response(503)
        if "company_tickers" in str(req.url):
            return httpx.Response(200, json={"0": {"cik_str": 1, "ticker": "ACME", "title": "Acme Corp"}})
        return httpx.Response(200, json=facts())
    c = E.EdgarClient(db, contact="me@example.com", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert asyncio.run(c.cik("acme")) == (1, "Acme Corp") and asyncio.run(c.cik("NOPE")) is None
    assert all("me@example.com" in u for u in seen) and len(seen) == 1                  # second lookup came from the cache
    data, origin, _ = asyncio.run(c.financials(1))
    assert origin == "live" and len(data["years"]) == 4
    db.x("UPDATE edgar_cache SET fetched_at='2020-01-01T00:00:00+00:00'")             # make it old, then break the network
    fail["on"] = True
    data, origin, _ = asyncio.run(c.financials(1))
    assert origin == "stale" and len(data["years"]) == 4
    with pytest.raises(ProviderUnavailable):
        asyncio.run(c.filings(1))                                                       # nothing cached for this one: unavailable, not invented


class FakeFund:
    def __init__(self, nxt="2026-11-20", fail=False):
        self.nxt, self.fail = nxt, fail

    async def get(self, inst, force=False):
        if self.fail:
            raise ProviderUnavailable("yahoo", "down")
        return {"name": "Acme", "sector": "Tech", "industry": "Widgets", "price": 10.0, "next_earnings_date": self.nxt, "flags": [], "financials_as_of": "2026-09-30", "values": {"pe": 12.0, "ps": 2.0},
                "groups": [{"name": "Valuation", "rows": [{"key": "pe", "label": "P/E (trailing)", "value": 12.0, "unit": "x", "basis": "price / EPS", "note": None}]}],
                "prov": {"provider": "yahoo", "fetched_at": NOW.isoformat(), "status": "DELAYED"}}


class FakeEdgar:
    enabled = True

    async def cik(self, t):
        return (1, "Acme Corp")

    async def financials(self, cik):
        return E.condense_facts(facts()), "live", NOW

    async def filings(self, cik):
        return {"sic_description": "Widgets", "fiscal_year_end": "1231", "exchanges": ["Nasdaq"], "filings": [{"form": "8-K", "filed": "2026-11-01", "items": [{"item": "2.02"}], "link": "https://sec.example/q"}]}, "live", NOW


def test_research_assembles_every_block_and_says_what_is_missing():
    inst = I.resolve("AAPL")
    out = asyncio.run(R.StockResearch(FakeEdgar(), FakeFund(), None).research(inst, NOW))
    assert out["financials"]["available"] and len(out["financials"]["years"]) == 4 and out["valuation"]["values"]["pe"] == 12.0
    assert out["earnings"]["next_date"] == "2026-11-20" and out["earnings"]["guidance"]["available"] is False and out["earnings"]["consensus"]["available"] is False
    assert out["bull"] and out["bear"] and out["catalysts"][0]["date"] == "2026-11-20"
    assert any("guidance" in g.lower() for g in out["gaps"]) and out["errors"] == []


def test_one_source_failing_does_not_hide_the_others():
    inst = I.resolve("AAPL")
    out = asyncio.run(R.StockResearch(FakeEdgar(), FakeFund(fail=True), None).research(inst, NOW))
    assert out["valuation"] is None and out["financials"]["available"] and any("Valuation" in e for e in out["errors"])


def test_earnings_calendar_filters_by_window_and_sorts():
    class F(FakeFund):
        async def get(self, inst, force=False):
            s = await super().get(inst)
            s["next_earnings_date"] = {"AAPL": "2026-11-10", "MSFT": "2027-06-01", "NVDA": "2026-11-08"}[inst.symbol]
            return s
    insts = [I.resolve(s) for s in ("AAPL", "MSFT", "NVDA")]
    out = asyncio.run(R.StockResearch(FakeEdgar(), F(), None).earnings_calendar(insts, 30, NOW))
    assert [r["symbol"] for r in out["items"]] == ["NVDA", "AAPL"] and out["checked"] == 3 and out["items"][0]["days_away"] == 3


def test_routes_validate_and_work_in_demo_mode(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "r.db"), demo=True, alert_loop=False, news_loop=False)) as c:
        assert c.get("/api/stocks/NOPE123/research").status_code == 404
        assert c.get("/api/stocks/BTC-USD/research").status_code in (404, 422)
        r = c.get("/api/stocks/AAPL/research")
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["demo"] is True and d["financials"]["available"] is False and any("Demo" in e for e in d["errors"]) and d["gaps"]
        e = c.get("/api/stocks/earnings?symbols=AAPL,MSFT&days=60")
        assert e.status_code == 200 and e.json()["data"]["checked"] == 2
