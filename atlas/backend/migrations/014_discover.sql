-- Discover: one saved scan per calendar day (UTC), so the daily shortlist is stable through the day and its inputs can be inspected afterwards.
CREATE TABLE discover_runs(
  asof TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  payload TEXT NOT NULL
);
