"""The orchestrator: runs the four agents concurrently, caches each finding by its own cadence, returns whatever is ready (partial results), and builds the
combined briefing. It never forces agreement: when agents read the setup differently, both views and the disagreement are shown."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import fmt
from .agents.common import Agent, Ctx, iso, unavailable
from .assets import Asset
from .cache import SharedCache
from .models import AGENT_TITLES, AGENTS, Briefing, BriefingLine, Disagreement, Finding, Point

log = logging.getLogger("atlas.signal")
TTL = {"technical": 90.0, "news": 600.0, "macro": 1800.0, "fundamentals": 21600.0}      # how long a finding is reused, by how fast its sources change
PARTIAL_TTL = 300.0
FAIL_TTL = 45.0
AGENT_TIMEOUT = {"technical": 35.0, "news": 25.0, "macro": 35.0, "fundamentals": 35.0}
REFRESH_COOLDOWN = 30.0
MAX_LINES = 3
STANCE_WORD = {"supportive": "supportive", "mixed": "mixed", "cautious": "cautious"}
SCOPE = {"technical": "price action", "macro": "the economic backdrop", "fundamentals": "the business's financials"}
HEAD_NAME = {"technical": "Technicals", "macro": "Macro", "fundamentals": "Fundamentals"}


class OrchestratorError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def ttl_for(f: Finding) -> float:
    if f.status in ("unavailable", "pending"):
        return FAIL_TTL
    if f.status == "partial":
        return min(PARTIAL_TTL, TTL[f.agent])
    return TTL[f.agent]


def _norm(t: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]+", t.lower()))


def _similar(a: str, b: str) -> bool:
    x, y = _norm(a), _norm(b)
    return bool(x and y) and len(x & y) / len(x | y) >= 0.8


def pending_finding(agent: str, demo: bool) -> Finding:
    return Finding(agent=agent, status="pending", takeaway="Still working on this. It will appear when ready.", demo=demo)


class Orchestrator:
    def __init__(self, agents: dict[str, Agent], make_ctx: Callable[[Asset], Ctx], *, demo: bool = False, explainer=None, cache: SharedCache | None = None,
                 clock: Callable[[], float] = time.monotonic, wall: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.agents, self.make_ctx, self.demo, self.explainer = agents, make_ctx, demo, explainer
        self.cache: SharedCache[Finding] = cache or SharedCache(clock=clock)
        self._clock, self._wall = clock, wall
        self._last_refresh: dict[tuple, float] = {}

    async def _run(self, name: str, asset: Asset) -> Finding:
        ctx = self.make_ctx(asset)
        ctx.now = self._wall()
        try:
            f = await asyncio.wait_for(self.agents[name].run(ctx), AGENT_TIMEOUT[name])
        except asyncio.TimeoutError:
            f = unavailable(name, "The analysis took too long and was stopped.", self.demo)
        except Exception as e:  # noqa: BLE001  one agent's bug must never take down the others
            log.exception("signal agent %s failed for %s", name, asset.id)
            f = unavailable(name, f"Internal error ({type(e).__name__}).", self.demo)
        f = f.model_copy(update={"agent": name, "demo": bool(self.demo or f.demo)})
        now = self._wall()
        ttl = ttl_for(f)
        f.analyzed_at, f.ttl_seconds, f.next_refresh_at = iso(now), int(ttl), iso(now + timedelta(seconds=ttl))
        if self.explainer is not None and f.status in ("ok", "partial"):
            try:
                f.explanation = await asyncio.wait_for(self.explainer.explain(f, asset), 25)
            except Exception:  # noqa: BLE001  the rule-based text is always there; the AI text is optional
                f.explanation = None
        return f

    async def research(self, asset: Asset, wait: float | None = 6.0) -> dict:
        entries = await asyncio.gather(*(self.cache.get((n, asset.id), (lambda n=n: self._run(n, asset)), ttl_for, wait) for n in AGENTS))
        findings: dict[str, Finding] = {}
        pending = []
        for n, e in zip(AGENTS, entries):
            if e is None:
                findings[n] = pending_finding(n, self.demo)
                pending.append(n)
            else:
                findings[n] = e.value
        now = self._wall()
        return {"asset": asset.public(), "generated_at": iso(now), "demo": self.demo, "pending": pending,
                "findings": {n: f.model_dump(mode="json") for n, f in findings.items()}, "briefing": build_briefing(findings, now, self.demo).model_dump(mode="json")}

    async def refresh(self, asset: Asset, name: str) -> dict:
        if name not in AGENTS:
            raise OrchestratorError("UNKNOWN_AGENT", f"agent must be one of {', '.join(AGENTS)}", 422)
        key = (name, asset.id)
        last = self._last_refresh.get(key)
        if last is not None and self._clock() - last < REFRESH_COOLDOWN:
            raise OrchestratorError("COOLDOWN", f"{AGENT_TITLES[name]} was just refreshed. Try again in {int(REFRESH_COOLDOWN - (self._clock() - last)) + 1}s.", 429)
        self._last_refresh[key] = self._clock()
        if not self.cache.running(key):
            self.cache.invalidate(key)
        await self.cache.get(key, lambda: self._run(name, asset), ttl_for, None)
        return await self.research(asset, wait=None)


def build_briefing(findings: dict[str, Finding], now: datetime, demo: bool) -> Briefing:
    usable = {n: f for n, f in findings.items() if f.status in ("ok", "partial")}
    lines: dict[str, list[BriefingLine]] = {}                       # keys are the Briefing field names: changed, supports, risks, watch
    for kind in ("changed", "supports", "risk", "watch"):
        pool = {n: sorted((p for p in f.points if p.kind == kind), key=lambda p: -p.priority) for n, f in usable.items()}
        picked: list[Point] = []
        seen: set[str] = set()
        while len(picked) < MAX_LINES:
            heads = sorted(((q[0].priority, n) for n, q in pool.items() if q), reverse=True)
            if not heads:
                break
            progressed = False
            for _, n in heads:
                while pool[n]:
                    p = pool[n].pop(0)
                    key = p.dedupe_key or p.text
                    if key in seen or any(_similar(p.text, q.text) for q in picked):
                        continue
                    seen.add(key)
                    picked.append(p)
                    progressed = True
                    break
                if len(picked) >= MAX_LINES:
                    break
            if not progressed:
                break
        picked.sort(key=lambda p: -p.priority)
        lines["risks" if kind == "risk" else kind] = [BriefingLine(agent=p.agent, text=p.text, fact_keys=p.fact_keys, at_utc=p.at_utc) for p in picked]
    dis = []
    views = {n: f.stance for n, f in usable.items() if f.stance in ("supportive", "cautious")}
    names = [n for n in ("technical", "macro", "fundamentals") if n in views]
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if views[a] != views[b]:
                dis.append(Disagreement(agents=[a, b], text=f"{AGENT_TITLES[a]} reads {views[a]} while {AGENT_TITLES[b]} reads {views[b]}. They look at different things ({SCOPE[a]} versus {SCOPE[b]}), so both views are shown."))
    parts = [f"{HEAD_NAME[n]} {STANCE_WORD[f.stance]}" for n in ("technical", "macro", "fundamentals") if (f := usable.get(n)) and f.stance in STANCE_WORD]
    news = usable.get("news")
    n24 = next((fa.value for fa in (news.facts if news else []) if fa.key == "stories_24h"), None)
    if n24 is not None:
        parts.append(f"{n24} news stor{'y' if n24 == 1 else 'ies'} in 24h")
    head = " · ".join(parts) if parts else "Not enough analysis is available yet."
    cov = {"agents_ok": sum(1 for f in findings.values() if f.status == "ok"), "agents_total": len(findings),
           "partial": [n for n, f in findings.items() if f.status == "partial"], "pending": [n for n, f in findings.items() if f.status == "pending"],
           "unavailable": [{"agent": n, "reason": (f.error or "")[:120]} for n, f in findings.items() if f.status == "unavailable"],
           "not_applicable": [n for n, f in findings.items() if f.status == "not_applicable"]}
    return Briefing(headline=head, generated_at=iso(now), demo=demo, coverage=cov, disagreements=dis, **lines)
