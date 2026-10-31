CREATE TABLE portfolios(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL CHECK (kind IN ('paper','manual')),
  base_ccy TEXT NOT NULL DEFAULT 'USD',
  starting_cash TEXT NOT NULL,
  cash TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE positions(
  portfolio_id INTEGER NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
  instrument_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  qty TEXT NOT NULL,
  avg_cost TEXT NOT NULL,
  realized TEXT NOT NULL DEFAULT '0',
  planned_stop TEXT,
  PRIMARY KEY (portfolio_id, instrument_id)
);
CREATE TABLE orders(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  portfolio_id INTEGER NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
  client_key TEXT NOT NULL,
  instrument_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  type TEXT NOT NULL,
  tif TEXT NOT NULL,
  qty TEXT NOT NULL,
  limit_price TEXT,
  stop_price TEXT,
  planned_stop TEXT,
  est_price TEXT NOT NULL,
  state TEXT NOT NULL,
  filled_qty TEXT NOT NULL DEFAULT '0',
  avg_fill_price TEXT,
  triggered INTEGER NOT NULL DEFAULT 0,
  reason TEXT,
  data_status TEXT,
  environment TEXT NOT NULL DEFAULT 'paper',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  expires_at TEXT,
  UNIQUE (portfolio_id, client_key)
);
CREATE INDEX idx_orders_state ON orders(state);
CREATE TABLE fills(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  portfolio_id INTEGER NOT NULL,
  instrument_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  qty TEXT NOT NULL,
  price TEXT NOT NULL,
  fee TEXT NOT NULL,
  ts TEXT NOT NULL,
  data_status TEXT,
  provider TEXT,
  note TEXT
);
CREATE INDEX idx_fills_portfolio ON fills(portfolio_id, id);
CREATE TABLE order_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  ts TEXT NOT NULL,
  event TEXT NOT NULL,
  detail TEXT NOT NULL
);
CREATE TABLE equity_history(
  portfolio_id INTEGER NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
  ts TEXT NOT NULL,
  equity TEXT NOT NULL,
  cash TEXT NOT NULL,
  PRIMARY KEY (portfolio_id, ts)
);
