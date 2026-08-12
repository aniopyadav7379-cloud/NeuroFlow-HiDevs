"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { ScoreBadge } from "@/components/shared/ScoreBadge";
import type { EvaluationFeedItem } from "@/lib/types";

function MetricBar({ label, value }: { label: string; value: number }) {
  const color = value > 0.8 ? "#34D399" : value >= 0.6 ? "#FBBF24" : "#F87171";
  return (
    <div className="flex items-center gap-2">
      <span className="w-16 shrink-0 text-[10px] text-ink-faint">{label}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-raised">
        <div className="h-full rounded-full" style={{ width: `${value * 100}%`, backgroundColor: color }} />
      </div>
      <span className="w-8 shrink-0 text-right font-mono text-[10px] text-ink-muted">{value.toFixed(2)}</span>
    </div>
  );
}

export function EvaluationCard({ item }: { item: EvaluationFeedItem }) {
  const [expanded, setExpanded] = useState(false);
  const { data: runDetail } = useQuery({
    queryKey: ["run", item.run_id],
    queryFn: async () => (await api.get(`/runs/${item.run_id}`)).data,
    enabled: expanded,
  });

  return (
    <div className="rounded-xl border border-border bg-surface p-4 shadow-panel">
      <button className="flex w-full items-start justify-between text-left" onClick={() => setExpanded((v) => !v)}>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm text-ink">{item.query}</div>
          <div className="mt-0.5 flex items-center gap-2 text-[11px] text-ink-faint">
            <span>{item.pipeline_name}</span>
            <span>·</span>
            <time>{new Date(item.evaluated_at).toLocaleTimeString()}</time>
          </div>
        </div>
        <ScoreBadge score={item.overall_score} />
      </button>

      <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5">
        <MetricBar label="Faithful." value={item.faithfulness} />
        <MetricBar label="Relevance" value={item.answer_relevance} />
        <MetricBar label="Precision" value={item.context_precision} />
        <MetricBar label="Recall" value={item.context_recall} />
      </div>

      {expanded && (
        <div className="mt-4 border-t border-border pt-3 text-xs text-ink-muted">
          {!runDetail ? (
            <span className="text-ink-faint">Loading full run…</span>
          ) : (
            <div className="flex flex-col gap-2">
              <div>
                <div className="text-ink-faint">Query</div>
                <div className="text-ink">{runDetail.query}</div>
              </div>
              <div>
                <div className="text-ink-faint">Answer</div>
                <div className="whitespace-pre-wrap text-ink">{runDetail.generation}</div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
