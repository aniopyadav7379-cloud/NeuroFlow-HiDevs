# NeuroFlow

NeuroFlow is a production-grade Retrieval-Augmented Generation (RAG) platform. It ingests documents from multiple modalities, retrieves and reranks context for user queries, generates grounded LLM responses, continuously evaluates output quality, and closes the loop by fine-tuning on its own high-quality generations.

This repository captures the **full system design** before implementation begins. Every subsequent task builds on the contracts and decisions frozen here.

## Subsystems

| Subsystem | Responsibility |
|---|---|
| Ingestion | Multi-modal file/URL intake → extraction → chunking → embedding → vector store |
| Retrieval | Hybrid search (vector + keyword + metadata) → RRF fusion → cross-encoder rerank |
| Generation | Prompt assembly → model routing → streamed response → I/O logging |
| Evaluation | Async LLM-as-judge scoring (faithfulness, relevance, context precision/recall) |
| Fine-Tuning | Mines high-quality (query, context, answer) triples → JSONL → fine-tune job → MLflow tracking → champion/challenger routing |

## Repo layout

```
NeuroFlow-HiDevs/
├── backend/          # API service (FastAPI) implementing api-contracts.md
├── frontend/         # Query UI / evaluation dashboard
├── pipelines/         # Ingestion, retrieval, fine-tune job orchestration code
├── evaluation/        # LLM-as-judge scorers, aggregation jobs
├── infra/             # Docker, migrations, deployment configs
├── docs/
│   ├── architecture.md      # Subsystem design + data flow diagrams
│   ├── api-contracts.md     # Full REST API spec
│   ├── data-models.md       # Postgres schema / pgvector tables
│   └── adr/                 # Architecture Decision Records
└── .gitignore
```

## Status

Design phase (Task 31). No production code yet — see `docs/` for the frozen contracts that all 19 downstream tasks implement against.

## Stack (locked by ADRs)

- **Vector store:** PostgreSQL + pgvector (see `adr/001-vector-store.md`)
- **Chunking:** hybrid sentence-boundary/semantic (see `adr/002-chunking-strategy.md`)
- **Evaluation:** LLM-as-judge, async (see `adr/003-evaluation-framework.md`)
- **Model routing:** cost/latency/capability/domain matrix (see `adr/004-model-routing.md`)
