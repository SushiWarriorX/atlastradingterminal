"""Allowances and atomic reservations.

Every limited resource (our Claude token and dollar budget, each data provider, worker compute time) is a bucket with a limit per window. Before a job starts it RESERVES its
estimated need in every bucket it touches; the reservation and the check happen inside one database write-lock (BEGIN IMMEDIATE), so two jobs, or the web process and the worker,
can never both see the same remaining balance and both spend it. After the run the reservation is replaced by what was really used. A crash leaves the reservation counted as spent
(the conservative reading: we cannot know the money was not used).

The usage reserve (default 20%) is kept back from every allowance for essential (priority 5) jobs: optional work may use at most (100 - reserve)% of a limit.
A limit of 0 means "no limit set", so the bucket never blocks; the dashboard says so.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..db import DB


def window_key(window: str, at: datetime) -> str:
    at = at.astimezone(timezone.utc)
    return {"day": at.strftime("%Y-%m-%d"), "month": at.strftime("%Y-%m"), "hour": at.strftime("%Y-%m-%dT%H"), "minute": at.strftime("%Y-%m-%dT%H:%M")}[window]


def window_end(window: str, at: datetime) -> datetime:
    """When the current window resets (UTC)."""
    at = at.astimezone(timezone.utc)
    from datetime import timedelta
    if window == "minute":
        return at.replace(second=0, microsecond=0) + timedelta(minutes=1)
    if window == "hour":
        return at.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    if window == "day":
        return at.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    first = at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return first.replace(year=first.year + (first.month == 12), month=first.month % 12 + 1)


class Budget:
    def __init__(self, db: DB):
        self.db = db

    def quotas(self) -> dict[str, dict]:
        return {r["bucket"]: dict(r) for r in self.db.q("SELECT * FROM sched_quotas")}

    def used(self, bucket: str, key: str, conn=None) -> float:
        q = "SELECT COALESCE(SUM(amount),0) FROM sched_reservations WHERE bucket=? AND window_key=? AND state IN ('reserved','committed')"
        row = (conn.execute(q, (bucket, key)).fetchone() if conn is not None else self.db.q(q, (bucket, key))[0])
        return float(row[0])

    def snapshot(self, at: datetime, reserve_pct: float) -> dict[str, dict]:
        """Used / limit / remaining per bucket for the dashboard and for interval adaptation. remaining_fraction is None when no limit is set."""
        out = {}
        for b, q in self.quotas().items():
            key = window_key(q["window"], at)
            used = self.used(b, key)
            limit = float(q["limit_amount"])
            out[b] = {"bucket": b, "window": q["window"], "unit": q["unit"], "limit": limit if limit > 0 else None, "used": round(used, 4), "resets_at": window_end(q["window"], at).isoformat(), "note": q["note"],
                      "remaining": None if limit <= 0 else max(limit - used, 0.0), "remaining_fraction": None if limit <= 0 else max(limit - used, 0.0) / limit,
                      "optional_work_allowed": True if limit <= 0 else used < limit * (1 - reserve_pct / 100.0)}
        return out

    def reserve(self, run_id: int, needs: dict[str, float], at: datetime, reserve_pct: float, essential: bool) -> tuple[bool, str | None, dict]:
        """All-or-nothing: either every bucket has room (and is charged now) or nothing is reserved. Returns (ok, reason_if_not, per-bucket detail)."""
        qs = self.quotas()
        created = at.astimezone(timezone.utc).isoformat()
        with self.db.tx(immediate=True) as conn:
            for b, amount in needs.items():
                if amount <= 0 or b not in qs:
                    continue
                q = qs[b]
                limit = float(q["limit_amount"])
                if limit <= 0:
                    continue
                key = window_key(q["window"], at)
                cap = limit if essential or not q["essential_only_reserve"] else limit * (1 - reserve_pct / 100.0)
                used = self.used(b, key, conn)
                if used + amount > cap + 1e-9:
                    why = (f"{b}: needs {amount:g} {q['unit']} but only {max(cap - used, 0):g} remain of the {'full allowance' if essential else f'{100 - reserve_pct:g}% usable by optional work'} "
                           f"({used:g} of {limit:g} used this {q['window']}; resets {window_end(q['window'], at).strftime('%H:%M UTC')})")
                    return False, why, {}
            detail = {}
            for b, amount in needs.items():
                if amount <= 0 or b not in qs or float(qs[b]["limit_amount"]) <= 0:
                    continue
                key = window_key(qs[b]["window"], at)
                conn.execute("INSERT INTO sched_reservations(run_id,bucket,window_key,amount,state,created_at) VALUES(?,?,?,?, 'reserved', ?)", (run_id, b, key, amount, created))
                detail[b] = amount
            return True, None, detail

    def settle(self, run_id: int, actual: dict[str, float]) -> None:
        """Replace the reservation with what was really used (never more than was reserved unless the job overspent, which is recorded as it happened)."""
        with self.db.tx(immediate=True) as conn:
            rows = conn.execute("SELECT id,bucket FROM sched_reservations WHERE run_id=? AND state='reserved'", (run_id,)).fetchall()
            for r in rows:
                conn.execute("UPDATE sched_reservations SET amount=?, state='committed' WHERE id=?", (float(actual.get(r["bucket"], 0.0)), r["id"]))

    def release(self, run_id: int) -> None:
        self.db.x("UPDATE sched_reservations SET state='released' WHERE run_id=? AND state='reserved'", (run_id,))

    def charge(self, run_id: int, bucket: str, amount: float, at: datetime) -> None:
        """Record spending that was not reserved in advance (for example a provider call a handler made beyond its estimate). Always recorded; the next reservation sees it."""
        qs = self.quotas()
        if bucket not in qs or amount <= 0:
            return
        self.db.x("INSERT INTO sched_reservations(run_id,bucket,window_key,amount,state,created_at) VALUES(?,?,?,?, 'committed', ?)",
                  (run_id, bucket, window_key(qs[bucket]["window"], at), amount, at.astimezone(timezone.utc).isoformat()))
