-- Task 7 (evaluation subsystem) needs a place to store two things
-- 001_schema.sql's evaluations table didn't have a column for:
--   - calibration_needed: set by PATCH /runs/{run_id}/rating when the
--     automated overall_score and the human user_rating disagree by more
--     than 0.3 (normalized to the same 0-1 scale)
--   - self-consistency stats (stretch goal): std_dev across 3 judge runs
--     at temperature=0.7, and a high_variance flag when std_dev > 0.2
--
-- Same migration-gap caveat as infra/init/003_generation_columns.sql:
-- docker-entrypoint-initdb.d only runs on a fresh Postgres data volume.

ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}';
