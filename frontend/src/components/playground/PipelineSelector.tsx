"use client";

import { usePipelines } from "@/hooks/usePipelines";
import { ScoreBadge } from "@/components/shared/ScoreBadge";

export function PipelineSelector({
  value,
  onChange,
  label,
}: {
  value: string | null;
  onChange: (id: string) => void;
  label?: string;
}) {
  const { data: pipelines, isLoading } = usePipelines();
  const active = (pipelines ?? []).filter((p) => p.status === "active");
  const selected = active.find((p) => p.pipeline_id === value);

  return (
    <div className="flex flex-col gap-1.5">
      {label && <label className="text-xs font-medium text-ink-muted">{label}</label>}
      <div className="relative">
        <select
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value)}
          disabled={isLoading}
          className="w-full appearance-none rounded-lg border border-border bg-surface-raised px-3 py-2 pr-9 text-sm text-ink outline-none transition-colors focus:border-accent disabled:opacity-50"
        >
          <option value="" disabled>
            {isLoading ? "Loading pipelines…" : "Select a pipeline"}
          </option>
          {active.map((p) => (
            <option key={p.pipeline_id} value={p.pipeline_id}>
              {p.name} — avg {p.last_run?.eval_score != null ? p.last_run.eval_score.toFixed(2) : "n/a"}
            </option>
          ))}
        </select>
        <svg
          className="pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-faint"
          viewBox="0 0 12 12"
          fill="none"
        >
          <path d="M2.5 4.5L6 8L9.5 4.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
      {selected && (
        <div className="flex items-center gap-2 text-xs text-ink-faint">
          <span>v{selected.current_version}</span>
          <ScoreBadge score={selected.last_run?.eval_score} />
        </div>
      )}
    </div>
  );
}
