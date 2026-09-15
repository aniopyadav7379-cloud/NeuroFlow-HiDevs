\set ON_ERROR_STOP on

-- Set context to pipeline A
SET app.current_pipeline_id = '11111111-1111-1111-1111-111111111111';

-- Insert pipeline A
INSERT INTO pipelines (id, name, config) VALUES ('11111111-1111-1111-1111-111111111111', 'Pipeline A', '{}');

-- Insert document & chunk for Pipeline A
INSERT INTO documents (id, filename, source_type, content_hash, pipeline_id) 
VALUES ('aaaaaaaa-1111-1111-1111-111111111111', 'docA.txt', 'text', 'hashA', '11111111-1111-1111-1111-111111111111');

INSERT INTO chunks (document_id, content, chunk_index, token_count)
VALUES ('aaaaaaaa-1111-1111-1111-111111111111', 'Secret Pipeline A Data', 0, 10);

-- Set context to pipeline B
SET app.current_pipeline_id = '22222222-2222-2222-2222-222222222222';
INSERT INTO pipelines (id, name, config) VALUES ('22222222-2222-2222-2222-222222222222', 'Pipeline B', '{}');

INSERT INTO documents (id, filename, source_type, content_hash, pipeline_id) 
VALUES ('bbbbbbbb-2222-2222-2222-222222222222', 'docB.txt', 'text', 'hashB', '22222222-2222-2222-2222-222222222222');

INSERT INTO chunks (document_id, content, chunk_index, token_count)
VALUES ('bbbbbbbb-2222-2222-2222-222222222222', 'Public Pipeline B Data', 0, 10);

-- Test 1: Query chunks under Pipeline B context (should only see Pipeline B's chunk)
\echo '--- TEST 1: Querying as Pipeline B ---'
SELECT content FROM chunks; 

-- Test 2: Query chunks without ANY context (should see NO chunks)
\echo '--- TEST 2: Querying without context ---'
RESET app.current_pipeline_id;
SELECT content FROM chunks;
