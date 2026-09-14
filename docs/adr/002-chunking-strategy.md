# ADR 002: Chunking Strategy

**Context**  
Before generating an embedding, documents must be split into chunks. The strategy used affects retrieval context precision and recall. Options include fixed-size chunking (e.g., 512 tokens), sentence-boundary chunking, and semantic chunking (splitting based on embedding similarity shifts).

**Decision**  
We will start with **sentence-boundary chunking** with overlapping windows (e.g., 3-5 sentences per chunk, 1 sentence overlap).

**Consequences**  
- **Pros:**
  - Fast to execute during ingestion and computationally cheaper than semantic chunking.
  - Prevents the "cut-off sentence" problem inherent in pure fixed-size chunking, which often degrades embedding quality.
  - Overlap ensures context is maintained across chunk boundaries.
- **Cons:**
  - May still clump disparate concepts together if a paragraph shifts topics abruptly.
- **Fallback/Evolution:** We will monitor the Context Precision evaluation metric. If Context Precision drops below 0.7 for complex documents (like research papers), we will switch to **semantic chunking** for those specific document modalities, incurring the extra latency cost during ingestion for improved retrieval quality.
