CREATE TYPE launch_stage AS ENUM
  ('spy','teaser','world_premiere','specs_release',
   'pricing','on_sale','market_launch','concept');

CREATE TABLE launch_events (
  id              BIGSERIAL PRIMARY KEY,
  dedupe_key      TEXT NOT NULL,
  brand           TEXT NOT NULL,
  brand_group     TEXT,
  model           TEXT NOT NULL,
  model_slug      TEXT NOT NULL,
  generation      TEXT,
  body_type       TEXT,
  stage           launch_stage NOT NULL,
  is_new_generation BOOLEAN,
  markets         TEXT[] DEFAULT '{}',
  global_debut    BOOLEAN DEFAULT false,
  event_date      DATE,
  sales_start     TEXT,
  powertrain      JSONB,
  price           JSONB,
  highlights      TEXT[],
  embedding       vector(384),
  confidence      NUMERIC(3,2),
  first_seen_at   TIMESTAMPTZ DEFAULT now(),
  updated_at      TIMESTAMPTZ DEFAULT now(),
  published       BOOLEAN DEFAULT false,
  review_status   TEXT DEFAULT 'pending',
  previous_event_id BIGINT REFERENCES launch_events(id)
);
CREATE INDEX ON launch_events (dedupe_key, first_seen_at DESC);
CREATE INDEX ON launch_events USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON launch_events USING gin (model gin_trgm_ops);

CREATE TABLE event_sources (
  event_id   BIGINT REFERENCES launch_events(id) ON DELETE CASCADE,
  item_id    BIGINT REFERENCES raw_items(id),
  source_id  BIGINT REFERENCES sources(id),
  is_primary BOOLEAN DEFAULT false,
  seen_at    TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (event_id, item_id)
);
