"""Scheduler settings kept in the database so they survive restarts and can be changed from the app. Nothing here is a guess about the user's plan or prices:
unknown things are stored as unknown, and the dashboard shows them as unknown.
"""
from __future__ import annotations

import copy
import json

from ..db import DB, now

DEFAULTS: dict = {
    "paused": False,                       # pause every job (they keep their place and resume where they were)
    "emergency_stop": False,               # nothing runs, nothing is retried, running jobs are cancelled at their next checkpoint
    "reserve_pct": 20.0,                   # share of each allowance kept back for essential (priority 5) work
    "max_concurrent": 2,
    "market": {"tz": "America/New_York", "open": "09:30", "close": "16:00", "weekdays": [0, 1, 2, 3, 4]},
    "claude": {
        "access": "unknown",               # unknown | api | subscription | claude_code. Never assumed: set by the user.
        "model": "claude-sonnet-5-5",
        "usage_telemetry": "unknown",      # unknown | per_request (the API returns token counts for each call) | none. Provider-side remaining allowance is never invented.
        "price_in_per_mtok": None,         # US dollars per million input tokens. None until the user enters the current price; dollar cost is then shown as unknown.
        "price_out_per_mtok": None,
        "daily_token_limit": 200_000,      # conservative until the user changes it. This is OUR budget, not the provider's remaining allowance.
        "daily_usd_limit": None,
        "monthly_usd_limit": None,
    },
}

# Allowances other than Claude. These are conservative defaults chosen here, not published provider limits; the user can edit them.
DEFAULT_QUOTAS = [
    ("ai_tokens", 200_000, "day", "tokens", "Our daily Claude token budget (not the provider's remaining allowance)."),
    ("ai_usd", 0, "day", "usd", "Daily Claude spend limit in dollars. 0 means no dollar limit is set (token budget still applies)."),
    ("ai_usd_month", 0, "month", "usd", "Monthly Claude spend limit in dollars. 0 means no dollar limit is set."),
    ("sec", 300, "hour", "requests", "SEC EDGAR asks for at most 10 requests a second; this is a much lower hourly budget."),
    ("rss", 600, "hour", "requests", "News and RSS feed fetches."),
    ("yahoo", 400, "hour", "requests", "Yahoo Finance is unofficial; its real limits are unknown, so this is a cautious guess to adjust."),
    ("public_api", 300, "hour", "requests", "Other free public APIs (Treasury, ECB, CoinGecko, mempool.space and similar)."),
    ("runtime", 14_400, "day", "seconds", "Worker compute time per day (infrastructure limit)."),
]


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(out.get(k), dict) and isinstance(v, dict) else v
    return out


def get(db: DB) -> dict:
    row = db.q("SELECT value FROM sched_settings WHERE key='settings'")
    return _merge(DEFAULTS, json.loads(row[0]["value"])) if row else copy.deepcopy(DEFAULTS)


def save(db: DB, patch: dict) -> dict:
    cur = _merge(get(db), patch)
    db.x("INSERT INTO sched_settings(key,value) VALUES('settings',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(cur),))
    sync_quotas(db, cur)
    return cur


def sync_quotas(db: DB, s: dict) -> None:
    """The Claude limits in the settings are mirrored into the quota table the budget reads."""
    c = s["claude"]
    db.x("UPDATE sched_quotas SET limit_amount=? WHERE bucket='ai_tokens'", (float(c.get("daily_token_limit") or 0),))
    db.x("UPDATE sched_quotas SET limit_amount=? WHERE bucket='ai_usd'", (float(c.get("daily_usd_limit") or 0),))
    db.x("UPDATE sched_quotas SET limit_amount=? WHERE bucket='ai_usd_month'", (float(c.get("monthly_usd_limit") or 0),))


def seed_quotas(db: DB) -> None:
    for bucket, limit, window, unit, note in DEFAULT_QUOTAS:
        db.x("INSERT OR IGNORE INTO sched_quotas(bucket,limit_amount,window,unit,note) VALUES(?,?,?,?,?)", (bucket, limit, window, unit, note))
    sync_quotas(db, get(db))


def set_quota(db: DB, bucket: str, limit: float) -> None:
    if not db.q("SELECT 1 FROM sched_quotas WHERE bucket=?", (bucket,)):
        raise KeyError(bucket)
    db.x("UPDATE sched_quotas SET limit_amount=? WHERE bucket=?", (float(limit), bucket))
    if bucket == "ai_tokens":
        save(db, {"claude": {"daily_token_limit": int(limit)}})
    db.audit("user", "sched_quota", {"bucket": bucket, "limit": limit})


def dollars(settings: dict, tokens_in: int, tokens_out: int) -> float | None:
    """Dollar cost of a call, or None when the user has not entered prices. We do not guess prices."""
    c = settings["claude"]
    if c.get("price_in_per_mtok") is None or c.get("price_out_per_mtok") is None:
        return None
    return tokens_in / 1e6 * float(c["price_in_per_mtok"]) + tokens_out / 1e6 * float(c["price_out_per_mtok"])
