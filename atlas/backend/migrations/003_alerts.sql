CREATE TABLE alerts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  rule TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  enabled INTEGER NOT NULL DEFAULT 1,
  state TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE alert_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  alert_id INTEGER,
  alert_name TEXT NOT NULL,
  rule_version INTEGER NOT NULL,
  kind TEXT NOT NULL,
  severity TEXT NOT NULL,
  ts TEXT NOT NULL,
  message TEXT NOT NULL,
  trigger TEXT NOT NULL,
  delivery TEXT NOT NULL,
  read INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_alert_events_ts ON alert_events(ts);
CREATE INDEX idx_alert_events_unread ON alert_events(read, id);
