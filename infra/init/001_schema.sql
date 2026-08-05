CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Documents and chunks
CREATE TABLE documents (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  filename TEXT NOT NULL,
  source_type VARCHAR(20) NOT NULL CHECK (source_type IN ('pdf','docx','image','csv','url','text')),
  content_hash TEXT UNIQUE NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}',
  pipeline_id UUID,
  status VARCHAR(20) NOT NULL DEFAULT 'processing',
  chunk_count INT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE chunks (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  content TEXT NOT NULL,
  embedding vector(1536),
  chunk_index INT NOT NULL,
  token_count INT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
CREATE INDEX ON chunks (document_id);
CREATE INDEX ON chunks USING gin (to_tsvector('english', content));

-- Pipelines and runs
CREATE TABLE pipelines (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name TEXT UNIQUE NOT NULL,
  config JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE pipeline_runs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  pipeline_id UUID NOT NULL REFERENCES pipelines(id),
  query TEXT NOT NULL,
  retrieved_chunk_ids UUID[],
  generation TEXT,
  latency_ms INT,
  input_tokens INT,
  output_tokens INT,
  model_used TEXT,
  status VARCHAR(20) NOT NULL DEFAULT 'running',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Evaluations
CREATE TABLE evaluations (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  run_id UUID NOT NULL REFERENCES pipeline_runs(id),
  faithfulness FLOAT CHECK (faithfulness BETWEEN 0 AND 1),
  answer_relevance FLOAT CHECK (answer_relevance BETWEEN 0 AND 1),
  context_precision FLOAT CHECK (context_precision BETWEEN 0 AND 1),
  context_recall FLOAT CHECK (context_recall BETWEEN 0 AND 1),
  overall_score FLOAT,
  judge_model TEXT,
  user_rating INT CHECK (user_rating BETWEEN 1 AND 5),
  evaluated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Fine-tuning
CREATE TABLE training_pairs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  run_id UUID NOT NULL REFERENCES pipeline_runs(id),
  system_prompt TEXT,
  user_message TEXT NOT NULL,
  assistant_message TEXT NOT NULL,
  quality_score FLOAT,
  included_in_job UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE finetune_jobs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  provider_job_id TEXT,
  base_model TEXT NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'pending',
  training_pair_count INT,
  mlflow_run_id TEXT,
  metrics JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ
);
