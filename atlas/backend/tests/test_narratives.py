"""Narrative of the day: scoring from known inputs, no repeats within 5 days, stability within a day, honest gaps, demo labelling, route."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from atlas_api.app import create_app
from atlas_api.db import DB
from atlas_api.discover import narratives as N
from atlas_api.models import Candle, DataStatus
from atlas_api.scanner.bars import BarBatch

NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
DAY = 86400


def bars(growth: float, n: int = 120, vol_last: float = 1.0, base: float = 100.0) -> list[Candle]:
    """Daily bars compounding at `growth` per day; the last bar's volume is vol_last times normal."""
    out, px = [], base
    for i in range(n):
        o, px = px, px * (1 + growth)
        out.append(Candle(time=1_700_000_000 + i * DAY, open=o, high=max(o, px) * 1.01, low=min(o, px) * 0.99, close=px, volume=(1_000_000 * vol_last) if i == n - 1 else 1_000_000))
    return out


class FakeBars:
    name = "fake"

    def __init__(self, hot: str):
        self.hot = hot

    async def fetch(self, symbols, progress=None):
        theme = next(t for t in N.THEMES if t["id"] == self.hot)
        data = {s: bars(0.004 if s in theme["tickers"] else 0.0005, vol_last=1.8 if s in theme["tickers"] else 1.0) for s in symbols}
        data[N.BENCH] = bars(0.0005)
        return BarBatch(bars=data, provider="fake daily bars", status=DataStatus.HISTORICAL, as_of=NOW)


class FakeNews:
    def __init__(self, per_kw: int = 0, fail: bool = False):
        self.per_kw, self.fail = per_kw, fail

    def items(self, symbol=None, q=None, hours=72, limit=60):
        if self.fail:
            raise RuntimeError("db locked")
        return {"items": [{"title": f"{q} headline {i}", "link": f"https://example.com/{q}/{i}", "feed": "Wire", "published": f"2026-11-08T0{i}:00:00+00:00"} for i in range(self.per_kw)]}


def svc(tmp_path, hot="quantum", news=None, name="n.db"):
    return N.NarrativeService(DB(str(tmp_path / name)), FakeBars(hot), news or FakeNews(), demo=False)


def run(s, now=NOW, **kw):
    return asyncio.run(s.today(now=now, **kw))


def test_the_theme_with_the_strongest_basket_wins_and_every_figure_is_explained(tmp_path):
    r = run(svc(tmp_path, "quantum"))
    assert r["theme"] == "quantum" and r["name"] == "Quantum computing"
    f = r["facts"]
    assert f["median_return_1m_pct"] > f["spy_return_1m_pct"] and f["relative_1m_pct"] > 5 and f["share_above_50d"] == 1.0 and f["median_volume_vs_normal"] == pytest.approx(1.8, abs=0.01)
    assert any("S&P 500" in w for w in r["why_now"]) and r["risks"] and r["context_note"].startswith("Written by hand")
    assert {b["symbol"] for b in r["basket"]} == set(next(t for t in N.THEMES if t["id"] == "quantum")["tickers"]) and "not a recommendation" in r["disclaimer"].lower()


def test_score_weights_and_scales_follow_the_published_method():
    t = next(x for x in N.THEMES if x["id"] == "quantum")
    feats = {s: {"sufficient": True, "ret_21d": 10.0, "above_sma50": True, "rvol": 1.5, "atr_pct": 3.0} for s in t["tickers"]}
    m = N.theme_metrics(t, feats, {"ret_21d": 0.0}, 5)
    # relative strength 50+10*2.5=75, breadth 100, volume 50+0.5*50=75, news 50
    assert m["parts"] == {"relative_strength": 75.0, "breadth": 100.0, "volume": 75.0, "news": 50.0}
    assert m["score"] == pytest.approx(0.40 * 75 + 0.25 * 100 + 0.15 * 75 + 0.20 * 50, abs=0.05)


def test_missing_news_is_left_out_and_the_rest_rescaled_not_counted_as_zero():
    t = next(x for x in N.THEMES if x["id"] == "quantum")
    feats = {s: {"sufficient": True, "ret_21d": 0.0, "above_sma50": True, "rvol": 1.0, "atr_pct": 3.0} for s in t["tickers"]}
    with_zero = N.theme_metrics(t, feats, {"ret_21d": 0.0}, 0)["score"]
    without = N.theme_metrics(t, feats, {"ret_21d": 0.0}, None)
    assert without["parts"]["news"] is None and without["score"] == pytest.approx((0.40 * 50 + 0.25 * 100 + 0.15 * 50) / 0.80, abs=0.05) and without["score"] > with_zero


def test_too_few_stocks_with_data_means_no_score():
    t = next(x for x in N.THEMES if x["id"] == "quantum")
    assert N.theme_metrics(t, {t["tickers"][0]: {"sufficient": True, "ret_21d": 5.0}}, None, 0) is None


def test_a_theme_is_not_repeated_within_five_days(tmp_path):
    s = svc(tmp_path, "quantum")
    first = run(s, NOW)
    assert first["theme"] == "quantum"
    second = run(s, NOW + timedelta(days=1))
    assert second["theme"] != "quantum" and "quantum" in second["recent_excluded"] and any("scored highest but was featured" in n for n in second["notes"])
    later = run(s, NOW + timedelta(days=7))             # outside the 5-day window the strongest theme is allowed again
    assert later["theme"] == "quantum"


def test_the_day_is_stable_and_refresh_recomputes(tmp_path):
    s = svc(tmp_path, "quantum")
    a = run(s)
    s.bars = FakeBars("space")                         # the market "changes" within the same day
    assert run(s)["theme"] == a["theme"]
    assert run(s, refresh=True)["theme"] == "space"
    assert [h["theme"] for h in s.history()] == ["space"]


def test_headlines_come_from_the_feeds_and_a_news_failure_only_drops_the_news_score(tmp_path):
    r = run(svc(tmp_path, "quantum", FakeNews(per_kw=3)))
    assert r["facts"]["headlines_48h"] == 3 and len(r["headlines"]) == 3 and all(h["link"].startswith("https://") for h in r["headlines"])
    r2 = run(svc(tmp_path, "quantum", FakeNews(fail=True), name="n2.db"))
    assert r2["theme"] == "quantum" and r2["facts"]["headlines_48h"] is None and r2["parts"]["news"] is None and any("not available" in w for w in r2["why_now"])


def test_no_price_data_gives_no_narrative_instead_of_a_guess(tmp_path):
    class Empty:
        name = "empty"

        async def fetch(self, symbols, progress=None):
            return BarBatch(bars={}, provider="none", notes=["Yahoo unreachable"])
    s = N.NarrativeService(DB(str(tmp_path / "e.db")), Empty(), FakeNews())
    r = run(s)
    assert r["theme"] is None and any("No theme had enough price data" in n for n in r["notes"]) and s.history() == []


def test_every_theme_has_context_risks_keywords_and_a_basket():
    ids = [t["id"] for t in N.THEMES]
    assert len(ids) == len(set(ids)) >= 12
    for t in N.THEMES:
        assert len(t["tickers"]) >= N.MIN_NAMES and t["keywords"] and t["context"] and len(t["risks"]) >= 3
        assert len(t["keywords"]) <= N.MAX_KEYWORDS
        assert not any(w in " ".join(t["risks"] + [t["context"]]).lower() for w in ("will soar", "buy now", "guaranteed"))


def test_route_in_demo_mode_is_labelled(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "r.db"), demo=True, alert_loop=False, news_loop=False)) as c:
        d = c.get("/api/discover/narrative").json()["data"]
        assert d["demo"] is True and "disclaimer" in d
        assert c.get("/api/discover/narrative/history").status_code == 200
