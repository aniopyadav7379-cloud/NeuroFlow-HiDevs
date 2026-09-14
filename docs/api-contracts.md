# API Contracts

## 1. Ingest
- **Endpoint:** `POST /ingest`
- **Description:** File or URL ingestion.
- **Request Body:**
  ```json
  {
    "source_uri": "https://example.com/doc.pdf",
    "modality": "pdf",
    "metadata": {
      "author": "John Doe",
      "tags": ["research", "ai"]
    }
  }
  ```
- **Response Body:**
  ```json
  {
    "document_id": "uuid",
    "status": "processing",
    "message": "Ingestion started."
  }
  ```
- **Error Codes:** `400 Bad Request`, `415 Unsupported Media Type`, `500 Internal Error`
- **Auth:** Bearer Token required.
- **Rate Limit:** 50 requests / minute.

## 2. Query
- **Endpoint:** `POST /query`
- **Description:** RAG query execution.
- **Request Body:**
  ```json
  {
    "query_text": "What is the chunking strategy?",
    "filters": {
      "tags": ["architecture"]
    }
  }
  ```
- **Response Body:**
  ```json
  {
    "query_id": "uuid",
    "response": "The chunking strategy used is...",
    "context_sources": ["chunk_uuid_1", "chunk_uuid_2"]
  }
  ```
- **Error Codes:** `400 Bad Request`, `401 Unauthorized`
- **Auth:** Bearer Token required.
- **Rate Limit:** 100 requests / minute.

## 3. Stream Query
- **Endpoint:** `GET /query/{query_id}/stream`
- **Description:** SSE stream for generation.
- **Request Body:** N/A (Path Parameter)
- **Response Body:** Server-Sent Events (SSE) stream of text tokens.
- **Error Codes:** `404 Not Found`, `401 Unauthorized`
- **Auth:** Bearer Token required.
- **Rate Limit:** 100 streams / minute.

## 4. Get Evaluations
- **Endpoint:** `GET /evaluations`
- **Description:** Paginated evaluation results.
- **Request Body:** N/A (Query Params: `page`, `limit`)
- **Response Body:**
  ```json
  {
    "data": [
      {
        "evaluation_id": "uuid",
        "query_id": "uuid",
        "faithfulness": 0.9,
        "answer_relevance": 0.85
      }
    ],
    "meta": {
      "page": 1,
      "total": 100
    }
  }
  ```
- **Error Codes:** `401 Unauthorized`, `403 Forbidden`
- **Auth:** Admin Bearer Token required.
- **Rate Limit:** 200 requests / minute.

## 5. Get Evaluation Aggregates
- **Endpoint:** `GET /evaluations/aggregate`
- **Description:** Rolling quality metrics.
- **Request Body:** N/A (Query Params: `time_window`)
- **Response Body:**
  ```json
  {
    "time_window": "7d",
    "average_faithfulness": 0.88,
    "average_relevance": 0.91,
    "total_queries": 5000
  }
  ```
- **Error Codes:** `401 Unauthorized`, `403 Forbidden`
- **Auth:** Admin Bearer Token required.
- **Rate Limit:** 100 requests / minute.

## 6. Create Pipeline
- **Endpoint:** `POST /pipelines`
- **Description:** Create named pipeline configuration.
- **Request Body:**
  ```json
  {
    "name": "Daily Ingestion",
    "schedule": "0 0 * * *",
    "config": {
      "chunk_size": 512,
      "embedding_model": "text-embedding-3-small"
    }
  }
  ```
- **Response Body:**
  ```json
  {
    "pipeline_id": "uuid",
    "status": "created"
  }
  ```
- **Error Codes:** `400 Bad Request`, `401 Unauthorized`
- **Auth:** Admin Bearer Token required.
- **Rate Limit:** 10 requests / minute.

## 7. Get Pipeline Runs
- **Endpoint:** `GET /pipelines/{id}/runs`
- **Description:** Pipeline execution history.
- **Request Body:** N/A
- **Response Body:**
  ```json
  {
    "pipeline_id": "uuid",
    "runs": [
      {
        "run_id": "uuid",
        "status": "success",
        "duration_seconds": 120,
        "started_at": "timestamp"
      }
    ]
  }
  ```
- **Error Codes:** `404 Not Found`, `401 Unauthorized`
- **Auth:** Bearer Token required.
- **Rate Limit:** 100 requests / minute.

## 8. Submit Fine-Tune Job
- **Endpoint:** `POST /finetune/jobs`
- **Description:** Submit fine-tuning job.
- **Request Body:**
  ```json
  {
    "base_model": "llama-3-8b",
    "dataset_filters": {
      "min_faithfulness": 0.8,
      "min_user_rating": 4
    }
  }
  ```
- **Response Body:**
  ```json
  {
    "job_id": "uuid",
    "status": "queued"
  }
  ```
- **Error Codes:** `400 Bad Request`, `401 Unauthorized`, `403 Forbidden`
- **Auth:** Admin Bearer Token required.
- **Rate Limit:** 5 requests / minute.

## 9. Get Fine-Tune Job
- **Endpoint:** `GET /finetune/jobs/{id}`
- **Description:** Job status and metrics.
- **Request Body:** N/A
- **Response Body:**
  ```json
  {
    "job_id": "uuid",
    "status": "running",
    "metrics": {
      "loss": 0.15,
      "step": 500
    }
  }
  ```
- **Error Codes:** `404 Not Found`, `401 Unauthorized`
- **Auth:** Admin Bearer Token required.
- **Rate Limit:** 60 requests / minute.

## 10. Health
- **Endpoint:** `GET /health`
- **Description:** System health check.
- **Request Body:** N/A
- **Response Body:**
  ```json
  {
    "status": "ok",
    "services": {
      "database": "up",
      "vector_store": "up"
    }
  }
  ```
- **Error Codes:** `503 Service Unavailable`
- **Auth:** None.
- **Rate Limit:** 1000 requests / minute.

## 11. Metrics
- **Endpoint:** `GET /metrics`
- **Description:** Prometheus metrics exposition.
- **Request Body:** N/A
- **Response Body:** Text-based Prometheus metrics format.
- **Error Codes:** `401 Unauthorized`
- **Auth:** Internal/Network restricted.
- **Rate Limit:** 60 requests / minute.
