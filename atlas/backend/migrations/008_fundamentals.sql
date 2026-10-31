-- Cached fundamentals snapshots (normalized payload as JSON). A failed refresh falls back to the last snapshot, labelled STALE.
CREATE TABLE fundamentals_cache(
  symbol TEXT PRIMARY KEY,
  fetched_at TEXT NOT NULL,
  provider TEXT NOT NULL,
  payload TEXT NOT NULL
);
