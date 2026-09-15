-- Enable RLS and FORCE it so it applies even to the table owner (the app user)
ALTER TABLE pipelines ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipelines FORCE ROW LEVEL SECURITY;

ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE ROW LEVEL SECURITY;

ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE chunks FORCE ROW LEVEL SECURITY;

ALTER TABLE pipeline_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_runs FORCE ROW LEVEL SECURITY;

ALTER TABLE evaluations ENABLE ROW LEVEL SECURITY;
ALTER TABLE evaluations FORCE ROW LEVEL SECURITY;

ALTER TABLE training_pairs ENABLE ROW LEVEL SECURITY;
ALTER TABLE training_pairs FORCE ROW LEVEL SECURITY;

-- 1. Pipelines
CREATE POLICY pipeline_isolation_policy ON pipelines
    USING (id = NULLIF(current_setting('app.current_pipeline_id', true), '')::uuid);

-- 2. Documents
CREATE POLICY document_isolation_policy ON documents
    USING (pipeline_id = NULLIF(current_setting('app.current_pipeline_id', true), '')::uuid);

-- 3. Chunks (via documents table linkage)
CREATE POLICY chunk_isolation_policy ON chunks
    USING (document_id IN (
        SELECT id FROM documents 
        WHERE pipeline_id = NULLIF(current_setting('app.current_pipeline_id', true), '')::uuid
    ));

-- 4. Pipeline Runs
CREATE POLICY run_isolation_policy ON pipeline_runs
    USING (pipeline_id = NULLIF(current_setting('app.current_pipeline_id', true), '')::uuid);

-- 5. Evaluations (via pipeline_runs linkage)
CREATE POLICY evaluation_isolation_policy ON evaluations
    USING (run_id IN (
        SELECT id FROM pipeline_runs 
        WHERE pipeline_id = NULLIF(current_setting('app.current_pipeline_id', true), '')::uuid
    ));

-- 6. Training Pairs (via pipeline_runs linkage)
CREATE POLICY training_pair_isolation_policy ON training_pairs
    USING (run_id IN (
        SELECT id FROM pipeline_runs 
        WHERE pipeline_id = NULLIF(current_setting('app.current_pipeline_id', true), '')::uuid
    ));
