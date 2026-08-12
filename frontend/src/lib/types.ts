// Mirrors backend/models/pipeline.py and the API response shapes from
// backend/api/{pipelines,query,runs,evaluations,ingest}.py. Kept as a
// single file since the backend doesn't (yet) publish an OpenAPI-derived
// client — these are hand-written to match the Pydantic models.

export type ChunkingStrategy = "fixed_size" | "semantic" | "hierarchical";
export type RerankerChoice = "cross-encoder" | "local-cross-encoder" | "none";
export type PromptVariant = "precise" | "balanced" | "creative";
export type PipelineStatus = "active" | "archived";

export interface IngestionConfig {
  chunking_strategy: ChunkingStrategy;
  chunk_size_tokens: number;
  chunk_overlap_tokens: number;
  extractors_enabled: string[];
}

export interface RetrievalConfig {
  dense_k: number;
  sparse_k: number;
  reranker: RerankerChoice;
  top_k_after_rerank: number;
  query_expansion: boolean;
  metadata_filters_enabled: boolean;
}

export interface ModelRoutingConfig {
  task_type: string;
  max_cost_per_call: number | null;
}

export interface GenerationConfig {
  model_routing: ModelRoutingConfig;
  max_context_tokens: number;
  temperature: number;
  system_prompt_variant: PromptVariant;
}

export interface EvaluationConfig {
  auto_evaluate: boolean;
  training_threshold: number;
}

export interface PipelineConfig {
  name: string;
  description?: string | null;
  rate_limit_rpm?: number | null;
  ingestion: IngestionConfig;
  retrieval: RetrievalConfig;
  generation: GenerationConfig;
  evaluation: EvaluationConfig;
}

export interface PipelineSummary {
  pipeline_id: string;
  name: string;
  description: string | null;
  status: PipelineStatus;
  current_version: number;
  created_at: string;
  last_run: {
    run_id: string;
    created_at: string;
    latency_ms: number | null;
    status: string;
    eval_score: number | null;
  } | null;
}

export interface PipelineDetail {
  pipeline_id: string;
  name: string;
  description: string | null;
  status: PipelineStatus;
  current_version: number;
  config: PipelineConfig;
  created_at: string;
  aggregate_evaluation: AggregateEvaluation;
}

export interface AggregateEvaluation {
  n_evaluations: number;
  avg_overall_score: number | null;
  avg_faithfulness: number | null;
  avg_answer_relevance: number | null;
  avg_context_precision: number | null;
  avg_context_recall: number | null;
}

export interface PipelineAnalytics {
  pipeline_id: string;
  n_runs: number;
  retrieval_latency_ms: LatencyStats;
  generation_latency_ms: LatencyStats;
  evaluation_scores: AggregateEvaluation;
  token_totals: { input_tokens: number | null; output_tokens: number | null };
  queries_per_day_last_30d: { date: string; count: number }[];
}

export interface LatencyStats {
  p50: number | null;
  p95: number | null;
  p99: number | null;
  avg: number | null;
}

export interface PipelineRunSummary {
  run_id: string;
  query: string;
  pipeline_version: number | null;
  status: string;
  latency_ms: number | null;
  retrieval_latency_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  model_used: string | null;
  created_at: string;
  evaluation: EvaluationScores | null;
}

export interface EvaluationScores {
  overall_score: number;
  faithfulness: number;
  answer_relevance: number;
  context_precision: number;
  context_recall: number;
}

export interface Citation {
  source: string;
  chunk_id: string | null;
  document: string | null;
  page: number | null;
  invalid_citation?: boolean;
}

export interface QueryResponse {
  run_id: string;
  generation: string;
  citations: Citation[];
  sources: string[];
  chunk_count: number;
}

export interface QueuedResponse {
  run_id: string;
  status: string;
}

// SSE event shapes from GET /query/{run_id}/stream
export type StreamEvent =
  | { type: "retrieval_start" }
  | { type: "retrieval_complete"; chunk_count: number; sources: string[] }
  | { type: "token"; delta: string }
  | { type: "done"; run_id: string; citations: Citation[] }
  | { type: "error"; message: string }
  | { type: "keepalive" };

export interface EvaluationFeedItem {
  run_id: string;
  pipeline_id: string;
  pipeline_name: string;
  query: string;
  overall_score: number;
  faithfulness: number;
  answer_relevance: number;
  context_precision: number;
  context_recall: number;
  evaluated_at: string;
}

export type DocumentStatus = "queued" | "processing" | "complete" | "failed";

export interface DocumentSummary {
  document_id: string;
  filename: string;
  source_type: string;
  status: DocumentStatus;
  chunk_count: number | null;
  metadata: Record<string, unknown>;
  created_at: string;
}
