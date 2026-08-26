CREATE TABLE source_incidents (
  id          BIGSERIAL PRIMARY KEY,
  source_id   BIGINT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  kind        TEXT NOT NULL,          -- 'pause' | 'block'
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON source_incidents (source_id, occurred_at DESC);
