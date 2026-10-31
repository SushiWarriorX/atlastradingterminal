CREATE TABLE saved_scans(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  spec TEXT NOT NULL,
  created_at TEXT NOT NULL,
  last_run_at TEXT
);
CREATE TABLE scan_runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  spec TEXT NOT NULL,
  matched INTEGER NOT NULL,
  universe_size INTEGER NOT NULL,
  data_as_of TEXT,
  provider TEXT,
  ran_at TEXT NOT NULL
);
