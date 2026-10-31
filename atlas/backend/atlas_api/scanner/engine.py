from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone

import numpy as np

from . import features as feat
from .bars import BarSource
from .rules import ScanSpec
from .universe import CORE, load


def rank_scores(rows: list[dict], weights: dict[str, float]) -> None:
    """Score = weighted mean of within-candidate percentile ranks (0-100). Adds `score` and `score_breakdown` in place.
    A candidate with a missing factor gets 0 for that factor's percentile (penalised, not skipped)."""
    if not weights or not rows:
        for r in rows:
            r["score"], r["score_breakdown"] = None, []
        return
    total = sum(abs(w) for w in weights.values())
    pct: dict[str, list[float | None]] = {}
    for k in weights:
        vals = np.array([np.nan if r.get(k) is None else r[k] for r in rows], dtype=float)
        ok = ~np.isnan(vals)
        p = np.full(len(rows), np.nan)
        if ok.sum():
            order = vals[ok].argsort().argsort()
            p[ok] = order / max(ok.sum() - 1, 1) * 100
        pct[k] = [None if np.isnan(x) else float(x) for x in p]
    for i, r in enumerate(rows):
        parts, s = [], 0.0
        for k, w in weights.items():
            p = pct[k][i]
            eff = 0.0 if p is None else (p if w > 0 else 100 - p)
            contrib = abs(w) * eff / total
            s += contrib
            parts.append({"field": k, "weight": w, "value": r.get(k), "percentile": p, "contribution": round(contrib, 2)})
        r["score"], r["score_breakdown"] = round(s, 1), parts


def evaluate(spec: ScanSpec, all_features: list[dict]) -> list[dict]:
    rows = [f for f in all_features if f["sufficient"] and all(flt.passes(f) for flt in spec.filters)]
    rank_scores(rows, spec.score_weights)
    key = spec.sort_by
    present = [r for r in rows if r.get(key) is not None]
    absent = [r for r in rows if r.get(key) is None]
    present.sort(key=lambda r: r[key], reverse=spec.sort_desc)
    return (present + absent)[: spec.limit]


async def run(spec: ScanSpec, source: BarSource, symbols: list[str] | None = None, progress=None) -> dict:
    t0 = time.monotonic()
    syms = symbols if symbols is not None else await load(spec.universe)
    batch = await source.fetch(sorted(set(syms) | {spec.benchmark}), progress)
    bench = batch.bars.get(spec.benchmark)
    notes = list(batch.notes)
    if bench is None:
        notes.append(f"benchmark {spec.benchmark} unavailable: relative-strength fields are empty and RS filters cannot pass")
    feats = await asyncio.to_thread(
        lambda: [feat.compute(s, batch.bars[s], bench, CORE.get(s)) for s in syms if s in batch.bars])
    insufficient = sum(1 for f in feats if not f["sufficient"])
    results = await asyncio.to_thread(evaluate, spec, feats)
    unknown_sector = sum(1 for f in feats if f["sector"] is None)
    if unknown_sector and any(f.field == "sector" for f in spec.filters):
        notes.append(f"{unknown_sector} symbols have no sector data and cannot match a sector filter")
    dates = [f["last_bar_date"] for f in feats if f["last_bar_date"]]
    return {
        "results": results,
        "meta": {
            "spec": spec.model_dump(), "universe": spec.universe, "universe_size": len(syms), "with_data": len(feats),
            "failed": len(batch.failed), "failed_sample": dict(list(batch.failed.items())[:5]),
            "insufficient_history": insufficient, "matched": len(results),
            "coverage_pct": round(len(feats) / len(syms) * 100, 1) if syms else 0.0,
            "provider": batch.provider, "status": batch.status.value,
            "data_as_of": batch.as_of.isoformat() if batch.as_of else None,
            "latest_bar_date": max(dates) if dates else None,
            "ran_at": datetime.now(timezone.utc).isoformat(), "duration_ms": int((time.monotonic() - t0) * 1000), "notes": notes,
        },
    }


class Jobs:
    """In-memory background scan jobs with progress."""

    def __init__(self, keep: int = 20):
        self.jobs: dict[str, dict] = {}
        self.keep = keep

    def start(self, spec: ScanSpec, source: BarSource, symbols: list[str] | None = None) -> str:
        jid = str(uuid.uuid4())
        job = {"id": jid, "status": "running", "done": 0, "total": 0, "result": None, "error": None, "spec": spec.model_dump()}
        self.jobs[jid] = job
        for old in list(self.jobs)[: -self.keep]:
            del self.jobs[old]

        def prog(d, t):
            job["done"], job["total"] = d, t

        async def go():
            try:
                job["result"] = await run(spec, source, symbols, prog)
                job["status"] = "done"
            except Exception as e:  # noqa: BLE001
                job["status"], job["error"] = "failed", f"{type(e).__name__}: {e}"

        job["task"] = asyncio.create_task(go())
        return jid

    def view(self, jid: str) -> dict | None:
        j = self.jobs.get(jid)
        return None if j is None else {k: v for k, v in j.items() if k != "task"}
