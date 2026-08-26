ALTER TABLE sources ADD COLUMN probation_since TIMESTAMPTZ;
UPDATE sources SET probation_since = added_at WHERE status = 'probation' AND probation_since IS NULL;

CREATE TABLE pending_retirements (
  source_id  BIGINT PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
  flagged_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE llm_usage (
  id          BIGSERIAL PRIMARY KEY,
  called_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  op          TEXT NOT NULL,          -- 'classify' | 'extract'
  model       TEXT NOT NULL,
  tokens_in   INT NOT NULL,
  tokens_out  INT NOT NULL,
  cost_usd    NUMERIC(10,4) NOT NULL
);
CREATE INDEX ON llm_usage (called_at);

CREATE TABLE daily_stats (
  day                DATE PRIMARY KEY,
  items_ingested     INT DEFAULT 0,
  items_classified   INT DEFAULT 0,
  items_approved     INT DEFAULT 0,
  items_extracted    INT DEFAULT 0,
  events_created     INT DEFAULT 0,
  events_published   INT DEFAULT 0,
  llm_calls          INT DEFAULT 0,
  llm_tokens_in      INT DEFAULT 0,
  llm_tokens_out     INT DEFAULT 0,
  llm_cost_usd       NUMERIC(10,4) DEFAULT 0,
  sources_active     INT DEFAULT 0,
  sources_blocked    INT DEFAULT 0,
  computed_at        TIMESTAMPTZ DEFAULT now()
);
