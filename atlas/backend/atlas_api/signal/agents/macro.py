"""Macro agent: explains the parts of the macro backdrop this particular asset is exposed to (rates, inflation, the dollar, liquidity, upcoming events).

Official figures (FRED series and the Fed's calendar, via the ATLAS Macro dashboard and Fed Watch services) are kept separate from interpretation. The
interpretation is rule-based and conditional: it says how such assets have tended to react, never what will happen. The stance counts which exposures are
currently tailwinds or headwinds, each equally; it describes the backdrop and is not a forecast.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .. import fmt
from ..exposure import exposure_for, phrase
from ..models import EventItem, Finding, Interpretation, Missing, Point, Source
from .common import Ctx, iso, mk_fact, unavailable

FRED = "FRED (St. Louis Fed)"
YIELD_MOVE_BPS, USD_MOVE_PCT, CORE_CPI_HIGH, CORE_CPI_GOAL, CURVE_FLAT_BPS = 25.0, 2.0, 3.0, 2.0, 50.0
STANCE_RULE = ("Each exposure that applies to this asset counts once: +1 when its current reading has tended to help this kind of asset, -1 when it has tended to hurt "
               "(rising 10Y yield by 25+ bps in a month, dollar up 2%+, Fed balance sheet shrinking, core CPI 3%+, inverted curve). Net +1 or more reads supportive, -1 or less cautious, "
               "otherwise mixed. At least two exposures must be measurable. Thresholds are hand-chosen and uncalibrated.")
DRIVER_NAME = {"yields": "interest-rate", "usd": "dollar", "liquidity": "liquidity", "inflation": "inflation", "curve": "yield-curve"}


def _chg(f: dict | None, part: str) -> float | None:
    return next((c["value"] for c in (f or {}).get("changes", []) if part in c["label"] and c.get("value") is not None), None)


def measure(F: dict[str, dict], bs: dict | None) -> dict[str, tuple[int, str]]:
    """driver -> (state, short text). state +1 = rising / high / steeper / growing, -1 = the opposite, 0 = neutral."""
    out: dict[str, tuple[int, str]] = {}
    ch = _chg(F.get("us10y"), "1 month")
    if ch is not None:
        out["yields"] = (1 if ch >= YIELD_MOVE_BPS else -1 if ch <= -YIELD_MOVE_BPS else 0, f"{ch:+.0f} bps")
    ch = _chg(F.get("usd"), "1 month")
    if ch is not None:
        out["usd"] = (1 if ch >= USD_MOVE_PCT else -1 if ch <= -USD_MOVE_PCT else 0, f"{ch:+.1f}%")
    c = F.get("curve", {}).get("value")
    if c is not None:
        out["curve"] = (-1 if c < 0 else 0 if c < CURVE_FLAT_BPS else 1, f"{c:+.0f} bps")
    ci = F.get("core_cpi", {}).get("value")
    if ci is not None:
        out["inflation"] = (1 if ci >= CORE_CPI_HIGH else -1 if ci < CORE_CPI_GOAL else 0, f"{ci:.1f}% y/y")
    if bs and bs.get("trend") and "error" not in bs:
        out["liquidity"] = ({"growing": 1, "shrinking": -1}.get(bs["trend"], 0), bs["trend"])
    return out


def _word(sign: int, state: int, good: str, bad: str, none: str) -> str:
    c = sign * state
    return good if c > 0 else bad if c < 0 else none


def driver_text(driver: str, state: int, sign: int, label: str, detail: str) -> str:
    L = phrase(label)
    if driver == "yields":
        if state == 0:
            return f"The 10-year yield is little changed over about a month ({detail})."
        return (f"The 10-year yield {'rose' if state > 0 else 'fell'} {detail.replace('+', '').replace('-', '')} over about a month. "
                f"{'Rising' if state > 0 else 'Falling'} yields have tended to {_word(sign, state, 'support', 'weigh on', 'matter little for')} {L}.")
    if driver == "usd":
        if state == 0:
            return f"The broad dollar index is little changed over about a month ({detail})."
        return (f"The broad dollar index {'rose' if state > 0 else 'fell'} {detail.replace('+', '').replace('-', '')} over about a month. "
                f"A {'stronger' if state > 0 else 'weaker'} dollar has tended to {_word(sign, state, 'help', 'weigh on', 'matter little for')} {L}.")
    if driver == "curve":
        if state < 0:
            return f"The 10Y-2Y yield curve is inverted ({detail}). Inversions have often come before slowdowns, which has tended to be a headwind for {L}, with timing that varies widely."
        if state == 0:
            return f"The 10Y-2Y yield curve is nearly flat ({detail})."
        return f"The 10Y-2Y yield curve is positively sloped ({detail}), the usual shape when growth fears are not acute."
    if driver == "inflation":
        if state > 0:
            return f"Core CPI inflation is {detail}, well above the Fed's 2% goal. Persistent inflation can keep interest rates higher for longer, which has tended to {_word(sign, state, 'help', 'weigh on', 'matter little for')} {L}."
        if state < 0:
            return f"Core CPI inflation is {detail}, below the Fed's 2% goal, which leaves the Fed more room to ease."
        return f"Core CPI inflation is {detail}, modestly above the Fed's 2% goal."
    if driver == "liquidity":
        return (f"The Fed's balance sheet is {detail} over about 13 weeks. "
                f"{'Shrinking holdings tighten liquidity' if state < 0 else 'Growing holdings add liquidity' if state > 0 else 'A steady balance sheet leaves liquidity unchanged'}, which has tended to "
                f"{_word(sign, state, 'help', 'weigh on', 'matter little for')} {L}.")
    return ""


def scenario_text(driver: str, sign: int, label: str) -> str:
    L = phrase(label)
    up = "weigh on" if sign < 0 else "help"
    down = "help" if sign < 0 else "weigh on"
    name = {"yields": "the 10-year yield keeps rising", "usd": "the dollar keeps strengthening", "liquidity": "the Fed's balance sheet keeps growing",
            "inflation": "inflation stays high", "curve": "the yield curve steepens"}[driver]
    back = {"yields": "yields fall back", "usd": "the dollar weakens", "liquidity": "the balance sheet shrinks", "inflation": "inflation cools", "curve": "the curve flattens or inverts"}[driver]
    return (f"Scenario: if {name}, that has tended to {up} {L}; if {back}, that has tended to {down} {L}. "
            "Reactions differ by period, and the reason behind the move matters.")


class MacroAgent:
    name = "macro"

    async def run(self, ctx: Ctx) -> Finding:
        a, now = ctx.asset, ctx.now
        exp = exposure_for(a)
        if ctx.demo:
            from .. import fixtures
            ov, fw = fixtures.macro_overview(now), fixtures.fedwatch(now)
        else:
            if ctx.macro is None:
                return unavailable("macro", "The FRED data provider is not configured.", False)
            ov = fw = None
            try:
                ov = await ctx.macro.overview()
            except Exception as e:  # noqa: BLE001
                return unavailable("macro", f"Macro dashboard unavailable ({type(e).__name__})", False)
            try:
                fw = await ctx.fedwatch.overview(now)
            except Exception:  # noqa: BLE001  events and the balance sheet are optional
                fw = None
        F = {f["id"]: f for f in ov.get("facts", []) if "error" not in f}
        errors = {f["id"]: f["error"] for f in ov.get("facts", []) if "error" in f}
        bs = (fw or {}).get("balance_sheet")
        demo = bool(ov.get("demo_fixture") or ctx.demo)
        src = "Demo fixture (synthetic, not real)" if demo else FRED
        if not F:
            return unavailable("macro", ov.get("notice") or "No macro series could be loaded: " + "; ".join(errors.values())[:150], demo)
        meas = measure(F, bs)
        used = {d: (s, t) for d, (s, t) in meas.items() if d in exp.drivers}
        facts = _facts(F, bs, used, src, demo)
        contrib = {d: exp.drivers[d] * s for d, (s, _) in used.items()}
        net = sum(contrib.values())
        stance = "insufficient" if len(used) < 2 else "supportive" if net >= 1 else "cautious" if net <= -1 else "mixed"
        interp = [Interpretation(text=exp.rationale, based_on=[], caveat="A general tendency for this kind of asset, not a rule.")]
        keymap = {"yields": ["us10y_chg_1m_bps"], "usd": ["usd_chg_1m_pct"], "curve": ["curve_bps"], "inflation": ["core_cpi_yoy"], "liquidity": ["balance_sheet_trend"]}
        for d, (s, t) in used.items():
            txt = driver_text(d, s, exp.drivers[d], exp.label, t)
            if txt:
                interp.append(Interpretation(text=txt, based_on=keymap[d], caveat="A tendency, not a forecast; the reason behind a move matters."))
        for d in list(used)[:2]:
            interp.append(Interpretation(text=scenario_text(d, exp.drivers[d], exp.label), based_on=keymap[d], caveat="A conditional scenario, not a prediction."))
        events = _events(ctx, fw, exp, now)
        pts = _points(a, exp, used, contrib, events, F, now)
        tail = [d for d, c in contrib.items() if c > 0]
        head = [d for d, c in contrib.items() if c < 0]
        takeaway = _takeaway(exp, stance, tail, head, events, now)
        missing = [Missing(what=f"{DRIVER_NAME.get(k, k).title()} data", why=str(v)[:120]) for k, v in errors.items() if k in ("us10y", "curve", "core_cpi", "usd", "fed")]
        for d in exp.drivers:
            if d not in meas:
                missing.append(Missing(what=f"{DRIVER_NAME[d].title()} exposure", why="the data needed to measure it is not available right now"))
        if fw is None and not ctx.demo:
            missing.append(Missing(what="Fed Watch (balance sheet and upcoming events)", why="the Fed Watch service did not respond"))
        limits = ["Describes the backdrop for this kind of asset; it is not a forecast and not advice.",
                  "FRED observation dates lag publication, CPI is monthly, and some readings are weeks old by design (see each fact's date).",
                  "Driver thresholds are hand-chosen and uncalibrated. The Macro dashboard and Fed Watch features are new and have not yet been verified against live data."]
        status = "ok" if not missing else "partial"
        as_of = max((f.get("obs_date") for f in F.values() if f.get("obs_date")), default=None)
        sources = [Source(name=src, url=None if demo else "https://fred.stlouisfed.org/", kind="official", as_of=as_of, status="DEMO" if demo else "HISTORICAL",
                          note="Observation dates, not publication times")]
        if not demo:
            sources.append(Source(name="Federal Reserve FOMC calendar (entered by hand)", url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", kind="official"))
        return Finding(agent="macro", status=status, stance=stance, stance_rule=STANCE_RULE, takeaway=takeaway, facts=facts, interpretations=interp, events=events,
                       missing=missing, sources=sources, limitations=limits, points=pts, data_as_of=as_of, demo=demo)


def _facts(F: dict, bs: dict | None, used: dict, src: str, demo: bool) -> list:
    out = []
    kind = "reported"
    y, yc = F.get("us10y"), _chg(F.get("us10y"), "1 month")
    if "yields" in used and y:
        out.append(mk_fact("us10y", "US 10-year Treasury yield", y["value"], f"{y['value']:.2f}%", src, as_of=y["obs_date"], kind=kind, unit="%"))
        out.append(mk_fact("us10y_chg_1m_bps", "10-year yield, change over ~1 month", yc, fmt.bps(yc), src, as_of=y["obs_date"], unit="bps"))
    u = F.get("usd")
    if "usd" in used and u:
        out.append(mk_fact("usd_level", "Broad US dollar index (not DXY)", u["value"], f"{u['value']:.1f}", src, as_of=u["obs_date"], kind=kind))
        out.append(mk_fact("usd_chg_1m_pct", "Dollar index, change over ~1 month", _chg(u, "1 month"), fmt.pct(_chg(u, "1 month"), signed=True), src, as_of=u["obs_date"], unit="%"))
    c = F.get("curve")
    if "curve" in used and c:
        out.append(mk_fact("curve_bps", "Yield curve (10Y minus 2Y)", c["value"], fmt.bps(c["value"]), src, as_of=c["obs_date"], unit="bps"))
    ci = F.get("core_cpi")
    if "inflation" in used and ci:
        out.append(mk_fact("core_cpi_yoy", "Core CPI inflation (year over year)", ci["value"], f"{ci['value']:.1f}%", src, as_of=ci["obs_date"], kind=kind, unit="%"))
    if "liquidity" in used and bs:
        out.append(mk_fact("balance_sheet_trend", "Fed balance sheet, ~13-week direction", bs.get("trend"), f"{bs.get('trend')} ({bs.get('value', 0):.2f} trillion dollars)", src, as_of=bs.get("obs_date"), kind="calculated"))
    f = F.get("fed")
    if f:
        out.append(mk_fact("fed_target", "Fed funds target range", f"{f['lower']:.2f}-{f['upper']:.2f}", f"{f['lower']:.2f}–{f['upper']:.2f}%", src, as_of=f["obs_date"], kind=kind, unit="%"))
    return out


def _events(ctx: Ctx, fw: dict | None, exp, now: datetime) -> list[EventItem]:
    ev: list[EventItem] = []
    if fw:
        nxt = next((e for e in fw.get("upcoming", []) if e["type"] == "statement"), None)
        if nxt:
            ev.append(EventItem(id=nxt["id"], title="FOMC interest-rate decision", at_utc=nxt["at_utc"], kind="scheduled", link=nxt.get("link"), note=nxt.get("meeting")))
        for r in fw.get("release_schedule", []):
            if r["series"] == "cpi" and "inflation" not in exp.drivers:
                continue
            if any(e.id == f"rel-{r['series']}" for e in ev):
                continue
            ev.append(EventItem(id=f"rel-{r['series']}", title={"cpi": "US CPI inflation release", "jobs": "US jobs report"}.get(r["series"], r["label"]), at_utc=r.get("at_utc"), date=r["date"], kind="release",
                                link="https://www.bls.gov/schedule/news_release/", note="BLS release calendar"))
    return ev[:3]


def _points(a, exp, used, contrib, events, F, now) -> list[Point]:
    P: list[Point] = []
    add = lambda kind, text, prio, keys, dk, at=None: P.append(Point(kind=kind, text=text, agent="macro", fact_keys=keys, priority=prio, dedupe_key=dk, at_utc=at))
    keymap = {"yields": ["us10y_chg_1m_bps"], "usd": ["usd_chg_1m_pct"], "curve": ["curve_bps"], "inflation": ["core_cpi_yoy"], "liquidity": ["balance_sheet_trend"]}
    L = phrase(exp.label)
    for d, (s, t) in used.items():
        c = contrib[d]
        if d in ("yields", "usd") and s != 0:
            word = "rose" if s > 0 else "fell"
            nm = "The 10-year yield" if d == "yields" else "The broad dollar index"
            add("changed", f"{nm} {word} {t.replace('+', '').replace('-', '')} over about a month.", 64, keymap[d], f"macro-{d}-move")
        if c > 0:
            subj = {"yields": "Falling yields" if s < 0 else "Rising yields", "usd": "A weaker dollar" if s < 0 else "A stronger dollar", "liquidity": "Growing Fed liquidity", "inflation": "Cooling inflation" if s < 0 else "High inflation",
                    "curve": "A steeper yield curve"}[d]
            add("supports", f"{subj} {'have' if subj.endswith('yields') else 'has'} tended to help {L} ({t}).", 58, keymap[d], f"macro-{d}-tail")
        elif c < 0:
            subj = {"yields": "Rising yields" if s > 0 else "Falling yields", "usd": "A stronger dollar" if s > 0 else "A weaker dollar", "liquidity": "A shrinking Fed balance sheet", "inflation": "High inflation" if s > 0 else "Low inflation",
                    "curve": "An inverted yield curve"}[d]
            add("risk", f"{subj} {'have' if subj.endswith('yields') else 'has'} tended to weigh on {L} ({t}).", 66, keymap[d], f"macro-{d}-head")
    fomc = next((e for e in events if e.id.startswith("statement")), None)
    if fomc and fomc.at_utc:
        days = (datetime.fromisoformat(fomc.at_utc) - now).total_seconds() / 86400
        if 0 <= days <= 10:
            away = "less than a day away" if days < 1 else f"{round(days)} day{'s' if round(days) != 1 else ''} away"
            add("risk", f"An FOMC interest-rate decision is {away}: rate-sensitive assets can move sharply around it.", 62, ["fed_target"], "macro-fomc-risk", fomc.at_utc)
        add("watch", "Next FOMC interest-rate decision.", 80 if days <= 14 else 60, ["fed_target"], "macro-fomc", fomc.at_utc)
    for e in events:
        if e.id.startswith("rel-"):
            add("watch", f"{e.title}.", 58, ["core_cpi_yoy"] if "cpi" in e.id else [], f"macro-{e.id}", e.at_utc)
    return P


def _takeaway(exp, stance: str, tail: list[str], head: list[str], events: list[EventItem], now: datetime) -> str:
    L = phrase(exp.label)
    if stance == "insufficient":
        return f"Not enough macro readings are available to judge the backdrop for {L}."
    word = {"supportive": "leans supportive", "cautious": "leans cautious", "mixed": "is mixed"}[stance]
    parts = []
    if tail:
        parts.append(" and ".join(DRIVER_NAME[d] for d in tail[:2]) + (" conditions help" if len(tail) > 1 else " conditions help"))
    if head:
        parts.append(" and ".join(DRIVER_NAME[d] for d in head[:2]) + " conditions weigh")
    detail = (": " + "; ".join(parts)) if parts else ": nothing is pushing strongly either way"
    return f"The macro backdrop for {L} {word}{detail}."
