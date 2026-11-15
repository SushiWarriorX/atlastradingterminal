"""Bitcoin network health from mempool.space: what it costs to get a transaction confirmed, how busy the queue is, the mining difficulty cycle, the network's computing power and who mines the blocks.
Free public data, no key. Everything is read from the source or simple arithmetic on it.

Why it is watched: fees and mempool size show how crowded the network is right now; hashrate shows how much computing power secures Bitcoin and how miners are doing
(falling hashrate can mean miners switching off when the price or fees are low); the share of blocks each mining pool found shows how concentrated block production is. What it is not: a price signal. Fees can be near zero while price moves a lot.
Estimates such as the next difficulty change are projections from recent block times and change as blocks arrive; they are labelled estimates. A failed request shows only
that section as unavailable; demo mode invents nothing.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import httpx

from .failreason import fail_reason

BASE = "https://mempool.space/api"
SOURCE = "mempool.space (free public Bitcoin explorer API)"
TTL = 300.0
FAIL_TTL = 60.0
TYPICAL_TX_VBYTES = 140            # a simple one-input, two-output transaction is roughly this big
EH = 1e18
POOL_WINDOWS = (("1w", "1 week", 7), ("1m", "1 month", 30), ("3m", "3 months", 91))        # mempool.space window code, label, days
BLOCKS_PER_DAY = 144                                                                           # one block about every ten minutes
HEADLINE_WINDOW = "1m"


def parse_fees(p: dict, mempool: dict | None) -> dict:
    f = {k: int(p[k]) for k in ("fastestFee", "halfHourFee", "hourFee", "economyFee", "minimumFee")}
    out = {"available": True, "sat_per_vbyte": {"fastest": f["fastestFee"], "half_hour": f["halfHourFee"], "hour": f["hourFee"], "economy": f["economyFee"], "minimum": f["minimumFee"]},
           "typical_tx_vbytes": TYPICAL_TX_VBYTES, "typical_tx_sats_fastest": f["fastestFee"] * TYPICAL_TX_VBYTES, "typical_tx_sats_economy": f["economyFee"] * TYPICAL_TX_VBYTES}
    if mempool:
        out["mempool"] = {"transactions": int(mempool["count"]), "megavbytes": round(float(mempool["vsize"]) / 1e6, 1), "blocks_worth": round(float(mempool["vsize"]) / 1e6, 1), "total_fees_btc": round(float(mempool["total_fee"]) / 1e8, 4)}
        out["mempool"]["blocks_worth"] = round(float(mempool["vsize"]) / 1e6, 1)           # a block holds about 1 million vbytes
    return out


def parse_difficulty(p: dict, height: int | None) -> dict:
    est = p.get("estimatedRetargetDate")
    return {"available": True, "progress_pct": round(float(p["progressPercent"]), 1), "estimated_change_pct": round(float(p["difficultyChange"]), 2), "previous_change_pct": round(float(p["previousRetarget"]), 2),
            "remaining_blocks": int(p["remainingBlocks"]), "estimated_date": datetime.fromtimestamp(est / 1000, timezone.utc).date().isoformat() if est else None,
            "next_adjustment_height": int(p["nextRetargetHeight"]), "block_height": height,
            "note": "Mining difficulty resets every 2,016 blocks (about two weeks) so blocks keep arriving about every ten minutes. The next change is an estimate from recent block times and moves as blocks arrive."}


def parse_hashrate(p: dict) -> dict:
    pts = []
    for r in p.get("hashrates") or []:
        try:
            pts.append((int(r["timestamp"]), float(r["avgHashrate"])))
        except (KeyError, TypeError, ValueError):
            continue
    pts.sort()
    if len(pts) < 30:
        raise ValueError("the source returned too little hashrate history")
    t, v = pts[-1]
    smooth = sum(x for _, x in pts[-7:]) / 7           # a single day's estimate is noisy, so the headline is the 7-day average
    out = {"available": True, "date": datetime.fromtimestamp(t, timezone.utc).date().isoformat(), "seven_day_average_eh": round(smooth / EH, 1), "latest_day_eh": round(v / EH, 1), "changes": [],
           "history": [{"date": datetime.fromtimestamp(x, timezone.utc).date().isoformat(), "eh": round(y / EH, 1)} for x, y in pts[-90:]]}
    for label, days in (("30 days", 30), ("90 days", 89)):
        if len(pts) > days:
            ref = sum(x for _, x in pts[-days - 7:-days]) / 7 if len(pts) >= days + 7 else pts[-days - 1][1]
            out["changes"].append({"label": label, "change_pct": round((smooth / ref - 1) * 100, 1)})
    cur = p.get("currentHashrate")
    out["current_eh"] = round(float(cur) / EH, 1) if isinstance(cur, (int, float)) and cur > 0 else None
    peak = max(pts, key=lambda x: x[1])
    out["highest_day"] = {"date": datetime.fromtimestamp(peak[0], timezone.utc).date().isoformat(), "eh": round(peak[1] / EH, 1)}
    out["note"] = "Hashrate is the computing power securing Bitcoin, in exahashes per second (EH/s). It is estimated from block times, so single days are noisy; the headline is a 7-day average."
    return out


def _pool_window(label: str, days: int, p: dict) -> dict:
    """One window of the pool statistics: every share is blocks found divided by ALL blocks in the window, blocks from miners the source could not name ("Unknown") included in the total and kept apart from the pools.
    Refused if the pools' block counts do not add up to the total or if the total is not plausible for the window (at about one block every ten minutes)."""
    rows = [(str(r["name"]), int(r["blockCount"])) for r in p["pools"]]
    total = int(p["blockCount"])
    if any(b < 0 for _, b in rows) or sum(b for _, b in rows) != total:
        raise ValueError("the pools' block counts do not add up to the total")
    expected = days * BLOCKS_PER_DAY
    if not 0.5 * expected <= total <= 1.5 * expected:
        raise ValueError(f"{total} blocks in {days} days is not plausible")
    named = sorted(((n, b) for n, b in rows if n.lower() != "unknown"), key=lambda r: (-r[1], r[0]))
    if not named:
        raise ValueError("no pool is named in the window")
    shares = [100.0 * b / total for _, b in named]
    cum, nakamoto = 0, None
    for k, (_, b) in enumerate(named, 1):
        cum += b
        if 2 * cum > total:                          # more than half of all blocks
            nakamoto = k
            break
    return {"label": label, "days": days, "blocks": total, "pools_seen": len(named), "top_pool": named[0][0], "top_pool_pct": round(shares[0], 1), "top3_pct": round(sum(shares[:3]), 1),
            "nakamoto": nakamoto, "hhi": round(sum(x * x for x in shares)), "unidentified_pct": round(100.0 * (total - sum(b for _, b in named)) / total, 1),
            "_named": named, "_total": total}


def parse_pools(windows: dict) -> dict:
    """Who mined the blocks over the last week, month and three months, from mempool.space's pool statistics. `windows` maps the window code ("1w", "1m", "3m") to the source's answer.
    The headline window (one month) also lists its largest pools."""
    out = [_pool_window(label, days, windows[code]) for code, label, days in POOL_WINDOWS]
    head = next(w for (code, _, _), w in zip(POOL_WINDOWS, out) if code == HEADLINE_WINDOW)
    named, total = head["_named"], head["_total"]
    top = [{"name": n, "blocks": b, "share_pct": round(100.0 * b / total, 1)} for n, b in named[:6]]
    for w in out:
        del w["_named"], w["_total"]
    return {"available": True, "headline_window": head["label"], "windows": out, "top_pools": top, "others_pct": round(100.0 * sum(b for _, b in named[6:]) / total, 1),
            "unidentified_pct": head["unidentified_pct"],
            "note": "A mining pool is a group of miners who combine their computing power and share the rewards. The share of blocks a pool found shows how concentrated block production is; it is not who owns the machines (miners can switch pools in minutes). "
                    "Blocks from miners the source could not name are shown apart. The Nakamoto coefficient is the smallest number of pools that together found more than half of the blocks; the HHI adds up the squared shares of the named pools (10,000 would be one pool)."}


class OnChain:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo, "source": SOURCE, "url": "https://mempool.space"}
        if self.demo:
            msg = "Demo mode: real network data is not shown because made-up values would look real."
            return {**base, "fees": {"available": False, "reason": msg}, "difficulty": {"available": False, "reason": msg}, "hashrate": {"available": False, "reason": msg}, "pools": {"available": False, "reason": msg}}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=20)
        try:
            async def get(path):
                r = await c.get(f"{BASE}/{path}", headers={"User-Agent": "ATLAS research terminal"})
                if r.status_code != 200:
                    raise ValueError(f"HTTP {r.status_code}")
                return r

            async def section(name, build):
                try:
                    return await build()
                except (httpx.HTTPError, ValueError, TypeError, KeyError, ZeroDivisionError) as e:
                    return {"available": False, "reason": f"mempool.space {name} could not be read right now ({fail_reason(e)})"}

            async def fees():
                p = (await get("v1/fees/recommended")).json()
                try:
                    mp = (await get("mempool")).json()
                except (httpx.HTTPError, ValueError):
                    mp = None
                return parse_fees(p, mp)

            async def diff():
                p = (await get("v1/difficulty-adjustment")).json()
                try:
                    h = int((await get("blocks/tip/height")).text.strip())
                except (httpx.HTTPError, ValueError):
                    h = None
                return parse_difficulty(p, h)

            async def hashrate():
                return parse_hashrate((await get("v1/mining/hashrate/3m")).json())

            async def pools():
                answers = await asyncio.gather(*(get(f"v1/mining/pools/{code}") for code, _, _ in POOL_WINDOWS))
                return parse_pools({code: a.json() for (code, _, _), a in zip(POOL_WINDOWS, answers)})
            res = {**base, "fees": await section("fees", fees), "difficulty": await section("difficulty", diff), "hashrate": await section("hashrate", hashrate), "pools": await section("mining pools", pools)}
        finally:
            if self._client is None:
                await c.aclose()
        good = all(res[k]["available"] for k in ("fees", "difficulty", "hashrate", "pools"))
        self._cache = (time.monotonic() + (TTL if good else FAIL_TTL), res)
        return res
