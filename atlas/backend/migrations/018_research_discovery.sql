-- Fundamental research and discovery: what I have seen, opened, saved, dismissed and researched; notes; "changes since my last review"; saved daily feeds; cached listing calendar.
CREATE TABLE disc_company_state(
  symbol TEXT PRIMARY KEY,
  first_seen_at TEXT,
  last_shown_at TEXT,
  shown_count INTEGER NOT NULL DEFAULT 0,
  opened_at TEXT,
  saved_at TEXT,
  dismissed_at TEXT,
  researched_at TEXT,
  last_material TEXT,
  last_score REAL
);

CREATE TABLE research_notes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  body TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX idx_research_notes_symbol ON research_notes(symbol, created_at);

CREATE TABLE research_reviews(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  reviewed_at TEXT NOT NULL,
  snapshot TEXT NOT NULL
);
CREATE INDEX idx_research_reviews_symbol ON research_reviews(symbol, reviewed_at);

CREATE TABLE disc_feed_runs(
  kind TEXT NOT NULL,
  asof TEXT NOT NULL,
  created_at TEXT NOT NULL,
  payload TEXT NOT NULL,
  PRIMARY KEY(kind, asof)
);

CREATE TABLE listing_cache(
  key TEXT PRIMARY KEY,
  fetched_at TEXT NOT NULL,
  payload TEXT NOT NULL
);
