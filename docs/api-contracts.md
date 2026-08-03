# NeuroFlow API Contracts

Base URL: `/api/v1`
Auth: Bearer JWT unless noted. Rate limits are per API key unless noted.

---

## `POST /ingest`

Ingest a file or URL.

**Auth:** required
**Rate limit:** 30 req/min per key

**Request body**
```json
{
  "source_type": "file | url",
  "file_ref": "string (object storage key, required if source_type=file)",
  "url": "string (required if source_type=url)",
  "metadata": {
    "source_name": "string",
    "tags": ["string"]
  },
  "pipeline_id": "string (optional, defaults to 'default')"
}
```

**Response `202 Accepted`**
```json
{
  "job_id": "uuid",
  "status": "pending",
  "created_at": "iso8601"
}
```

**Errors**
| Code | Meaning |
|---|---|
| 400 | Missing/invalid `source_type`, unsupported MIME type |
| 401 | Missing/invalid auth |
| 413 | File exceeds max ingest size |
| 429 | Rate limit exceeded |

---

## `POST /query`

Execute a RAG query.

**Auth:** required
**Rate limit:** 60 req/min per key

**Request body**
```json
{
  "query": "string",
  "pipeline_id": "string (optional, defaults to 'default')",
  "filters": {
    "tags": ["string"],
    "date_range": { "from": "iso8601", "to": "iso8601" }
  },
  "conversation_id": "string (optional, for multi-turn)",
  "stream": "boolean (default true)"
}
```

**Response `200 OK`**
```json
{
  "query_id": "uuid",
  "status": "streaming | complete",
  "stream_url": "/query/{query_id}/stream"
}
```

**Errors**
| Code | Meaning |
|---|---|
| 400 | Empty query, invalid filters |
| 401 | Missing/invalid auth |
| 404 | `pipeline_id` not found |
| 429 | Rate limit exceeded |

---

## `GET /query/{query_id}/stream`

SSE stream of generation tokens for a query.

**Auth:** required (same key that created the query, or a scoped share token)
**Rate limit:** n/a (long-lived connection; capped at 1 concurrent stream per `query_id`)

**Response:** `text/event-stream`
```
event: token
data: {"text": "The"}

event: token
data: {"text": " answer"}

event: citation
data: {"chunk_id": "uuid", "doc_id": "uuid", "span": [120, 340]}

event: done
data: {"generation_id": "uuid", "finish_reason": "stop", "usage": {"prompt_tokens": 812, "completion_tokens": 143}}
```

**Errors**
| Code | Meaning |
|---|---|
| 401 | Missing/invalid auth |
| 404 | `query_id` not found or already consumed |
| 410 | Stream expired (generation already completed and archived) |

---

## `GET /evaluations`

Paginated evaluation results.

**Auth:** required
**Rate limit:** 120 req/min per key

**Query params:** `page` (default 1), `page_size` (default 25, max 100), `pipeline_id`, `model`, `from`, `to`, `min_faithfulness`

**Response `200 OK`**
```json
{
  "page": 1,
  "page_size": 25,
  "total": 4213,
  "results": [
    {
      "generation_id": "uuid",
      "query_id": "uuid",
      "model": "string",
      "faithfulness": 0.0,
      "answer_relevance": 0.0,
      "context_precision": 0.0,
      "context_recall": 0.0,
      "user_rating": "integer|null",
      "evaluated_at": "iso8601"
    }
  ]
}
```

**Errors**
| Code | Meaning |
|---|---|
| 400 | Invalid pagination/filter params |
| 401 | Missing/invalid auth |

---

## `GET /evaluations/aggregate`

Rolling quality metrics.

**Auth:** required
**Rate limit:** 60 req/min per key

**Query params:** `window` (`1h`\|`24h`\|`7d`, default `24h`), `pipeline_id` (optional), `model` (optional), `group_by` (`model`\|`pipeline`\|`domain`, optional)

**Response `200 OK`**
```json
{
  "window": "24h",
  "generated_at": "iso8601",
  "aggregates": [
    {
      "group": "gpt-tier-b",
      "count": 1820,
      "avg_faithfulness": 0.0,
      "avg_answer_relevance": 0.0,
      "avg_context_precision": 0.0,
      "avg_context_recall": 0.0,
      "avg_user_rating": 0.0
    }
  ]
}
```

**Errors**
| Code | Meaning |
|---|---|
| 400 | Invalid `window` or `group_by` |
| 401 | Missing/invalid auth |

---

## `POST /pipelines`

Create a named pipeline configuration (chunking strategy, embedding model, retrieval params, default model tier).

**Auth:** required (admin scope)
**Rate limit:** 10 req/min per key

**Request body**
```json
{
  "name": "string",
  "chunking_strategy": "fixed | sentence | semantic",
  "embedding_model": "string",
  "retrieval": { "top_k": 50, "rerank_top_n": 30, "context_window_size": 8 },
  "default_model_tier": "A | B | C"
}
```

**Response `201 Created`**
```json
{
  "pipeline_id": "uuid",
  "name": "string",
  "created_at": "iso8601"
}
```

**Errors**
| Code | Meaning |
|---|---|
| 400 | Invalid config values |
| 401 | Missing/invalid auth |
| 403 | Caller lacks admin scope |
| 409 | Pipeline name already exists |

---

## `GET /pipelines/{id}/runs`

Pipeline execution history (ingestion jobs + queries run against this pipeline).

**Auth:** required
**Rate limit:** 120 req/min per key

**Query params:** `page`, `page_size`, `type` (`ingest`\|`query`, optional)

**Response `200 OK`**
```json
{
  "pipeline_id": "uuid",
  "page": 1,
  "page_size": 25,
  "total": 512,
  "runs": [
    { "run_id": "uuid", "type": "ingest", "status": "complete", "started_at": "iso8601", "finished_at": "iso8601" }
  ]
}
```

**Errors**
| Code | Meaning |
|---|---|
| 401 | Missing/invalid auth |
| 404 | `id` not found |

---

## `POST /finetune/jobs`

Submit a fine-tuning job.

**Auth:** required (admin scope)
**Rate limit:** 5 req/min per key

**Request body**
```json
{
  "base_model": "string",
  "dataset_query": {
    "min_faithfulness": 0.8,
    "min_user_rating": 4,
    "pipeline_id": "string (optional)",
    "domain": "string (optional)",
    "max_examples": 5000
  },
  "hyperparameters": { "epochs": 3, "learning_rate": 0.0001 }
}
```

**Response `202 Accepted`**
```json
{
  "job_id": "uuid",
  "status": "queued",
  "dataset_size": 0,
  "mlflow_run_id": "string",
  "created_at": "iso8601"
}
```

**Errors**
| Code | Meaning |
|---|---|
| 400 | Invalid hyperparameters, `dataset_query` yields zero rows |
| 401 | Missing/invalid auth |
| 403 | Caller lacks admin scope |
| 422 | `base_model` not fine-tunable |

---

## `GET /finetune/jobs/{id}`

Job status and metrics.

**Auth:** required (admin scope)
**Rate limit:** 60 req/min per key

**Response `200 OK`**
```json
{
  "job_id": "uuid",
  "status": "queued | running | evaluating | promoted | rejected | failed",
  "base_model": "string",
  "fine_tuned_model_ref": "string|null",
  "mlflow_run_id": "string",
  "shadow_eval": {
    "sample_size": 0,
    "faithfulness_delta": 0.0,
    "answer_relevance_delta": 0.0
  },
  "created_at": "iso8601",
  "updated_at": "iso8601"
}
```

**Errors**
| Code | Meaning |
|---|---|
| 401 | Missing/invalid auth |
| 403 | Caller lacks admin scope |
| 404 | `id` not found |

---

## `GET /health`

**Auth:** none
**Rate limit:** none

**Response `200 OK`**
```json
{ "status": "ok", "version": "string", "dependencies": { "postgres": "ok", "vector_store": "ok" } }
```

---

## `GET /metrics`

Prometheus-format metrics exposition.

**Auth:** none (network-restricted to internal scrape targets, not public)
**Rate limit:** none

**Response `200 OK`** — `text/plain; version=0.0.4` Prometheus exposition format.
