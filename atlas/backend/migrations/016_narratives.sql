-- Discover: the narrative of the day, one saved result per UTC day so it is stable while you read it and recent themes are not repeated. Research data only.
CREATE TABLE narrative_runs(
  asof TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  theme TEXT NOT NULL,
  payload TEXT NOT NULL
);
