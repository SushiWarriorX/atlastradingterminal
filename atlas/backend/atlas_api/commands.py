"""Command-bar grammar -> validated structured operation. No free-form execution."""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from . import instruments as I

# view -> implementation status (single source of truth; the UI reads this via /api/meta/views)
VIEWS = {
    "overview": (True, None, "Global Market Overview"),
    "markets": (True, None, "Markets"),
    "btc": (True, None, "BTC Trading Desk"),
    "equities": (True, None, "US Equity Trading Desk"),
    "charts": (True, None, "Multi-chart"),
    "scanner": (True, None, "Equity scanner (daily bars, Yahoo)"),
    "news": (True, None, "News (RSS headlines, polled)"),
    "macro": (True, None, "Macro Research Desk"),
    "ai": (True, None, "AI Research Desk"),
    "ideas": (False, 6, "Trade idea board"),
    "portfolio": (True, None, "Portfolio and paper trading"),
    "risk": (True, None, "Portfolio risk"),
    "fundamentals": (True, None, "Company fundamentals (Yahoo, unofficial)"),
    "backtest": (True, None, "Backtester (daily bars, point-in-time rules)"),
    "journal": (True, None, "Trade journal and performance"),
    "alerts": (True, None, "Alerts"),
    "settings": (True, None, "Settings"),
}
NAV = {"OVERVIEW": "overview", "MARKETS": "markets", "BTC": "btc", "EQUITIES": "equities", "CHARTS": "charts",
       "SCAN": "scanner", "SCANNER": "scanner", "NEWS": "news", "MACRO": "macro", "FED": "macro", "CPI": "macro",
       "AI": "ai", "IDEAS": "ideas", "PORT": "portfolio", "PORTFOLIO": "portfolio", "RISK": "risk",
       "BACKTEST": "backtest", "BT": "backtest", "FA": "fundamentals", "FUNDAMENTALS": "fundamentals", "JOURNAL": "journal", "PERF": "journal", "PERFORMANCE": "journal", "ALERTS": "alerts", "SETTINGS": "settings"}
FUNCS = {"MTF": "equities", "CHART": "charts", "GP": "charts", "NEWS": "news", "N": "news", "TECH": "charts", "FA": "fundamentals",
         "OI": "btc", "FUNDING": "btc", "DES": "equities", "AI": "ai"}
MACRO_PARAMS = {"FED": "fed", "CPI": "inflation"}
# Which sub-feature of an implemented view is missing -> honest message
PARTIAL = {"FED": (5, "Fed dashboard (policy rate, FOMC calendar) not built; showing yields"),
           "CPI": (5, "CPI dashboard not built; showing yields")}
ALL_WORDS = sorted(set(NAV) | set(FUNCS) | {"HELP", "COMPARE", "ALERT", "BUY", "SELL"})


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
    if len(toks) > 4 and not toks[0] in ALL_WORDS:
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
    if head in ("BUY", "SELL") and len(toks) > 1:
        return _order_draft(head, toks[1:])
    if head in ("ALERT", "ALERTS") and len(toks) > 1:
        return _alert_draft(toks[1:])
    if head == "AI":
        inst = _sym(toks[1]) if len(toks) > 1 else None
        return Command(True, view="ai", instrument_ids=[inst.id] if inst else [], params={"brief": bool(inst)})
    if head in ("SCAN", "SCANNER") and len(toks) > 1:
        from .scanner.presets import ALIASES, PRESETS, UNAVAILABLE_PRESETS

        key = "_".join(toks[1:]).lower()
        pid = ALIASES.get(toks[1], key)
        if pid in UNAVAILABLE_PRESETS:
            return Command(True, view="scanner", implemented=False, phase=4, message=UNAVAILABLE_PRESETS[pid])
        if pid not in PRESETS:
            s = difflib.get_close_matches(toks[1], list(ALIASES) + [p.upper() for p in PRESETS], n=3, cutoff=0.5)
            return Command(False, error=f"Unknown scan '{' '.join(toks[1:])}'." + (f" Did you mean {', '.join(s)}?" if s else " Presets: " + ", ".join(sorted(ALIASES))), suggestions=s)
        return Command(True, view="scanner", params={"preset": pid})
    if head in ("BACKTEST", "BT") and len(toks) > 1:
        from .scanner.presets import ALIASES, PRESETS, UNAVAILABLE_PRESETS

        key = "_".join(toks[1:]).lower()
        pid = ALIASES.get(toks[1], key)
        if pid in UNAVAILABLE_PRESETS:
            return Command(True, view="backtest", implemented=False, phase=4, message=UNAVAILABLE_PRESETS[pid])
        if pid not in PRESETS:
            s = difflib.get_close_matches(toks[1], list(ALIASES) + [p.upper() for p in PRESETS], n=3, cutoff=0.5)
            return Command(False, error=f"Unknown backtest '{' '.join(toks[1:])}'." + (f" Did you mean {', '.join(s)}?" if s else " Presets: " + ", ".join(sorted(ALIASES))), suggestions=s)
        return Command(True, view="backtest", params={"preset": pid})
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

    if head in ("BUY", "SELL"):
        return _order_draft(head, ["?"])      # bare command word: show usage, never treat it as a ticker
    if head == "ALERT":
        return _alert_draft(["?"])
    inst = _sym(head)
    if inst is None:
        s = _suggest(head)
        return Command(False, error=f"Unknown command or symbol '{head}'." + (f" Did you mean {', '.join(s)}?" if s else " HELP lists commands."), suggestions=s)
    if len(toks) == 1:
        return Command(True, view="btc" if inst.asset_class == "crypto" else "equities", instrument_ids=[inst.id],
                       message=inst.note)
    fn = toks[1]
    if fn not in FUNCS:
        s = difflib.get_close_matches(fn, list(FUNCS), n=3, cutoff=0.5)
        return Command(False, error=f"Unknown function '{fn}' for {inst.symbol}." + (f" Did you mean {', '.join(s)}?" if s else ""), suggestions=s)
    view = FUNCS[fn]
    if view == "equities" and inst.asset_class == "crypto":
        view = "btc"
    if fn == "NEWS" or fn == "N":
        return Command(True, view="news", instrument_ids=[inst.id])
    partial = PARTIAL.get(fn)
    return Command(True, view=view, instrument_ids=[inst.id], params={"function": fn},
                   implemented=partial is None, phase=partial[0] if partial else None, message=partial[1] if partial else inst.note)


def _order_draft(side: str, toks: list[str]) -> Command:
    """BUY AAPL 10 | BUY BTC 0.1 LMT 69000 SL 67000 | SELL BTC 0.1 STOP 68000. Returns a DRAFT for the paper ticket: nothing is sent."""
    usage = "Usage: BUY|SELL <SYM> <qty> [LMT <price>] [STOP <price>] [SL <planned stop>]  (paper trading only; opens the ticket, sends nothing)"
    if toks == ["?"]:
        return Command(False, error=usage)
    inst = _sym(toks[0])
    if inst is None or len(toks) < 2:
        return Command(False, error=(f"Unknown symbol '{toks[0]}'. " if inst is None else "") + usage, suggestions=_suggest(toks[0]))
    try:
        num = lambda t: float(t.replace(",", "").lstrip("$"))
        qty, rest, d = num(toks[1]), toks[2:], {}
        if qty <= 0 or len(rest) % 2:
            raise ValueError
        for k, v in zip(rest[::2], rest[1::2]):
            key = {"LMT": "limit_price", "LIMIT": "limit_price", "STOP": "stop_price", "STP": "stop_price", "SL": "planned_stop"}.get(k)
            if key is None or key in d:
                raise ValueError
            d[key] = num(v)
    except ValueError:
        return Command(False, error=usage)
    typ = "stop_limit" if "limit_price" in d and "stop_price" in d else "limit" if "limit_price" in d else "stop" if "stop_price" in d else "market"
    return Command(True, view="portfolio", instrument_ids=[inst.id], params={"order_draft": {"instrument_id": inst.id, "side": side.lower(), "qty": toks[1].replace(",", ""), "type": typ, **{k: str(v).rstrip("0").rstrip(".") if "." in str(v) else str(v) for k, v in d.items()}}},
                   message="Order drafted in the paper ticket. Press Preview to run the risk checks; nothing is sent until you confirm.")


def _alert_draft(toks: list[str]) -> Command:
    """ALERT BTC ABOVE 70000 | ALERT AAPL RSI BELOW 30 | ALERT NVDA RVOL 3. Returns a DRAFT for the user to confirm."""
    usage = "Usage: ALERT <SYM> ABOVE|BELOW <price> · ALERT <SYM> RSI ABOVE|BELOW <n> · ALERT <SYM> RVOL <x>"
    if toks == ["?"]:
        return Command(False, error=usage)
    inst = _sym(toks[0])
    if inst is None:
        return Command(False, error=f"Unknown symbol '{toks[0]}'. {usage}", suggestions=_suggest(toks[0]))
    rest = toks[1:]
    try:
        num = lambda t: float(t.replace(",", "").lstrip("$>=<"))
        if len(rest) == 2 and rest[0] in ("ABOVE", "BELOW", ">", "<"):
            draft = {"kind": "price", "instrument_id": inst.id, "op": "above" if rest[0] in ("ABOVE", ">") else "below", "level": num(rest[1])}
        elif len(rest) == 3 and rest[0] == "RSI" and rest[1] in ("ABOVE", "BELOW"):
            draft = {"kind": "rsi", "instrument_id": inst.id, "op": rest[1].lower(), "level": num(rest[2])}
        elif len(rest) == 2 and rest[0] == "RVOL":
            draft = {"kind": "rvol", "instrument_id": inst.id, "threshold": num(rest[1])}
        else:
            return Command(False, error=usage)
    except ValueError:
        return Command(False, error=f"Could not read the number. {usage}")
    return Command(True, view="alerts", instrument_ids=[inst.id], params={"draft": draft},
                   message="Alert drafted. Review it in the Alerts panel and press Create (nothing is created until you confirm).")


def suggest(prefix: str, limit: int = 8) -> list[dict]:
    p = prefix.strip().upper()
    if not p:
        return []
    last = p.split()[-1]
    out = [{"text": w, "kind": "command"} for w in ALL_WORDS if w.startswith(last)]
    out += [{"text": i.symbol, "kind": "symbol", "name": i.name, "id": i.id} for i in I.search(last, 6) if len(p.split()) == 1]
    return out[:limit]
