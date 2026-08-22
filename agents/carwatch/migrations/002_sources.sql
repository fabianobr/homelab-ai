CREATE TYPE source_status AS ENUM
  ('active','probation','retired','broken','blocked','candidate');

CREATE TABLE sources (
  id              BIGSERIAL PRIMARY KEY,
  domain          TEXT NOT NULL,
  feed_url        TEXT UNIQUE NOT NULL,
  kind            TEXT NOT NULL,
  tier            SMALLINT NOT NULL,
  brand_scope     TEXT[] DEFAULT '{}',
  region          TEXT,
  lang            TEXT DEFAULT 'en',
  status          source_status NOT NULL DEFAULT 'candidate',
  etag            TEXT,
  last_modified   TEXT,
  added_at        TIMESTAMPTZ DEFAULT now(),
  last_ok_at      TIMESTAMPTZ,
  last_item_at    TIMESTAMPTZ,
  consecutive_failures  INT DEFAULT 0,
  blocked_until   TIMESTAMPTZ,
  notes           TEXT
);
CREATE INDEX ON sources (status, tier);
CREATE INDEX ON sources (domain);

CREATE TABLE source_metrics (
  source_id            BIGINT PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
  computed_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  items_30d            INT DEFAULT 0,
  passed_prefilter_30d INT DEFAULT 0,
  events_30d           INT DEFAULT 0,
  unique_events_30d    INT DEFAULT 0,
  first_seen_30d       INT DEFAULT 0,
  median_lead_minutes  INT,
  yield_pct            NUMERIC(5,2),
  precision_30d        NUMERIC(5,2)
);

CREATE TABLE raw_items (
  id            BIGSERIAL PRIMARY KEY,
  source_id     BIGINT REFERENCES sources(id),
  url           TEXT NOT NULL,
  url_hash      TEXT UNIQUE NOT NULL,
  title         TEXT NOT NULL,
  summary       TEXT,
  lang          TEXT,
  published_at  TIMESTAMPTZ,
  fetched_at    TIMESTAMPTZ DEFAULT now(),
  body          TEXT,
  prefilter_ok  BOOLEAN,
  classified    JSONB,
  status        TEXT DEFAULT 'new'
);
CREATE INDEX ON raw_items (status, fetched_at DESC);
CREATE INDEX ON raw_items (source_id, published_at DESC);
