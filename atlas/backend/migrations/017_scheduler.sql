-- Shared scheduler: persistent jobs, runs, budget reservations, quotas, dead letters and operator events. Research only; nothing here places a trade.
CREATE TABLE sched_settings(
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE sched_jobs(
  id TEXT PRIMARY KEY,
  enabled INTEGER NOT NULL DEFAULT 1,
  paused INTEGER NOT NULL DEFAULT 0,
  priority INTEGER NOT NULL DEFAULT 3,                 -- 1 (optional) .. 5 (essential)
  interval_market_s INTEGER NOT NULL,                  -- preferred interval while the US market is open
  interval_off_s INTEGER NOT NULL,                     -- preferred interval otherwise
  max_tokens INTEGER NOT NULL DEFAULT 0,               -- AI tokens one run may use (0 = the job uses no AI)
  max_runtime_s INTEGER NOT NULL DEFAULT 300,
  max_experiments INTEGER NOT NULL DEFAULT 0,
  next_run_at TEXT,
  effective_interval_s INTEGER,
  effective_reason TEXT,
  run_requested INTEGER NOT NULL DEFAULT 0,            -- manual "run now"
  lease_until TEXT,                                    -- set while a run is executing: stops overlapping and duplicate runs across processes
  lease_run_id INTEGER,
  last_started_at TEXT,
  last_success_at TEXT,
  last_status TEXT,
  last_error TEXT,
  deferred_reason TEXT,
  consecutive_failures INTEGER NOT NULL DEFAULT 0,
  avg_cost_tokens REAL,
  avg_runtime_s REAL,
  runs_total INTEGER NOT NULL DEFAULT 0,
  checkpoint TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE sched_runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  trigger TEXT NOT NULL,                               -- schedule | manual | retry
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,                                -- running | ok | failed | timeout | deferred | interrupted
  attempt INTEGER NOT NULL DEFAULT 1,
  reason TEXT,
  tokens_in INTEGER NOT NULL DEFAULT 0,
  tokens_out INTEGER NOT NULL DEFAULT 0,
  provider_calls INTEGER NOT NULL DEFAULT 0,
  duration_s REAL,
  summary TEXT,
  error TEXT
);
CREATE INDEX sched_runs_job ON sched_runs(job_id, id DESC);
CREATE TABLE sched_reservations(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  bucket TEXT NOT NULL,
  window_key TEXT NOT NULL,
  amount REAL NOT NULL,
  state TEXT NOT NULL,                                 -- reserved | committed | released
  created_at TEXT NOT NULL
);
CREATE INDEX sched_res_bucket ON sched_reservations(bucket, window_key, state);
CREATE TABLE sched_quotas(
  bucket TEXT PRIMARY KEY,
  limit_amount REAL NOT NULL,
  window TEXT NOT NULL,                                -- day | month | hour | minute
  unit TEXT NOT NULL,
  essential_only_reserve INTEGER NOT NULL DEFAULT 1,   -- keep the usage reserve for essential (priority 5) jobs
  note TEXT
);
CREATE TABLE sched_dead_letters(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  run_id INTEGER,
  failed_at TEXT NOT NULL,
  attempts INTEGER NOT NULL,
  error TEXT,
  checkpoint TEXT,
  resolved INTEGER NOT NULL DEFAULT 0,
  resolved_at TEXT
);
CREATE TABLE sched_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  kind TEXT NOT NULL,                                  -- failure | budget | stale | action | info
  dedupe_key TEXT NOT NULL,
  severity TEXT NOT NULL,                              -- info | warn | critical
  message TEXT NOT NULL,
  notified INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX sched_events_key ON sched_events(dedupe_key, id DESC);
