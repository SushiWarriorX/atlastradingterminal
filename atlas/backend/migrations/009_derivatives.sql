-- BTC derivatives snapshots recorded over time, so "high versus normal" can be measured against our own history (never against a guess).
CREATE TABLE deriv_history(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  venue TEXT NOT NULL,                  -- hyperliquid | binance | bybit | okx | ALL (aggregate)
  mark REAL,
  funding_annual_pct REAL,
  oi_btc REAL,
  oi_usd REAL,
  basis_pct REAL
);
CREATE INDEX idx_deriv_history ON deriv_history(venue, ts);
