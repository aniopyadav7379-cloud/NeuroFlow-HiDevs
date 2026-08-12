import { useEffect, useRef, useState } from "react";
import { API_BASE_URL } from "@/lib/api";
import type { EvaluationFeedItem } from "@/lib/types";

const MAX_FEED_ITEMS = 200;

/** Consumes GET /evaluations/stream (backend/api/evaluations.py), which
 * forwards Redis pub/sub messages published each time EvaluationJudge
 * writes a row (evaluation/judge.py). Prepends new items so the feed
 * reads newest-first, capped so a long session doesn't grow the DOM
 * unboundedly. */
export function useEvaluationFeed() {
  const [items, setItems] = useState<EvaluationFeedItem[]>([]);
  const [connected, setConnected] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const source = new EventSource(`${API_BASE_URL}/evaluations/stream`);
    sourceRef.current = source;

    source.onopen = () => setConnected(true);

    source.addEventListener("evaluation", (evt) => {
      const data = JSON.parse((evt as MessageEvent).data) as EvaluationFeedItem;
      setItems((prev) => [data, ...prev].slice(0, MAX_FEED_ITEMS));
    });

    source.onerror = () => setConnected(false);

    return () => {
      source.close();
      sourceRef.current = null;
    };
  }, []);

  return { items, connected };
}
