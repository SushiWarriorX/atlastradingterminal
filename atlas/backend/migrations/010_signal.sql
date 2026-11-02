-- Signal Mobile: the user's saved assets, in order. The asset id is the stable key (never the ticker); name/symbol/type/venue are
-- kept so the list can still be drawn when a name directory is unavailable.
CREATE TABLE signal_watchlist(
  asset_id TEXT PRIMARY KEY,
  position INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  name TEXT NOT NULL,
  asset_type TEXT NOT NULL,
  venue TEXT NOT NULL,
  added_at TEXT NOT NULL
);
CREATE INDEX idx_signal_watchlist_pos ON signal_watchlist(position);
