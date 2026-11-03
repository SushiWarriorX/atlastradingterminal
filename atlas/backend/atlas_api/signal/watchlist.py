"""The saved watchlist, stored server-side (so it survives app reinstalls and follows the user between devices). Order is explicit and contiguous."""
from __future__ import annotations

from datetime import datetime, timezone

from ..db import DB
from .assets import Asset

MAX_ITEMS = 100


class WatchlistError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class WatchlistStore:
    def __init__(self, db: DB):
        self.db = db

    def list(self) -> list[dict]:
        return [dict(r) for r in self.db.q("SELECT asset_id, symbol, name, asset_type, venue, added_at, position FROM signal_watchlist ORDER BY position")]

    def ids(self) -> list[str]:
        return [r["asset_id"] for r in self.db.q("SELECT asset_id FROM signal_watchlist ORDER BY position")]

    def add(self, a: Asset) -> bool:
        """Append (idempotent). Returns False if it was already saved."""
        with self.db.tx() as c:
            if c.execute("SELECT 1 FROM signal_watchlist WHERE asset_id=?", (a.id,)).fetchone():
                return False
            n = c.execute("SELECT COUNT(*) FROM signal_watchlist").fetchone()[0]
            if n >= MAX_ITEMS:
                raise WatchlistError("WATCHLIST_FULL", f"The watchlist holds at most {MAX_ITEMS} assets.", 409)
            c.execute("INSERT INTO signal_watchlist(asset_id, position, symbol, name, asset_type, venue, added_at) VALUES(?,?,?,?,?,?,?)",
                      (a.id, n, a.symbol, a.name[:120], a.type, a.venue, datetime.now(timezone.utc).isoformat()))
        return True

    def remove(self, asset_id: str) -> bool:
        with self.db.tx() as c:
            if c.execute("DELETE FROM signal_watchlist WHERE asset_id=?", (asset_id,)).rowcount == 0:
                return False
            for pos, (aid,) in enumerate(c.execute("SELECT asset_id FROM signal_watchlist ORDER BY position").fetchall()):
                c.execute("UPDATE signal_watchlist SET position=? WHERE asset_id=?", (pos, aid))
        return True

    def reorder(self, ids: list[str]) -> None:
        """`ids` must be exactly the saved ids in the new order (no additions, removals or duplicates)."""
        cur = self.ids()
        if len(ids) != len(set(ids)) or set(ids) != set(cur):
            raise WatchlistError("ORDER_MISMATCH", "The new order must contain exactly the saved assets, once each. Refresh and try again.", 409)
        with self.db.tx() as c:
            for pos, aid in enumerate(ids):
                c.execute("UPDATE signal_watchlist SET position=? WHERE asset_id=?", (pos, aid))
