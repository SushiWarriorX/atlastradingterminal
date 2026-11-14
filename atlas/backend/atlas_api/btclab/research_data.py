"""Research-only inputs for experiments that are not about price: the Bitcoin Fear & Greed history (alternative.me) and the Bitcoin network's daily hash-rate history (mempool.space). Neither is shown in Signal.

Rules (DATA_SOURCES.md): free, keyless, fetched live with the plain client and a timeout; every series checks itself and a failing check returns NOTHING (never a repaired or partial series); a missing day stays missing (never zero, never filled);
every figure is dated. Both are NOT point-in-time: alternative.me may have changed how the index is built since 2018, and the hash rate is an estimate from block times (noisy by 10 to 20% from one day to the next).

Check it live with: python -m atlas_api.btclab.research_data
"""
from __future__ import annotations

import bisect
import json
from datetime import date, datetime, timezone

import httpx

from ..fincond import parse as _parse_fred

FNG_URL = "https://api.alternative.me/fng/?limit=0&format=json"
HASHRATE_URL = "https://mempool.space/api/v1/mining/hashrate/all"
TIMEOUT = 40.0
FNG_MIN_ROWS = 1000                                  # the real history has 3,200+ days from 2018-02-01
FNG_MAX_GAP_DAYS = 7                                 # the real history has two gaps: 3 days (2018-04) and 1 day (2024-10)
MAX_STALE_DAYS = 3
HASH_POSITIVE_FROM, HASH_STEP_FROM = date(2010, 1, 1), date(2012, 1, 1)      # the first six days after the genesis block really have no blocks; early years are sparse
HASH_STEP_LIMITS = (0.4, 2.5)                        # day-over-day ratio; the real series stays within 0.61 to 1.82 from 2012
HASH_RATIO_LIMITS = (0.8, 1.3)                       # yearly median of hash rate / (difficulty x 2^32 / 600); the real yearly medians are 1.0 to 1.1


FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
INDEX_MIN_ROWS = 250
INDEX_LIMITS = (10.0, 1_000_000.0)                   # an equity index level; the Nasdaq Composite has been 54.9 to 27,600 since 1971
INDEX_MAX_GAP_DAYS = 7                               # the longest real gap in the Nasdaq Composite is the September 2001 closure: exactly 7 days
INDEX_MAX_MOVE = 0.25                                # the largest real one-day move in the Nasdaq Composite is 14.2%
INDEX_MAX_STALE_DAYS = 7                             # a close is published the next morning; a long weekend plus a holiday is still under 7 days


def _day(ts: float) -> date:
    return datetime.fromtimestamp(ts, timezone.utc).date()


# ---- Fear & Greed ---------------------------------------------------------------------------------------------------------------------------------------------------------------
def parse_fng(payload) -> list[tuple[date, int, str]]:
    """[(day, value, label)] oldest first. Raises ValueError on anything unreadable: a value that is not a whole number from 0 to 100, a timestamp that is not 00:00 UTC, a day that appears twice, a missing field."""
    try:
        raw = payload["data"]
        out, seen = [], set()
        for x in raw:
            ts, value, label = int(x["timestamp"]), x["value"], x["value_classification"]
            if isinstance(value, bool) or int(value) != float(value):
                raise ValueError("a value was not a whole number")
            value = int(value)
            if not 0 <= value <= 100:
                raise ValueError(f"a value was outside 0 to 100: {value}")
            if ts % 86400 != 0:
                raise ValueError("a timestamp was not at 00:00 UTC")
            if not isinstance(label, str) or not label:
                raise ValueError("a label was missing")
            d = _day(ts)
            if d in seen:
                raise ValueError(f"{d} appears twice")
            seen.add(d)
            out.append((d, value, label))
    except (KeyError, TypeError) as e:
        raise ValueError(f"unexpected Fear & Greed response ({type(e).__name__})") from e
    if not out:
        raise ValueError("the Fear & Greed response was empty")
    return sorted(out)


def fng_gaps(rows) -> list[tuple[date, date, int]]:
    """(last day before, first day after, missing days) for every hole. Holes stay holes."""
    return [(a[0], b[0], (b[0] - a[0]).days - 1) for a, b in zip(rows, rows[1:]) if (b[0] - a[0]).days != 1]


def check_fng(rows, today: date | None = None, min_rows: int = FNG_MIN_ROWS) -> list[str]:
    """Problems found; an empty list means the series passes."""
    problems = []
    if len(rows) < min_rows:
        problems.append(f"only {len(rows)} days (need {min_rows})")
    spans: dict[str, list[int]] = {}
    for _, v, lab in rows:
        spans.setdefault(lab, [v, v])
        spans[lab][0], spans[lab][1] = min(spans[lab][0], v), max(spans[lab][1], v)
    ordered = sorted(spans.values())
    if any(a[1] >= b[0] for a, b in zip(ordered, ordered[1:])):
        problems.append("the labels overlap: a label must be a function of the value, in order")
    long_gaps = [g for g in fng_gaps(rows) if g[2] > FNG_MAX_GAP_DAYS]
    if long_gaps:
        problems.append(f"a gap of {long_gaps[0][2]} days after {long_gaps[0][0]}")
    if today is not None and (today - rows[-1][0]).days > MAX_STALE_DAYS:
        problems.append(f"the newest day is {(today - rows[-1][0]).days} days old")
    return problems


# ---- hash rate ------------------------------------------------------------------------------------------------------------------------------------------------------------------
def parse_hashrate(payload) -> tuple[list[tuple[date, float]], list[tuple[int, float]]]:
    """(daily hash rate in hashes per second, oldest first; difficulty adjustments as (unix time, difficulty)). Raises ValueError on anything unreadable."""
    try:
        daily = [(_day(int(x["timestamp"])), float(x["avgHashrate"])) for x in payload["hashrates"]]
        diff = sorted((int(x["time"]), float(x["difficulty"])) for x in payload["difficulty"])
    except (KeyError, TypeError) as e:
        raise ValueError(f"unexpected hash-rate response ({type(e).__name__})") from e
    if not daily or not diff:
        raise ValueError("the hash-rate response was empty")
    if any(v != v or v in (float("inf"), float("-inf")) for _, v in daily):
        raise ValueError("a hash-rate value was not a number")
    return daily, diff


def check_hashrate(daily, diff, today: date | None = None) -> list[str]:
    """Problems found; an empty list means the series passes. The key check needs no outside source: the hash rate must follow the difficulty (hash rate = difficulty x 2^32 / block time, and block time averages about 600 seconds)."""
    problems = []
    days = [d for d, _ in daily]
    if any(b <= a for a, b in zip(days, days[1:])):
        problems.append("the days are not in strictly increasing order")
    elif any((b - a).days != 1 for a, b in zip(days, days[1:])):
        gap = next(a for a, b in zip(days, days[1:]) if (b - a).days != 1)
        problems.append(f"a day is missing after {gap}")
    bad = [d for d, v in daily if d >= HASH_POSITIVE_FROM and v <= 0]
    if bad:
        problems.append(f"a non-positive hash rate on {bad[0]}")
    jumps = [b[0] for a, b in zip(daily, daily[1:]) if a[0] >= HASH_STEP_FROM and a[1] > 0 and b[1] > 0 and not HASH_STEP_LIMITS[0] <= b[1] / a[1] <= HASH_STEP_LIMITS[1]]
    if jumps:
        problems.append(f"the hash rate moved more than {HASH_STEP_LIMITS[1]}x in a day on {jumps[0]}")
    times = [t for t, _ in diff]
    by_year: dict[int, list[float]] = {}
    for d, v in daily:
        if d < HASH_STEP_FROM or v <= 0:
            continue
        ts = int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())
        i = bisect.bisect_right(times, ts) - 1
        if i >= 0:
            by_year.setdefault(d.year, []).append(v / (diff[i][1] * 2 ** 32 / 600.0))
    for year, ratios in sorted(by_year.items()):
        ratios.sort()
        med = ratios[len(ratios) // 2]
        if not HASH_RATIO_LIMITS[0] <= med <= HASH_RATIO_LIMITS[1]:
            problems.append(f"the hash rate does not follow the difficulty in {year} (median ratio {med:.2f})")
            break
    if today is not None and daily and (today - days[-1]).days > MAX_STALE_DAYS:
        problems.append(f"the newest day is {(today - days[-1]).days} days old")
    return problems


# ---- equity index closes (the equity-trend experiment) -------------------------------------------------------------------------------------------------------------------------
def parse_index(text: str, sid: str) -> list[tuple[date, float]]:
    """[(day, close)] oldest first from a FRED CSV. A closed market is an empty or '.' value and is left out, never filled in. Raises ValueError on anything unreadable."""
    return sorted(_parse_fred(text, sid).items())


def check_index(rows, today: date | None = None, min_rows: int = INDEX_MIN_ROWS, limits: tuple[float, float] = INDEX_LIMITS) -> list[str]:
    """Problems found; an empty list means the series passes."""
    problems = []
    if len(rows) < min_rows:
        problems.append(f"only {len(rows)} closes (need {min_rows})")
    bad = [d for d, v in rows if not limits[0] <= v <= limits[1]]
    if bad:
        problems.append(f"a close outside {limits[0]:g} to {limits[1]:g} on {bad[0]}")
    gaps = [(a[0], b[0]) for a, b in zip(rows, rows[1:]) if (b[0] - a[0]).days > INDEX_MAX_GAP_DAYS]
    if gaps:
        problems.append(f"a gap of {(gaps[0][1] - gaps[0][0]).days} days after {gaps[0][0]}")
    jumps = [b[0] for a, b in zip(rows, rows[1:]) if a[1] > 0 and abs(b[1] / a[1] - 1) > INDEX_MAX_MOVE]
    if jumps:
        problems.append(f"a one-day move of more than {INDEX_MAX_MOVE:.0%} on {jumps[0]}")
    if today is not None and rows and (today - rows[-1][0]).days > INDEX_MAX_STALE_DAYS:
        problems.append(f"the newest close is {(today - rows[-1][0]).days} days old")
    return problems


def fetch_index(series_id: str, client: httpx.Client | None = None, today: date | None = None, since: str = "2013-01-01", min_rows: int = INDEX_MIN_ROWS) -> dict:
    """Daily closes of a FRED index series from `since`. `rows` is None unless every check passed (a failing check shows nothing). Plain client: FRED stalls on an unfamiliar User-Agent."""
    today = today or datetime.now(timezone.utc).date()
    source = f"{FRED_CSV}?id={series_id}"
    own = client is None
    client = client or httpx.Client()
    try:
        r = client.get(FRED_CSV, params={"id": series_id, "cosd": since}, timeout=TIMEOUT)
        r.raise_for_status()
        rows = parse_index(r.text, series_id)
    except (httpx.HTTPError, ValueError) as e:
        return _result(source, False, [f"unavailable: {type(e).__name__}: {str(e)[:120]}"], rows=None)
    finally:
        if own:
            client.close()
    problems = check_index(rows, today, min_rows)
    return _result(source, not problems, problems, rows=None if problems else rows, first=rows[0][0].isoformat(), last=rows[-1][0].isoformat())


# ---- live (plain client, timeout, labelled unavailable) ------------------------------------------------------------------------------------------------------------------------
def _get_json(client: httpx.Client, url: str):
    r = client.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    return json.loads(r.text)


def _result(source: str, ok: bool, problems: list[str], **extra) -> dict:
    return {"ok": ok, "source": source, "problems": problems, **extra}


def fetch_fng(client: httpx.Client | None = None, today: date | None = None, min_rows: int = FNG_MIN_ROWS) -> dict:
    """The whole Fear & Greed history. `rows` is None unless every check passed (a failing check shows nothing)."""
    today = today or datetime.now(timezone.utc).date()
    own = client is None
    client = client or httpx.Client()
    try:
        rows = parse_fng(_get_json(client, FNG_URL))
    except (httpx.HTTPError, ValueError) as e:
        return _result(FNG_URL, False, [f"unavailable: {type(e).__name__}: {str(e)[:120]}"], rows=None)
    finally:
        if own:
            client.close()
    problems = check_fng(rows, today, min_rows)
    return _result(FNG_URL, not problems, problems, rows=None if problems else rows, first=rows[0][0].isoformat(), last=rows[-1][0].isoformat(),
                   gaps=[{"after": a.isoformat(), "before": b.isoformat(), "missing_days": n} for a, b, n in fng_gaps(rows)])


def fetch_hashrate(client: httpx.Client | None = None, today: date | None = None) -> dict:
    """The whole daily hash-rate history with the difficulty adjustments. `daily` is None unless every check passed."""
    today = today or datetime.now(timezone.utc).date()
    own = client is None
    client = client or httpx.Client()
    try:
        daily, diff = parse_hashrate(_get_json(client, HASHRATE_URL))
    except (httpx.HTTPError, ValueError) as e:
        return _result(HASHRATE_URL, False, [f"unavailable: {type(e).__name__}: {str(e)[:120]}"], daily=None, difficulty=None)
    finally:
        if own:
            client.close()
    problems = check_hashrate(daily, diff, today)
    return _result(HASHRATE_URL, not problems, problems, daily=None if problems else daily, difficulty=None if problems else diff, first=daily[0][0].isoformat(), last=daily[-1][0].isoformat())


if __name__ == "__main__":
    for res in (fetch_fng(), fetch_hashrate()):
        n = len(res.get("rows") or res.get("daily") or [])
        print(json.dumps({k: v for k, v in res.items() if k not in ("rows", "daily", "difficulty")} | {"points_returned": n}, indent=1))
