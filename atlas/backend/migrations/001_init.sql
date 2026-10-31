CREATE TABLE watchlists(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);
CREATE TABLE watchlist_items(
  watchlist_id INTEGER NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
  instrument_id TEXT NOT NULL,
  position INTEGER NOT NULL,
  PRIMARY KEY (watchlist_id, instrument_id)
);
CREATE TABLE preferences(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE layouts(
  workspace TEXT PRIMARY KEY,
  layout TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE snapshots(
  snapshot_id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  payload TEXT NOT NULL
);
CREATE TABLE analyses(
  analysis_id TEXT PRIMARY KEY,
  agent TEXT NOT NULL,
  model TEXT,
  snapshot_id TEXT,
  question TEXT,
  output TEXT,
  status TEXT NOT NULL,
  input_tokens INTEGER DEFAULT 0,
  output_tokens INTEGER DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE audit_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  detail TEXT NOT NULL
);
CREATE INDEX idx_analyses_created ON analyses(created_at);
