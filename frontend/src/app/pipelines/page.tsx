"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { usePipelines } from "@/hooks/usePipelines";
import { getPipelineRuns } from "@/lib/api";
import { PipelineCard } from "@/components/pipelines/PipelineCard";
import { CreatePipelineModal } from "@/components/pipelines/CreatePipelineModal";
import { PipelineAnalyticsDrawer } from "@/components/pipelines/PipelineAnalyticsDrawer";
import type { PipelineSummary } from "@/lib/types";

function PipelineCardWithSparkline({ pipeline, onClick }: { pipeline: PipelineSummary; onClick: () => void }) {
  const { data: runs } = useQuery({
    queryKey: ["pipeline-runs-sparkline", pipeline.pipeline_id],
    queryFn: () => getPipelineRuns(pipeline.pipeline_id),
  });
  const scores = (runs?.runs ?? [])
    .filter((r) => r.evaluation)
    .slice(0, 14)
    .reverse()
    .map((r) => ({ value: r.evaluation!.overall_score }));
  const last7dCount = (runs?.runs ?? []).filter(
    (r) => Date.now() - new Date(r.created_at).getTime() < 7 * 24 * 60 * 60 * 1000
  ).length;

  return <PipelineCard pipeline={pipeline} sparkline={scores} queryCount7d={last7dCount} onClick={onClick} />;
}

export default function PipelinesPage() {
  const { data: pipelines, isLoading } = usePipelines();
  const [showCreate, setShowCreate] = useState(false);
  const [openPipelineId, setOpenPipelineId] = useState<string | null>(null);
  const queryClient = useQueryClient();

  return (
    <div className="mx-auto max-w-5xl px-8 py-10">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-ink">Pipelines</h1>
          <p className="mt-1 text-sm text-ink-muted">Configure and monitor NeuroFlow's RAG pipelines.</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="rounded-lg bg-accent px-3.5 py-2 text-sm font-medium text-canvas hover:opacity-90"
        >
          + New pipeline
        </button>
      </div>

      {isLoading && <p className="mt-8 text-sm text-ink-faint">Loading pipelines…</p>}

      <div className="mt-8 grid grid-cols-2 gap-4 lg:grid-cols-3">
        {(pipelines ?? []).map((p) => (
          <PipelineCardWithSparkline key={p.pipeline_id} pipeline={p} onClick={() => setOpenPipelineId(p.pipeline_id)} />
        ))}
      </div>

      {showCreate && (
        <CreatePipelineModal
          onClose={() => setShowCreate(false)}
          onCreated={() => queryClient.invalidateQueries({ queryKey: ["pipelines"] })}
        />
      )}

      <PipelineAnalyticsDrawer pipelineId={openPipelineId} onClose={() => setOpenPipelineId(null)} />
    </div>
  );
}
