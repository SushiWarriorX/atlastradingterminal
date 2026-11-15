"""btcquant registry (protocol section 10 and the freeze rules of section 8): the permanent record of every candidate, so that failed ideas are not repeated and a result can be traced to the exact rules, data and protocol
that produced it.

Files under `btcquant/registry/` (all plain text, all committed):
  candidates.jsonl    one line per candidate ever evaluated, appended and never edited: specification hash, family, parameters, protocol version, data manifest hash, results, decision, and any renamed-copy flag
  positions.npz       the exposure schedule of each candidate (used only to recognise a renamed copy of an earlier idea)
  challengers.json    candidates admitted to a shadow paper account (spec hash -> record)
  champions.json      candidates promoted to the main portfolio, with the written promotion record; their rules are frozen
  holdout_log.jsonl   every look at the TEST period, once per frozen candidate version

Rules enforced here: every record stores its full specification (strategies.spec) and the hash of it, so an old record keeps its hash when a protocol constant is later amended; a renamed copy (exposure schedule correlating 0.90 or more with an earlier candidate's over the same days) is flagged and counted with
the original; a promotion needs a current challenger; a champion's hash is re-derived from its stored rules at every check; the TEST period can be looked at once per specification hash.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import config as C
from . import strategies as S

DUP_CORRELATION = 0.90


class HoldoutAlreadyUsed(Exception):
    """The TEST period has already been looked at for this specification."""


class RegistryError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _append_jsonl(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, sort_keys=True) + "\n")


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, sort_keys=True, indent=2) + "\n", encoding="utf-8")


class Registry:
    def __init__(self, root: Path | None = None, now=_now):
        self.root = Path(root) if root is not None else C.REGISTRY_DIR
        self._now = now

    # ---- paths ----
    @property
    def candidates_path(self) -> Path:
        return self.root / "candidates.jsonl"

    @property
    def positions_path(self) -> Path:
        return self.root / "positions.npz"

    @property
    def challengers_path(self) -> Path:
        return self.root / "challengers.json"

    @property
    def champions_path(self) -> Path:
        return self.root / "champions.json"

    @property
    def holdout_path(self) -> Path:
        return self.root / "holdout_log.jsonl"

    # ---- candidates ----
    def candidates(self) -> list:
        return _read_jsonl(self.candidates_path)

    def chosen(self, run: str = "research") -> list:
        """The configuration chosen on TRAIN for each family in the latest logged run of that kind (its outcome in `decision`): every logged record of the run that is not marked as merely tested."""
        latest = {}
        for c in self.candidates():
            if c.get("run") == run and c["decision"] != "tested, not selected on TRAIN":
                latest[c["family"]] = c
        return [latest[f] for f in sorted(latest)]

    def is_known(self, spec_hash: str) -> bool:
        return any(c["spec_hash"] == spec_hash for c in self.candidates())

    def _positions(self) -> dict:
        if not self.positions_path.exists():
            return {}
        with np.load(self.positions_path) as z:
            return {k: z[k] for k in z.files}

    def find_duplicates(self, exposure, exclude: str | None = None) -> list:
        """Earlier candidates whose exposure schedule over the same days correlates DUP_CORRELATION or more with this one. Schedules of different lengths are not compared; a constant schedule has no correlation."""
        e = np.asarray(exposure, dtype=float)
        out = []
        for h, other in self._positions().items():
            if h == exclude or len(other) != len(e) or np.std(e) < 1e-12 or np.std(other) < 1e-12:
                continue
            r = float(np.corrcoef(e, other)[0, 1])
            if r >= DUP_CORRELATION:
                out.append({"spec_hash": h, "correlation": r})
        return sorted(out, key=lambda d: -d["correlation"])

    def log_candidate(self, entry: dict, exposure=None) -> dict:
        """Append one candidate. `entry` must carry spec_hash, family, params, protocol, decision; it should carry the data manifest hash and the results. Returns the stored record."""
        for key in ("family", "params", "decision"):
            if key not in entry:
                raise RegistryError(f"a candidate record needs '{key}'")
        sp = S.spec(entry["family"], entry["params"], entry.get("version", 1))
        h = S.hash_spec(sp)
        if "spec_hash" in entry and entry["spec_hash"] != h:
            raise RegistryError("the specification hash does not match the family and parameters")
        dups = self.find_duplicates(exposure, exclude=h) if exposure is not None else []
        rec = {**entry, "spec": sp, "spec_hash": h, "protocol": sp["protocol"], "logged_at": self._now(), "repeat": self.is_known(h), "duplicates": dups,
               "counted_with": dups[0]["spec_hash"] if dups else None}
        _append_jsonl(self.candidates_path, rec)
        if exposure is not None and h not in self._positions():
            store = self._positions()
            store[h] = np.asarray(exposure, dtype=np.float32)
            self.root.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(self.positions_path, **store)
        return rec

    # ---- challengers and champions ----
    def challengers(self) -> dict:
        return _read_json(self.challengers_path)

    def champions(self) -> dict:
        return _read_json(self.champions_path)

    def admit(self, record: dict) -> dict:
        """Make a candidate a challenger (a shadow paper account). The record carries spec_hash, family, params and the admission evidence."""
        for key in ("family", "params"):
            if key not in record:
                raise RegistryError(f"a challenger record needs '{key}'")
        sp = S.spec(record["family"], record["params"], record.get("version", 1))
        h = S.hash_spec(sp)
        if "spec_hash" in record and record["spec_hash"] != h:
            raise RegistryError("the specification hash does not match the family and parameters")
        ch = self.challengers()
        if h in ch:
            raise RegistryError("already a challenger")
        ch[h] = {**record, "spec": sp, "spec_hash": h, "admitted_at": self._now()}
        _write_json(self.challengers_path, ch)
        return ch[h]

    def promote(self, spec_hash: str, evidence: dict) -> dict:
        """Promote a current challenger to champion with a written record. Its rules are frozen from here: check_frozen re-derives the hash at every run."""
        ch, champs = self.challengers(), self.champions()
        if spec_hash not in ch:
            raise RegistryError("only a current challenger can be promoted")
        if spec_hash in champs:
            raise RegistryError("already a champion")
        c = ch[spec_hash]
        champs[spec_hash] = {"spec_hash": spec_hash, "spec": c["spec"], "family": c["family"], "params": c["params"], "version": c.get("version", 1), "promoted_at": self._now(), "evidence": evidence}
        _write_json(self.champions_path, champs)
        return champs[spec_hash]

    def check_frozen(self) -> list:
        """Problems found: any challenger or champion whose stored specification no longer hashes to its recorded hash, or whose family and parameters no longer match that specification. Empty means untouched."""
        problems = []
        for kind, store in (("challenger", self.challengers()), ("champion", self.champions())):
            for h, r in store.items():
                sp = r.get("spec")
                if sp is None or h != r.get("spec_hash") or S.hash_spec(sp) != h:
                    problems.append(f"{kind} {h}: the stored specification does not hash to the recorded hash")
                elif sp["family"] != r["family"] or sp["params"] != {k: r["params"][k] for k in sorted(r["params"])}:
                    problems.append(f"{kind} {h}: the stored rules differ from the stored specification")
        return problems

    def drift(self) -> list:
        """Not an error: challengers and champions whose specification was written under other protocol constants than today's (an amendment since). They keep their old hash and their old rules."""
        out = []
        for kind, store in (("challenger", self.challengers()), ("champion", self.champions())):
            for h, r in store.items():
                now = S.spec(r["family"], r["params"], r.get("version", 1))
                if now != r.get("spec"):
                    out.append({"kind": kind, "spec_hash": h, "changed": sorted(k for k in now if now[k] != r["spec"].get(k))})
        return out

    # ---- the TEST period ----
    def holdout_used(self, spec_hash: str) -> bool:
        return any(r["spec_hash"] == spec_hash for r in _read_jsonl(self.holdout_path))

    def holdout_look(self, spec_hash: str, summary: dict) -> dict:
        """Record the one look at the TEST period for this specification. A second look is refused."""
        if self.holdout_used(spec_hash):
            raise HoldoutAlreadyUsed(f"the TEST period was already looked at for {spec_hash}")
        rec = {"spec_hash": spec_hash, "looked_at": self._now(), **summary}
        _append_jsonl(self.holdout_path, rec)
        return rec
