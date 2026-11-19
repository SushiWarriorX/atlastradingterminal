"""btcquant research run (protocol section 7 applied to the families pre-registered under a protocol version, ONCE per protocol version and data version).

`run_research` evaluates the families that were pre-registered under the protocol version it runs under (every family of version 1.2 the first time; later, only the families an amendment added: the earlier results stand and
are not run again), logs all their configurations in the candidate registry, admits the families that pass gates A1 to A5 as challengers with their own paper accounts, and writes the full record (JSON, named by the protocol
version) and a plain-language report (markdown). A second run on the same protocol and the same data is refused: the protocol says "once", and a result is never improved by running it again. A new protocol version or new data
is a new run, reported next to the old one; `merged` reads all the runs as one record. The number of trials N behind the deflated Sharpe ratio counts every configuration of every family, new ones included.

The report says what was tested, what was admitted and why, what was not, and what none of it proves. It never says that anything makes money.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import backtest as B
from . import config as C
from . import data as D
from . import paper as P
from . import registry as R
from . import strategies as S
from . import validation as V


class ResearchAlreadyRun(Exception):
    """This protocol version has already been run on exactly this data."""


class NothingToRun(Exception):
    """No family was pre-registered under this protocol version, so there is nothing for it to evaluate."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def data_version(prep: B.Prepared) -> dict:
    """What the run is computed from: the hash of the candle file's contents (as in the data manifest), the number of candles and the last one."""
    m = D.manifest(prep.candles, C.DAY)
    return {"sha256": m["sha256"], "candles": m["count"], "first": m["first"], "last": m["last"]}


def runs_path(reg: R.Registry) -> Path:
    return reg.root / "research_runs.jsonl"


def previous_runs(reg: R.Registry) -> list:
    p = runs_path(reg)
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()] if p.exists() else []


def account_id(family: str, params: dict) -> str:
    return f"{family}-{S.spec_hash(family, params)[:8]}"


def _chosen_exposure(prep: B.Prepared, family: str, params: dict) -> np.ndarray:
    tr, va = prep.period("TRAIN"), prep.period("VALIDATION")
    return np.concatenate([B.run(prep, family, params, *tr).exposure, B.run(prep, family, params, *va).exposure])


def _short(ev: dict) -> dict:
    """The few numbers that go in a candidate's record (the full evaluation is kept in the research file)."""
    return {"train_sharpe": ev["train"]["sharpe"], "validation_sharpe": ev["validation"]["sharpe"], "train_return": ev["train"]["total_return"], "validation_return": ev["validation"]["total_return"],
            "information_ratio_train": ev["excess"]["train"], "information_ratio_validation": ev["excess"]["validation"], "validation_timing_p": ev["validation_timing"]["p"],
            "stability": ev["stability"]["passes"], "doubled_cost_sharpe": ev["costs"][V.A5_COST_INDEX]["sharpe"], "dsr": ev["deflated_sharpe"]["dsr"], "dsr_excess": (ev["excess"]["deflated"] or {}).get("dsr"),
            "gates_failed": ev["admission"]["failed"]}


def families_of(version: str) -> list:
    """The research families pre-registered under a protocol version."""
    return [f.id for f in S.RESEARCH if f.since == version]


def merged(runs: list) -> dict | None:
    """All research runs as one record: the newest outcome of every family, every admitted candidate, the newest run's date, data and trial count, and the list of runs. None when nothing has been run."""
    if not runs:
        return None
    outcomes, admitted = {}, {}
    for r in runs:
        outcomes.update(r["outcomes"])
        for a in r["admitted"]:
            admitted[a.get("spec_hash") or json.dumps(a, sort_keys=True)] = a
    last = runs[-1]
    return {"protocol": last["protocol"], "ran_at": last["ran_at"], "data": last["data"], "n_trials": last["n_trials"], "outcomes": dict(sorted(outcomes.items())), "admitted": list(admitted.values()),
            "runs": [{"protocol": r["protocol"], "ran_at": r["ran_at"], "families": sorted(r["outcomes"])} for r in runs]}


def run_research(prep: B.Prepared, reg: R.Registry, book: P.PaperBook | None, report_dir: Path | None = None, *, force: bool = False, n_shifts: int = V.NULL_SHIFTS, now=_now) -> dict:
    version = data_version(prep)
    if not force and any(r["protocol"] == C.PROTOCOL_VERSION and r["data"]["sha256"] == version["sha256"] for r in previous_runs(reg)):
        raise ResearchAlreadyRun(f"protocol {C.PROTOCOL_VERSION} was already run on these data ({version['last']}); a result is never improved by running it again")
    fams = families_of(C.PROTOCOL_VERSION)
    if not fams:
        raise NothingToRun(f"no family was pre-registered under protocol {C.PROTOCOL_VERSION}; the results of the earlier versions stand and are not run again")
    ev = V.evaluate_all(prep, families=fams, n_shifts=n_shifts)
    admitted, counted = [], {}
    for fid, e in ev["families"].items():
        chosen = B.param_key(e["chosen"])
        for row in e["table"]:
            params = row["params"]
            is_chosen = B.param_key(params) == chosen
            entry = {"family": fid, "params": params, "decision": e["outcome"] if is_chosen else "tested, not selected on TRAIN", "data": version, "run": "research",
                     "results": _short(e) if is_chosen else {k: row[k] for k in ("train_sharpe", "score", "trades", "turnover", "train_return", "validation_sharpe", "validation_return")}}
            rec = reg.log_candidate(entry, exposure=_chosen_exposure(prep, fid, params) if is_chosen else None)
            if is_chosen:
                counted[fid] = rec.get("counted_with")
        if e["outcome"] == "admitted":
            h = S.spec_hash(fid, e["chosen"])
            ch = reg.challengers().get(h) or reg.admit({"family": fid, "params": e["chosen"], "evidence": _short(e), "data": version, "counted_with": counted.get(fid)})
            if book is not None:
                aid = account_id(fid, e["chosen"])
                if not book.exists(aid):
                    book.open(aid, fid, e["chosen"], prep, stage="challenger")
            admitted.append({"family": fid, "params": e["chosen"], "spec_hash": ch["spec_hash"], "counted_with": counted.get(fid)})
    result = {"protocol": C.PROTOCOL_VERSION, "ran_at": now(), "data": version, "n_trials": ev["n_trials"], "admitted": admitted, "outcomes": {f: e["outcome"] for f, e in ev["families"].items()}, "families": list(fams)}
    with runs_path(reg).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(result, sort_keys=True) + "\n")
    if report_dir is not None:
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / f"research_{C.PROTOCOL_VERSION}.json").write_text(json.dumps({**result, "evaluation": ev}, sort_keys=True, indent=1, default=float) + "\n", encoding="utf-8")
        (report_dir / f"research_{C.PROTOCOL_VERSION}.md").write_text(research_report(result, ev), encoding="utf-8")
    return {**result, "evaluation": ev}


def _f(x, k=2, pct=False) -> str:
    if x is None:
        return "n/a"
    return f"{100 * x:.{k}f}%" if pct else f"{x:.{k}f}"


def research_report(result: dict, ev: dict) -> str:
    L = []
    d = result["data"]
    L.append(f"# Research run, protocol {result['protocol']}, data to {d['last'][:10]}\n")
    L.append(f"Run once on {result['ran_at']} UTC on {d['candles']:,} daily BTC-USD candles ({d['first'][:10]} to {d['last'][:10]}, Coinbase; hash `{d['sha256'][:16]}`). Everything below is a simulation on past prices. "
             "It is not a recommendation and nothing in it shows that any rule will make money.\n")
    adm = result["admitted"]
    shifts = next(iter(ev["families"].values()))["validation_timing"]["shifts"]
    if len(ev["families"]) < len(S.RESEARCH):
        n_fam = len(ev["families"])
        L.append(f"This run covers the {n_fam} {'family' if n_fam == 1 else 'families'} pre-registered under protocol {result['protocol']} ({', '.join(f'`{f}`' for f in ev['families'])}). The families pre-registered under other protocol versions are not part of this run: their results stand as they were reported in their own run files and are not repeated here. "
                 f"The number of trials behind the deflated Sharpe ratio is {result['n_trials']}, every configuration of every family.\n")
    L.append("## Headline\n")
    if adm:
        names = ", ".join(f"`{a['family']}`" for a in adm)
        indep = len({a['counted_with'] or a['spec_hash'] for a in adm})
        L.append(f"**{len(adm)} of {len(ev['families'])} {'family was' if len(ev['families']) == 1 else 'families were'} admitted as {'a challenger' if len(adm) == 1 else 'challengers'}** ({names}; about {indep} independent idea{'s' if indep != 1 else ''} once renamed copies are counted together). Admitted means: they passed the five "
                 "admission gates and now have a shadow paper account. It is a reason to watch, not evidence of an edge. `CALIBRATION.md` shows how often the same gates admit something on data where no rule has any skill; "
                 "read this result against that rate. No family can be promoted to the main portfolio until it has a forward record of at least 90 days and passes the promotion gates.\n")
    else:
        L.append("**No family was admitted.** Every family either had too few trades to judge or failed at least one admission gate. The main portfolio stays in cash, and no challenger account was opened.\n")
    L.append("## Families\n")
    L.append("| family | chosen on TRAIN | outcome | trades | TRAIN Sharpe | VALIDATION Sharpe | info ratio TRAIN / VALIDATION | VALIDATION timing p | stable | failed gates |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for fid, e in ev["families"].items():
        g = e["admission"]["gates"]
        L.append(f"| `{fid}` | {json.dumps(e['chosen'])} | **{e['outcome'].replace('_', ' ')}** | {g['A1']['value']} | {_f(e['train']['sharpe'])} | {_f(e['validation']['sharpe'])} | "
                 f"{_f(e['excess']['train'])} / {_f(e['excess']['validation'])} | {_f(e['validation_timing']['p'])} | {'n/a (one setting)' if e['stability'].get('single') else 'yes' if e['stability']['passes'] else 'no'} | {', '.join(e['admission']['failed']) or 'none'} |")
    L.append("\nSharpe ratios are annualised, after costs, from a flat start with $10,000. The information ratio is the Sharpe ratio of the returns in excess of holding the same average share of Bitcoin all the time "
             f"(it removes the drift of simply being invested). The timing p is the share of {shifts} shifted copies of the strategy's own schedule that did at least as well on the 2023-2024 VALIDATION days "
             "(small means the timing matters).\n")
    L.append("## What each family did against holding\n")
    L.append("| family | VALIDATION return | hold | exposure-matched hold | max drawdown | exposure | costs doubled: Sharpe | walk-forward Sharpe / hold | positive windows | trips |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for fid, e in ev["families"].items():
        v, w = e["validation"], e["walk_forward"] or {}
        trips = len(e["trips"]["TRAIN"]) + len(e["trips"]["VALIDATION"])
        L.append(f"| `{fid}` | {_f(v['total_return'], 1, True)} | {_f(v['hold_return'], 1, True)} | {_f(v['matched_hold_return'], 1, True)} | {_f(v['max_drawdown'], 1, True)} | {_f(v['exposure'], 0, True)} | "
                 f"{_f(e['costs'][V.A5_COST_INDEX]['sharpe'])} | {_f(w.get('stitched_sharpe'))} / {_f(w.get('hold_sharpe'))} | {w.get('positive_windows', 0)} of {w.get('windows', 0)} | {trips} |")
    L.append("\nThe walk-forward re-chooses each family's settings every six months from 2022 and scores them on the following six months; its later windows overlap the TEST period, as pre-registered.\n")
    L.append("## What was not tested or not shown\n")
    unreviewed = [f for f in ("rsi_momentum", "bollinger_mr", "rsi_oversold", "vol_breakout", "regime_switch") if f in ev["families"]]
    bullets = ["- The TEST period (2025 onward) has not been used to choose or admit anything. It overlaps data that earlier experiments in this repository already scored, so it can never be a clean test; only the forward paper record is clean.",
               "- Deflated Sharpe ratios are reported in the JSON file but are not gates: on raw returns they reward the market's drift, and on excess returns they cannot be passed with this much history (`CALIBRATION.md`)."]
    if unreviewed:
        bullets.append(f"- {', '.join(f'`{f}`' for f in unreviewed)} {'has' if len(unreviewed) == 1 else 'have'} no peer-reviewed test on Bitcoin behind {'it' if len(unreviewed) == 1 else 'them'} (`strategies/SOURCES.md`).")
    bullets += ["- Prices are Coinbase BTC-USD, not Binance BTC/USDT (that host is blocked from this environment).",
                "- Nothing is traded: no order was placed anywhere, and exchange minimum sizes, outages, taxes and market impact are not modelled."]
    L.append("\n".join(bullets) + "\n")
    L.append("## Credibly profitable?\n")
    L.append("No. Nothing here is evidence that a rule makes money. The forward paper record, accumulated day by day from now on, is the only clean evidence there will be.\n")
    return "\n".join(L)


def main(argv: list) -> int:
    """`python -m atlas_api.btcquant.research`: the one-off research run on the stored daily candles. It refuses to repeat itself on the same protocol and data."""
    candles = D.load(D.daily_path())
    rep = D.validate(candles, C.DAY)
    if rep.fatal or len(candles) < 300:
        print("research run stopped: the stored candles are missing or failed validation: " + "; ".join(rep.fatal[:3]))
        return 1
    prep = B.Prepared(candles)
    try:
        out = run_research(prep, R.Registry(), P.PaperBook(), C.REPORT_DIR)
    except ResearchAlreadyRun as e:
        print(f"research run refused: {e}")
        return 1
    print(f"research run done: protocol {out['protocol']}, data to {out['data']['last'][:10]}, {len(out['admitted'])} of {len(out['outcomes'])} families admitted: {[a['family'] for a in out['admitted']]}")
    for fid, outcome in out["outcomes"].items():
        print(f"  {fid:14s} {outcome}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv))
