-- Task 9 (fine-tuning pipeline) needs two columns 001_schema.sql's
-- finetune_jobs didn't have:
--   fine_tuned_model_ref — the actual fine-tuned model NAME returned by
--     the provider once training succeeds (distinct from provider_job_id,
--     which is the OpenAI *job* id, e.g. "ftjob-abc123" — the model name,
--     e.g. "ft:gpt-4o-mini:neuroflow:legal:abc123", is a separate string
--     only known after the job completes).
--   target_task_type — which router task_type (domain) this fine-tune is
--     for, so registration can set ModelConfig.task_types correctly (see
--     pipelines/finetuning/registration.py) — "the domain it was trained
--     on" per the task spec.
--
-- Same migration-gap caveat as 003/004/005: only applies on a fresh
-- Postgres data volume via docker-entrypoint-initdb.d.

ALTER TABLE finetune_jobs ADD COLUMN IF NOT EXISTS fine_tuned_model_ref TEXT;
ALTER TABLE finetune_jobs ADD COLUMN IF NOT EXISTS target_task_type TEXT NOT NULL DEFAULT 'rag_generation';
