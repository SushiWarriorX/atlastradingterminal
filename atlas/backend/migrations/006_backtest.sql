-- Saved backtest runs: the spec and the full result so a past run can be reopened without recomputing.
CREATE TABLE backtest_runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  spec TEXT NOT NULL,
  result TEXT NOT NULL,
  trades INTEGER NOT NULL,
  ran_at TEXT NOT NULL
);
