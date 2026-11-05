-- BTC Strategy Lab: cached public price bars (Coinbase) and perpetual funding history (Hyperliquid). Research data only.
CREATE TABLE btc_bars(
  tf TEXT NOT NULL, t INTEGER NOT NULL, o REAL NOT NULL, h REAL NOT NULL, l REAL NOT NULL, c REAL NOT NULL, v REAL NOT NULL,
  PRIMARY KEY(tf, t)
);
CREATE TABLE btc_funding(
  t INTEGER PRIMARY KEY, rate REAL NOT NULL           -- hourly funding rate (fraction), time in unix seconds
);
CREATE TABLE btc_meta(
  key TEXT PRIMARY KEY, value TEXT NOT NULL            -- e.g. last fetch times
);
