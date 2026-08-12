"use client";

import { useMemo, useState } from "react";
import { useEvaluationFeed } from "@/hooks/useEvaluationFeed";
import { EvaluationCard } from "@/components/evaluations/EvaluationCard";
import { FilterBar, type EvaluationFilters } from "@/components/evaluations/FilterBar";

export default function EvaluationsPage() {
  const { items, connected } = useEvaluationFeed();
  const [filters, setFilters] = useState<EvaluationFilters>({ pipelineId: null, minFaithfulness: null, sinceHours: null });

  const filtered = useMemo(() => {
    return items.filter((item) => {
      if (filters.pipelineId && item.pipeline_id !== filters.pipelineId) return false;
      if (filters.minFaithfulness != null && item.faithfulness >= filters.minFaithfulness) return false;
      if (filters.sinceHours != null) {
        const ageHours = (Date.now() - new Date(item.evaluated_at).getTime()) / 3_600_000;
        if (ageHours > filters.sinceHours) return false;
      }
      return true;
    });
  }, [items, filters]);

  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-ink">Evaluation Feed</h1>
          <p className="mt-1 text-sm text-ink-muted">Live results as EvaluationJudge scores each generation.</p>
        </div>
        <div className="flex items-center gap-1.5 text-xs text-ink-faint">
          <span className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-score-good" : "bg-score-bad"}`} />
          {connected ? "live" : "reconnecting…"}
        </div>
      </div>

      <div className="mt-6">
        <FilterBar filters={filters} onChange={setFilters} />
      </div>

      <div className="mt-6 flex flex-col gap-3">
        {filtered.length === 0 && (
          <p className="text-sm text-ink-faint">
            {items.length === 0 ? "Waiting for the first evaluation…" : "No evaluations match these filters."}
          </p>
        )}
        {filtered.map((item) => (
          <EvaluationCard key={item.run_id} item={item} />
        ))}
      </div>
    </div>
  );
}
