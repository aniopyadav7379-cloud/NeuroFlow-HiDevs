import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { EvaluationScores } from "@/lib/types";

const POLL_INTERVAL_MS = 700;
const MAX_POLL_MS = 30_000;

/** Evaluation runs async (fire-and-forget from pipelines/generation/
 * generator.py, consumed by evaluation/worker.py) — it's typically ready
 * a couple seconds after generation finishes, not instantly. This polls
 * GET /runs/{runId} until a score appears or MAX_POLL_MS elapses, so the
 * gauges (EvaluationGauge) can show a pulsing "pending" state and then
 * animate in the moment real numbers land. */
export function useRunEvaluation(runId: string | null) {
  const [scores, setScores] = useState<EvaluationScores | null>(null);

  useEffect(() => {
    setScores(null);
    if (!runId) return;

    let cancelled = false;
    let elapsed = 0;

    const poll = async () => {
      if (cancelled) return;
      try {
        const { data } = await api.get(`/runs/${runId}`);
        if (data.evaluation) {
          if (!cancelled) setScores(data.evaluation);
          return;
        }
      } catch {
        // keep polling — the row may just not exist yet on the very first tick
      }
      elapsed += POLL_INTERVAL_MS;
      if (elapsed < MAX_POLL_MS && !cancelled) {
        setTimeout(poll, POLL_INTERVAL_MS);
      }
    };

    const initialDelay = setTimeout(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearTimeout(initialDelay);
    };
  }, [runId]);

  return scores;
}
