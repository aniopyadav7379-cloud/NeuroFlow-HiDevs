"use client";

import { useState } from "react";
import { usePlaygroundStore } from "@/store/playgroundStore";
import { PipelineSelector } from "@/components/playground/PipelineSelector";
import { QueryInput } from "@/components/playground/QueryInput";
import { ResponsePanel } from "@/components/playground/ResponsePanel";
import { ComparePanel } from "@/components/playground/ComparePanel";
import { submitQuery } from "@/lib/api";

export default function PlaygroundPage() {
  const {
    pipelineAId, pipelineBId, compareMode, query,
    setPipelineA, setPipelineB, setCompareMode, setQuery,
  } = usePlaygroundStore();

  const [runIdA, setRunIdA] = useState<string | null>(null);
  const [runIdB, setRunIdB] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const canSubmit = query.trim().length > 0 && pipelineAId && (!compareMode || pipelineBId) && !submitting;

  const handleSubmit = async () => {
    if (!canSubmit || !pipelineAId) return;
    setSubmitting(true);
    setRunIdA(null);
    setRunIdB(null);
    try {
      const resA = await submitQuery(pipelineAId, query, true);
      setRunIdA("run_id" in resA ? resA.run_id : null);
      if (compareMode && pipelineBId) {
        const resB = await submitQuery(pipelineBId, query, true);
        setRunIdB("run_id" in resB ? resB.run_id : null);
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl px-8 py-10">
      <h1 className="text-lg font-semibold text-ink">Query Playground</h1>
      <p className="mt-1 text-sm text-ink-muted">Run a query against a pipeline and watch it think.</p>

      <div className="mt-6 flex flex-col gap-4 rounded-xl border border-border bg-surface p-5 shadow-panel">
        <div className={`grid gap-4 ${compareMode ? "grid-cols-2" : "grid-cols-1"}`}>
          <PipelineSelector value={pipelineAId} onChange={setPipelineA} label={compareMode ? "Pipeline A" : "Pipeline"} />
          {compareMode && <PipelineSelector value={pipelineBId} onChange={setPipelineB} label="Pipeline B" />}
        </div>

        <QueryInput value={query} onChange={setQuery} compareMode={compareMode} onCompareModeChange={setCompareMode} />

        <button
          onClick={handleSubmit}
          disabled={!canSubmit}
          className="self-start rounded-lg bg-accent px-4 py-2 text-sm font-medium text-canvas transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {submitting ? "Submitting…" : "Run query"}
        </button>
      </div>

      <div className="mt-6">
        {compareMode ? (
          <ComparePanel runIdA={runIdA} runIdB={runIdB} />
        ) : (
          <ResponsePanel runId={runIdA} />
        )}
      </div>
    </div>
  );
}
