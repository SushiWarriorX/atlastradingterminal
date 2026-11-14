"""Research price history for ETFs from the free Nasdaq public feed (api.nasdaq.com), with dividends, turned into a TOTAL-RETURN series. For research experiments only; nothing in Signal shows it.

What the source gives (checked live 2026-11-14): daily open/high/low/close/volume for any US-listed ETF but only the LAST TEN YEARS (the feed stops at 2016-11-14), and dividend history only for Nasdaq-listed funds
(for example TLT, IEF, SHY back to 2002, BND 2007, QQQ 2012, ACWI 2013, VXUS 2013; NYSE Arca funds such as SPY, VNQ, GLD, EFA, VTI answer 'not available'). The close is NOT adjusted for dividends, so a total-return
series is rebuilt here: on each ex-dividend day the dividend is reinvested, factor = (close + dividend) / previous close. A fund that pays no dividends (physical gold) needs none.
Every step is checked: the row count must equal the feed's own totalRecords, dates must be strictly increasing, closes positive, dividend types known, and a dividend that falls on a non-trading day is rolled to the next trading day and counted.
Run the live validation: python -m atlas_api.btclab.etf_history
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta

HIST_URL = "https://api.nasdaq.com/api/quote/{sym}/historical?assetclass=etf&fromdate={a}&todate={b}&limit=9999"
DIV_URL = "https://api.nasdaq.com/api/quote/{sym}/dividends?assetclass=etf"
MAX_GAP_DAYS = 7
MAX_DAILY_MOVE = 0.25


def _d(s: str) -> date:
    return datetime.strptime(s.strip(), "%m/%d/%Y").date()


def _num(s: str) -> float:
    return float(str(s).replace("$", "").replace(",", "").strip())


def parse_history(payload: dict) -> list[tuple[date, float]]:
    """[(date, close)] oldest first. Raises if the feed's own total does not match the rows, or a row is unreadable, duplicated or non-positive."""
    data = (payload or {}).get("data") or {}
    rows = ((data.get("tradesTable") or {}).get("rows")) or []
    if not rows:
        raise ValueError("the feed returned no price rows")
    total = data.get("totalRecords")
    if total is not None and int(total) != len(rows):
        raise ValueError(f"incomplete history: the feed says {total} rows, got {len(rows)}")
    out, seen = [], set()
    for r in rows:
        try:
            d, c = _d(r["date"]), _num(r["close"])
        except (KeyError, ValueError) as e:
            raise ValueError(f"unreadable price row {r!r}") from e
        if c <= 0 or not math.isfinite(c):
            raise ValueError(f"non-positive close on {d}")
        if d in seen:
            raise ValueError(f"duplicate date {d}")
        seen.add(d)
        out.append((d, c))
    return sorted(out)


def parse_dividends(payload: dict) -> list[tuple[date, float]] | None:
    """[(ex date, cash amount)] oldest first, or None when the feed says it has no dividend history for this fund (which is NOT the same as 'pays none'). Only plain cash dividends are accepted."""
    div = (((payload or {}).get("data") or {}).get("dividends")) or {}
    rows = div.get("rows")
    if rows is None:
        return None
    out = []
    for r in rows:
        if r.get("type") != "Cash" or r.get("currency", "USD") != "USD":
            raise ValueError(f"unreviewed dividend type {r.get('type')!r} {r.get('currency')!r}: not silently ignored")
        try:
            out.append((_d(r["exOrEffDate"]), _num(r["amount"])))
        except (KeyError, ValueError) as e:
            raise ValueError(f"unreadable dividend row {r!r}") from e
        if out[-1][1] <= 0:
            raise ValueError("non-positive dividend")
    return sorted(out)


def total_return_index(prices: list[tuple[date, float]], divs: list[tuple[date, float]] | None) -> tuple[list[tuple[date, float]], dict]:
    """Total-return index starting at 1.0 on the first date. Dividends are reinvested on the ex-dividend day: factor = (close + dividend) / previous close. A dividend on a non-trading day is applied on the next trading day; one before the first
    or after the last price date is skipped. Returns (series, stats) where stats counts the dividends used, rolled and skipped."""
    days = [d for d, _ in prices]
    close = dict(prices)
    pending: dict[date, float] = {}
    stats = {"used": 0, "rolled": 0, "skipped_outside": 0}
    for ex, amt in (divs or []):
        if ex <= days[0] or ex > days[-1]:
            stats["skipped_outside"] += 1
            continue
        t = ex if ex in close else next(d for d in days if d > ex)
        if t != ex:
            stats["rolled"] += 1
        pending[t] = pending.get(t, 0.0) + amt
        stats["used"] += 1
    out, tri = [(days[0], 1.0)], 1.0
    for a, b in zip(days, days[1:]):
        tri *= (close[b] + pending.get(b, 0.0)) / close[a]
        out.append((b, tri))
    return out, stats


def checks(prices: list[tuple[date, float]]) -> dict:
    gaps = [(b - a).days for (a, _), (b, _) in zip(prices, prices[1:])]
    moves = [abs(b / a - 1) for (_, a), (_, b) in zip(prices, prices[1:])]
    res = {"rows": len(prices), "first": prices[0][0].isoformat(), "last": prices[-1][0].isoformat(), "max_gap_days": max(gaps, default=0), "max_daily_move": max(moves, default=0.0)}
    res["ok"] = res["max_gap_days"] <= MAX_GAP_DAYS and res["max_daily_move"] <= MAX_DAILY_MOVE
    return res


def daily_changes(series: list[tuple[date, float]], relative: bool = True) -> dict[date, float]:
    return {b: (vb / va - 1 if relative else vb - va) for (_, va), (b, vb) in zip(series, series[1:])}


def correlation(a: dict[date, float], b: dict[date, float]) -> tuple[float, int]:
    """Pearson correlation of two date-keyed series over the dates both have; returns (r, n)."""
    ks = sorted(set(a) & set(b))
    xs, ys = [a[k] for k in ks], [b[k] for k in ks]
    n = len(ks)
    if n < 3:
        raise ValueError("fewer than 3 shared dates")
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs)); sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        raise ValueError("a series is constant")
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy), n


# ---- live fetching and the validation run (command line only) ----------------------------------------------------------------------------------------------------------------------------
def _get(url: str, ua: bool) -> str:
    import time
    import urllib.request
    req = urllib.request.Request(url, headers=({"User-Agent": "Mozilla/5.0", "Accept": "application/json"} if ua else {}))      # FRED stalls on an unfamiliar User-Agent, Nasdaq wants a browser-like one
    for wait in (0, 3, 10):
        time.sleep(wait)
        try:
            return urllib.request.urlopen(req, timeout=40).read().decode()
        except Exception as e:                                                                                                      # noqa: BLE001
            last = e
    raise RuntimeError(f"could not fetch {url[:60]}: {last}")


def fetch(sym: str, today: date | None = None):
    today = today or date.today()
    prices = parse_history(json.loads(_get(HIST_URL.format(sym=sym, a="2000-01-01", b=today.isoformat()), True)))
    divs = parse_dividends(json.loads(_get(DIV_URL.format(sym=sym), True)))
    return prices, divs


def fred(series: str, start: str = "2016-10-01") -> list[tuple[date, float]]:
    txt = _get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd={start}", False).strip().split("\n")[1:]
    return [(date.fromisoformat(a), float(b)) for a, b in (ln.split(",") for ln in txt) if b not in ("", ".")]


if __name__ == "__main__":
    out = {}
    spy, _ = fetch("SPY")
    r, n = correlation(daily_changes(spy), daily_changes(fred("SP500")))
    out["SPY_vs_FRED_SP500"] = {"corr_daily_returns": round(r, 5), "shared_days": n, **checks(spy)}
    for sym, ser in (("TLT", "DGS20"), ("IEF", "DGS10")):
        px, dv = fetch(sym)
        tri, st = total_return_index(px, dv)
        r2, n2 = correlation(daily_changes(px), daily_changes(fred(ser), relative=False))
        out[f"{sym}_vs_FRED_{ser}"] = {"corr_with_yield_change": round(r2, 4), "shared_days": n2, "price_return": round(px[-1][1] / px[0][1] - 1, 4), "total_return": round(tri[-1][1] - 1, 4), "dividends": st, **checks(px)}
    for sym in ("ACWI", "GLD", "QQQ", "BND"):
        px, dv = fetch(sym)
        tri, st = total_return_index(px, dv)
        out[sym] = {"price_return": round(px[-1][1] / px[0][1] - 1, 4), "total_return": round(tri[-1][1] - 1, 4), "dividends_available": dv is not None, "dividends": st, **checks(px)}
    print(json.dumps(out, indent=1))
