-- Task 8 (configurable pipelines): version history and run-time tracking.
--
-- Design: `pipelines` stays the logical pipeline (name, status, and a
-- convenience copy of the CURRENT config/version for cheap reads).
-- `pipeline_versions` holds every historical config immutably — a PATCH
-- never overwrites a row here, it only inserts a new one and bumps
-- pipelines.current_version. pipeline_runs.pipeline_version records
-- exactly which version produced that run, which is what makes the A/B
-- comparison (and later, "did v3 actually improve on v2") meaningful.
--
-- Same migration-gap caveat as 003/004: only applies on a fresh Postgres
-- data volume via docker-entrypoint-initdb.d.

ALTER TABLE pipelines ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE pipelines ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'active';
ALTER TABLE pipelines ADD COLUMN IF NOT EXISTS current_version INT NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS pipeline_versions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  pipeline_id UUID NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
  version INT NOT NULL,
  config JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (pipeline_id, version)
);

ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS pipeline_version INT;
ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS retrieval_latency_ms INT;
