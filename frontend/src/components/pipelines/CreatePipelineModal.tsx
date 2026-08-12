"use client";

import { useState } from "react";
import Editor from "@monaco-editor/react";
import { createPipeline } from "@/lib/api";

const DEFAULT_CONFIG = {
  name: "new-pipeline",
  description: "",
  ingestion: {
    chunking_strategy: "fixed_size",
    chunk_size_tokens: 512,
    chunk_overlap_tokens: 64,
    extractors_enabled: ["pdf", "docx", "image", "csv", "url"],
  },
  retrieval: {
    dense_k: 20,
    sparse_k: 20,
    reranker: "cross-encoder",
    top_k_after_rerank: 8,
    query_expansion: true,
    metadata_filters_enabled: true,
  },
  generation: {
    model_routing: { task_type: "rag_generation", max_cost_per_call: null },
    max_context_tokens: 4000,
    temperature: 0.2,
    system_prompt_variant: "balanced",
  },
  evaluation: { auto_evaluate: true, training_threshold: 0.8 },
};

// Mirrors backend/models/pipeline.py's PipelineConfig for inline
// validation feedback before the request round-trip — Monaco's JSON
// schema mode gives free inline errors (unknown keys, wrong types,
// enum violations) without duplicating pydantic's logic in JS.
const PIPELINE_CONFIG_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["name"],
  properties: {
    name: { type: "string", minLength: 1, maxLength: 200 },
    description: { type: ["string", "null"] },
    rate_limit_rpm: { type: ["integer", "null"], exclusiveMinimum: 0 },
    ingestion: {
      type: "object",
      additionalProperties: false,
      properties: {
        chunking_strategy: { enum: ["fixed_size", "semantic", "hierarchical"] },
        chunk_size_tokens: { type: "integer", exclusiveMinimum: 0, maximum: 8192 },
        chunk_overlap_tokens: { type: "integer", minimum: 0 },
        extractors_enabled: {
          type: "array",
          items: { enum: ["pdf", "docx", "image", "csv", "url", "pptx"] },
        },
      },
    },
    retrieval: {
      type: "object",
      additionalProperties: false,
      properties: {
        dense_k: { type: "integer", exclusiveMinimum: 0, maximum: 200 },
        sparse_k: { type: "integer", exclusiveMinimum: 0, maximum: 200 },
        reranker: { enum: ["cross-encoder", "local-cross-encoder", "none"] },
        top_k_after_rerank: { type: "integer", exclusiveMinimum: 0, maximum: 100 },
        query_expansion: { type: "boolean" },
        metadata_filters_enabled: { type: "boolean" },
      },
    },
    generation: {
      type: "object",
      additionalProperties: false,
      properties: {
        model_routing: {
          type: "object",
          additionalProperties: false,
          properties: {
            task_type: { type: "string" },
            max_cost_per_call: { type: ["number", "null"], minimum: 0 },
          },
        },
        max_context_tokens: { type: "integer", exclusiveMinimum: 0 },
        temperature: { type: "number", minimum: 0, maximum: 2 },
        system_prompt_variant: { enum: ["precise", "balanced", "creative"] },
      },
    },
    evaluation: {
      type: "object",
      additionalProperties: false,
      properties: {
        auto_evaluate: { type: "boolean" },
        training_threshold: { type: "number", minimum: 0, maximum: 1 },
      },
    },
  },
};

export function CreatePipelineModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [text, setText] = useState(JSON.stringify(DEFAULT_CONFIG, null, 2));
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [hasMarkerErrors, setHasMarkerErrors] = useState(false);

  const handleCreate = async () => {
    setError(null);
    let parsed;
    try {
      parsed = JSON.parse(text);
    } catch {
      setError("Invalid JSON — fix syntax errors before creating.");
      return;
    }
    if (hasMarkerErrors) {
      setError("Config doesn't match the pipeline schema — see the inline red squiggles.");
      return;
    }
    setSubmitting(true);
    try {
      await createPipeline(parsed);
      onCreated();
      onClose();
    } catch (e: unknown) {
      const message =
        e && typeof e === "object" && "response" in e
          ? JSON.stringify((e as { response?: { data?: unknown } }).response?.data)
          : "Failed to create pipeline";
      setError(message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-8">
      <div className="flex h-full max-h-[720px] w-full max-w-2xl flex-col rounded-xl border border-border bg-surface shadow-panel">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <span className="text-sm font-medium text-ink">New pipeline config</span>
          <button onClick={onClose} className="text-ink-faint hover:text-ink">
            ✕
          </button>
        </div>

        <div className="flex-1 overflow-hidden">
          <Editor
            height="100%"
            defaultLanguage="json"
            theme="vs-dark"
            value={text}
            onChange={(v) => setText(v ?? "")}
            path="pipeline-config.json"
            onValidate={(markers) => setHasMarkerErrors(markers.some((m) => m.severity === 8))}
            beforeMount={(monaco) => {
              monaco.languages.json.jsonDefaults.setDiagnosticsOptions({
                validate: true,
                schemas: [
                  {
                    uri: "https://neuroflow.internal/pipeline-config-schema.json",
                    fileMatch: ["pipeline-config.json"],
                    schema: PIPELINE_CONFIG_SCHEMA,
                  },
                ],
              });
            }}
            options={{ minimap: { enabled: false }, fontSize: 13 }}
          />
        </div>

        {error && (
          <div className="border-t border-border bg-score-bad/10 px-5 py-2 text-xs text-score-bad">{error}</div>
        )}

        <div className="flex justify-end gap-2 border-t border-border px-5 py-3">
          <button onClick={onClose} className="rounded-md px-3 py-1.5 text-sm text-ink-muted hover:text-ink">
            Cancel
          </button>
          <button
            onClick={handleCreate}
            disabled={submitting}
            className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-canvas hover:opacity-90 disabled:opacity-40"
          >
            {submitting ? "Creating…" : "Create pipeline"}
          </button>
        </div>
      </div>
    </div>
  );
}
