import axios from "axios";
import type {
  DocumentSummary,
  PipelineAnalytics,
  PipelineConfig,
  PipelineDetail,
  PipelineRunSummary,
  PipelineSummary,
  QueryResponse,
  QueuedResponse,
} from "./types";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export const api = axios.create({ baseURL: API_BASE_URL });

// ── pipelines ────────────────────────────────────────────────────────
export async function listPipelines(): Promise<PipelineSummary[]> {
  const { data } = await api.get<{ pipelines: PipelineSummary[] }>("/pipelines");
  return data.pipelines;
}

export async function getPipeline(pipelineId: string): Promise<PipelineDetail> {
  const { data } = await api.get<PipelineDetail>(`/pipelines/${pipelineId}`);
  return data;
}

export async function createPipeline(config: PipelineConfig): Promise<{ pipeline_id: string }> {
  const { data } = await api.post<{ pipeline_id: string }>("/pipelines", config);
  return data;
}

export async function updatePipeline(pipelineId: string, config: PipelineConfig) {
  const { data } = await api.patch(`/pipelines/${pipelineId}`, config);
  return data;
}

export async function deletePipeline(pipelineId: string) {
  await api.delete(`/pipelines/${pipelineId}`);
}

export async function getPipelineRuns(pipelineId: string, page = 1): Promise<{ runs: PipelineRunSummary[]; total: number }> {
  const { data } = await api.get(`/pipelines/${pipelineId}/runs`, { params: { page } });
  return data;
}

export async function getPipelineAnalytics(pipelineId: string): Promise<PipelineAnalytics> {
  const { data } = await api.get<PipelineAnalytics>(`/pipelines/${pipelineId}/analytics`);
  return data;
}

export interface PipelineSuggestion {
  metric: string;
  current_value: number | null;
  config_path: string;
  current_config_value: unknown;
  suggested_config_value: unknown;
  reason: string;
}

export async function getPipelineSuggestions(pipelineId: string): Promise<PipelineSuggestion[]> {
  const { data } = await api.get<{ suggestions: PipelineSuggestion[] }>(`/pipelines/${pipelineId}/suggestions`);
  return data.suggestions;
}

// ── query / generation ──────────────────────────────────────────────
export async function submitQuery(pipelineId: string, query: string, stream: boolean): Promise<QueuedResponse | QueryResponse> {
  const { data } = await api.post("/query", { pipeline_id: pipelineId, query, stream });
  return data;
}

export async function compareQuery(query: string, pipelineAId: string, pipelineBId: string) {
  const { data } = await api.post("/pipelines/compare", {
    query,
    pipeline_a_id: pipelineAId,
    pipeline_b_id: pipelineBId,
  });
  return data;
}

export async function rateRun(runId: string, rating: number) {
  const { data } = await api.patch(`/runs/${runId}/rating`, { rating });
  return data;
}

// ── documents ────────────────────────────────────────────────────────
export async function listDocuments(): Promise<DocumentSummary[]> {
  // NOTE: backend/api/ingest.py exposes GET /documents/{id} (single doc)
  // but no list-all-documents endpoint yet. This calls a conventional
  // GET /documents and expects a `{documents: [...]}` shape — the
  // backend needs a matching route added; the frontend is written
  // against the API contract this page needs, documented here rather
  // than silently fabricating data client-side.
  const { data } = await api.get<{ documents: DocumentSummary[] }>("/documents");
  return data.documents;
}

export async function getDocument(documentId: string): Promise<DocumentSummary> {
  const { data } = await api.get<DocumentSummary>(`/documents/${documentId}`);
  return data;
}

export async function uploadDocument(file: File, onProgress?: (pct: number) => void) {
  const form = new FormData();
  form.append("file", file);
  const { data } = await api.post("/ingest", form, {
    headers: { "Content-Type": "multipart/form-data" },
    onUploadProgress: (evt) => {
      if (onProgress && evt.total) onProgress(Math.round((evt.loaded / evt.total) * 100));
    },
  });
  return data;
}
