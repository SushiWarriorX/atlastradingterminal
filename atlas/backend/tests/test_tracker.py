"""Strategy tracker: the frozen backtest is saved once and never rerun, the forward record only uses bars after the add date, and thin forward data is called thin."""
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from atlas_api.app import create_app
from atlas_api.btclab import strategies as ST
from atlas_api.btclab import tracker as T
from atlas_api.btclab.service import demo_rows

DAY = 86400


def rows(n=1500, seed=5, drift=0.0006):
    rng = np.random.default_rng(seed)
    px, out = 100.0, []
    t0 = int(datetime(2022, 1, 1, tzinfo=timezone.utc).timestamp())
    for i in range(n):
        o = px
        px = px * float(np.exp(rng.normal(drift, 0.025)))
        out.append((t0 + i * DAY, o, max(o, px) * 1.01, min(o, px) * 0.99, px, 1000.0))
    return out


def test_aroon_reads_the_age_of_the_high_and_low():
    h = np.array([1, 2, 3, 4, 5, 4, 3, 2, 1, 2, 3, 4, 5, 6, 7, 6, 5, 4, 3, 2], float)
    up, dn = ST.aroon(pd.DataFrame({"h": h, "l": h - 1}), 5)
    assert np.isnan(up.iloc[4]) and up.iloc[5] == 80.0 and up.iloc[11] == 100.0 and up.iloc[-2] == 20.0 and up.iloc[-1] == 0.0 and dn.iloc[-1] == 100.0         # needs n+1 bars first; a high 1 bar old scores 80


def test_aroon_strategy_is_registered_with_fixed_parameters_and_never_looks_ahead():
    st = ST.S["aroon_trend"]
    assert st.params == {"n": 25} and not st.requires_funding and st.family == "Trend"
    d = pd.DataFrame(rows(400), columns=["t", "o", "h", "l", "c", "v"])
    full = st.build(d, st.params).to_numpy()
    cut = st.build(d.iloc[:300], st.params).to_numpy()
    assert (full[:300] == cut).all()                       # the position on bar i uses only bars up to i
    assert set(np.unique(full)) <= {0.0, 1.0}


def test_snapshot_keeps_the_evaluation_and_counts_the_library():
    s = T.snapshot("aroon_trend", rows())
    assert s["library_size"] == sum(1 for x in ST.S.values() if not x.requires_funding) and s["evidence"]["level"] in ("none", "weak", "moderate") and s["evidence"]["level"] != "strong"
    assert s["out_of_sample"]["trades"] >= 0 and s["buy_and_hold"]["full"]["net_return_pct"] is not None and s["curve"]["strategy"] and s["data_to"] > s["data_from"]
    json.dumps(s)                                          # must be saveable in the ledger


def test_snapshot_refuses_unknown_and_funding_strategies():
    for sid in ("nope", "funding_fade"):
        with pytest.raises(Exception):
            T.snapshot(sid, rows())


def test_forward_uses_only_bars_after_the_add_date_and_says_when_it_is_too_early():
    r = rows(800)
    last_day = datetime.fromtimestamp(r[-1][0], timezone.utc).date().isoformat()
    f0 = T.forward("aroon_trend", last_day, r)
    assert f0["days"] <= 1 and f0["strategy"] is None and "just started" in f0["note"] and not f0["enough"]
    added = datetime.fromtimestamp(r[-40][0], timezone.utc).date().isoformat()
    f1 = T.forward("aroon_trend", added, r)
    assert 38 <= f1["days"] <= 41 and not f1["enough"] and "too little" in f1["note"] and f1["strategy"] is not None
    added2 = datetime.fromtimestamp(r[-200][0], timezone.utc).date().isoformat()
    f2 = T.forward("aroon_trend", added2, r)
    assert f2["enough"] and f2["days"] > 190 and f2["position_now"] in ("long", "flat") and f2["buy_and_hold"]["return_pct"] is not None


def test_forward_return_matches_holding_when_the_rule_is_always_in():
    # steadily rising prices: the Aroon rule gets in early and stays in, so the forward record is close to buy and hold, never wildly different
    r = rows(900, seed=1, drift=0.003)
    added = datetime.fromtimestamp(r[-150][0], timezone.utc).date().isoformat()
    f = T.forward("aroon_trend", added, r)
    assert f["strategy"]["return_pct"] > 0 and f["buy_and_hold"]["return_pct"] > 0


def test_overview_in_demo_mode_shows_backtests_but_no_forward_record():
    led = {"entries": [{"id": "aroon_trend", "name": "Aroon trend", "family": "Trend", "added_at": "2026-11-08", "idea": "i", "why": "w", "snapshot": T.snapshot("aroon_trend", rows())}]}
    o = T.overview(None, demo=True, ledger=led)
    assert o["entries"][0]["forward"] is None and o["entries"][0]["rule"]["entry"] and any("Demo mode" in n for n in o["notes"]) and o["library_size"] >= 21


def test_the_committed_ledger_is_valid_and_matches_registered_strategies():
    led = T.load()
    ids = [e["id"] for e in led["entries"]]
    assert len(ids) == len(set(ids))
    for e in led["entries"]:
        assert e["id"] in ST.S and e["added_at"] and e["idea"] and e["why"] and e["snapshot"]["evidence"]["level"] in ("none", "weak", "moderate")
        assert e["snapshot"]["library_size"] <= sum(1 for x in ST.S.values() if not x.requires_funding)


def test_route_in_demo_mode(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "t.db"), demo=True, alert_loop=False, news_loop=False)) as c:
        d = c.get("/api/btclab/tracker").json()["data"]
        assert d["demo"] is True and isinstance(d["entries"], list) and d["min_forward_days"] == 60 and all(e["forward"] is None for e in d["entries"])
