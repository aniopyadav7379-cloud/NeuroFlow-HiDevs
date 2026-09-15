DELETE FROM training_pairs;
DELETE FROM evaluations;

DO $$
DECLARE
    p_id uuid;
    r_id uuid;
    i integer;
BEGIN
    SELECT id INTO p_id FROM pipelines LIMIT 1;
    
    FOR i IN 1..12 LOOP
        r_id := gen_random_uuid();
        INSERT INTO pipeline_runs (id, pipeline_id, query, status) VALUES (r_id, p_id, 'Q', 'completed');
        INSERT INTO evaluations (run_id, user_rating, faithfulness) VALUES (r_id, 5, 0.9);
        INSERT INTO training_pairs (run_id, quality_score, user_message, assistant_message) VALUES (r_id, 0.9, 'U', 'A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A A [Source 1]');
    END LOOP;
END $$;
