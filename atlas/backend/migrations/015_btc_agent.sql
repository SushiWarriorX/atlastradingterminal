-- Strategy Lab improvement loop: one saved result per run, so reruns can be compared. Research data only.
CREATE TABLE btc_agent_runs(
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  strategy TEXT NOT NULL,
  verdict TEXT NOT NULL,
  fixes TEXT NOT NULL,
  data_to TEXT NOT NULL,
  payload TEXT NOT NULL
);
