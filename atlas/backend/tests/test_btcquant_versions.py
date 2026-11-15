"""btcquant protocol versions: adding a family needs a new protocol version, and that must change nothing that was already registered. Every specification hash and paper account id that exists survives a version bump; a family
pre-registered under a later version carries that version; a research run covers only the families of its own version; and the runs of all versions read as one record in the dashboard, the daily report and the phone view,
tested end to end on a synthetic world with a toy family under version 1.3 (no real family is added by this file)."""
import dataclasses
import json
from pathlib import Path

import pytest

from atlas_api.btcquant import backtest as B
from atlas_api.btcquant import calibration as K
from atlas_api.btcquant import config as C
from atlas_api.btcquant import daily as DY
from atlas_api.btcquant import data as D
from atlas_api.btcquant import paper as P
from atlas_api.btcquant import registry as R
from atlas_api.btcquant import research as RS
from atlas_api.btcquant import strategies as S
from atlas_api.btcquant import view as V

DAY = 86400


def toy_family(since="1.3"):
    return dataclasses.replace(S.FAMILIES["tsmom"], id="toy", name="Toy momentum", grid={"L": [20, 45]}, since=since)


# ---------------------------------------------------------------------------------------------------------- hashes and account ids
def test_every_registered_hash_and_paper_account_id_survives_a_protocol_version_bump(monkeypatch):
    registry = C.ROOT / "registry" / "candidates.jsonl"
    accounts = sorted((C.ROOT / "state" / "accounts").glob("*.json"))
    if not registry.exists() or not accounts:
        pytest.skip("no research run has been committed")
    cands = [json.loads(line) for line in registry.read_text().splitlines() if line.strip()]
    metas = [json.loads(p.read_text())["meta"] for p in accounts]
    assert len(cands) >= 100 and len(metas) >= 15                                            # the twelve families' 100 configurations and the fifteen accounts of the first daily run, or more
    for bump in (None, "1.3", "2.0"):
        with monkeypatch.context() as m:
            if bump:
                m.setattr(C, "PROTOCOL_VERSION", bump)
            assert all(S.spec_hash(c["family"], c["params"]) == c["spec_hash"] for c in cands), bump                       # all 100 configurations of the real run
            for meta in metas:
                assert S.spec_hash(meta["family"], meta["params"]) == meta["spec_hash"], (bump, meta["id"])                  # every paper account keeps its specification
                if meta["stage"] in ("monitor", "challenger", "champion"):
                    assert RS.account_id(meta["family"], meta["params"]) == meta["id"], (bump, meta["id"])                   # and so its id: no duplicate would be opened


def test_a_family_pre_registered_under_a_later_version_carries_that_version_in_its_specification(monkeypatch):
    params = {"L": 20}
    old = S.spec_hash("tsmom", params)
    monkeypatch.setitem(S.FAMILIES, "toy", toy_family("1.3"))
    assert S.spec("toy", params)["protocol"] == "1.3" and S.spec("tsmom", params)["protocol"] == "1.2"
    under_13 = S.spec_hash("toy", params)
    monkeypatch.setitem(S.FAMILIES, "toy", toy_family("1.2"))
    assert S.spec_hash("toy", params) != under_13                                         # the same rules under another pre-registered version are another specification
    monkeypatch.setattr(C, "PROTOCOL_VERSION", "1.7")
    assert S.spec("nobody", params)["protocol"] == "1.7" and S.spec("tsmom", params)["protocol"] == "1.2"      # a name the library does not know falls back to the current version
    assert S.spec_hash("tsmom", params) == old


def test_a_research_run_covers_the_families_of_its_own_version_only(monkeypatch):
    assert RS.families_of("1.2") == [f.id for f in S.RESEARCH] and len(RS.families_of("1.2")) == 12 and RS.families_of("1.3") == []
    toy = toy_family("1.3")
    monkeypatch.setitem(S.FAMILIES, "toy", toy)
    monkeypatch.setattr(S, "RESEARCH", [*S.RESEARCH, toy])
    assert RS.families_of("1.3") == ["toy"] and len(RS.families_of("1.2")) == 12 and "toy" not in RS.families_of("1.2")
    assert S.n_configurations() == 102                                                    # N grows by the new family's configurations


def test_the_research_runs_of_all_versions_read_as_one_record():
    assert RS.merged([]) is None
    first = {"protocol": "1.2", "ran_at": "2026-11-15T10:34:08Z", "data": {"last": "2026-11-14T00:00:00Z"}, "n_trials": 100, "outcomes": {"b": "rejected", "a": "admitted"},
             "admitted": [{"family": "a", "spec_hash": "h1"}]}
    second = {"protocol": "1.3", "ran_at": "2026-11-17T01:00:00Z", "data": {"last": "2026-11-16T00:00:00Z"}, "n_trials": 102, "outcomes": {"toy": "too_thin", "b": "rejected"},
              "admitted": [{"family": "a", "spec_hash": "h1"}, {"family": "toy", "spec_hash": "h2"}]}
    m = RS.merged([first, second])
    assert m["protocol"] == "1.3" and m["ran_at"] == "2026-11-17T01:00:00Z" and m["data"] == second["data"] and m["n_trials"] == 102
    assert m["outcomes"] == {"a": "admitted", "b": "rejected", "toy": "too_thin"} and list(m["outcomes"]) == ["a", "b", "toy"]
    assert [a["spec_hash"] for a in m["admitted"]] == ["h1", "h2"]                          # a candidate admitted twice is one candidate
    assert m["runs"] == [{"protocol": "1.2", "ran_at": "2026-11-15T10:34:08Z", "families": ["a", "b"]}, {"protocol": "1.3", "ran_at": "2026-11-17T01:00:00Z", "families": ["b", "toy"]}]
    assert RS.merged([first])["runs"][0]["families"] == ["a", "b"] and len(RS.merged([first])["admitted"]) == 1
    later = {**second, "outcomes": {"a": "rejected"}}
    assert RS.merged([first, later])["outcomes"]["a"] == "rejected"                          # the newest outcome of a family is the one shown
    assert RS.merged([{**first, "admitted": [{"family": "tsmom"}]}])["admitted"] == [{"family": "tsmom"}]          # a record without a hash is kept, not an error


# ---------------------------------------------------------------------------------------------------------- the whole thing, end to end
@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Two research runs on one synthetic noise world (nothing is admitted): protocol 1.2 for the twelve families, then protocol 1.3 for a toy family, with a daily run after each. Everything that is checked is
    computed inside the patched block and returned as plain data, so no other test sees the toy family or the version number."""
    root = tmp_path_factory.mktemp("two_runs")
    candles = K.synthetic_candles("null_mild", 1)
    D.save(root / "data" / "btcusd_1d.csv", candles)
    now = candles[-1][0] + DAY + 900
    reg, book = R.Registry(root / "registry"), P.PaperBook(root / "state")
    out = {}
    with pytest.MonkeyPatch.context() as mp:
        prep = B.Prepared(candles)
        RS.run_research(prep, reg, book, root / "reports", n_shifts=40, now=lambda: "2026-11-15T12:00:00Z")
        dash1 = DY.run_daily(root=root, now=now, candles=candles)
        out["hashes_before"] = sorted(c["spec_hash"] for c in reg.candidates())
        out["ids_before"] = sorted(a["id"] for a in dash1["accounts"])
        out["report12_before"] = (root / "reports" / "research_1.2.json").read_bytes()
        out["md12"] = (root / "reports" / "research_1.2.md").read_text()
        out["view1"] = V.paper_view(root)
        toy = toy_family("1.3")
        mp.setitem(S.FAMILIES, "toy", toy)
        mp.setattr(S, "RESEARCH", [*S.RESEARCH, toy])
        mp.setattr(C, "PROTOCOL_VERSION", "1.3")
        out["second"] = RS.run_research(prep, reg, book, root / "reports", n_shifts=40, now=lambda: "2026-11-17T01:00:00Z")
        dash2 = DY.run_daily(root=root, now=now + DAY, candles=candles + [(candles[-1][0] + DAY,) + tuple(candles[-1][1:])])
        out["dash"] = dash2
        out["runs"] = RS.previous_runs(reg)
        out["hashes_after"] = sorted(c["spec_hash"] for c in reg.candidates())
        out["candidates"] = reg.candidates()
        out["report12_after"] = (root / "reports" / "research_1.2.json").read_bytes()
        out["files"] = sorted(p.name for p in (root / "reports").glob("research_*"))
        out["md13"] = (root / "reports" / "research_1.3.md").read_text()
        out["report_text"] = (root / "reports" / "latest.md").read_text()
        out["view"] = V.paper_view(root)
        out["again"] = DY.run_daily(root=root, now=now + DAY, candles=candles + [(candles[-1][0] + DAY,) + tuple(candles[-1][1:])])["opened_today"]
        out["toy_id"] = RS.account_id("toy", out["second"]["evaluation"]["families"]["toy"]["chosen"])
    out["dash1"] = dash1
    return out


def test_the_second_run_evaluates_only_the_new_family_and_counts_every_configuration_as_a_trial(world):
    second = world["second"]
    assert second["protocol"] == "1.3" and second["families"] == ["toy"] and list(second["outcomes"]) == ["toy"] and second["n_trials"] == 102
    assert list(second["evaluation"]["families"]) == ["toy"] and second["evaluation"]["n_trials"] == 102
    assert [r["protocol"] for r in world["runs"]] == ["1.2", "1.3"] and len(world["runs"][0]["outcomes"]) == 12 and len(world["runs"][0]["families"]) == 12


def test_the_twelve_earlier_results_and_their_hashes_stand_as_they_were(world):
    assert world["report12_before"] == world["report12_after"]                                    # the first report file is byte for byte what it was
    assert set(world["hashes_before"]) <= set(world["hashes_after"]) and len(world["hashes_before"]) == 100
    new = [c for c in world["candidates"] if c["family"] == "toy"]
    assert len(new) == 2 and {c["protocol"] for c in new} == {"1.3"} and {c["protocol"] for c in world["candidates"] if c["family"] != "toy"} == {"1.2"}
    assert sorted(set(world["hashes_after"]) - set(world["hashes_before"])) == sorted(c["spec_hash"] for c in new)
    assert world["files"] == ["research_1.2.json", "research_1.2.md", "research_1.3.json", "research_1.3.md"]


def test_the_version_bump_opens_one_new_account_and_no_duplicates(world):
    before, after = set(world["ids_before"]), sorted(a["id"] for a in world["dash"]["accounts"])
    assert before <= set(after) and len(after) == len(before) + 1 and sorted(set(after) - before) == [world["toy_id"]]
    assert len(set(after)) == len(after) and world["dash"]["opened_today"] == [world["toy_id"]] and world["again"] == []
    assert {a["id"]: a["stage"] for a in world["dash"]["accounts"]}[world["toy_id"]] == "monitor"          # nothing was admitted, so the new family is watched like the others


def test_the_dashboard_reads_both_runs_as_one_record(world):
    r = world["dash"]["research"]
    assert r["protocol"] == "1.3" and r["ran_at"] == "2026-11-17T01:00:00Z" and len(r["outcomes"]) == 13 and "toy" in r["outcomes"] and r["admitted"] == []
    assert [x["protocol"] for x in r["runs"]] == ["1.2", "1.3"] and r["runs"][1]["families"] == ["toy"] and len(r["runs"][0]["families"]) == 12
    assert world["dash1"]["research"]["runs"] == [{"protocol": "1.2", "ran_at": "2026-11-15T12:00:00Z", "families": sorted(world["dash1"]["research"]["outcomes"])}] and len(world["dash1"]["research"]["outcomes"]) == 12


def test_each_research_report_says_which_families_it_covers(world):
    md12, md13 = world["md12"], world["md13"]
    assert md12.startswith("# Research run, protocol 1.2,") and "This run covers" not in md12 and "| `tsmom` |" in md12 and "| `toy` |" not in md12
    assert md13.startswith("# Research run, protocol 1.3,") and "This run covers the 1 families pre-registered under protocol 1.3 (`toy`)" in md13 and "were not run again" in md13
    assert "The number of trials behind the deflated Sharpe ratio is 102" in md13 and "| `toy` |" in md13 and "| `tsmom` |" not in md13
    assert "no peer-reviewed test on Bitcoin" in md12 and "no peer-reviewed test on Bitcoin" not in md13                    # that caveat is about five of the first twelve families
    assert "**No family was admitted.**" in md13 and "timing p is the share of 40 shifted copies" in md13


def test_a_partial_run_that_admits_its_family_says_one_of_one(tmp_path):
    prep = B.Prepared(K.synthetic_candles("planted_strong", 6))
    ev = RS.V.evaluate_all(prep, families=["tsmom"], n_shifts=40, walk=False)
    result = {"protocol": "1.2", "ran_at": "2026-11-15T12:00:00Z", "data": RS.data_version(prep), "n_trials": ev["n_trials"], "outcomes": {"tsmom": ev["families"]["tsmom"]["outcome"]},
              "admitted": [{"family": "tsmom", "spec_hash": "x", "counted_with": None}]}
    text = RS.research_report(result, ev)
    assert "**1 of 1 families were admitted as challengers**" in text and "This run covers the 1 families pre-registered under protocol 1.2 (`tsmom`)" in text
    assert "timing p is the share of 40 shifted copies" in text and "`tsmom` has no peer-reviewed test" not in text


def test_the_daily_report_names_both_reports_and_counts_thirteen_families(world):
    text = world["report_text"]
    assert "The research runs so far (protocols 1.2 and 1.3;" in text and "admitted 0 of 13 families as challengers" in text and "`reports/research_1.2.md` and `reports/research_1.3.md`" in text
    assert "13 accounts watched at once will always have a lucky one" in text


def test_the_phone_view_keeps_the_old_verdicts_and_adds_the_new_one(world):
    v, v1 = world["view"], world["view1"]
    by = {a["family"]: a for a in v["accounts"] if a["stage"] == "monitor"}
    assert len(by) == 13 and by["toy"]["backtest"]["outcome"] in ("rejected", "too_thin")
    old = {a["family"]: a for a in v1["accounts"] if a["stage"] == "monitor"}
    assert len(old) == 12 and "toy" not in old
    for fam, a in old.items():                                                               # each earlier verdict, with its reasons and period figures, is still read from the first report file
        assert by[fam]["backtest"]["outcome"] == a["backtest"]["outcome"] and by[fam]["backtest"]["why"] == a["backtest"]["why"] and by[fam]["backtest"]["train"] == a["backtest"]["train"]
        assert a["backtest"]["train"] is not None
    assert by["toy"]["backtest"]["train"] is not None and by["toy"]["backtest"]["why"] and by["toy"]["name"] == "Toy momentum"           # and the new one from the second
    assert v["headline"].startswith("None of the 13 strategies passed the admission bar in the research runs up to 2026-11-17") and "research run of" not in v["headline"]
    assert v1["headline"].startswith("None of the 12 strategies passed the admission bar in the research run of 2026-11-15")
    assert v["counts"]["research_ran_at"] == "2026-11-17T01:00:00Z" and v["counts"]["research_admitted"] == 0 and v["counts"]["monitors"] == 13


def evaluation(**fams):
    return {"evaluation": {"families": {f: {"admission": {"failed": g}, "train": {"total_return": 0.1, "trades": 5}, "validation": None, "validation_timing": {"p": p}} for f, (g, p) in fams.items()}}}


def test_verdict_details_are_read_from_every_report_file_oldest_first_and_a_later_run_wins(tmp_path):
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "research_1.2.json").write_text(json.dumps(evaluation(a=(["A3"], 0.3), b=(["A2"], 0.2))))
    (tmp_path / "reports" / "research_1.3.json").write_text(json.dumps(evaluation(b=(["A1"], 0.9), c=(["A4"], 0.4))))
    dash = {"protocol": "1.3", "research": {"outcomes": {"a": "rejected", "b": "rejected", "c": "rejected"}, "runs": [{"protocol": "1.2"}, {"protocol": "1.3"}]}}
    v = V.verdicts(tmp_path, dash)
    assert v["a"]["why"] == [V.GATE_WORDS["A3"]] and v["a"]["timing_p"] == 0.3                         # only in the first file
    assert v["b"]["why"] == [V.GATE_WORDS["A1"]] and v["b"]["timing_p"] == 0.9                         # in both: the later run's entry
    assert v["c"]["why"] == [V.GATE_WORDS["A4"]]
    (tmp_path / "reports" / "research_1.2.json").write_text("{not json")                                # a damaged file loses only its own families
    v = V.verdicts(tmp_path, dash)
    assert v["a"]["why"] == [] and v["a"]["outcome"] == "rejected" and v["b"]["why"] == [V.GATE_WORDS["A1"]] and v["c"]["why"] == [V.GATE_WORDS["A4"]]
    (tmp_path / "reports" / "research_1.3.json").unlink()                                                # a missing one too
    assert all(x["why"] == [] and x["train"] is None for x in V.verdicts(tmp_path, dash).values())
    single = {"protocol": "1.3", "research": {"outcomes": {"c": "rejected"}}}                           # a dashboard without a list of runs reads the file of its own protocol
    (tmp_path / "reports" / "research_1.3.json").write_text(json.dumps(evaluation(c=(["A5"], 0.5))))
    assert V.verdicts(tmp_path, single)["c"]["why"] == [V.GATE_WORDS["A5"]]


def test_the_command_counts_the_families_of_the_run_not_twelve(tmp_path, monkeypatch, capsys):
    cs = K.synthetic_candles("null_mild", 2)
    (tmp_path / "data").mkdir()
    D.save(tmp_path / "data" / "btcusd_1d.csv", cs)
    toy = toy_family("1.3")
    monkeypatch.setitem(S.FAMILIES, "toy", toy)
    monkeypatch.setattr(S, "RESEARCH", [*S.RESEARCH, toy])
    monkeypatch.setattr(C, "PROTOCOL_VERSION", "1.3")
    monkeypatch.setattr(D, "daily_path", lambda: tmp_path / "data" / "btcusd_1d.csv")
    monkeypatch.setattr(C, "REPORT_DIR", tmp_path / "reports")
    monkeypatch.setattr(R.Registry, "__init__", lambda self, root=None, now=R._now: (setattr(self, "root", tmp_path / "registry"), setattr(self, "_now", now))[0])
    monkeypatch.setattr(P.PaperBook, "__init__", lambda self, root=None, now=P._now: (setattr(self, "root", tmp_path / "state"), setattr(self, "_now", now))[0])
    real = RS.V.evaluate_all
    monkeypatch.setattr(RS.V, "evaluate_all", lambda prep, **k: real(prep, n_shifts=20, families=k.get("families")))
    assert RS.main([]) == 0
    out = capsys.readouterr().out
    assert "research run done: protocol 1.3, data to 2026-11-14, 0 of 1 families admitted: []" in out and out.count("\n") == 2 and "  toy " in out
    assert (tmp_path / "reports" / "research_1.3.md").exists() and not (tmp_path / "reports" / "research_1.2.md").exists()
