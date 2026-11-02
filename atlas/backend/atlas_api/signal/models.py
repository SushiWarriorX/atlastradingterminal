"""The contract between the backend research layer and any client (the mobile app mirrors these shapes in TypeScript).

Three kinds of content are kept apart: FACTS (reported or calculated by code, each with a source and timestamp), INTERPRETATIONS (the agent's reading of those
facts, tied to fact keys) and MISSING information (what could not be obtained, and why).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AgentName = Literal["news", "technical", "macro", "fundamentals"]
AGENTS: tuple[str, ...] = ("news", "technical", "macro", "fundamentals")
AGENT_TITLES = {"news": "News", "technical": "Technical", "macro": "Macro", "fundamentals": "Fundamentals"}
Stance = Literal["supportive", "mixed", "cautious", "neutral", "insufficient"]


class Source(BaseModel):
    name: str
    url: str | None = None                 # original page (http/https only)
    kind: Literal["data", "article", "official", "protocol"] = "data"
    as_of: str | None = None               # ISO UTC: the data's own timestamp
    status: str | None = None              # LIVE | DELAYED | HISTORICAL | STALE | DEMO | UNAVAILABLE
    note: str | None = None


class Fact(BaseModel):
    key: str
    label: str
    value: float | int | str | bool | None = None
    display: str                           # formatted once on the server
    unit: str | None = None
    as_of: str | None = None
    source: str                            # a Source.name
    timeframe: str | None = None           # e.g. "1D", "1W" for technical facts
    kind: Literal["reported", "calculated"] = "calculated"


class Interpretation(BaseModel):
    text: str
    based_on: list[str] = Field(default_factory=list)     # fact keys
    caveat: str | None = None
    timeframe: str | None = None


class Missing(BaseModel):
    what: str
    why: str


class Point(BaseModel):
    """A candidate line for the combined briefing. Agents propose; the orchestrator selects, de-duplicates and orders."""
    kind: Literal["changed", "supports", "risk", "watch"]
    text: str
    agent: AgentName
    fact_keys: list[str] = Field(default_factory=list)
    priority: int = 50
    dedupe_key: str | None = None
    at_utc: str | None = None              # a scheduled moment the client shows in the viewer's timezone


class Story(BaseModel):
    id: str
    title: str                             # untrusted external text: display as plain text only
    link: str | None = None
    source: str
    published: str | None = None           # when it was published
    event_time: str | None = None          # when the event happened, if the feed says (RSS usually does not)
    fetched_at: str | None = None
    scope: Literal["asset", "industry"] = "asset"
    kind: Literal["reporting", "opinion", "unconfirmed"] = "reporting"        # by wording only
    category: str = "general"
    why_it_matters: str | None = None
    why_origin: Literal["rules", "ai"] = "rules"
    also: list[dict] = Field(default_factory=list)                           # other outlets with a near-duplicate headline
    demo: bool = False


class Level(BaseModel):
    id: str
    kind: Literal["support", "resistance"]
    price: float
    display: str
    timeframe: str
    distance_pct: float | None = None
    derivation: str


class EventItem(BaseModel):
    id: str
    title: str
    at_utc: str | None = None              # shown in the viewer's timezone
    date: str | None = None
    kind: Literal["scheduled", "release"] = "scheduled"
    link: str | None = None
    note: str | None = None


class Explanation(BaseModel):
    text: str
    origin: Literal["ai"] = "ai"
    model: str
    note: str = "Written by an AI model from the facts above. Every figure is filled in by code from those facts."


class Finding(BaseModel):
    agent: AgentName
    status: Literal["ok", "partial", "unavailable", "not_applicable", "pending"]
    stance: Stance | None = None
    stance_rule: str | None = None
    takeaway: str
    facts: list[Fact] = Field(default_factory=list)
    interpretations: list[Interpretation] = Field(default_factory=list)
    stories: list[Story] = Field(default_factory=list)
    levels: list[Level] = Field(default_factory=list)
    events: list[EventItem] = Field(default_factory=list)
    missing: list[Missing] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    points: list[Point] = Field(default_factory=list)
    explanation: Explanation | None = None
    data_as_of: str | None = None          # newest data timestamp behind this finding
    analyzed_at: str | None = None         # when this analysis was produced
    ttl_seconds: int = 0                   # how long it is reused before being recomputed
    next_refresh_at: str | None = None
    demo: bool = False
    error: str | None = None               # why it is unavailable (sanitised)


class BriefingLine(BaseModel):
    agent: AgentName
    text: str
    fact_keys: list[str] = Field(default_factory=list)
    at_utc: str | None = None


class Disagreement(BaseModel):
    agents: list[AgentName]
    text: str


class Briefing(BaseModel):
    headline: str
    changed: list[BriefingLine] = Field(default_factory=list)
    supports: list[BriefingLine] = Field(default_factory=list)
    risks: list[BriefingLine] = Field(default_factory=list)
    watch: list[BriefingLine] = Field(default_factory=list)
    disagreements: list[Disagreement] = Field(default_factory=list)
    coverage: dict = Field(default_factory=dict)       # {"agents_ok": n, "agents_total": 4, "missing": [...], "pending": [...]}
    generated_at: str
    demo: bool = False
