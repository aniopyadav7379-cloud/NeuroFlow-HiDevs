# ADR 002: Chunking Strategy — fixed-size vs sentence-boundary vs semantic

## Context

Chunk boundaries directly determine retrieval quality: too coarse and irrelevant text dilutes the embedding and wastes context budget; too fine and chunks lose the surrounding meaning needed for faithful answers. Three approaches:

- **Fixed-size** — split every N tokens/characters with overlap. Fast, deterministic, ignores document structure; can cut sentences and arguments mid-thought.
- **Sentence-boundary** — split on sentence boundaries, group into chunks up to a token budget. Respects grammar, still ignores topical structure — a chunk can span an unrelated sentence pair.
- **Semantic** — embed sentences, group by embedding similarity (or use structural cues like headings) so each chunk is topically coherent. Best coherence, most compute-expensive and slowest to run at ingestion time, and coherence detection is imperfect on noisy text (OCR output, spreadsheets).

## Decision

Use a **hybrid: sentence-boundary chunking as the default, with semantic chunking applied where document structure signals are strong or weak lexical density would otherwise degrade retrieval.**

Concretely:
- **Default (most documents):** sentence-boundary chunking with a target size (~250–400 tokens) and small overlap (~15%), splitting additionally on structural boundaries (headings, paragraph breaks) when present — this is `pipelines.chunking_strategy = 'sentence'`.
- **Switch to semantic chunking when:**
  - the source is long-form, low-structure prose (e.g. legal contracts, narrative reports) where topic shifts don't align with paragraph breaks, and faithfulness/context-precision evals for that pipeline are measurably lower than the sentence-boundary baseline; or
  - the pipeline owner explicitly configures `chunking_strategy = 'semantic'` for a known-hard domain.
- **Fixed-size is not used as a default** anywhere; it's retained only as a fallback for content where sentence segmentation fails outright (e.g. malformed OCR text with no reliable sentence boundaries, raw CSV row text) — `chunking_strategy = 'fixed'` in that narrow case.

## Consequences

- **Positive:** sentence-boundary chunking is cheap and predictable at ingestion time, which keeps the Ingestion Subsystem's latency and cost bounded for the common case, while semantic chunking is available as an opt-in upgrade exactly where the Evaluation Subsystem's context-precision/recall scores justify the extra cost.
- **Negative:** running two chunking code paths adds complexity, and the "switch when evals are measurably lower" trigger requires enough evaluation history on a pipeline before the decision can be made — new pipelines start on the sentence-boundary default with no data-driven overrides.
- **Follow-up:** the fine-tuning subsystem's dataset mining should track `chunking_strategy` as a feature so that faithfulness gains from semantic chunking (if any) are visible in aggregate evals, giving a concrete signal for promoting more pipelines to semantic chunking over time.
