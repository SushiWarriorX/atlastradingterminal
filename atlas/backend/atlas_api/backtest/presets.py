"""Backtest presets are the scanner presets with explicit, editable exit defaults. Nothing here is tuned."""
from __future__ import annotations

from ..scanner.presets import PRESETS
from .spec import BtSpec

SHORT = {"bearish_breakdown"}


def preset_spec(pid: str, overrides: dict | None = None) -> BtSpec:
    p = PRESETS[pid]
    base = {"name": p["name"], "universe": p["spec"].universe, "benchmark": p["spec"].benchmark,
            "entry": [f.model_dump() for f in p["spec"].filters], "side": "short" if pid in SHORT else "long"}
    return BtSpec.model_validate({**base, **(overrides or {})})


def listing() -> list[dict]:
    return [{"id": k, "name": v["name"], "description": v["description"], "spec": preset_spec(k).model_dump(mode="json")} for k, v in PRESETS.items()]
