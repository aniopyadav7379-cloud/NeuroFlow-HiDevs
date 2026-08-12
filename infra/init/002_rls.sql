-- Row Level Security: isolate data between pipelines.
--
-- The app sets a per-connection/session GUC before running any query:
--   SET app.current_pipeline_id = '<uuid>';
-- All policies below scope rows to that pipeline. A session that never sets
-- the GUC (or sets it to something that isn't a valid uuid) sees zero rows
-- in every RLS-protected table — fail closed, not fail open.
--
-- finetune_jobs is intentionally NOT pipeline-scoped: fine-tune jobs can
-- pull training pairs across pipelines (see architecture.md / ADR 004
-- follow-up), so it's treated as an admin-only table instead (see bottom).

-- Helper: current pipeline from session GUC, NULL if unset/invalid rather
-- than raising, so a missing GUC fails the row match instead of erroring
-- the whole query.
CREATE OR REPLACE FUNCTION current_pipeline_id() RETURNS UUID
LANGUAGE sql STABLE AS $$
  SELECT NULLIF(current_setting('app.current_pipeline_id', true), '')::UUID
$$;

-- A dedicated non-superuser application role. RLS policies apply to table
-- owners too when FORCE ROW LEVEL SECURITY is set, but connecting as this
-- role (rather than the migration/owner role) is the normal safe setup.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'neuroflow_app') THEN
    CREATE ROLE neuroflow_app LOGIN PASSWORD 'change_me_in_env';
  END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO neuroflow_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO neuroflow_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO neuroflow_app;

-- ── pipelines ────────────────────────────────────────────────────────────
ALTER TABLE pipelines ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipelines FORCE ROW LEVEL SECURITY;

CREATE POLICY pipelines_isolation ON pipelines
  USING (id = current_pipeline_id())
  WITH CHECK (id = current_pipeline_id());

-- ── documents ────────────────────────────────────────────────────────────
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE ROW LEVEL SECURITY;

CREATE POLICY documents_isolation ON documents
  USING (pipeline_id = current_pipeline_id())
  WITH CHECK (pipeline_id = current_pipeline_id());

-- ── chunks (scoped via parent document, no pipeline_id column of its own) ─
ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE chunks FORCE ROW LEVEL SECURITY;

CREATE POLICY chunks_isolation ON chunks
  USING (
    EXISTS (
      SELECT 1 FROM documents d
      WHERE d.id = chunks.document_id
        AND d.pipeline_id = current_pipeline_id()
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM documents d
      WHERE d.id = chunks.document_id
        AND d.pipeline_id = current_pipeline_id()
    )
  );

-- ── pipeline_runs ────────────────────────────────────────────────────────
ALTER TABLE pipeline_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_runs FORCE ROW LEVEL SECURITY;

CREATE POLICY pipeline_runs_isolation ON pipeline_runs
  USING (pipeline_id = current_pipeline_id())
  WITH CHECK (pipeline_id = current_pipeline_id());

-- ── evaluations (scoped via parent run) ─────────────────────────────────
ALTER TABLE evaluations ENABLE ROW LEVEL SECURITY;
ALTER TABLE evaluations FORCE ROW LEVEL SECURITY;

CREATE POLICY evaluations_isolation ON evaluations
  USING (
    EXISTS (
      SELECT 1 FROM pipeline_runs r
      WHERE r.id = evaluations.run_id
        AND r.pipeline_id = current_pipeline_id()
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM pipeline_runs r
      WHERE r.id = evaluations.run_id
        AND r.pipeline_id = current_pipeline_id()
    )
  );

-- ── training_pairs (scoped via parent run) ──────────────────────────────
ALTER TABLE training_pairs ENABLE ROW LEVEL SECURITY;
ALTER TABLE training_pairs FORCE ROW LEVEL SECURITY;

CREATE POLICY training_pairs_isolation ON training_pairs
  USING (
    EXISTS (
      SELECT 1 FROM pipeline_runs r
      WHERE r.id = training_pairs.run_id
        AND r.pipeline_id = current_pipeline_id()
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM pipeline_runs r
      WHERE r.id = training_pairs.run_id
        AND r.pipeline_id = current_pipeline_id()
    )
  );

-- ── finetune_jobs: admin-only, not pipeline-scoped ──────────────────────
-- No per-pipeline concept applies (a job can draw training pairs from
-- several pipelines), so this is locked to a separate admin role instead
-- of the per-pipeline GUC. neuroflow_app has no policy allowing rows, so
-- with RLS forced it sees none by default; grant a service role for the
-- fine-tune scheduler explicitly if/when that worker needs write access.
ALTER TABLE finetune_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE finetune_jobs FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'neuroflow_admin') THEN
    CREATE ROLE neuroflow_admin LOGIN PASSWORD 'change_me_in_env';
  END IF;
END
$$;

GRANT SELECT, INSERT, UPDATE, DELETE ON finetune_jobs TO neuroflow_admin;

CREATE POLICY finetune_jobs_admin_only ON finetune_jobs
  TO neuroflow_admin
  USING (true)
  WITH CHECK (true);

-- ═══════════════════════════════════════════════════════════════════════
-- Manual test (run as neuroflow_app, NOT as the table owner/migration role
-- — table owners bypass RLS unless connected through a role the FORCE
-- clause applies to and you're not a superuser):
--
--   -- as neuroflow_app, pipeline A context:
--   SET app.current_pipeline_id = '<pipeline-A-uuid>';
--   SELECT count(*) FROM chunks;                 -- only pipeline A's chunks
--
--   -- switch context to pipeline B:
--   SET app.current_pipeline_id = '<pipeline-B-uuid>';
--   SELECT count(*) FROM chunks;                 -- only pipeline B's chunks,
--                                                 -- zero of pipeline A's
--
--   -- no context set at all:
--   RESET app.current_pipeline_id;
--   SELECT count(*) FROM chunks;                 -- 0 rows, fail closed
-- ═══════════════════════════════════════════════════════════════════════
