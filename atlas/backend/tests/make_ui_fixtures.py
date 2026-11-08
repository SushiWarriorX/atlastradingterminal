"""Writes UI test fixtures from the REAL backend code, using SYNTHETIC companies (see research_fixtures.py): five company types for the research page, plus the listings and candidates feeds.

Run from atlas/backend:  python3 tests/make_ui_fixtures.py ../web/e2e/fixtures
Nothing here is real company data; every name says (synthetic). The listings feed uses the real Nasdaq IPO calendar fixtures saved in tests/fixtures.
"""
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx  # noqa: E402

import research_fixtures as X  # noqa: E402
from atlas_api.db import DB  # noqa: E402
from atlas_api.discover import listings as L  # noqa: E402
from atlas_api.discover.listings_service import ListingsService  # noqa: E402
from atlas_api.discover.newtome import NewToMe  # noqa: E402
from atlas_api.discover.store import DiscoveryStore  # noqa: E402
from atlas_api.research import facts as F  # noqa: E402
from atlas_api.research import service as S  # noqa: E402

NOW = datetime(2026, 2, 1, 12, tzinfo=timezone.utc)
KINDS = {"software": (X.software, 7372, 40.0), "mature": (X.mature, 3490, 40.0), "recent_ipo": (X.recent_ipo, 7372, 20.0), "loss_making": (X.loss_making_software, 7372, 10.0), "bank": (X.bank, 6022, 20.0)}


def research(kind: str) -> dict:
    mk, sic, price = KINDS[kind]
    now = datetime(2026, 11, 8, 12, tzinfo=timezone.utc) if kind == "recent_ipo" else NOW                      # the recent listing's three quarters end in September 2026
    out = S.assemble(F.condense(mk(), now.date()), sic, price, now.isoformat(), "test quote (synthetic)", now)
    return {"symbol": kind.upper(), "as_of": now.isoformat(), "demo": False, "errors": [], "available": True, **out,
            "sources": {"filings": {"origin": "fixture", "fetched_at": NOW.isoformat(), "source": "SYNTHETIC SEC-schema fixture (not real company data)"}, "submissions": None},
            "my_state": {"state": {"symbol": kind.upper(), "first_seen_at": None, "opened_at": NOW.isoformat(), "saved_at": None, "dismissed_at": None, "researched_at": None, "shown_count": 0}, "notes": [], "last_review": None}}


def listings() -> dict:
    months = {m: json.loads((Path(__file__).parent / "fixtures" / f"nasdaq_ipo_{m}.json").read_text()) for m in ("2026-09", "2026-10", "2026-11")}
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=months.get(req.url.params["date"], {"status": {"rCode": 200}, "data": {}}))))
    db = DB(":memory:")
    svc = ListingsService(db, L.NasdaqIpoFeed(db, client), None, None)
    now = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
    asyncio.run(svc.refresh(now))
    feed = svc.read(30, now)
    for item in feed["recent"]:
        if item["symbol"] == "NARA":                                         # show one confirmed and SEC-verified deal so the UI states are all exercised
            item.update(status="trading", first_trade_date="2026-11-03", status_text="Confirmed trading: first trading day 2026-11-03 (from an independent price history).",
                        verification={"verified": True, "note": "Final prospectus (424B4) filed 2026-11-04.", "evidence": {"form": "424B4", "filed": "2026-11-04", "link": "https://www.sec.gov/Archives/edgar/data/1/x/y.htm"}},
                        newness={"new": True, "reason": "Genuinely new: no price history before 2026-11-03."})
            feed["counts"]["confirmed_trading"] = 1
            feed["counts"]["verified_by_sec"] = 1
    return feed


def candidates() -> dict:
    rows = [{"symbol": s, "name": f"{n} (synthetic)", "lastsale": f"${p}", "marketCap": "2500000000", "volume": "900000", "country": "United States", "ipoyear": "2016", "sector": sec, "industry": "Prepackaged software"}
            for s, n, sec, p in (("CLDX", "Cloud Software Inc", "Technology", "30.00"), ("DATA", "Data Platform Inc", "Technology", "40.00"), ("MATU", "Mature Industrial Co", "Industrials", "40.00"))]
    letters = "ABCDEFGHIJ"
    rows += [{"symbol": f"F{a}{b}", "name": f"Filler {a}{b} Inc", "lastsale": "$10.00", "marketCap": "900000000", "volume": "500000", "country": "China", "ipoyear": "", "sector": "Finance", "industry": "x"} for a in letters for b in letters]
    mk = {"CLDX": (X.software, 7372), "DATA": (X.software, 7372), "MATU": (X.mature, 3490)}

    async def researcher(symbol, price, price_time, price_source, now):
        if symbol not in mk:
            return {"available": False, "reason": f"No SEC company with ticker {symbol} was found"}
        m, sic = mk[symbol]
        return {**S.assemble(F.condense(m(), NOW.date()), sic, price, price_time, price_source, NOW), "available": True}
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"data": {"rows": rows}})))
    db = DB(":memory:")
    n = NewToMe(db, DiscoveryStore(db), researcher, client, False)
    asyncio.run(n.refresh(NOW, study=300))
    return n.read({"min_market_cap": 0, "max_market_cap": float("inf"), "min_dollar_volume": 0}, now=NOW, mark=False)


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "fixtures_out")
    out.mkdir(parents=True, exist_ok=True)
    for k in KINDS:
        (out / f"research_{k}.json").write_text(json.dumps(research(k), indent=1, default=str))
    (out / "listings.json").write_text(json.dumps(listings(), indent=1, default=str))
    (out / "candidates.json").write_text(json.dumps(candidates(), indent=1, default=str))
    print("wrote", sorted(p.name for p in out.iterdir()))
