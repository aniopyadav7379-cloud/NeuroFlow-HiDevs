# Data Models

This document outlines the core data models used across the NeuroFlow system.

## 1. Document
Represents a source file or URL ingested into the system.
- `id` (UUID)
- `source_uri` (String)
- `modality` (Enum: text, image, pdf, etc.)
- `created_at` (Timestamp)
- `metadata` (JSONB)

## 2. Chunk
Represents a smaller segment of a Document.
- `id` (UUID)
- `document_id` (UUID, Foreign Key)
- `content` (Text)
- `embedding` (Vector)
- `chunk_index` (Integer)
- `metadata` (JSONB)

## 3. Query
Represents a user query executed through the retrieval and generation pipeline.
- `id` (UUID)
- `user_id` (UUID)
- `query_text` (Text)
- `timestamp` (Timestamp)
- `model_routed` (String)

## 4. Evaluation
Represents an automated evaluation score for a specific query generation.
- `id` (UUID)
- `query_id` (UUID, Foreign Key)
- `faithfulness` (Float)
- `answer_relevance` (Float)
- `context_precision` (Float)
- `context_recall` (Float)
- `user_rating` (Integer, Optional)

## 5. FineTuningJob
Represents a scheduled or completed fine-tuning job.
- `id` (UUID)
- `status` (Enum: queued, running, completed, failed)
- `base_model` (String)
- `dataset_size` (Integer)
- `metrics` (JSONB)
- `created_at` (Timestamp)
