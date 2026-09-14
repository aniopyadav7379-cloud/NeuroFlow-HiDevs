import { useEffect, useRef, useState } from "react";
import { API_BASE_URL } from "@/lib/api";
import type { Citation } from "@/lib/types";

export type StreamStatus = "idle" | "retrieving" | "streaming" | "done" | "error";

export interface SSEStreamState {
  status: StreamStatus;
  sources: string[];
  chunkCount: number;
  text: string;
  citations: Citation[];
  errorMessage: string | null;
}

const INITIAL_STATE: SSEStreamState = {
  status: "idle",
  sources: [],
  chunkCount: 0,
  text: "",
  citations: [],
  errorMessage: null,
};

/**
 * Consumes GET /query/{runId}/stream. Backend (pipelines/generation/
 * events.py + backend/api/query.py) sends SSE events with a named
 * `event:` field matching each event's `type` — native EventSource
 * dispatches those as distinct events via addEventListener(type, ...),
 * so this hook doesn't need any manual SSE parsing.
 */
export function useSSEStream(runId: string | null): SSEStreamState {
  const [state, setState] = useState<SSEStreamState>(INITIAL_STATE);
  const textRef = useRef("");

  useEffect(() => {
    textRef.current = "";
    setState(INITIAL_STATE);
    if (!runId) return;

    const source = new EventSource(`${API_BASE_URL}/query/${runId}/stream`);

    source.addEventListener("retrieval_start", () => {
      setState((s) => ({ ...s, status: "retrieving" }));
    });

    source.addEventListener("retrieval_complete", (evt) => {
      const data = JSON.parse((evt as MessageEvent).data);
      setState((s) => ({
        ...s,
        status: "streaming",
        sources: data.sources ?? [],
        chunkCount: data.chunk_count ?? 0,
      }));
    });

    source.addEventListener("token", (evt) => {
      const data = JSON.parse((evt as MessageEvent).data);
      textRef.current += data.delta ?? "";
      setState((s) => ({ ...s, status: "streaming", text: textRef.current }));
    });

    source.addEventListener("done", (evt) => {
      const data = JSON.parse((evt as MessageEvent).data);
      setState((s) => ({ ...s, status: "done", citations: data.citations ?? [] }));
      source.close();
    });

    source.addEventListener("error", (evt) => {
      // Two distinct cases share this name: our own {"type": "error", ...}
      // application event (has .data), vs a raw EventSource transport
      // error (connection drop, no .data). Handle both without treating
      // a transport hiccup as if the pipeline itself failed.
      const messageEvt = evt as MessageEvent;
      if (messageEvt.data) {
        try {
          const data = JSON.parse(messageEvt.data);
          setState((s) => ({ ...s, status: "error", errorMessage: data.message ?? "Unknown error" }));
        } catch {
          setState((s) => ({ ...s, status: "error", errorMessage: "Stream error" }));
        }
      } else {
        setState((s) => (s.status === "done" ? s : { ...s, status: "error", errorMessage: "Connection lost" }));
      }
      source.close();
    });

    // keepalive events need no handling — their only job is to keep the
    // connection alive through proxies/load balancers with idle timeouts.

    return () => source.close();
  }, [runId]);

  return state;
}
