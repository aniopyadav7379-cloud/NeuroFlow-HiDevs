# ADR 001: Vector Store Selection

**Context**  
NeuroFlow requires a highly scalable, robust vector store to support embedding similarity search, metadata filtering, and integration with standard relational data. The options considered were pgvector (PostgreSQL extension), Pinecone, Weaviate, and Qdrant. NeuroFlow must also store significant structured data (evaluations, document metadata, logs) alongside the vectors.

**Decision**  
We will use **pgvector** as the primary vector store for NeuroFlow.

**Consequences**  
- **Pros:** 
  - Allows us to keep structured metadata and vector embeddings in the same database (PostgreSQL), drastically simplifying our architecture.
  - ACID compliance for ingestion transactions (e.g., chunk writes succeed or fail together with document metadata).
  - Reduced operational overhead and no external SaaS lock-in compared to Pinecone.
- **Cons:** 
  - pgvector's HNSW implementation is slightly less performant at massive scales (100M+ vectors) compared to dedicated vector databases like Qdrant. 
  - Requires careful index tuning to maintain high QPS during concurrent writes and reads. If we hit limits, we may need to separate read/write workloads or migrate later.
