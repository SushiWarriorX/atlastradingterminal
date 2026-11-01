"""Command-bar grammar -> validated structured operation. No free-form execution."""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from . import instruments as I

# view -> implementation status (single source of truth; the UI reads this via /api/meta/views)
VIEWS = {
    "overview": (True, None, "Global Market Overview"),
    "btc": (True, None, "BTC Trading Desk"),
    "equities": (True, None, "US Equity Trading Desk"),
    "charts": (True, None, "Multi-chart"),
    "scanner": (True, None, "Equity scanner (daily bars, Yahoo)"),
    "news": (True, None, "News (RSS headlines, polled)"),
    "macro": (True, None, "Macro Research Desk"),
    "ai": (True, None, "AI Research Desk"),
    "backtest": (True, None, "Backtester (daily bars, point-in-time rules)"),
    "journal": (True, None, "Trade journal and performance"),
    "settings": (True, None, "Settings"),
}
NAV = {"OVERVIEW": "overview", "BTC": "btc", "EQUITIES": "equities", "CHARTS": "charts",
       "SCAN": "scanner", "SCANNER": "scanner", "NEWS": "news", "MACRO": "macro", "FED": "macro", "CPI": "macro",
       "AI": "ai",
       "BACKTEST": "backtest", "BT": "backtest", "JOURNAL": "journal", "PERF": "journal", "PERFORMANCE": "journal", "SETTINGS": "settings"}
FUNCS = {"MTF": "equities", "CHART": "charts", "GP": "charts", "NEWS": "news", "N": "news", "TECH": "charts",
         "OI": "btc", "FUNDING": "btc", "DES": "equities", "AI": "ai"}
MACRO_PARAMS = {"FED": "fed", "CPI": "inflation"}
# Which sub-feature of an implemented view is missing -> honest message
PARTIAL = {"FED": (5, "Fed dashboard (policy rate, FOMC calendar) not built; showing yields"),
           "CPI": (5, "CPI dashboard not built; showing yields")}
# Words from sections that were removed: a clear message beats treating "BUY" or "RISK" as a ticker symbol.
REMOVED = {"BUY": "Order drafting", "SELL": "Order drafting", "ALERT": "Alerts", "ALERTS": "Alerts", "PORT": "Portfolio", "PORTFOLIO": "Portfolio", "RISK": "Risk",
           "IDEAS": "Trade Ideas", "MARKETS": "Markets", "FUNDAMENTALS": "Fundamentals", "FA": "Fundamentals"}
ALL_WORDS = sorted(set(NAV) | set(FUNCS) | {"HELP", "COMPARE"})


@dataclass
class Command:
    ok: bool
    view: str | None = None
    instrument_ids: list[str] = field(default_factory=list)
    params: dict = field(default_factory=dict)
    implemented: bool = True
    phase: int | None = None
    message: str | None = None
    error: str | None = None
    suggestions: list[str] = field(default_factory=list)


def _sym(token: str):
    return I.by_symbol(token) or (I.adhoc(token) if token.isalpha() and len(token) <= 5 else None)


def _suggest(token: str) -> list[str]:
    pool = ALL_WORDS + [i.symbol for i in I.CATALOG]
    return difflib.get_close_matches(token.upper(), pool, n=3, cutoff=0.6)


def resolve(text: str) -> Command:
    toks = text.strip().upper().split()
    if not toks:
        return Command(False, error="Type a command, symbol, or question. HELP lists commands.")
    if len(toks) > 4 and toks[0] not in ALL_WORDS and toks[0] not in REMOVED:
        return Command(True, view="ai", params={"ask": text.strip()}, message="Free-text question routed to the AI Research Desk.")

    head = toks[0]
    if head == "HELP":
        return Command(True, view="help")
    if head == "COMPARE":
        insts = [_sym(t) for t in toks[1:]]
        if len(toks) < 3 or any(i is None for i in insts):
            return Command(False, error="Usage: COMPARE <SYM> <SYM>, e.g. COMPARE BTC QQQ")
        if len(insts) > 4 or len({i.id for i in insts}) != len(insts):
            return Command(False, error="COMPARE takes 2 to 4 distinct symbols.")
        return Command(True, view="charts", instrument_ids=[i.id for i in insts], params={"compare": [i.id for i in insts]},
                       message="Comparing on calendar-aligned daily bars (rebased to 100).")
    if head in REMOVED:
        return Command(False, error=f"'{head}' is not available: the {REMOVED[head]} section was removed from ATLAS. HELP lists the commands that exist.")
    if head == "AI":
        inst = _sym(toks[1]) if len(toks) > 1 else None
        return Command(True, view="ai", instrument_ids=[inst.id] if inst else [], params={"brief": bool(inst)})
    if head in PRESET_VIEWS and len(toks) > 1:
        return _preset_command(PRESET_VIEWS[head], toks)
    if head in NAV and head not in ("BTC",) or (head == "BTC" and len(toks) == 1):
        if head == "BTC":
            inst = I.by_symbol("BTC")
            return Command(True, view="btc", instrument_ids=[inst.id])
        view = NAV[head]
        impl, phase, note = VIEWS[view]
        extra = PARTIAL.get(head)
        return Command(True, view=view, params={"focus": MACRO_PARAMS[head]} if head in MACRO_PARAMS else {},
                       implemented=impl, phase=None if impl else phase,
                       message=(extra[1] if extra else (None if impl else note)))

    inst = _sym(head)
    if inst is None:
        s = _suggest(head)
        return Command(False, error=f"Unknown command or symbol '{head}'." + (f" Did you mean {', '.join(s)}?" if s else " HELP lists commands."), suggestions=s)
    if len(toks) == 1:
        return Command(True, view=_desk_for(inst), instrument_ids=[inst.id], message=inst.note)
    fn = toks[1]
    if fn not in FUNCS:
        s = difflib.get_close_matches(fn, list(FUNCS), n=3, cutoff=0.5)
        return Command(False, error=f"Unknown function '{fn}' for {inst.symbol}." + (f" Did you mean {', '.join(s)}?" if s else ""), suggestions=s)
    view = FUNCS[fn]
    if view == "equities":
        view = _desk_for(inst)
    if fn in ("NEWS", "N"):
        return Command(True, view="news", instrument_ids=[inst.id])
    partial = PARTIAL.get(fn)
    return Command(True, view=view, instrument_ids=[inst.id], params={"function": fn},
                   implemented=partial is None, phase=partial[0] if partial else None, message=partial[1] if partial else inst.note)


PRESET_VIEWS = {"SCAN": "scanner", "SCANNER": "scanner", "BACKTEST": "backtest", "BT": "backtest"}


def _preset_command(view: str, toks: list[str]) -> Command:
    """SCAN <preset> and BACKTEST <preset> share the scanner's presets, aliases and "not built" list."""
    from .scanner.presets import ALIASES, PRESETS, UNAVAILABLE_PRESETS

    pid = ALIASES.get(toks[1], "_".join(toks[1:]).lower())
    if pid in UNAVAILABLE_PRESETS:
        return Command(True, view=view, implemented=False, phase=4, message=UNAVAILABLE_PRESETS[pid])
    if pid not in PRESETS:
        what = "scan" if view == "scanner" else "backtest"
        s = difflib.get_close_matches(toks[1], list(ALIASES) + [p.upper() for p in PRESETS], n=3, cutoff=0.5)
        return Command(False, error=f"Unknown {what} '{' '.join(toks[1:])}'." + (f" Did you mean {', '.join(s)}?" if s else " Presets: " + ", ".join(sorted(ALIASES))), suggestions=s)
    return Command(True, view=view, params={"preset": pid})


def _desk_for(inst) -> str:
    """Which desk an instrument belongs on: BTC desk is BTC only, Equities desk is stocks and ETFs only, everything else (indices, macro series) goes to Charts."""
    return "btc" if inst.asset_class == "crypto" else "equities" if inst.asset_class in ("equity", "etf") else "charts"


def suggest(prefix: str, limit: int = 8) -> list[dict]:
    p = prefix.strip().upper()
    if not p:
        return []
    last = p.split()[-1]
    out = [{"text": w, "kind": "command"} for w in ALL_WORDS if w.startswith(last)]
    out += [{"text": i.symbol, "kind": "symbol", "name": i.name, "id": i.id} for i in I.search(last, 6) if len(p.split()) == 1]
    return out[:limit]
