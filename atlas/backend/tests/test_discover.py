"""Discover: scales, factor rescaling, ranking rules, sector cap, daily persistence, filters, honest failure, demo run, routes."""
import asyncio
import math
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from atlas_api.app import create_app
from atlas_api.db import DB
from atlas_api.discover import score as SC
from atlas_api.discover.service import DiscoverService
from atlas_api.models import Candle, DataStatus
from atlas_api.scanner.bars import BarBatch
from atlas_api.scanner.universe import CORE
from atlas_api.stocks import edgar as E

NOW = datetime(2026, 11, 5, 14, tzinfo=timezone.utc)
FEAT = dict(price=100.0, ret_126d=30.0, above_sma50=True, above_sma200=True, dist_52w_high_pct=-3.0, dollar_volume_avg20=200e6, dist_sma50_pct=8.0)
FIN = {"last": {"revenue_growth_pct": 20.0, "operating_margin_pct": 25.0, "fcf_margin_pct": 15.0, "eps_diluted": 5.0, "net_cash": 1e9, "debt_to_equity": 0.4}, "cagr": 18.0, "pe": 20.0}


def test_scales_are_piecewise_linear_and_clamped():
    assert SC.interp(-5, [(0, 0), (10, 50), (25, 100)]) == 0 and SC.interp(5, [(0, 0), (10, 50), (25, 100)]) == 25 and SC.interp(99, [(0, 0), (10, 50), (25, 100)]) == 100
    assert SC.interp(None, [(0, 0), (1, 1)]) is None


def test_factors_and_total_follow_the_stated_weights():
    f = SC.factors(FEAT, FIN)
    assert set(f) == set(SC.WEIGHTS) and all(v is not None for v in f.values())
    assert f["balance_sheet"]["score"] == 100 and f["liquidity"]["score"] == 100
    assert f["valuation"]["score"] == pytest.approx(SC.interp(20, [(15, 100), (25, 70)]))
    sc, cov = SC.total(f)
    assert cov == 6 and sc == pytest.approx(sum(SC.WEIGHTS[k] * f[k]["score"] for k in f))
    assert sum(SC.WEIGHTS.values()) == pytest.approx(1.0)


def test_missing_factors_are_left_out_not_guessed_and_too_few_means_unranked():
    f = SC.factors(FEAT, None)                                       # no filings: only momentum and liquidity
    assert f["growth"] is None and f["valuation"] is None
    assert SC.total(f)[0] is None
    one_missing = SC.factors(FEAT, {**FIN, "last": {**FIN["last"], "eps_diluted": None}, "pe": None})
    sc, cov = SC.total(one_missing)
    assert cov == 5 and sc is not None


def test_a_loss_scores_zero_on_valuation_and_is_flagged():
    fin = {**FIN, "last": {**FIN["last"], "eps_diluted": -1.0}, "pe": None}
    assert SC.factors(FEAT, fin)["valuation"]["score"] == 0
    assert any("Lost money" in r for r in SC.risks(FEAT, fin))


def test_risks_are_rule_based_and_always_name_the_data_age():
    r = SC.risks({**FEAT, "dist_sma50_pct": 30, "ret_126d": 80, "dollar_volume_avg20": 15e6}, {**FIN, "pe": 70})
    text = " ".join(r)
    assert "Expensive" in text and "Stretched" in text and "up 80%" in text and "thinly traded" in text and "up to a year old" in text
    assert not any(w in text.lower() for w in ("buy", "sell", "will rise", "price target"))


class Bars:
    name = "fake"

    def __init__(self, fail=False, rets=None):
        self.fail, self.rets = fail, rets or {}

    async def fetch(self, symbols, progress=None):
        if self.fail:
            return BarBatch({}, {s: "down" for s in symbols}, "fake", DataStatus.HISTORICAL, None, ["bars unavailable"])
        out = {}
        for i, s in enumerate(symbols):
            drift = self.rets.get(s, 0.0004 + (i % 7) * 0.0002)
            px, rows = 50.0 + i, []
            for k in range(260):
                o = px
                px *= 1 + drift + 0.004 * math.sin(k / 3 + i)
                rows.append(Candle(time=1_700_000_000 + 86400 * k, open=o, high=max(o, px) * 1.003, low=min(o, px) * 0.997, close=px, volume=5e6 + 1e5 * i))
            out[s] = rows
        return BarBatch(out, {}, "fake", DataStatus.HISTORICAL, NOW, [])


class Edgar:
    enabled = True

    def __init__(self, missing=()):
        self.missing = set(missing)

    async def cik(self, t):
        return None if t in self.missing else (abs(hash(t)) % 10**6, f"{t} Corp")

    async def financials(self, cik):
        g = 1.05 + (cik % 20) / 100
        yrs = [{"end": f"{2021 + i}-12-31", "revenue": 100.0 * g ** i, "gross_profit": 50 * g ** i, "operating_income": (10 + cik % 20) * g ** i, "net_income": 8 * g ** i, "eps_diluted": 2.0 + i,
                "operating_cash_flow": 20 * g ** i, "capex": 5.0, "cash": 30.0, "debt": 10.0 + cik % 50, "equity": 60.0, "assets": 100.0, "liabilities": 40.0} for i in range(5)]
        return {"name": "x", "years": yrs}, "live", NOW


def svc(tmp_path, bars=None, edgar=None, demo=False):
    return DiscoverService(DB(str(tmp_path / "d.db")), bars or Bars(), edgar or Edgar(), demo)


def test_shortlist_has_five_with_reasons_risks_evidence_and_a_sector_cap(tmp_path):
    s = svc(tmp_path)
    run = asyncio.run(s.shortlist(now=NOW))
    sl = run["shortlist"]
    assert len(sl) == 5 and [x["rank"] for x in sl] == [1, 2, 3, 4, 5]
    assert all(sl[i]["score"] >= sl[i + 1]["score"] for i in range(4))
    counts = {}
    for x in sl:
        counts[x["sector"]] = counts.get(x["sector"], 0) + 1
        assert x["reasons"] and x["risks"] and len(x["evidence"]) == 6 and x["coverage"] >= SC.MIN_FACTORS
        assert all(e["source"] and e["as_of"] for e in x["evidence"] if e["value"] is not None)
        assert x["as_of"]["prices"] and x["as_of"]["fiscal_year_end"] and x["asset_id"].startswith("EQUITY:")
    assert max(counts.values()) <= SC.MAX_PER_SECTOR
    assert run["method"]["weights"] == SC.WEIGHTS and run["gaps"] and "Not a recommendation" in run["disclaimer"]
    assert run["universe"]["size"] == len(CORE) and run["universe"]["scored"] <= 30


def test_same_inputs_same_shortlist_and_the_day_is_saved(tmp_path):
    a = asyncio.run(svc(tmp_path).shortlist(now=NOW))
    s = svc(tmp_path)
    asyncio.run(s.shortlist(now=NOW))
    s.bars = Bars(fail=True)                                            # a second call the same day must not re-scan
    again = asyncio.run(s.shortlist(now=NOW))
    assert [x["symbol"] for x in again["shortlist"]] == [x["symbol"] for x in a["shortlist"]]
    assert again["asof"] == "2026-11-05"


def test_failed_scan_keeps_the_last_good_shortlist_and_says_so(tmp_path):
    s = svc(tmp_path)
    good = asyncio.run(s.shortlist(now=NOW))
    s.bars = Bars(fail=True)
    later = datetime(2026, 11, 6, 14, tzinfo=timezone.utc)
    out = asyncio.run(s.shortlist(now=later))
    assert out["asof"] == good["asof"] and "last saved shortlist" in out["stale_notice"]


def test_no_filings_means_no_candidates_and_a_plain_reason(tmp_path):
    class Off(Edgar):
        enabled = False

        async def cik(self, t):
            return None
    run = asyncio.run(svc(tmp_path, edgar=Off()).shortlist(now=NOW))
    assert run["shortlist"] == [] and any("ATLAS_SEC_CONTACT" in n for n in run["notes"])


def test_filters_apply_to_the_saved_ranking(tmp_path):
    s = svc(tmp_path)
    run = asyncio.run(s.shortlist(now=NOW))
    sector = run["ranked"][0]["sector"]
    r = s.ranked(sector=sector)
    assert r["items"] and all(x["sector"] == sector for x in r["items"])
    assert all(x["score"] >= 60 for x in s.ranked(min_score=60)["items"])
    assert all(x["pe"] is not None and x["pe"] <= 30 for x in s.ranked(max_pe=30)["items"])
    assert all(x["revenue_growth_pct"] >= 8 for x in s.ranked(min_growth=8)["items"])
    assert s.ranked(min_score=101)["items"] == [] and s.ranked(limit=2)["items"].__len__() <= 2


def test_demo_run_is_labelled_synthetic_and_routes_work(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "x.db"), demo=True, alert_loop=False, news_loop=False)) as c:
        d = c.get("/api/discover/shortlist").json()["data"]
        assert d["demo"] is True and "synthetic" in d["data"]["fundamentals"] and len(d["shortlist"]) <= 5
        assert c.get("/api/discover/method").json()["data"]["weights"]["growth"] == 0.25
        r = c.get("/api/discover/ranked?min_score=0&limit=3").json()["data"]
        assert r["asof"] == d["asof"] and len(r["items"]) <= 3
        assert c.get("/api/discover/shortlist").json()["data"]["created_at"] == d["created_at"]      # served from the saved day
