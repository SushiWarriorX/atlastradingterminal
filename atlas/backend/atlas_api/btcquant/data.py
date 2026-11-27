"""Bitcoin candles for the btcquant system: download from the public Coinbase candle endpoint, validate, store as CSV, describe with a manifest.

Rules that keep it honest (protocol section 1):
- Everything is UTC and a candle is identified by its OPEN time (epoch seconds).
- A candle is COMPLETE only when its open time plus its length is not after the current time. Only complete candles are ever stored or used; the candle that contains "now" is incomplete and is skipped.
- Gaps are reported and never filled. Structural problems (unsorted, duplicate, impossible high or low, non-positive price, negative volume) are fatal: the run stops and says so.
- 4-hour candles are built from COMPLETE 1-hour candles only, aligned to 00, 04, 08, 12, 16, 20 UTC, and only when all four hours exist.
- A stored candle is never overwritten. If a later download disagrees with one (a revision), it is reported and the stored copy is kept, so a result can always be reproduced from the stored file and its manifest hash.

Provider note: Binance BTC/USDT was asked for and is blocked from this environment (HTTP 403 from the network proxy, never worked around); Coinbase BTC-USD is the alternative.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from . import config as C

CB = "https://api.exchange.coinbase.com"
PAGE = 300                                    # candles per request (Coinbase maximum)
HEADER = ["t", "o", "h", "l", "c", "v"]
Candle = tuple                                # (t, o, h, l, c, v): open time (epoch seconds), open, high, low, close, volume


class DataError(Exception):
    """A fatal problem with the data. The run stops and says why."""


@dataclass
class Report:
    fatal: list
    flags: list                               # things worth a look that do not stop the run
    gaps: list                                # [(from_t, to_t, missing_candles)]

    @property
    def ok(self) -> bool:
        return not self.fatal


def now_utc() -> int:
    return int(time.time())


def is_complete(t_open: int, interval: int, now: int) -> bool:
    """A candle is complete when open + length <= now. The candle that contains `now` is not."""
    return t_open + interval <= now


def complete_only(candles: list[Candle], interval: int, now: int) -> list[Candle]:
    return [c for c in candles if is_complete(c[0], interval, now)]


def parse_coinbase(rows: list) -> list[Candle]:
    """Coinbase returns [time, low, high, open, close, volume], newest first. Returns (t, o, h, l, c, v) oldest first."""
    out = []
    for r in rows:
        if len(r) < 6:
            raise DataError(f"a candle has {len(r)} fields instead of 6")
        out.append((int(r[0]), float(r[3]), float(r[2]), float(r[1]), float(r[4]), float(r[5])))
    out.sort(key=lambda c: c[0])
    return out


def iso(t: int) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate(candles: list[Candle], interval: int, flag_moves: bool = True) -> Report:
    """Structural checks (fatal) and review flags. Gaps are listed, never filled."""
    fatal, flags, gaps = [], [], []
    prev = None
    for c in candles:
        t, o, h, l, cl, v = c
        if t % interval != 0:
            fatal.append(f"{iso(t)}: the open time is not on a {interval}-second boundary")
        if prev is not None:
            if t == prev[0]:
                fatal.append(f"{iso(t)}: duplicate candle")
            elif t < prev[0]:
                fatal.append(f"{iso(t)}: candles are not in time order")
            elif t - prev[0] > interval:
                gaps.append((prev[0], t, (t - prev[0]) // interval - 1))
        if min(o, h, l, cl) <= 0:
            fatal.append(f"{iso(t)}: a price is not above zero")
        if h < max(o, cl) or l > min(o, cl) or h < l:
            fatal.append(f"{iso(t)}: the high or low is inconsistent with the open and close")
        if v < 0:
            fatal.append(f"{iso(t)}: negative volume")
        if flag_moves and prev is not None and prev[4] > 0 and abs(cl / prev[4] - 1) > C.MAX_DAILY_MOVE and interval == C.DAY:
            flags.append(f"{iso(t)}: close-to-close move of {cl / prev[4] - 1:+.1%} (check against another source)")
        prev = c
    return Report(fatal[:50], flags[:50], gaps)


def resample_4h(hours: list[Candle], now: int | None = None) -> list[Candle]:
    """4-hour candles from 1-hour candles aligned to 00/04/08/12/16/20 UTC. A 4-hour candle exists only when its four hours exist (and, if `now` is given, are complete)."""
    by_key: dict[int, list[Candle]] = {}
    for c in hours:
        if now is not None and not is_complete(c[0], C.HOUR, now):
            continue
        by_key.setdefault(c[0] - c[0] % 14400, []).append(c)
    out = []
    for k in sorted(by_key):
        g = sorted(by_key[k], key=lambda x: x[0])
        if len(g) == 4 and [x[0] for x in g] == [k, k + 3600, k + 7200, k + 10800]:
            out.append((k, g[0][1], max(x[2] for x in g), min(x[3] for x in g), g[-1][4], sum(x[5] for x in g)))
    return out


def to_csv_bytes(candles: list[Candle]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(HEADER)
    for t, o, h, l, c, v in candles:
        w.writerow([t, repr(o), repr(h), repr(l), repr(c), repr(v)])
    return buf.getvalue().encode()


def from_csv_bytes(raw: bytes) -> list[Candle]:
    rows = list(csv.reader(io.StringIO(raw.decode())))
    if not rows or rows[0] != HEADER:
        raise DataError("the candle file has an unexpected header")
    return [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])) for r in rows[1:]]


def save(path: Path, candles: list[Candle]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = to_csv_bytes(candles)
    if path.suffix == ".gz":
        path.write_bytes(gzip.compress(raw, mtime=0))                    # mtime 0: the same candles always give the same bytes
    else:
        path.write_bytes(raw)


def load(path: Path) -> list[Candle]:
    if not path.exists():
        return []
    raw = path.read_bytes()
    return from_csv_bytes(gzip.decompress(raw) if path.suffix == ".gz" else raw)


def manifest(candles: list[Candle], interval: int, fetched_at: str | None = None) -> dict:
    """What a result was computed from. The hash is of the candle CSV, so it does not depend on compression."""
    rep = validate(candles, interval)
    return {"provider": C.PROVIDER, "product": C.PRODUCT, "interval_seconds": interval, "count": len(candles),
            "first": iso(candles[0][0]) if candles else None, "last": iso(candles[-1][0]) if candles else None,
            "sha256": hashlib.sha256(to_csv_bytes(candles)).hexdigest(), "gap_count": len(rep.gaps), "gaps": [{"from": iso(a), "to": iso(b), "missing": n} for a, b, n in rep.gaps[:5]],
            "fatal": rep.fatal[:5], "flags": rep.flags[:5], "fetched_at": fetched_at}


def merge(stored: list[Candle], fresh: list[Candle]) -> tuple[list[Candle], list[str]]:
    """Add candles we do not have. A candle we already have is never overwritten: a disagreement is reported."""
    have = {c[0]: c for c in stored}
    revisions = []
    for c in fresh:
        old = have.get(c[0])
        if old is None:
            have[c[0]] = c
        elif old != c and max(abs(old[i] / c[i] - 1) for i in (1, 2, 3, 4)) > 0.001:
            revisions.append(f"{iso(c[0])}: the provider now shows close {c[4]} where {old[4]} is stored (kept the stored copy)")
    return [have[t] for t in sorted(have)], revisions


class Downloader:
    """Blocking downloader for the Coinbase public candle endpoint. Paged, polite (about 8 requests a second), retries a rate limit."""

    def __init__(self, client: httpx.Client | None = None, sleep: float = 0.12):
        self._client, self._sleep = client, sleep

    def _get(self, c: httpx.Client, params: dict) -> list:
        for attempt in range(4):
            try:
                r = c.get(f"{CB}/products/{C.PRODUCT}/candles", params=params)
            except httpx.HTTPError as e:
                raise DataError("the candle provider could not be reached") from e
            if r.status_code == 429:
                time.sleep(1 + attempt)
                continue
            if r.status_code != 200:
                raise DataError(f"the candle provider answered HTTP {r.status_code}")
            return r.json()
        raise DataError("the candle provider kept rate-limiting the request")

    def fetch(self, interval: int, start: int, end: int) -> list[Candle]:
        """Candles with open time in [start, end], oldest first, any incomplete ones included (the caller filters)."""
        own = self._client is None
        c = self._client or httpx.Client(timeout=30)
        out: list[Candle] = []
        try:
            t = start - start % interval
            while t <= end:
                last = min(t + (PAGE - 1) * interval, end - end % interval)
                rows = self._get(c, {"granularity": interval, "start": iso(t), "end": iso(last)})
                out += parse_coinbase(rows)
                t = last + interval
                if self._sleep:
                    time.sleep(self._sleep)
        finally:
            if own:
                c.close()
        dedup = {x[0]: x for x in out}
        return [dedup[t] for t in sorted(dedup)]


def update(path: Path, interval: int, now: int | None = None, downloader: Downloader | None = None, start: int | None = None) -> dict:
    """Bring a stored candle file up to date: fetch what is missing, keep complete candles only, validate, save. Returns the manifest plus notes."""
    now = now_utc() if now is None else now
    dl = downloader or Downloader()
    stored = load(path)
    first = start if start is not None else int(C.WARMUP_START.timestamp())
    begin = (stored[-1][0] + interval) if stored else first
    notes = []
    if begin <= now:
        fresh = complete_only(dl.fetch(interval, begin, now), interval, now)
        merged, revisions = merge(stored, fresh)
        notes += revisions
    else:
        merged = stored
    rep = validate(merged, interval)
    if not rep.ok:
        raise DataError("the candle data failed validation: " + "; ".join(rep.fatal[:3]))
    save(path, merged)
    m = manifest(merged, interval, datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    m["added"] = len(merged) - len(stored)
    m["notes"] = notes
    return m


def daily_path() -> Path:
    return C.DATA_DIR / "btcusd_1d.csv"


def hourly_path() -> Path:
    return C.DATA_DIR / "btcusd_1h.csv.gz"


def manifest_path() -> Path:
    return C.DATA_DIR / "manifest.json"


def record_manifest(label: str, m: dict, path: Path | None = None) -> None:
    """Keep the latest manifest of each stored candle file in one small JSON file, so a result can name the exact data it used (protocol section 1). A damaged file is replaced, never trusted."""
    path = path or manifest_path()
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(current, dict):
            current = {}
    except (OSError, ValueError):
        current = {}
    current[label] = m
    path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    which = argv[1] if len(argv) > 1 else "1d"
    todo = {"1d": [("1d", daily_path(), C.DAY)], "1h": [("1h", hourly_path(), C.HOUR)], "all": [("1d", daily_path(), C.DAY), ("1h", hourly_path(), C.HOUR)]}.get(which)
    if todo is None:
        print("usage: python -m atlas_api.btcquant.data [1d|1h|all]")
        return 2
    for name, path, interval in todo:
        try:
            m = update(path, interval)
        except DataError as e:
            print(f"{name}: FAILED: {e}")
            return 1
        record_manifest(name, m)
        print(f"{name}: {m['count']} candles {m['first']} to {m['last']}, +{m['added']} new, {m['gap_count']} gaps, sha256 {m['sha256'][:16]}")
        for n in m["notes"] + m["flags"]:
            print("   note:", n)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
