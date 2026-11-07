-- SEC EDGAR responses, condensed. company_tickers.json and company facts are large; only what the stock research page needs is kept.
CREATE TABLE edgar_cache(
  key TEXT PRIMARY KEY,
  fetched_at TEXT NOT NULL,
  payload TEXT NOT NULL
);
