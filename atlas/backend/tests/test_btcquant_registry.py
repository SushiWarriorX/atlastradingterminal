"""btcquant registry: append-only candidate log, renamed-copy detection at its 0.90 boundary, challengers and champions with frozen specifications (and the difference between tampering and an amendment), and the
once-only look at the TEST period."""
import json

import numpy as np
import pytest

from atlas_api.btcquant import config as C
from atlas_api.btcquant import registry as R
from atlas_api.btcquant import strategies as S


def reg(tmp_path):
    clock = iter(f"2026-11-15T10:{i:02d}:00Z" for i in range(60))
    return R.Registry(tmp_path / "registry", now=lambda: next(clock))


def entry(**kw):
    e = {"family": "sma_cross", "params": {"fast": 20, "slow": 100}, "decision": "tested"}
    e.update(kw)
    return e


def corr_series(base, rho, seed):
    z = np.random.default_rng(seed).normal(size=len(base))
    z = (z - z.mean()) / z.std()
    b = (base - base.mean()) / base.std()
    return rho * b + np.sqrt(1 - rho ** 2) * z


# ---- the specification ----

def test_a_specification_records_the_rules_and_the_protocol_constants_that_change_them():
    sp = S.spec("sma_cross", {"slow": 100, "fast": 20})
    assert sp["family"] == "sma_cross" and list(sp["params"]) == ["fast", "slow"] and sp["version"] == 1 and sp["protocol"] == "1.2"
    assert {"fee", "slippage", "risk", "stop_k", "atr_n", "breaker", "cool_off", "band"} <= set(sp)
    assert S.hash_spec(sp) == S.spec_hash("sma_cross", {"fast": 20, "slow": 100})


def test_a_stored_specification_keeps_its_hash_when_a_constant_is_amended_later(monkeypatch):
    old = S.spec("sma_cross", {"fast": 20, "slow": 100})
    h = S.hash_spec(old)
    monkeypatch.setattr(C, "FEE", 0.002)
    assert S.hash_spec(old) == h and S.spec_hash("sma_cross", {"fast": 20, "slow": 100}) != h              # the old record is not re-read through today's constants


# ---- the candidate log ----

def test_a_candidate_is_logged_with_its_specification_hash_time_and_protocol(tmp_path):
    r = reg(tmp_path)
    rec = r.log_candidate(entry(results={"train_sharpe": 1.0}))
    assert rec["spec_hash"] == S.spec_hash("sma_cross", {"fast": 20, "slow": 100}) and rec["spec"]["params"] == {"fast": 20, "slow": 100} and rec["protocol"] == "1.2"
    assert rec["logged_at"] == "2026-11-15T10:00:00Z" and rec["repeat"] is False and rec["duplicates"] == [] and rec["counted_with"] is None and rec["results"] == {"train_sharpe": 1.0}
    assert r.candidates() == [rec] and r.is_known(rec["spec_hash"]) and not r.is_known("0" * 16)


def test_the_log_is_append_only_and_a_repeat_is_flagged_not_hidden(tmp_path):
    r = reg(tmp_path)
    first = r.log_candidate(entry())
    text = r.candidates_path.read_text()
    again = r.log_candidate(entry(decision="tested again"))
    assert again["repeat"] is True and r.candidates_path.read_text().startswith(text) and len(r.candidates()) == 2 and r.candidates()[0] == first
    other = r.log_candidate(entry(params={"fast": 30, "slow": 100}))
    assert other["repeat"] is False and other["spec_hash"] != first["spec_hash"]


def test_a_record_needs_its_family_parameters_and_decision_and_a_supplied_hash_must_match(tmp_path):
    r = reg(tmp_path)
    for missing in ("family", "params", "decision"):
        e = entry()
        del e[missing]
        with pytest.raises(R.RegistryError):
            r.log_candidate(e)
    with pytest.raises(R.RegistryError, match="does not match"):
        r.log_candidate(entry(spec_hash="0123456789abcdef"))
    assert r.log_candidate(entry(spec_hash=S.spec_hash("sma_cross", {"fast": 20, "slow": 100})))["repeat"] is False
    assert len(r.candidates()) == 1


# ---- renamed copies ----

def test_a_renamed_copy_is_a_schedule_correlating_at_least_point_nine_and_is_counted_with_the_original(tmp_path):
    r = reg(tmp_path)
    rng = np.random.default_rng(1)
    base = rng.normal(size=1000)
    a = r.log_candidate(entry(), exposure=base)
    close = corr_series(base, 0.95, 2)
    b = r.log_candidate(entry(params={"fast": 30, "slow": 100}), exposure=close)
    assert [d["spec_hash"] for d in b["duplicates"]] == [a["spec_hash"]] and b["duplicates"][0]["correlation"] == pytest.approx(0.95, abs=0.01) and b["counted_with"] == a["spec_hash"]
    far = corr_series(base, 0.80, 3)
    c = r.log_candidate(entry(params={"fast": 50, "slow": 100}), exposure=far)
    assert c["duplicates"] == [] and c["counted_with"] is None


def test_with_several_earlier_copies_the_strongest_one_comes_first_and_is_the_one_it_is_counted_with(tmp_path):
    r = reg(tmp_path)
    base = np.random.default_rng(9).normal(size=1500)
    weak = r.log_candidate(entry(params={"fast": 10, "slow": 50}), exposure=corr_series(base, 0.93, 10))
    strong = r.log_candidate(entry(params={"fast": 20, "slow": 50}), exposure=corr_series(base, 0.99, 11))
    new = r.log_candidate(entry(params={"fast": 30, "slow": 50}), exposure=base)
    assert [d["spec_hash"] for d in new["duplicates"]] == [strong["spec_hash"], weak["spec_hash"]] and new["counted_with"] == strong["spec_hash"]
    assert new["duplicates"][0]["correlation"] > new["duplicates"][1]["correlation"] > 0.9


def test_the_correlation_boundary_is_point_nine(tmp_path):
    r = reg(tmp_path)
    base = np.random.default_rng(4).normal(size=2000)
    r.log_candidate(entry(), exposure=base)
    above, below = corr_series(base, 0.905, 5), corr_series(base, 0.895, 6)
    assert np.corrcoef(base, above)[0, 1] >= 0.9 > np.corrcoef(base, below)[0, 1]
    assert len(r.find_duplicates(above)) == 1 and r.find_duplicates(below) == []
    assert R.DUP_CORRELATION == 0.90


def test_schedules_that_cannot_be_compared_are_not_called_copies(tmp_path):
    r = reg(tmp_path)
    base = np.random.default_rng(7).normal(size=500)
    r.log_candidate(entry(), exposure=base)
    assert r.find_duplicates(base[:400]) == []                                       # different days
    assert r.find_duplicates(np.zeros(500)) == []                                    # a constant schedule has no correlation
    r2 = reg(tmp_path / "other")
    r2.log_candidate(entry(), exposure=np.zeros(500))
    assert r2.find_duplicates(base) == [] and r2.find_duplicates(np.zeros(500)) == []


def test_a_repeat_of_the_same_specification_is_not_its_own_duplicate_and_its_schedule_is_stored_once(tmp_path):
    r = reg(tmp_path)
    base = np.random.default_rng(8).normal(size=300)
    r.log_candidate(entry(), exposure=base)
    again = r.log_candidate(entry(), exposure=base)
    assert again["repeat"] is True and again["duplicates"] == []
    with np.load(r.positions_path) as z:
        assert len(z.files) == 1 and z[z.files[0]].dtype == np.float32


# ---- challengers, champions, freezing ----

def test_admitting_a_challenger_stores_its_specification_once(tmp_path):
    r = reg(tmp_path)
    rec = r.admit({"family": "donchian", "params": {"N": 20}, "evidence": {"A3": 0.04}})
    assert rec["spec_hash"] == S.spec_hash("donchian", {"N": 20}) and rec["admitted_at"] == "2026-11-15T10:00:00Z" and r.challengers() == {rec["spec_hash"]: rec}
    with pytest.raises(R.RegistryError, match="already a challenger"):
        r.admit({"family": "donchian", "params": {"N": 20}})
    with pytest.raises(R.RegistryError, match="does not match"):
        r.admit({"family": "donchian", "params": {"N": 40}, "spec_hash": rec["spec_hash"]})
    with pytest.raises(R.RegistryError):
        r.admit({"family": "donchian"})


def test_only_a_current_challenger_can_be_promoted_and_only_once(tmp_path):
    r = reg(tmp_path)
    ch = r.admit({"family": "donchian", "params": {"N": 20}})
    with pytest.raises(R.RegistryError, match="only a current challenger"):
        r.promote("0" * 16, {})
    champ = r.promote(ch["spec_hash"], {"P1": "30 trades", "forward_days": 120})
    assert champ["spec"] == ch["spec"] and champ["evidence"]["forward_days"] == 120 and champ["promoted_at"] == "2026-11-15T10:01:00Z" and r.champions() == {ch["spec_hash"]: champ}
    with pytest.raises(R.RegistryError, match="already a champion"):
        r.promote(ch["spec_hash"], {})


def test_a_champion_keeps_the_specification_its_challenger_was_admitted_under(tmp_path, monkeypatch):
    r = reg(tmp_path)
    ch = r.admit({"family": "donchian", "params": {"N": 20}})
    monkeypatch.setattr(C, "FEE", 0.002)                                           # an amendment between admission and promotion
    champ = r.promote(ch["spec_hash"], {})
    assert champ["spec"] == ch["spec"] and champ["spec"]["fee"] == 0.001 and r.check_frozen() == []


def test_an_edited_family_is_found_too(tmp_path):
    r = reg(tmp_path)
    ch = r.admit({"family": "donchian", "params": {"N": 20}})
    data = json.loads(r.challengers_path.read_text())
    data[ch["spec_hash"]]["family"] = "tsmom"
    r.challengers_path.write_text(json.dumps(data))
    assert any("differ from the stored specification" in p for p in r.check_frozen())


def test_nothing_is_wrong_in_an_untouched_registry_and_tampering_is_found(tmp_path):
    r = reg(tmp_path)
    ch = r.admit({"family": "donchian", "params": {"N": 20}})
    r.promote(ch["spec_hash"], {})
    assert r.check_frozen() == []
    data = json.loads(r.champions_path.read_text())
    data[ch["spec_hash"]]["params"] = {"N": 40}                                    # someone edits the champion's parameters but not its specification
    r.champions_path.write_text(json.dumps(data))
    assert any("differ from the stored specification" in p for p in r.check_frozen())
    data[ch["spec_hash"]]["spec"]["params"] = {"N": 40}                            # ... and then the specification too: the hash no longer matches
    r.champions_path.write_text(json.dumps(data))
    problems = r.check_frozen()
    assert any("does not hash" in p for p in problems)
    c = json.loads(r.challengers_path.read_text())
    c[ch["spec_hash"]].pop("spec")
    r.challengers_path.write_text(json.dumps(c))
    assert sum("challenger" in p for p in r.check_frozen()) == 1


def test_an_amendment_to_a_protocol_constant_is_not_tampering(tmp_path, monkeypatch):
    r = reg(tmp_path)
    ch = r.admit({"family": "sma_cross", "params": {"fast": 20, "slow": 100}})
    assert r.drift() == []
    monkeypatch.setattr(C, "FEE", 0.002)
    monkeypatch.setattr(C, "PROTOCOL_VERSION", "1.3")
    assert r.check_frozen() == []                                                  # the record still hashes to itself
    assert r.drift() == [{"kind": "challenger", "spec_hash": ch["spec_hash"], "changed": ["fee", "protocol"]}]


# ---- the TEST period ----

def test_the_test_period_can_be_looked_at_once_per_specification(tmp_path):
    r = reg(tmp_path)
    h = S.spec_hash("donchian", {"N": 20})
    assert not r.holdout_used(h)
    rec = r.holdout_look(h, {"test_sharpe": 0.4, "days": 683})
    assert rec["looked_at"] == "2026-11-15T10:00:00Z" and rec["test_sharpe"] == 0.4 and r.holdout_used(h)
    with pytest.raises(R.HoldoutAlreadyUsed):
        r.holdout_look(h, {"test_sharpe": 0.9})
    r.holdout_look(S.spec_hash("donchian", {"N": 40}), {"test_sharpe": 0.1})            # another specification has its own single look
    assert len(r.holdout_path.read_text().splitlines()) == 2 and json.loads(r.holdout_path.read_text().splitlines()[0])["test_sharpe"] == 0.4


def test_the_chosen_configuration_of_each_family_comes_from_the_latest_run_of_that_kind(tmp_path):
    r = reg(tmp_path)
    r.log_candidate(entry(family="sma_cross", params={"fast": 10, "slow": 50}, decision="rejected", run="research"))
    r.log_candidate(entry(family="sma_cross", params={"fast": 20, "slow": 50}, decision="tested, not selected on TRAIN", run="research"))
    r.log_candidate(entry(family="tsmom", params={"L": 30}, decision="admitted", run="research"))
    r.log_candidate(entry(family="tsmom", params={"L": 60}, decision="rejected", run="research"))                       # a later run chose another configuration
    r.log_candidate(entry(family="donchian", params={"N": 20}, decision="rejected", run="other"))
    got = r.chosen()
    assert [(c["family"], c["params"], c["decision"]) for c in got] == [("sma_cross", {"fast": 10, "slow": 50}, "rejected"), ("tsmom", {"L": 60}, "rejected")]
    assert [c["family"] for c in r.chosen("other")] == ["donchian"] and r.chosen("none") == []
