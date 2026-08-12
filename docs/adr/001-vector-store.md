# ADR 001: Vector Store — pgvector over Pinecone, Weaviate, Qdrant

## Context

NeuroFlow needs a vector store for similarity search over chunk embeddings, alongside relational storage for documents, jobs, evaluations, and fine-tune metadata. The candidates:

- **Pinecone** — managed, purpose-built ANN service, no self-hosting.
- **Weaviate** — dedicated vector DB, hybrid search built in, more operational surface.
- **Qdrant** — dedicated vector DB, strong filtering, also a separate service to run/scale.
- **pgvector** — a Postgres extension; vectors live in the same database as everything else.

NeuroFlow's retrieval pipeline already does keyword search (Postgres full-text) and metadata filtering (structured columns) alongside vector search, and joins evaluation/generation data against retrieved chunks for scoring and fine-tune mining. This is a relational-heavy workload with a vector-search component, not a pure vector-search workload.

## Decision

Use **PostgreSQL + pgvector** as the single datastore for documents, chunks/embeddings, pipelines, queries, generations, evaluations, and fine-tune jobs.

Reasons:
- **One database, one transaction boundary.** Chunk write + embedding write + full-text index update happen atomically (Ingestion Subsystem §1). A separate vector service would require distributed transactions or eventual consistency between the vector store and Postgres metadata — directly risking the "never expose partial ingestion" guarantee.
- **Hybrid search is native.** Vector similarity (`pgvector`), full-text (`tsvector`), and metadata filters (SQL `WHERE`) all run in the same query engine, which simplifies the RRF fusion step — no cross-service score reconciliation.
- **Joins for evaluation and fine-tune mining.** Evaluation aggregation and fine-tune dataset mining are SQL joins across `generations`, `evaluations`, and `chunks`. Keeping vectors in Postgres avoids fan-out lookups to an external vector API for every mining/aggregation query.
- **Operational simplicity for current scale.** One managed Postgres instance (with read replicas as needed) is less operational surface than Postgres + a separate vector service, and this project's scale (single-tenant, moderate document volume) doesn't yet demand Pinecone/Weaviate/Qdrant's specialized ANN scaling.

## Consequences

- **Positive:** simpler ops, atomic writes, native hybrid search, straightforward analytics joins, no vendor lock-in to a proprietary vector API.
- **Negative:** pgvector's ANN indexes (`ivfflat`/`hnsw`) don't match dedicated vector DBs at very large scale (tens of millions+ of vectors) or under very high QPS — recall/latency tradeoffs get harder to tune.
- **Mitigation / switch trigger:** if chunk volume or query throughput outgrows what a well-tuned pgvector `hnsw` index + read replicas can serve within latency SLA, re-evaluate a dedicated vector store (Qdrant first choice, for its filtering parity with the current metadata-filter design) and migrate only the `chunks.embedding` column out, keeping everything else in Postgres.
