-- RSS news: feeds (editable, with fetch health) and items (headline, link and a short plain-text summary only; never full article text).
CREATE TABLE news_feeds(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  url TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL DEFAULT 'rss' CHECK (kind IN ('rss','symbol')),
  enabled INTEGER NOT NULL DEFAULT 1,
  builtin INTEGER NOT NULL DEFAULT 0,
  etag TEXT,
  last_modified TEXT,
  last_fetch TEXT,
  last_ok TEXT,
  last_error TEXT,
  last_count INTEGER,
  created_at TEXT NOT NULL
);
CREATE TABLE news_items(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  feed_id INTEGER NOT NULL,
  uid TEXT NOT NULL,
  title TEXT NOT NULL,
  link TEXT,
  summary TEXT,
  published TEXT,
  fetched_at TEXT NOT NULL,
  symbols TEXT NOT NULL DEFAULT '[]',
  UNIQUE (feed_id, uid)
);
CREATE INDEX idx_news_items_time ON news_items(published);
CREATE INDEX idx_news_items_feed ON news_items(feed_id);
