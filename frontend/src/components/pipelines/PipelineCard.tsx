"use client";

import type { PipelineSummary } from "@/lib/types";
import { Sparkline } from "./Sparkline";

function scoreColor(score: number | null) {
  if (score == null) return "#5B6470";
  if (score > 0.8) return "#34D399";
  if (score >= 0.6) return "#FBBF24";
  return "#F87171";
}

export function PipelineCard({
  pipeline,
  sparkline,
  queryCount7d,
  onClick,
}: {
  pipeline: PipelineSummary;
  sparkline: { value: number }[];
  queryCount7d: number;
  onClick: () => void;
}) {
  const score = pipeline.last_run?.eval_score ?? null;
  const color = scoreColor(score);

  return (
    <button
      onClick={onClick}
      className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-4 text-left shadow-panel transition-colors hover:border-border-strong"
    >
      <div className="flex items-start justify-between">
        <div>
          <div className="text-sm font-medium text-ink">{pipeline.name}</div>
          <div className="mt-0.5 font-mono text-[11px] text-ink-faint">v{pipeline.current_version}</div>
        </div>
        <span
          className="rounded-full px-2 py-0.5 font-mono text-xs tabular-nums"
          style={{ color, backgroundColor: `${color}1A`, border: `1px solid ${color}66` }}
        >
          {score == null ? "—" : score.toFixed(2)}
        </span>
      </div>

      <Sparkline data={sparkline} color={color} />

      <div className="flex items-center justify-between text-[11px] text-ink-faint">
        <span>{queryCount7d} queries / 7d</span>
        <span className={pipeline.status === "active" ? "text-score-good" : "text-ink-faint"}>
          {pipeline.status}
        </span>
      </div>
    </button>
  );
}
