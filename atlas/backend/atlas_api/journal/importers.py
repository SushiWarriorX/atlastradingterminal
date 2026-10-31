"""CSV -> executions/cashflows. Tolerant parsing with an explicit, user-visible column mapping.

Nothing is guessed silently: the mapping is suggested from header names, shown to the user, editable, and every row that is skipped or
fails is counted with a reason. Naive timestamps are assumed UTC unless the `tz` option says otherwise (the preview shows the result).
The Variational preset is a BEST GUESS from public documentation summaries: its docs host could not be reached while building this,
so column names are unverified and the preview step exists to catch a wrong guess.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from ..trading.money import ZERO
from .matching import Exec, Flow

ROLES_TRADES = ["ts", "symbol", "side", "qty", "price", "fee", "ext_id", "kind", "status", "currency", "asset_class", "multiplier"]
ROLES_FLOWS = ["ts", "symbol", "amount", "flow_type", "ext_id", "currency", "status"]
ALIASES = {
    "ts": ["timestamp", "datetime", "time", "date", "createdat", "creationtime", "creationtimestamp", "createdtime", "created", "executedat", "tradedate", "tradetime", "filledat", "executiontime"],
    "symbol": ["symbol", "underlying", "market", "pair", "instrument", "asset", "ticker", "contract", "product"],
    "side": ["side", "direction", "buysell", "action"],
    "qty": ["quantity", "qty", "size", "shares", "filledquantity", "filledsize", "executedqty", "amount", "volume"],
    "price": ["price", "tradeprice", "fillprice", "executionprice", "avgprice", "averageprice", "filledprice", "executedprice"],
    "fee": ["fee", "fees", "commission", "ibcommission", "tradingfee", "totalfee", "feeusd"],
    "ext_id": ["tradeid", "fillid", "executionid", "execid", "ibexecid", "transactionid", "id"],
    "kind": ["tradetype", "type", "kind", "category"],
    "status": ["status", "state"],
    "currency": ["currency", "currencyprimary", "quotecurrency", "settlecurrency"],
    "asset_class": ["assetclass", "assetcategory", "securitytype"],
    "multiplier": ["multiplier"],
    "amount": ["amount", "funding", "fundingpayment", "payment", "value", "usdvalue", "pnl"],
    "flow_type": ["transfertype", "type", "kind", "category", "event"],
}
PRESETS = {
    "ibkr_flex": {"label": "IBKR Flex Query (Trades)", "verified": False,
                  "note": "Header names follow IBKR's documented Flex Trade fields; confirm in the preview. Flex timestamps use the time zone chosen in the query: set the timezone option if they are not UTC.",
                  "fixed": {"ts": "DateTime", "symbol": "Symbol", "side": "Buy/Sell", "qty": "Quantity", "price": "TradePrice", "fee": "IBCommission", "ext_id": "IBExecID",
                            "currency": "CurrencyPrimary", "asset_class": "AssetClass", "multiplier": "Multiplier"},
                  "options": {"default_asset_class": "stock"}},
    "variational": {"label": "Variational Omni export (trades)", "verified": False,
                    "note": "Variational documents CSV exports (trades with a type of trade / liquidation / settlement, funding, realized P&L, transfers) but its docs could not be reached to confirm exact column names. Check the suggested mapping in the preview.",
                    "fixed": {}, "options": {"default_asset_class": "crypto", "symbol_strip": ["-PERP", "/USDC", "-USDC", "-USD", "USDC", "PERP"], "venue": "VARIATIONAL"}},
    "generic": {"label": "Generic trades CSV", "verified": True, "note": "", "fixed": {}, "options": {"default_asset_class": "stock"}},
}
BUY = {"buy", "b", "bot", "long", "bid", "buytoopen", "buytoclose", "1", "+", "purchase"}
SELL = {"sell", "s", "sld", "short", "ask", "selltoopen", "selltoclose", "-1", "-", "sale"}
OK_STATUS = {"", "filled", "complete", "completed", "confirmed", "executed", "success", "successful", "settled", "done", "closed"}
FLOW_KINDS = {"funding": "funding", "fundingpayment": "funding", "fundingfee": "funding", "transfer": "transfer", "deposit": "transfer", "withdrawal": "transfer", "withdraw": "transfer",
              "fee": "fee", "fees": "fee", "tradingfee": "fee"}
DEFAULT_KIND = {"trade": "trade", "": "trade", "liquidation": "liquidation", "liquidated": "liquidation", "settlement": "settlement", "settled": "settlement"}
FORMATS = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y%m%d;%H%M%S", "%Y%m%d %H%M%S", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y", "%Y-%m-%d", "%Y%m%d", "%d/%m/%Y %H:%M:%S"]


def norm(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", h.lower())


def suggest_mapping(headers: list[str], roles: list[str], preset: str | None = None) -> dict[str, str | None]:
    """role -> header (or None). Preset fixed names win when present; otherwise greedy alias matching, one column per role."""
    by_norm = {norm(h): h for h in headers}
    used: set[str] = set()
    out: dict[str, str | None] = {}
    fixed = (PRESETS.get(preset or "") or {}).get("fixed", {})
    for r in roles:
        pick = None
        want = fixed.get(r)
        if want and norm(want) in by_norm and by_norm[norm(want)] not in used:
            pick = by_norm[norm(want)]
        else:
            for a in ALIASES.get(r, []):
                h = by_norm.get(a)
                if h and h not in used:
                    pick = h
                    break
        if pick:
            used.add(pick)
        out[r] = pick
    if preset == "ibkr_flex" and out.get("ext_id") is None and "tradeid" in by_norm:
        out["ext_id"] = by_norm["tradeid"]
    return out


def to_decimal(v: str | None) -> Decimal | None:
    if v is None:
        return None
    s = v.strip().replace("−", "-").replace(",", "").replace("$", "").replace(" ", "")
    if s in ("", "-", "--", "n/a", "N/A", "null", "None"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise ValueError(f"not a number: {v!r}")
    return -d if neg else d


def parse_ts(v: str, tz: str = "UTC") -> datetime:
    s = v.strip()
    if not s:
        raise ValueError("empty timestamp")
    if re.fullmatch(r"-?\d+(\.\d+)?", s) and not re.fullmatch(r"\d{8}", s):
        x = float(s)
        x = x / 1e9 if x > 1e17 else x / 1e6 if x > 1e14 else x / 1e3 if x > 1e11 else x      # ns / us / ms / s
        return datetime.fromtimestamp(x, timezone.utc)
    zone = ZoneInfo(tz)
    iso = s.replace("Z", "+00:00") if s.endswith("Z") else s
    try:
        d = datetime.fromisoformat(iso)
    except ValueError:
        d = None
        for f in FORMATS:
            try:
                d = datetime.strptime(s, f)
                break
            except ValueError:
                continue
        if d is None:
            raise ValueError(f"unrecognised timestamp format: {v!r}")
    return (d.replace(tzinfo=zone) if d.tzinfo is None else d).astimezone(timezone.utc)


def norm_symbol(s: str, strip: list[str]) -> str:
    out = s.strip().upper()
    for suf in sorted(strip or [], key=len, reverse=True):
        if out.endswith(suf.upper()) and len(out) > len(suf):
            out = out[: -len(suf)]
    return out.strip("-/ ")


def norm_class(v: str | None, default: str) -> str:
    x = (v or default).strip().lower()
    return {"stk": "stock", "stock": "stock", "equity": "stock", "etf": "stock", "crypto": "crypto", "cash": "forex", "fx": "forex", "fut": "future",
            "opt": "option", "perp": "crypto", "perpetual": "crypto"}.get(x, x or default)


@dataclass
class ParseResult:
    kind: str
    headers: list[str]
    mapping: dict
    options: dict
    executions: list[Exec] = field(default_factory=list)
    flows: list[Flow] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    skipped: Counter = field(default_factory=Counter)
    kinds: Counter = field(default_factory=Counter)
    rows_total: int = 0
    warnings: list[str] = field(default_factory=list)


def read_rows(text: str) -> tuple[list[str], list[dict]]:
    text = text.lstrip("﻿")
    if not text.strip():
        raise ValueError("the file is empty")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rdr = csv.reader(io.StringIO(text), dialect)
    rows = [r for r in rdr if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise ValueError("no data rows found (need a header row and at least one row)")
    headers = [h.strip() for h in rows[0]]
    if len(set(headers)) != len(headers):
        raise ValueError("duplicate column names in the header row")
    out = []
    for n, r in enumerate(rows[1:], start=2):
        out.append({"__line": n, **{h: (r[i].strip() if i < len(r) else "") for i, h in enumerate(headers)}})
    return headers, out


def _ext(source: str, parts: list[str], seen: Counter) -> str:
    h = hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]
    seen[h] += 1
    return f"{h}#{seen[h]}"        # identical rows in one file stay distinct; re-importing the same file reproduces the same ids


def parse(text: str, source: str, kind: str = "trades", mapping: dict | None = None, preset: str | None = None, options: dict | None = None) -> ParseResult:
    headers, rows = read_rows(text)
    roles = ROLES_TRADES if kind == "trades" else ROLES_FLOWS
    pre = PRESETS.get(preset or "", {})
    m = {**suggest_mapping(headers, roles, preset), **{k: v for k, v in (mapping or {}).items() if v is not None or k in (mapping or {})}}
    m = {k: (v if v in headers else None) for k, v in m.items()}
    opts = {"tz": "UTC", "default_asset_class": "stock", "symbol_strip": [], "venue": None, "amount_sign": "as_is", "default_currency": "USD", **pre.get("options", {}), **(options or {})}
    res = ParseResult(kind, headers, m, opts, rows_total=len(rows))
    required = ["ts", "symbol", "price", "qty"] if kind == "trades" else ["ts", "amount"]
    missing = [r for r in required if not m.get(r)]
    if kind == "trades" and not m.get("side") and not m.get("qty"):
        missing.append("side")
    if missing:
        res.errors.append({"line": 1, "error": f"required column(s) not mapped: {', '.join(missing)}"})
        return res
    seen: Counter = Counter()
    unknown: Counter = Counter()
    for row in rows:
        line = row["__line"]
        g = lambda role: row.get(m[role], "") if m.get(role) else ""
        try:
            st = norm(g("status"))
            if st not in {norm(x) for x in OK_STATUS}:
                res.skipped[f"status={g('status') or '?'}"] += 1
                continue
            ts = parse_ts(g("ts"), opts["tz"])
            ccy = (g("currency") or opts["default_currency"]).upper()
            if kind == "trades":
                qty, price = to_decimal(g("qty")), to_decimal(g("price"))
                if qty is None or price is None:
                    raise ValueError("missing quantity or price")
                sd = norm(g("side"))
                if m.get("side"):
                    side = "buy" if sd in BUY else "sell" if sd in SELL else None
                    if side is None:
                        raise ValueError(f"unrecognised side {g('side')!r}")
                else:
                    side = "sell" if qty < 0 else "buy"          # signed-quantity exports
                if qty == 0:
                    res.skipped["zero quantity"] += 1
                    continue
                if price < 0:
                    raise ValueError("negative price")
                fee = abs(to_decimal(g("fee")) or ZERO)
                knd = DEFAULT_KIND.get(norm(g("kind")))
                if knd is None:
                    unknown[g("kind")] += 1
                    knd = "trade"
                res.kinds[knd] += 1
                sym = norm_symbol(g("symbol"), opts["symbol_strip"])
                if not sym:
                    raise ValueError("empty symbol")
                ext = g("ext_id") or _ext(source, [ts.isoformat(), sym, side, str(abs(qty)), str(price), str(fee)], seen)
                mult = to_decimal(g("multiplier")) or Decimal(1)
                res.executions.append(Exec(source=source, ext_id=ext, ts=ts, symbol=sym, asset_class=norm_class(g("asset_class"), opts["default_asset_class"]), side=side, qty=abs(qty),
                                           price=price, fee=fee, kind=knd, currency=ccy, multiplier=abs(mult) or Decimal(1),
                                           instrument_id=f"CRYPTO:{opts['venue']}:{sym}-USD:PERP" if opts.get("venue") else None))
            else:
                amt = to_decimal(g("amount"))
                if amt is None:
                    raise ValueError("missing amount")
                if opts["amount_sign"] == "invert":
                    amt = -amt
                ft = FLOW_KINDS.get(norm(g("flow_type")), None)
                if ft is None:
                    res.skipped[f"type={g('flow_type') or '?'} (not funding/fee/transfer; exchange-reported P&L is not used)"] += 1
                    continue
                res.kinds[ft] += 1
                sym = norm_symbol(g("symbol"), opts["symbol_strip"]) if g("symbol") else None
                ext = g("ext_id") or _ext(source, [ts.isoformat(), sym or "", ft, str(amt)], seen)
                res.flows.append(Flow(source=source, ext_id=ext, ts=ts, symbol=sym or None, kind=ft, amount=amt, currency=ccy))
        except ValueError as e:
            res.errors.append({"line": line, "error": str(e)})
    if kind == "flows" and res.flows and opts["amount_sign"] == "as_is":
        res.warnings.append("Funding signs: a POSITIVE amount is treated as money RECEIVED. If your export shows payments made as positive, set amount_sign to invert.")
    if unknown:
        res.warnings.append(f"unknown trade type value(s) treated as normal trades: {dict(unknown)}")
    if res.executions or res.flows:
        if opts["tz"] == "UTC":
            res.warnings.append("Timestamps without a timezone are assumed UTC. If your export uses local time, set the timezone option: time-of-day statistics depend on it.")
    return res
