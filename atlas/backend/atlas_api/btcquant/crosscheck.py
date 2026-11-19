"""Second-source check of the stored daily Bitcoin candles. Read-only: nothing here writes a candle file, a ledger, a report or a state file.

Every paper account and every test of btcquant rests on one file of Coinbase BTC-USD daily candles. This module fetches the daily candles of Hyperliquid's BTC contract (free and keyless: POST https://api.hyperliquid.xyz/info, type candleSnapshot), lines them up with the stored candles by UTC day and describes how far the closes differ: the median and the 99th percentile of the difference, the largest one, the days over two thresholds, the correlation of the daily returns and the newest candle. Run it with `python -m atlas_api.btcquant.crosscheck`; nothing calls it by itself.

What it can and cannot say: Hyperliquid's BTC contract is a perpetual future, not spot. Its close differs from Coinbase's spot close by its own basis and order flow, so small differences (a median near 0.05%) are normal and larger ones on days of stress are expected (2023-03-12, the USDC depeg: 1.06%). The check looks for a stored candle that is WRONG (a bad print, a shifted day, a missing day), not for a tradable difference, and a second venue is a cross-check, not a proof of either price.
"""
from __future__ import annotations

import argparse
import math
import statistics
import sys
import zlib
from datetime import datetime, timezone
from pathlib import Path

import httpx

from ..failreason import fail_reason
from . import data as D

HL = "https://api.hyperliquid.xyz/info"
DAY = 86400
MAX_ROWS = 5000                                   # the most candles one candleSnapshot request returns
VENUE = "Hyperliquid BTC perpetual (a perpetual future, not spot)"
NOTE = ("Hyperliquid's BTC contract is a perpetual future, not spot: its close differs from Coinbase's spot close by its own basis and order flow, so small differences are normal and larger ones on days of stress are expected. "
        "This check looks for a stored candle that is WRONG (a bad print, a shifted day, a missing day), not for a tradable difference, and a second venue is a cross-check, not a proof of either price.")
LIMITS = {"mid_pct": 0.5, "big_pct": 2.0, "warn_pct": 1.0, "min_correlation": 0.99}


class CrosscheckError(Exception):
    """A problem that stops the check, in plain words."""


def _iso(day: int) -> str:
    return datetime.fromtimestamp(day * DAY, timezone.utc).strftime("%Y-%m-%d")


def _client() -> httpx.Client:
    return httpx.Client(timeout=30)


def fetch(client: httpx.Client, start: int, end: int, now: int | None = None) -> list[tuple]:
    """The venue's daily candles from `start` to `end` (epoch seconds): complete ones only, as (open time in seconds, o, h, l, c, v)."""
    body = {"type": "candleSnapshot", "req": {"coin": "BTC", "interval": "1d", "startTime": start * 1000, "endTime": end * 1000}}
    try:
        r = client.post(HL, json=body, headers={"User-Agent": "ATLAS research terminal"})
    except httpx.HTTPError as e:
        raise CrosscheckError(f"Hyperliquid could not be reached ({fail_reason(e)})") from e
    if r.status_code != 200:
        raise CrosscheckError(f"Hyperliquid answered HTTP {r.status_code}")
    try:
        rows = r.json()
    except ValueError:
        rows = None
    if not isinstance(rows, list):
        raise CrosscheckError("Hyperliquid did not send a list of candles")
    if len(rows) >= MAX_ROWS:
        raise CrosscheckError(f"Hyperliquid sent {MAX_ROWS:,} candles, the most one request gives; ask for a shorter range")
    out = []
    for x in rows:
        try:
            out.append((int(x["t"]) // 1000, float(x["o"]), float(x["h"]), float(x["l"]), float(x["c"]), float(x["v"])))
        except (KeyError, TypeError, ValueError):
            raise CrosscheckError("a candle Hyperliquid sent cannot be read") from None
    return D.complete_only(out, DAY, D.now_utc() if now is None else now)


def _closes(candles: list) -> tuple[dict, list]:
    """The close of each UTC day, and the days whose close is not a positive number (zero, negative, NaN or infinite: a bad print, which cannot be compared)."""
    good, bad = {}, []
    for c in candles:
        if c[4] > 0 and math.isfinite(c[4]):
            good[c[0] // DAY] = c[4]
        else:
            bad.append(c[0] // DAY)
    return good, sorted(bad)


def compare(stored: list, other: list, mid_pct: float = LIMITS["mid_pct"], big_pct: float = LIMITS["big_pct"], warn_pct: float = LIMITS["warn_pct"], min_correlation: float = LIMITS["min_correlation"]) -> dict:
    """Close of `other` against the close of `stored` on every UTC day present in both, in percent of the stored close."""
    (a, bad_a), (b, bad_b) = _closes(stored), _closes(other)
    days = sorted(a.keys() & b.keys())
    out = {"n_days": len(days), "only_in_stored": len(a.keys() - b.keys()), "only_in_other": len(b.keys() - a.keys()), "bad_in_stored": len(bad_a), "bad_at_venue": len(bad_b),
           "limits": {"mid_pct": mid_pct, "big_pct": big_pct, "warn_pct": warn_pct, "min_correlation": min_correlation}, "note": NOTE}
    flags = [f"{len(bad)} close(s) {where} are not a positive number (the first on {_iso(bad[0])}): they are left out" for bad, where in ((bad_a, "in the stored file"), (bad_b, "at the venue")) if bad]
    if not days:
        return {**out, "first_day": None, "last_day": None, "median_abs_pct": None, "p99_abs_pct": None, "largest": None, "days_over_mid": 0, "days_over_big": 0,
                "newest": None, "returns": None, "flags": flags + ["no day is present in both files"]}
    diffs = [((b[d] - a[d]) / a[d] * 100, d) for d in days]
    size = sorted(abs(x) for x, _ in diffs)
    worst = max(diffs, key=lambda t: abs(t[0]))
    pairs = [(d, d + 1) for d in days if d + 1 in a and d + 1 in b]                                      # consecutive days only: a gap breaks a pair
    ra, rb = [a[y] / a[x] - 1 for x, y in pairs], [b[y] / b[x] - 1 for x, y in pairs]
    try:
        corr = statistics.correlation(ra, rb)
    except statistics.StatisticsError:                                                                    # fewer than two pairs, or a series that never moves
        corr = None
    newest = days[-1]
    newest_diff = (b[newest] - a[newest]) / a[newest] * 100
    over_big = sum(1 for x in size if x > big_pct)
    if abs(newest_diff) > warn_pct:
        flags.append(f"the newest common candle ({_iso(newest)}) differs by {newest_diff:+.2f}%, more than {warn_pct:g}%")
    if over_big:
        flags.append(f"{over_big} day(s) differ by more than {big_pct:g}%: look at them before trusting the file")
    if corr is not None and corr < min_correlation:
        flags.append(f"the daily returns follow each other less closely than {min_correlation:g} (correlation {round(corr, 5):g})")
    return {**out, "first_day": _iso(days[0]), "last_day": _iso(newest), "median_abs_pct": round(statistics.median(size), 3), "p99_abs_pct": round(size[math.ceil(0.99 * len(size)) - 1], 3),
            "largest": {"day": _iso(worst[1]), "diff_pct": round(worst[0], 3)}, "days_over_mid": sum(1 for x in size if x > mid_pct), "days_over_big": over_big,
            "newest": {"day": _iso(newest), "stored_close": a[newest], "other_close": b[newest], "diff_pct": round(newest_diff, 3)},
            "returns": {"pairs": len(pairs), "correlation": None if corr is None else round(corr, 5), "same_sign": sum(1 for x, y in zip(ra, rb) if (x > 0) == (y > 0) and (x < 0) == (y < 0))},
            "flags": flags}


def check(path: Path | str | None = None, client: httpx.Client | None = None, now: int | None = None, **limits) -> dict:
    """The stored daily file against the venue, from the first stored candle to `now`."""
    path = Path(path) if path else D.daily_path()
    try:
        stored = D.load(path)
    except D.DataError as e:
        raise CrosscheckError(f"the stored file cannot be read: {e}") from e
    except (ValueError, IndexError, OSError, EOFError, zlib.error) as e:
        raise CrosscheckError("the stored file cannot be read: a row or the file itself is damaged") from e
    if not stored:
        raise CrosscheckError(f"no stored candles at {path}")
    now = D.now_utc() if now is None else now
    own = client is None
    client = client or _client()
    try:
        other = fetch(client, stored[0][0], now, now=now)
    finally:
        if own:
            client.close()
    return {**compare(stored, other, **limits), "stored_file": str(path), "venue": VENUE}


def describe(r: dict) -> str:
    lim, lines = r["limits"], ["Second-source check of the stored Bitcoin daily candles (read-only: nothing is written)", f"Stored file: {r['stored_file']}; other venue: {r['venue']}"]
    if r["n_days"]:
        lg, rt, nw = r["largest"], r["returns"], r["newest"]
        lines += [f"{r['n_days']} days in both files, {r['first_day']} to {r['last_day']} ({r['only_in_stored']} only in the stored file, {r['only_in_other']} only at the venue).",
                  f"Close difference (venue against stored): median {r['median_abs_pct']}%, 99% of days within {r['p99_abs_pct']}%, largest {lg['diff_pct']:+}% on {lg['day']}; "
                  f"{r['days_over_mid']} days over {lim['mid_pct']:g}%, {r['days_over_big']} over {lim['big_pct']:g}%.",
                  f"Daily returns: {rt['pairs']} pairs, correlation {'n/a' if rt['correlation'] is None else rt['correlation']}, same sign on {rt['same_sign']}.",
                  f"Newest common candle {nw['day']}: stored {nw['stored_close']}, venue {nw['other_close']} ({nw['diff_pct']:+}%)."]
    lines += [f"FLAG: {f}" for f in r["flags"]] or ["No flags."]
    return "\n".join(lines + [r["note"]])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Compare the stored daily Bitcoin candles with Hyperliquid's BTC perpetual (read-only).")
    p.add_argument("--file", help="the stored daily candle file (default: the btcquant data folder's btcusd_1d.csv)")
    for k, v in LIMITS.items():
        p.add_argument("--" + k.replace("_", "-"), type=float, default=v)
    a = p.parse_args(argv)
    try:
        print(describe(check(a.file, **{k: getattr(a, k) for k in LIMITS})))
    except CrosscheckError as e:
        print(f"The check could not be made: {e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
