"""btcquant research run: all 100 configurations are logged, the families that pass the admission gates become challengers with their own paper accounts, the run happens once per protocol version and data version,
and the report says what it must and never claims an edge. Two synthetic datasets: a planted strong trend edge (seed 6, where seven trend-like families are admitted) and pure noise (seed 1, where none is)."""
import json

import numpy as np
import pytest

from atlas_api.btcquant import backtest as B
from atlas_api.btcquant import calibration as K
from atlas_api.btcquant import config as C
from atlas_api.btcquant import data as D
from atlas_api.btcquant import paper as P
from atlas_api.btcquant import registry as R
from atlas_api.btcquant import research as RS
from atlas_api.btcquant import strategies as S


@pytest.fixture(scope="module")
def edge(tmp_path_factory):
    root = tmp_path_factory.mktemp("edge")
    prep = B.Prepared(K.synthetic_candles("planted_strong", 6))
    reg, book = R.Registry(root / "registry"), P.PaperBook(root / "state")
    res = RS.run_research(prep, reg, book, root / "reports", n_shifts=40, now=lambda: "2026-11-15T12:00:00Z")
    return {"root": root, "prep": prep, "reg": reg, "book": book, "res": res}


@pytest.fixture(scope="module")
def noise(tmp_path_factory):
    root = tmp_path_factory.mktemp("noise")
    prep = B.Prepared(K.synthetic_candles("null_mild", 1))
    reg, book = R.Registry(root / "registry"), P.PaperBook(root / "state")
    res = RS.run_research(prep, reg, book, root / "reports", n_shifts=40)
    return {"root": root, "prep": prep, "reg": reg, "book": book, "res": res}


def test_every_configuration_is_logged_and_exactly_one_per_family_carries_the_outcome(edge):
    cands = edge["reg"].candidates()
    assert len(cands) == 100 and len({c["spec_hash"] for c in cands}) == 100 and all(c["protocol"] == "1.2" and c["run"] == "research" and c["data"]["candles"] == 2875 for c in cands)
    decided = [c for c in cands if c["decision"] != "tested, not selected on TRAIN"]
    assert len(decided) == 12 and {c["family"] for c in decided} == {f.id for f in S.RESEARCH} and all(c["decision"] in ("admitted", "rejected", "too_thin") for c in decided)
    assert {c["family"]: c["decision"] for c in decided} == edge["res"]["outcomes"]
    assert all("information_ratio_validation" in c["results"] and "gates_failed" in c["results"] for c in decided)
    other = next(c for c in cands if c["decision"] == "tested, not selected on TRAIN")
    assert {"train_sharpe", "score", "trades", "turnover", "validation_sharpe"} <= set(other["results"])


def test_the_admitted_families_become_challengers_with_a_paper_account_each(edge):
    adm = edge["res"]["admitted"]
    assert len(adm) == 7 and {a["family"] for a in adm} == {"sma_cross", "donchian", "ma_atr_trend", "tsmom", "rsi_momentum", "mom_vol", "vol_breakout"}
    ch = edge["reg"].challengers()
    assert sorted(ch) == sorted(a["spec_hash"] for a in adm) and edge["reg"].check_frozen() == []
    for a in adm:
        aid = RS.account_id(a["family"], a["params"])
        assert edge["book"].exists(aid) and edge["book"].load(aid)[1]["stage"] == "challenger" and aid == f"{a['family']}-{a['spec_hash'][:8]}"
    assert edge["book"].ids() == sorted(RS.account_id(a["family"], a["params"]) for a in adm)


def test_renamed_copies_among_the_admitted_are_counted_together(edge):
    logged = {c["spec_hash"]: c for c in edge["reg"].candidates()}
    copies = [a for a in edge["res"]["admitted"] if a["counted_with"]]
    assert copies                                                                      # in this dataset several trend rules take nearly the same positions
    for c in copies:
        rec = logged[c["spec_hash"]]
        assert rec["counted_with"] == c["counted_with"] and c["counted_with"] in logged and rec["duplicates"][0]["spec_hash"] == c["counted_with"]
        assert rec["duplicates"][0]["correlation"] >= R.DUP_CORRELATION and c["counted_with"] != c["spec_hash"]
    ch = edge["reg"].challengers()
    assert all(ch[c["spec_hash"]]["counted_with"] == c["counted_with"] for c in copies) and sum(1 for a in edge["res"]["admitted"] if not a["counted_with"]) >= 1


def test_the_run_is_recorded_and_the_files_are_written(edge):
    runs = RS.previous_runs(edge["reg"])
    assert len(runs) == 1 and runs[0]["protocol"] == "1.2" and runs[0]["ran_at"] == "2026-11-15T12:00:00Z" and runs[0]["data"]["sha256"] == RS.data_version(edge["prep"])["sha256"] and runs[0]["n_trials"] == 100
    full = json.loads((edge["root"] / "reports" / "research_1.2.json").read_text())
    assert full["evaluation"]["n_trials"] == 100 and set(full["evaluation"]["families"]) == {f.id for f in S.RESEARCH} and full["admitted"] == edge["res"]["admitted"] == runs[0]["admitted"]
    assert (edge["root"] / "reports" / "research_1.2.md").read_text() == RS.research_report({k: v for k, v in edge["res"].items() if k != "evaluation"}, edge["res"]["evaluation"])


def test_the_report_with_admissions_says_what_admission_means_and_claims_no_edge(edge):
    text = (edge["root"] / "reports" / "research_1.2.md").read_text()
    assert "**7 of 12 families were admitted as challengers**" in text and "not evidence of an edge" in text and "CALIBRATION.md" in text and "forward record of at least 90 days" in text
    assert "## Credibly profitable?\n\nNo." in text and "makes money" in text and text.count("Nothing here is evidence") == 1 and "not a recommendation" in text
    for fid in (f.id for f in S.RESEARCH):
        assert f"`{fid}`" in text
    assert "TEST period" in text and "Coinbase BTC-USD, not Binance" in text and "no order was placed anywhere" in text
    assert "independent idea" in text


def test_a_second_run_on_the_same_protocol_and_data_is_refused_and_forcing_it_is_logged_as_a_repeat(edge):
    with pytest.raises(RS.ResearchAlreadyRun, match="never improved"):
        RS.run_research(edge["prep"], edge["reg"], edge["book"], None, n_shifts=40)
    assert len(edge["reg"].candidates()) == 100 and len(RS.previous_runs(edge["reg"])) == 1


def test_new_data_or_a_new_protocol_version_is_a_new_run(edge, tmp_path, monkeypatch):
    longer = K.synthetic_candles("planted_strong", 6)
    extra = (longer[-1][0] + 86400,) + longer[-1][1:]
    prep2 = B.Prepared(longer + [extra])
    reg2 = R.Registry(edge["root"] / "registry")
    assert RS.data_version(prep2)["sha256"] != RS.data_version(edge["prep"])["sha256"]
    monkeypatch.setattr(RS.V, "evaluate_all", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("reached the evaluation: not refused")))
    with pytest.raises(RuntimeError, match="reached the evaluation"):
        RS.run_research(prep2, reg2, None, None)                                      # different data: not refused
    monkeypatch.setattr(C, "PROTOCOL_VERSION", "1.3")
    with pytest.raises(RuntimeError, match="reached the evaluation"):
        RS.run_research(edge["prep"], reg2, None, None)                                # same data, other protocol: not refused


def test_with_no_admissions_nothing_is_opened_and_the_report_says_so(noise):
    assert noise["res"]["admitted"] == [] and noise["reg"].challengers() == {} and noise["book"].ids() == [] and len(noise["reg"].candidates()) == 100
    text = (noise["root"] / "reports" / "research_1.2.md").read_text()
    assert "**No family was admitted.**" in text and "main portfolio stays in cash" in text and "## Credibly profitable?" in text
    assert all(c["decision"] in ("rejected", "too_thin", "tested, not selected on TRAIN") for c in noise["reg"].candidates())


def test_the_data_version_is_the_hash_of_the_candles(edge):
    v = RS.data_version(edge["prep"])
    m = D.manifest(edge["prep"].candles, C.DAY)
    assert v == {"sha256": m["sha256"], "candles": 2875, "first": "2019-01-01T00:00:00Z", "last": "2026-11-14T00:00:00Z"}
    assert RS.account_id("tsmom", {"L": 30}) == f"tsmom-{S.spec_hash('tsmom', {'L': 30})[:8]}"


def test_forcing_a_repeat_logs_every_candidate_again_as_a_repeat_and_does_not_open_accounts_twice(edge, monkeypatch):
    monkeypatch.setattr(RS.V, "evaluate_all", lambda *a, **k: edge["res"]["evaluation"])                         # the evaluation itself is not the point here
    before = len(edge["reg"].candidates())
    again = RS.run_research(edge["prep"], edge["reg"], edge["book"], None, force=True)
    cands = edge["reg"].candidates()
    assert len(cands) == before + 100 and all(c["repeat"] for c in cands[before:]) and len(RS.previous_runs(edge["reg"])) == 2
    assert len(edge["reg"].challengers()) == 7 and len(edge["book"].ids()) == 7 and len(again["admitted"]) == 7
    with np.load(edge["reg"].positions_path) as z:
        assert len(z.files) == 12                                                                                  # one schedule per chosen configuration, kept for the renamed-copy check
    assert (edge["root"] / "reports" / "research_1.2.json").exists()


def test_without_a_report_directory_or_a_book_only_the_registry_is_written(edge, tmp_path, monkeypatch):
    monkeypatch.setattr(RS.V, "evaluate_all", lambda *a, **k: edge["res"]["evaluation"])
    reg = R.Registry(tmp_path / "registry")
    out = RS.run_research(edge["prep"], reg, None, None)
    assert len(out["admitted"]) == 7 and len(reg.challengers()) == 7 and not (tmp_path / "reports").exists() and not (tmp_path / "state").exists()


def test_the_command_line_runs_once_and_refuses_a_repeat(tmp_path, monkeypatch, capsys):
    cs = K.synthetic_candles("null_mild", 2)
    (tmp_path / "data").mkdir()
    D.save(tmp_path / "data" / "btcusd_1d.csv", cs)
    monkeypatch.setattr(D, "daily_path", lambda: tmp_path / "data" / "btcusd_1d.csv")
    monkeypatch.setattr(C, "REPORT_DIR", tmp_path / "reports")
    monkeypatch.setattr(R.Registry, "__init__", lambda self, root=None, now=R._now: (setattr(self, "root", tmp_path / "registry"), setattr(self, "_now", now))[0])
    monkeypatch.setattr(P.PaperBook, "__init__", lambda self, root=None, now=P._now: (setattr(self, "root", tmp_path / "state"), setattr(self, "_now", now))[0])
    real = RS.V.evaluate_all
    monkeypatch.setattr(RS.V, "evaluate_all", lambda prep, **k: real(prep, n_shifts=20))
    assert RS.main(["research"]) == 0
    out = capsys.readouterr().out
    assert "research run done: protocol 1.2, data to 2026-11-14" in out and "of 12 families admitted" in out and out.count("\n") == 13
    assert (tmp_path / "reports" / "research_1.2.md").exists() and len((tmp_path / "registry" / "research_runs.jsonl").read_text().splitlines()) == 1
    assert RS.main(["research"]) == 1 and "research run refused" in capsys.readouterr().out
    (tmp_path / "data" / "btcusd_1d.csv").write_bytes(b"")
    D.save(tmp_path / "data" / "btcusd_1d.csv", cs[:100])
    assert RS.main(["research"]) == 1 and "stopped" in capsys.readouterr().out
