"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  Line,
  LineChart,
  PolarAngleAxis,
  PolarGrid,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getPipeline, getPipelineAnalytics, getPipelineRuns, getPipelineSuggestions } from "@/lib/api";

export function PipelineAnalyticsDrawer({ pipelineId, onClose }: { pipelineId: string | null; onClose: () => void }) {
  const { data: detail } = useQuery({
    queryKey: ["pipeline", pipelineId],
    queryFn: () => getPipeline(pipelineId!),
    enabled: !!pipelineId,
  });
  const { data: analytics } = useQuery({
    queryKey: ["pipeline-analytics", pipelineId],
    queryFn: () => getPipelineAnalytics(pipelineId!),
    enabled: !!pipelineId,
  });
  const { data: runsData } = useQuery({
    queryKey: ["pipeline-runs", pipelineId],
    queryFn: () => getPipelineRuns(pipelineId!),
    enabled: !!pipelineId,
  });
  const { data: suggestions } = useQuery({
    queryKey: ["pipeline-suggestions", pipelineId],
    queryFn: () => getPipelineSuggestions(pipelineId!),
    enabled: !!pipelineId,
  });

  if (!pipelineId) return null;

  const latencyBars = [
    { name: "p50", retrieval: analytics?.retrieval_latency_ms.p50 ?? 0, generation: analytics?.generation_latency_ms.p50 ?? 0 },
    { name: "p95", retrieval: analytics?.retrieval_latency_ms.p95 ?? 0, generation: analytics?.generation_latency_ms.p95 ?? 0 },
    { name: "p99", retrieval: analytics?.retrieval_latency_ms.p99 ?? 0, generation: analytics?.generation_latency_ms.p99 ?? 0 },
  ];

  const radarData = analytics
    ? [
        { metric: "Faithfulness", value: analytics.evaluation_scores.avg_faithfulness ?? 0 },
        { metric: "Relevance", value: analytics.evaluation_scores.avg_answer_relevance ?? 0 },
        { metric: "Precision", value: analytics.evaluation_scores.avg_context_precision ?? 0 },
        { metric: "Recall", value: analytics.evaluation_scores.avg_context_recall ?? 0 },
      ]
    : [];

  const costTrend = (analytics?.queries_per_day_last_30d ?? []).map((d) => ({
    date: d.date.slice(5),
    // NOTE: true per-query cost isn't stored per-run yet (generator.py
    // persists token counts, not cost_usd) — this trend line shows query
    // VOLUME per day as a proxy until that gap (documented in
    // backend/api/pipelines.py's analytics endpoint) is closed.
    count: d.count,
  }));

  const failedRuns = (runsData?.runs ?? []).filter((r) => r.status === "failed").slice(0, 5);

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button aria-label="Close" className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative flex h-full w-full max-w-xl flex-col overflow-y-auto border-l border-border bg-surface p-6 shadow-panel">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <div className="text-sm font-medium text-ink">{detail?.name}</div>
            <div className="text-xs text-ink-faint">{analytics?.n_runs ?? 0} runs recorded</div>
          </div>
          <button onClick={onClose} className="text-ink-faint hover:text-ink">✕</button>
        </div>

        <section className="mb-6">
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-ink-faint">Latency (ms)</h3>
          <div className="h-40 rounded-lg border border-border bg-surface-raised p-2">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={latencyBars}>
                <XAxis dataKey="name" stroke="#5B6470" fontSize={11} />
                <YAxis stroke="#5B6470" fontSize={11} />
                <Tooltip contentStyle={{ background: "#1B1F24", border: "1px solid #262B31", fontSize: 12 }} />
                <Bar dataKey="retrieval" fill="#4FD1C5" radius={[3, 3, 0, 0]} />
                <Bar dataKey="generation" fill="#FBBF24" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>

        <section className="mb-6">
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-ink-faint">Queries / day (30d)</h3>
          <div className="h-32 rounded-lg border border-border bg-surface-raised p-2">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={costTrend}>
                <XAxis dataKey="date" stroke="#5B6470" fontSize={10} />
                <YAxis stroke="#5B6470" fontSize={11} />
                <Tooltip contentStyle={{ background: "#1B1F24", border: "1px solid #262B31", fontSize: 12 }} />
                <Line type="monotone" dataKey="count" stroke="#4FD1C5" strokeWidth={1.5} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </section>

        <section className="mb-6">
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-ink-faint">Evaluation metrics</h3>
          <div className="h-56 rounded-lg border border-border bg-surface-raised p-2">
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart data={radarData}>
                <PolarGrid stroke="#262B31" />
                <PolarAngleAxis dataKey="metric" stroke="#8A93A0" fontSize={11} />
                <Radar dataKey="value" stroke="#4FD1C5" fill="#4FD1C5" fillOpacity={0.25} />
              </RadarChart>
            </ResponsiveContainer>
          </div>
        </section>

        {suggestions && suggestions.length > 0 && (
          <section className="mb-6">
            <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-ink-faint">Suggestions</h3>
            <div className="flex flex-col gap-2">
              {suggestions.map((s, i) => (
                <div key={i} className="rounded-lg border border-accent/30 bg-accent/5 p-3 text-xs text-ink-muted">
                  {s.reason}
                </div>
              ))}
            </div>
          </section>
        )}

        <section>
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-ink-faint">Recent failed runs</h3>
          {failedRuns.length === 0 ? (
            <p className="text-xs text-ink-faint">No failures recorded.</p>
          ) : (
            <div className="flex flex-col gap-2">
              {failedRuns.map((r) => (
                <div key={r.run_id} className="rounded-lg border border-score-bad/30 bg-score-bad/5 p-2.5 text-xs">
                  <div className="truncate text-ink-muted">{r.query}</div>
                  <div className="mt-1 font-mono text-[10px] text-ink-faint">{r.created_at}</div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
