"""Validated scan specification. The only way to express a scan: whitelisted fields, typed operators."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .features import FIELDS

NUM_OPS = {">", ">=", "<", "<=", "==", "between"}
STR_OPS = {"==", "!=", "in"}


class Filter(BaseModel):
    field: str
    op: Literal[">", ">=", "<", "<=", "==", "!=", "between", "in"]
    value: float | bool | str | list[float] | list[str]

    @model_validator(mode="after")
    def _typed(self):
        if self.field not in FIELDS:
            raise ValueError(f"unknown field '{self.field}'")
        typ = FIELDS[self.field][0]
        if typ == "number":
            if self.op not in NUM_OPS:
                raise ValueError(f"operator {self.op} not valid for numeric field {self.field}")
            if self.op == "between":
                if not (isinstance(self.value, list) and len(self.value) == 2 and all(isinstance(x, (int, float)) for x in self.value)):
                    raise ValueError("between needs [low, high]")
            elif isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
                raise ValueError(f"{self.field} needs a numeric value")
        elif typ == "bool":
            if self.op != "==" or not isinstance(self.value, bool):
                raise ValueError(f"{self.field} supports only == true/false")
        else:
            if self.op not in STR_OPS:
                raise ValueError(f"operator {self.op} not valid for text field {self.field}")
            if self.op == "in" and not isinstance(self.value, list):
                raise ValueError("in needs a list")
            if self.op != "in" and not isinstance(self.value, str):
                raise ValueError(f"{self.field} needs a text value")
        return self

    def passes(self, row: dict) -> bool:
        x = row.get(self.field)
        if x is None:
            return False  # missing data never silently passes
        v = self.value
        return {">": lambda: x > v, ">=": lambda: x >= v, "<": lambda: x < v, "<=": lambda: x <= v, "==": lambda: x == v,
                "!=": lambda: x != v, "between": lambda: v[0] <= x <= v[1], "in": lambda: x in v}[self.op]()

    def describe(self) -> str:
        return f"{FIELDS[self.field][1]} {self.op} {self.value}"


class ScanSpec(BaseModel):
    name: str = "Custom scan"
    universe: str = "core"
    benchmark: str = "SPY"
    filters: list[Filter] = Field(default_factory=list)
    score_weights: dict[str, float] = Field(default_factory=dict)   # field -> weight (negative = lower is better)
    sort_by: str = "score"
    sort_desc: bool = True
    limit: int = Field(default=100, ge=1, le=500)

    @field_validator("score_weights")
    @classmethod
    def _w(cls, w):
        for k in w:
            if k not in FIELDS or FIELDS[k][0] != "number":
                raise ValueError(f"score weight field '{k}' must be a numeric field")
        return w

    @field_validator("sort_by")
    @classmethod
    def _s(cls, s):
        if s != "score" and s not in FIELDS:
            raise ValueError(f"unknown sort field '{s}'")
        return s
