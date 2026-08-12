"use client";

import { usePipelines } from "@/hooks/usePipelines";

export interface EvaluationFilters {
  pipelineId: string | null;
  minFaithfulness: number | null;
  sinceHours: number | null;
}

export function FilterBar({ filters, onChange }: { filters: EvaluationFilters; onChange: (f: EvaluationFilters) => void }) {
  const { data: pipelines } = usePipelines();

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-surface p-3">
      <select
        value={filters.pipelineId ?? ""}
        onChange={(e) => onChange({ ...filters, pipelineId: e.target.value || null })}
        className="rounded-md border border-border bg-surface-raised px-2.5 py-1.5 text-xs text-ink outline-none focus:border-accent"
      >
        <option value="">All pipelines</option>
        {(pipelines ?? []).map((p) => (
          <option key={p.pipeline_id} value={p.pipeline_id}>{p.name}</option>
        ))}
      </select>

      <label className="flex items-center gap-1.5 text-xs text-ink-muted">
        faithfulness &lt;
        <input
          type="number"
          step={0.1}
          min={0}
          max={1}
          placeholder="off"
          value={filters.minFaithfulness ?? ""}
          onChange={(e) => onChange({ ...filters, minFaithfulness: e.target.value ? Number(e.target.value) : null })}
          className="w-16 rounded-md border border-border bg-surface-raised px-2 py-1 text-xs text-ink outline-none focus:border-accent"
        />
      </label>

      <select
        value={filters.sinceHours ?? ""}
        onChange={(e) => onChange({ ...filters, sinceHours: e.target.value ? Number(e.target.value) : null })}
        className="rounded-md border border-border bg-surface-raised px-2.5 py-1.5 text-xs text-ink outline-none focus:border-accent"
      >
        <option value="">All time</option>
        <option value="1">Last hour</option>
        <option value="24">Last 24h</option>
        <option value="168">Last 7d</option>
      </select>
    </div>
  );
}
