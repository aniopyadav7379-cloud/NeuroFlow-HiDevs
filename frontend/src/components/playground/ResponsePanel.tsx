"use client";

import { useState } from "react";
import { useSSEStream } from "@/hooks/useSSEStream";
import { useRunEvaluation } from "@/hooks/useRunEvaluation";
import { CitationChip, CitationDrawer } from "./CitationDrawer";
import { EvaluationGauge } from "@/components/shared/EvaluationGauge";
import { FeedbackButtons } from "./FeedbackButtons";
import type { Citation } from "@/lib/types";

export function ResponsePanel({ runId, pipelineLabel }: { runId: string | null; pipelineLabel?: string }) {
  const stream = useSSEStream(runId);
  const evaluation = useRunEvaluation(stream.status === "done" ? runId : null);
  const [openCitation, setOpenCitation] = useState<Citation | null>(null);

  if (!runId) {
    return (
      <div className="flex h-full min-h-[240px] items-center justify-center rounded-xl border border-dashed border-border text-sm text-ink-faint">
        Run a query to see results here
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border bg-surface p-5 shadow-panel">
      {pipelineLabel && (
        <div className="text-xs font-medium uppercase tracking-wider text-ink-faint">{pipelineLabel}</div>
      )}

      {/* retrieval status, shown BEFORE the answer starts streaming */}
      <div className="flex items-center gap-2 text-xs text-ink-muted">
        {stream.status === "retrieving" && (
          <>
            <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-accent" />
            Retrieving relevant sources…
          </>
        )}
        {(stream.status === "streaming" || stream.status === "done") && stream.sources.length > 0 && (
          <>
            <span className="h-1.5 w-1.5 rounded-full bg-accent" />
            {stream.chunkCount} chunks from {stream.sources.length} source
            {stream.sources.length === 1 ? "" : "s"}: {stream.sources.join(", ")}
          </>
        )}
        {stream.status === "error" && <span className="text-score-bad">{stream.errorMessage}</span>}
      </div>

      {/* streamed answer */}
      <div className="min-h-[80px] whitespace-pre-wrap text-[15px] leading-relaxed text-ink">
        {stream.text}
        {stream.status === "streaming" && (
          <span className="ml-0.5 inline-block h-4 w-[7px] translate-y-0.5 animate-pulse-dot bg-accent" />
        )}
      </div>

      {/* citations */}
      {stream.citations.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {stream.citations.map((c) => (
            <CitationChip key={c.source} citation={c} onClick={() => setOpenCitation(c)} />
          ))}
        </div>
      )}

      {/* evaluation gauges — appear once evaluation lands (typically a
          couple seconds after generation finishes, per the async
          evaluation pipeline) */}
      {stream.status === "done" && (
        <div className="flex items-center justify-between border-t border-border pt-4">
          <div className="flex gap-5">
            <EvaluationGauge label="Faithfulness" score={evaluation?.faithfulness ?? null} />
            <EvaluationGauge label="Relevance" score={evaluation?.answer_relevance ?? null} />
            <EvaluationGauge label="Precision" score={evaluation?.context_precision ?? null} />
            <EvaluationGauge label="Recall" score={evaluation?.context_recall ?? null} />
          </div>
          <FeedbackButtons runId={runId} />
        </div>
      )}

      <CitationDrawer citation={openCitation} onClose={() => setOpenCitation(null)} />
    </div>
  );
}
