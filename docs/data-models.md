# NeuroFlow Data Models

All tables live in a single Postgres database with the `pgvector` extension enabled. Table names are singular subsystem nouns, plural for collections.

## `documents`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| pipeline_id | uuid FK → pipelines.id | |
| source_type | text | `file` \| `url` |
| source_ref | text | storage key or URL |
| mime_type | text | |
| metadata | jsonb | tags, source_name, custom fields |
| ingested_at | timestamptz | |

## `ingestion_jobs`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | = `job_id` in API |
| document_id | uuid FK → documents.id, nullable until doc created | |
| status | text | `pending`\|`processing`\|`complete`\|`failed` |
| error | text | nullable |
| created_at / updated_at | timestamptz | |

## `chunks`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| document_id | uuid FK → documents.id | |
| ordinal | int | position within document |
| text | text | |
| char_span | int4range | offsets into extracted text |
| embedding | vector(d) | pgvector column, dimension per embedding model |
| embedding_model | text | version-stamped |
| metadata | jsonb | page/row ref, section heading |
| tsv | tsvector | generated column for keyword search |

Indexes: `ivfflat`/`hnsw` on `embedding`; GIN on `tsv`; btree on `document_id`.

## `pipelines`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| name | text unique | |
| chunking_strategy | text | `fixed`\|`sentence`\|`semantic` |
| embedding_model | text | |
| retrieval_config | jsonb | top_k, rerank_top_n, context_window_size |
| default_model_tier | text | `A`\|`B`\|`C` |
| created_at | timestamptz | |

## `queries`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | = `query_id` |
| pipeline_id | uuid FK | |
| conversation_id | uuid nullable | |
| query_text | text | |
| filters | jsonb | |
| created_at | timestamptz | |

## `generations`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | = `generation_id` |
| query_id | uuid FK → queries.id | |
| model | text | routed model identifier |
| routing_reason | jsonb | tier, cost, latency, domain signals used |
| context_chunk_ids | uuid[] | chunks actually included in prompt |
| prompt | text | full assembled prompt |
| response | text | full response |
| prompt_tokens / completion_tokens | int | |
| latency_ms | int | |
| cost_usd | numeric | |
| user_rating | int nullable | 1–5, set post-hoc via feedback endpoint |
| created_at | timestamptz | |

## `evaluations`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| generation_id | uuid FK → generations.id | |
| faithfulness | numeric(3,2) | 0–1 |
| answer_relevance | numeric(3,2) | 0–1 |
| context_precision | numeric(3,2) | 0–1 |
| context_recall | numeric(3,2) | 0–1 |
| judge_model | text | |
| evaluated_at | timestamptz | |

## `finetune_jobs`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| base_model | text | |
| dataset_query | jsonb | mining filter used |
| dataset_hash | text | dedupe/reproducibility |
| dataset_size | int | |
| hyperparameters | jsonb | |
| mlflow_run_id | text | |
| fine_tuned_model_ref | text nullable | |
| status | text | `queued`\|`running`\|`evaluating`\|`promoted`\|`rejected`\|`failed` |
| shadow_eval | jsonb | sample_size, deltas vs base |
| created_at / updated_at | timestamptz | |

## Relationships

```
pipelines 1─* documents 1─* chunks
pipelines 1─* queries 1─1 generations 1─1 evaluations
generations *─* chunks   (via context_chunk_ids)
finetune_jobs *─* generations  (via dataset_query, resolved at mining time — not FK-enforced)
```
