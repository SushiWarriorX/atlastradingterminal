-- Journal: raw executions and cashflows from any source, trades are DERIVED from them at read time (never stale).
CREATE TABLE executions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  ext_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  symbol TEXT NOT NULL,
  instrument_id TEXT,
  asset_class TEXT NOT NULL,
  side TEXT NOT NULL CHECK (side IN ('buy','sell')),
  qty TEXT NOT NULL,
  price TEXT NOT NULL,
  fee TEXT NOT NULL DEFAULT '0',
  kind TEXT NOT NULL DEFAULT 'trade',
  currency TEXT NOT NULL DEFAULT 'USD',
  multiplier TEXT NOT NULL DEFAULT '1',
  batch_id INTEGER,
  created_at TEXT NOT NULL,
  UNIQUE (source, ext_id)
);
CREATE INDEX idx_executions_source ON executions(source, symbol, ts);
CREATE TABLE cashflows(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  ext_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  symbol TEXT,
  kind TEXT NOT NULL,
  amount TEXT NOT NULL,
  currency TEXT NOT NULL DEFAULT 'USD',
  note TEXT,
  batch_id INTEGER,
  created_at TEXT NOT NULL,
  UNIQUE (source, ext_id)
);
CREATE TABLE journal_notes(
  trade_key TEXT PRIMARY KEY,
  setup TEXT, thesis TEXT, catalyst TEXT, timeframe TEXT,
  planned_stop TEXT, targets TEXT,
  notes TEXT, mistakes TEXT, lessons TEXT, tags TEXT,
  screenshot TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE import_batches(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  kind TEXT NOT NULL,
  filename TEXT,
  rows_total INTEGER NOT NULL,
  inserted INTEGER NOT NULL,
  duplicates INTEGER NOT NULL,
  skipped INTEGER NOT NULL,
  mapping TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE csv_mappings(source TEXT PRIMARY KEY, mapping TEXT NOT NULL, updated_at TEXT NOT NULL);

-- Broker routing: a portfolio can be simulated ('sim') or linked to an IBKR account ('ibkr').
ALTER TABLE portfolios ADD COLUMN venue TEXT NOT NULL DEFAULT 'sim';
ALTER TABLE portfolios ADD COLUMN broker_account TEXT;
ALTER TABLE orders ADD COLUMN venue TEXT NOT NULL DEFAULT 'sim';
ALTER TABLE orders ADD COLUMN broker_order_id TEXT;
ALTER TABLE fills ADD COLUMN ext_id TEXT;
CREATE UNIQUE INDEX idx_fills_ext ON fills(portfolio_id, ext_id) WHERE ext_id IS NOT NULL;
