-- Strategy Lab, multi-coin research data: cached public daily bars (Coinbase, spot, USD) for a fixed list of coins. Research data only; gaps are reported, never filled.
CREATE TABLE coin_bars(
  symbol TEXT NOT NULL, t INTEGER NOT NULL, o REAL NOT NULL, h REAL NOT NULL, l REAL NOT NULL, c REAL NOT NULL, v REAL NOT NULL,
  PRIMARY KEY(symbol, t)
);
CREATE TABLE coin_meta(
  symbol TEXT PRIMARY KEY, status TEXT NOT NULL, first_t INTEGER, last_t INTEGER, bars INTEGER NOT NULL DEFAULT 0, fetched_at TEXT, note TEXT      -- status: ok | not_listed | error
);
