"use client";

import { useState } from "react";
import { useSSEStream } from "@/hooks/useSSEStream";
import { useRunEvaluation } from "@/hooks/useRunEvaluation";
import { ResponsePanel } from "./ResponsePanel";
import { DiffView } from "./DiffView";
import { EvaluationGauge } from "@/components/shared/EvaluationGauge";

export function ComparePanel({ runIdA, runIdB }: { runIdA: string | null; runIdB: string | null }) {
  const [showDiff, setShowDiff] = useState(false);
  const streamA = useSSEStream(runIdA);
  const streamB = useSSEStream(runIdB);
  const evalA = useRunEvaluation(streamA.status === "done" ? runIdA : null);
  const evalB = useRunEvaluation(streamB.status === "done" ? runIdB : null);

  const bothDone = streamA.status === "done" && streamB.status === "done";

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-4">
        <ResponsePanel runId={runIdA} pipelineLabel="Pipeline A" />
        <ResponsePanel runId={runIdB} pipelineLabel="Pipeline B" />
      </div>

      {bothDone && (
        <div className="flex flex-col gap-4 rounded-xl border border-border bg-surface p-5">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-ink">Comparison</span>
            <button
              onClick={() => setShowDiff((v) => !v)}
              className="rounded-md border border-border px-2.5 py-1 text-xs text-ink-muted transition-colors hover:border-border-strong hover:text-ink"
            >
              {showDiff ? "Hide diff" : "Show diff"}
            </button>
          </div>

          {showDiff && <DiffView textA={streamA.text} textB={streamB.text} />}

          <div className="grid grid-cols-2 gap-6 border-t border-border pt-4">
            <div className="flex gap-4">
              <EvaluationGauge label="Faithfulness" score={evalA?.faithfulness ?? null} />
              <EvaluationGauge label="Relevance" score={evalA?.answer_relevance ?? null} />
              <EvaluationGauge label="Precision" score={evalA?.context_precision ?? null} />
              <EvaluationGauge label="Recall" score={evalA?.context_recall ?? null} />
            </div>
            <div className="flex gap-4">
              <EvaluationGauge label="Faithfulness" score={evalB?.faithfulness ?? null} />
              <EvaluationGauge label="Relevance" score={evalB?.answer_relevance ?? null} />
              <EvaluationGauge label="Precision" score={evalB?.context_precision ?? null} />
              <EvaluationGauge label="Recall" score={evalB?.context_recall ?? null} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
