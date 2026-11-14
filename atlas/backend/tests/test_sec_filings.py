"""SEC filings feed: parsed from a real trimmed EDGAR submissions response (Apple, fetched 2026-11-08), plain-English forms, links to sec.gov, honest when SEC is off."""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from atlas_api import instruments as I
from atlas_api.app import create_app
from atlas_api.db import DB
from atlas_api.stocks import edgar as E
from atlas_api.stocks import research as R

RAW = json.loads((Path(__file__).parent / "fixtures" / "sec_submissions_aapl_trimmed.json").read_text())
NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


def test_filings_are_parsed_newest_first_with_plain_meaning_and_sec_links():
    out = E.condense_filings(RAW)
    rows = out["filings"]
    assert out["name"] == "Apple Inc." and rows
    assert {r["form"] for r in rows} >= {"10-K", "10-Q", "8-K", "4"}
    k = next(r for r in rows if r["form"] == "10-K")
    assert k["meaning"] == "Annual report" and k["importance"] == "high" and k["link"].startswith("https://www.sec.gov/Archives/edgar/data/320193/")
    e = next(r for r in rows if r["form"] == "8-K" and r["items"])
    assert all(i["meaning"] for i in e["items"])
    f4 = next(r for r in rows if r["form"] == "4")
    assert "Insider" in f4["meaning"] and f4["link"] and ".." not in f4["link"]


def test_unknown_forms_and_hostile_document_names_are_dropped_or_unlinked():
    raw = {"cik": 1, "name": "X", "filings": {"recent": {"form": ["10-K", "ZZZ", "8-K"], "accessionNumber": ["0000000001-26-000001"] * 3, "filingDate": ["2026-01-01"] * 3,
                                                          "primaryDocument": ["a.htm", "b.htm", "../../etc/passwd"], "items": ["", "", "2.02"]}}}
    rows = E.condense_filings(raw)["filings"]
    assert [r["form"] for r in rows] == ["10-K", "8-K"] and rows[1]["link"] is None


class FakeEdgar:
    enabled = True

    async def cik(self, t):
        return (320193, "Apple Inc.") if t == "AAPL" else None

    async def all_filings(self, cik):
        return E.condense_filings(RAW), "live", NOW


def feed(**kw):
    s = R.StockResearch(kw.pop("edgar", FakeEdgar()), None, None, demo=kw.pop("demo", False))
    return asyncio.run(s.filings_feed([I.resolve("AAPL"), I.resolve("SPY")], now=NOW, **kw))


def test_feed_filters_by_form_sorts_and_reports_missing_companies():
    r = feed(forms=["10-K", "10-Q"], days=3000)
    assert r["items"] and all(x["form"] in ("10-K", "10-Q") for x in r["items"]) and r["items"][0]["filed"] >= r["items"][-1]["filed"]
    assert r["items"][0]["symbol"] == "AAPL" and "official" in r["source"] and "does not say what a given filing contains" in r["note"]
    assert any("SPY" in e for e in r["errors"])            # an ETF has no SEC company: said plainly


def test_feed_honours_the_window_and_the_limit():
    assert len(feed(limit=3, days=3000)["items"]) == 3
    assert feed(days=1)["items"] == [] or all(x["filed"] >= "2026-11-07" for x in feed(days=1)["items"])


def test_without_a_contact_the_feed_says_how_to_fix_it():
    class Off(FakeEdgar):
        enabled = False
    r = feed(edgar=Off())
    assert r["items"] == [] and r["needs_contact"] and "ATLAS_SEC_CONTACT" in r["errors"][0]


def test_demo_mode_invents_no_filings():
    r = feed(demo=True)
    assert r["items"] == [] and "Demo mode" in r["errors"][0]


def test_edgar_client_caches_the_filing_list_and_sends_the_contact(tmp_path):
    seen = []

    def handler(req):
        seen.append(req.headers["user-agent"])
        return httpx.Response(200, json=RAW)
    c = E.EdgarClient(DB(str(tmp_path / "e.db")), contact="me@example.com", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    a = asyncio.run(c.all_filings(320193))
    b = asyncio.run(c.all_filings(320193))
    assert a[1] == "live" and b[1] == "cache" and len(seen) == 1 and "me@example.com" in seen[0]


def test_route_in_demo_mode(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "f.db"), demo=True, alert_loop=False)) as c:
        d = c.get("/api/stocks/filings?symbols=AAPL,MSFT&forms=10-K,8-K").json()["data"]
        assert d["demo"] is True and d["items"] == [] and d["forms"] == ["10-K", "8-K"]
