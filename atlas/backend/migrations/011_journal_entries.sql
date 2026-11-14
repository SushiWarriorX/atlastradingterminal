-- Simple journal entries: one row per trade the user writes down by hand. Everything except the symbol and the date is optional, so an entry can be as small as a note.
-- Money is stored as exact decimal text, like the rest of the journal. Realised P&L is never stored: it is calculated from these fields when read.
CREATE TABLE journal_entries(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  asset_class TEXT NOT NULL DEFAULT 'other',
  direction TEXT NOT NULL DEFAULT 'long' CHECK(direction IN ('long','short')),
  size TEXT,
  entry_price TEXT,
  exit_price TEXT,
  entry_at TEXT NOT NULL,
  exit_at TEXT,
  fees TEXT NOT NULL DEFAULT '0',
  planned_stop TEXT,
  note TEXT,
  thesis TEXT,
  risk_plan TEXT,
  outcome TEXT,
  screenshot TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX idx_journal_entries_time ON journal_entries(entry_at);
CREATE INDEX idx_journal_entries_symbol ON journal_entries(symbol);
