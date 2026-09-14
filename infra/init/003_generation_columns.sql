-- Task 6 (generation pipeline) needs two columns 001_schema.sql's
-- pipeline_runs didn't have:
--   prompt   — the full assembled prompt, logged BEFORE the LLM call
--              (pipelines/generation/generator.py step 1)
--   metadata — chain-of-thought reasoning text for analytical/comparative
--              queries (stretch goal), stored for debugging but never
--              shown to the user
--
-- NOTE on when this actually runs: docker-entrypoint-initdb.d only runs
-- infra/init/*.sql on a *fresh* Postgres data volume. If you already have
-- a running stack from an earlier task, `docker compose up` will NOT
-- re-run this file automatically — either apply it manually against your
-- existing database, or drop the postgres_data volume and let it
-- reinitialize. backend/db/migrations.py's fallback path (ensure_schema)
-- also only triggers when a whole expected table is missing, not for a
-- missing column on an existing table, so it won't auto-apply this either
-- against an already-initialized DB. This is a known gap for column-level
-- migrations — a real project would want a proper migration tool
-- (alembic) once schema changes stop being "new tables only".

ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS prompt TEXT;
ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}';
