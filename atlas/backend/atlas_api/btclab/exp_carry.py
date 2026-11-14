"""Experiment 4 from EDGE_PLAN.md: BTC funding carry with a funding-regime switch, judged by the conditions written down BEFORE the run (commit 539ca0e).

Rule (fixed): ON = half the capital long BTC spot, half cash margin for an equal-notional short BTC perpetual on Hyperliquid; the price legs are assumed to cancel; the margin cash earns NOTHING;
daily ON return on total capital = 0.5 x (sum of that UTC day's hourly funding rates). OFF = all capital in 3-month Treasury bills (FRED DTB3, percent a year, carried forward), daily return = DTB3 / 100 / 365.
Switch: at the end of UTC day t, F14 = (sum of hourly funding in days t-13..t) / 14 x 365; be ON on day t+1 if 0.5 x F14 >= DTB3(t)/100 + 0.01, else OFF. Start OFF. Each switch costs 0.30% of capital.
Split: first 70% of the days after the 14-day warm-up are design (nothing tuned), last 30% sealed. Comparisons: always in bills, always-ON carry, BTC buy-and-hold.
Pass = ALL of, sealed: (a) net annualised return >= always-bills + 1.0 percentage point; (b) worst drop no deeper than 3.0%; (c) net annualised return >= always-ON carry. Data check: no gap over 3 hours between funding records inside the sealed period, else INVALID.
NOT modelled: basis and hedge drift, exchange/counterparty/liquidation risk, USDC depeg, taxes. One market cycle of data. A pass would be a weak "candidate" only.
Run: python -m atlas_api.btclab.exp_carry
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone

WINDOW = 14
SPLIT = 0.70
NOTIONAL_SHARE = 0.5
HURDLE = 0.01
SWITCH_COST = 0.0030
PASS_EXCESS = 0.01
PASS_MAX_DROP = 0.03
MAX_GAP_HOURS = 3.0


def hourly_records(records: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """(unix seconds, hourly rate) records, sorted, starting at the first record whose gap to the previous one is 1 hour (earlier ones had an unverified 8-hour unit and are dropped)."""
    r = sorted(records)
    for i in range(1, len(r)):
        if abs((r[i][0] - r[i - 1][0]) - 3600) <= 120:
            return r[i - 1:]
    return []


def daily_funding(records: list[tuple[float, float]]) -> dict[date, float]:
    """Sum of the hourly rates per UTC day, only for COMPLETE days (the first and last day of the data are dropped if partial: the first day only if it starts after 00:59 UTC, the last always)."""
    out: dict[date, float] = {}
    for t, rate in records:
        d = datetime.fromtimestamp(t, timezone.utc).date()
        out[d] = out.get(d, 0.0) + rate
    if not out:
        return out
    days = sorted(out)
    first_t = datetime.fromtimestamp(records[0][0], timezone.utc)
    if first_t.hour > 0 and days:
        days = days[1:]
    days = days[:-1]
    return {d: out[d] for d in days}


def fill_bills(rows: list[tuple[date, float]], days: list[date]) -> dict[date, float]:
    """DTB3 percent per day, carried forward from the latest earlier observation; days before the first observation raise."""
    rows = sorted(rows)
    out, j, last = {}, 0, None
    for d in days:
        while j < len(rows) and rows[j][0] <= d:
            last = rows[j][1]
            j += 1
        if last is None:
            raise ValueError("no T-bill rate on or before the first day")
        out[d] = last
    return out


def decisions(days: list[date], fund: dict[date, float], bills: dict[date, float]) -> dict[date, bool]:
    """state[d] = ON for day d, decided at the END of the previous day from funding up to and including it (no look-ahead). Needs WINDOW days of funding."""
    state = {}
    for i in range(WINDOW, len(days)):
        prev = days[i - 1]
        window = days[i - WINDOW:i]
        f14 = sum(fund[x] for x in window) / WINDOW * 365
        state[days[i]] = NOTIONAL_SHARE * f14 >= bills[prev] / 100 + HURDLE
    return state


def simulate(days: list[date], fund: dict[date, float], bills: dict[date, float], state: dict[date, bool], start_on: bool = False) -> list[float]:
    """Daily net returns for the strategy over `days` (all must be in `state`). A switch relative to the previous day's state costs SWITCH_COST; `start_on` is the state before the first day."""
    out, prev = [], start_on
    for d in days:
        on = state[d]
        r = NOTIONAL_SHARE * fund[d] if on else bills[d] / 100 / 365
        if on != prev:
            r -= SWITCH_COST
        out.append(r)
        prev = on
    return out


def always_on(days: list[date], fund: dict[date, float]) -> list[float]:
    return [NOTIONAL_SHARE * fund[d] - (SWITCH_COST if i == 0 else 0.0) for i, d in enumerate(days)]


def always_bills(days: list[date], bills: dict[date, float]) -> list[float]:
    return [bills[d] / 100 / 365 for d in days]


def ann_return(rs: list[float]) -> float:
    g = 1.0
    for r in rs:
        g *= 1 + r
    return g ** (365 / len(rs)) - 1


def worst_drop(rs: list[float]) -> float:
    eq, peak, w = 1.0, 1.0, 0.0
    for r in rs:
        eq *= 1 + r
        peak = max(peak, eq)
        w = min(w, eq / peak - 1)
    return w


def excess_sharpe(rs: list[float], base: list[float]) -> float | None:
    ex = [a - b for a, b in zip(rs, base)]
    m = sum(ex) / len(ex)
    sd = math.sqrt(sum((x - m) ** 2 for x in ex) / (len(ex) - 1)) if len(ex) > 1 else 0.0
    return None if sd == 0 else m / sd * math.sqrt(365)


def max_gap_hours(records: list[tuple[float, float]], d0: date, d1: date) -> float:
    ts = [t for t, _ in sorted(records) if d0 <= datetime.fromtimestamp(t, timezone.utc).date() <= d1]
    return max(((b - a) / 3600 for a, b in zip(ts, ts[1:])), default=0.0)


def run(records: list[tuple[float, float]], dtb3: list[tuple[date, float]], btc_close: dict[date, float]) -> dict:
    rec = hourly_records(records)
    fund = daily_funding(rec)
    days_all = sorted(fund)
    # contiguous calendar check: every day between first and last must have funding
    span = [days_all[0] + timedelta(days=i) for i in range((days_all[-1] - days_all[0]).days + 1)]
    missing = [d for d in span if d not in fund]
    if missing:
        return {"valid": False, "reason": f"{len(missing)} days have no funding at all, first {missing[0]}"}
    bills = fill_bills(dtb3, span)
    state = decisions(span, fund, bills)
    panel = [d for d in span if d in state]
    cut = int(len(panel) * SPLIT)
    sealed = panel[cut:]
    gap = max_gap_hours(rec, sealed[0], sealed[-1])
    base = {"panel_days": len(panel), "design_days": cut, "sealed_days": len(sealed), "sealed_from": sealed[0].isoformat(), "sealed_to": sealed[-1].isoformat(),
            "max_gap_hours_in_sealed": round(gap, 2), "funding_from": days_all[0].isoformat(), "funding_to": days_all[-1].isoformat()}
    if gap > MAX_GAP_HOURS:
        return {**base, "valid": False, "reason": f"a {gap:.1f} hour gap in the funding records inside the sealed period"}
    prev_state = state[panel[cut - 1]] if cut > 0 else False
    strat = simulate(sealed, fund, bills, state, start_on=prev_state)
    on_all = always_on(sealed, fund)
    bl = always_bills(sealed, bills)
    hold, ok = [], True
    for i, d in enumerate(sealed):
        p0 = btc_close.get(d - timedelta(days=1)); p1 = btc_close.get(d)
        if p0 is None or p1 is None:
            ok = False
            break
        hold.append(p1 / p0 - 1)
    switches = sum(1 for a, b in zip([prev_state] + [state[d] for d in sealed], [state[d] for d in sealed]) if a != b)
    res = {**base, "valid": True, "switches_in_sealed": switches, "days_on_in_sealed": sum(1 for d in sealed if state[d]),
           "strategy": {"ann_return": ann_return(strat), "worst_drop": worst_drop(strat), "excess_sharpe_vs_bills": excess_sharpe(strat, bl)},
           "always_on": {"ann_return": ann_return(on_all), "worst_drop": worst_drop(on_all), "excess_sharpe_vs_bills": excess_sharpe(on_all, bl)},
           "always_bills": {"ann_return": ann_return(bl), "worst_drop": worst_drop(bl)},
           "btc_hold": ({"ann_return": ann_return(hold), "worst_drop": worst_drop(hold)} if ok else None)}
    a = res["strategy"]["ann_return"] >= res["always_bills"]["ann_return"] + PASS_EXCESS
    b = res["strategy"]["worst_drop"] >= -PASS_MAX_DROP
    c = res["strategy"]["ann_return"] >= res["always_on"]["ann_return"]
    res["conditions"] = {"a_beats_bills_by_1pp": a, "b_worst_drop_within_3pct": b, "c_at_least_always_on": c}
    res["passed"] = bool(a and b and c)
    return res


# ---- live data (only used by the command line) -------------------------------------------------------------------------------------------------------------------------------------
def _fetch(first_ms: int = int(datetime(2023, 5, 1, tzinfo=timezone.utc).timestamp() * 1000)):
    import time
    import urllib.error
    import urllib.request

    def post(start):
        r = urllib.request.Request("https://api.hyperliquid.xyz/info", data=json.dumps({"type": "fundingHistory", "coin": "BTC", "startTime": start}).encode(), headers={"Content-Type": "application/json"})
        for wait in (0, 5, 15, 40, 90):                                                           # Hyperliquid answers 429 when asked quickly: wait and retry (data fetching only, not the rule)
            time.sleep(wait)
            try:
                return json.load(urllib.request.urlopen(r, timeout=40))
            except urllib.error.HTTPError as e:
                if e.code != 429:
                    raise
        raise RuntimeError("Hyperliquid kept answering 429")
    recs, s = [], first_ms
    while True:
        d = post(s)
        if not d:
            break
        recs += [(x["time"] / 1000.0, float(x["fundingRate"])) for x in d]
        if len(d) < 500:
            break
        s = d[-1]["time"] + 1
        time.sleep(1.0)
    txt = urllib.request.urlopen("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTB3&cosd=2023-01-01", timeout=40).read().decode().strip().split("\n")[1:]
    dtb3 = [(date.fromisoformat(a), float(b)) for a, b in (ln.split(",") for ln in txt) if b not in ("", ".")]
    close, t = {}, datetime(2023, 5, 1, tzinfo=timezone.utc)
    end = datetime.now(timezone.utc)
    while t < end:
        stop = min(t + timedelta(days=290), end)
        url = f"https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=86400&start={t.isoformat()}&end={stop.isoformat()}"
        for row in json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=40)):
            close[datetime.fromtimestamp(row[0], timezone.utc).date()] = float(row[4])
        t = stop
    return recs, dtb3, close


if __name__ == "__main__":
    recs, dtb3, close = _fetch()
    print(json.dumps(run(recs, dtb3, close), indent=1, default=str))
