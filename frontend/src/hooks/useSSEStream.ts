import { useState, useEffect, useRef } from "react";

export function useSSEStream(runId: string | null) {
  const [content, setContent] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [isComplete, setIsComplete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!runId) return;

    // Reset state
    setContent("");
    setIsStreaming(true);
    setIsComplete(false);
    setError(null);

    // Hardcode API base to localhost:8000 for local dev
    const url = `http://localhost:8000/query/${runId}/stream`;
    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.event === "token") {
          setContent((prev) => prev + data.data);
        } else if (data.event === "error") {
          setError(data.data);
          es.close();
          setIsStreaming(false);
        }
      } catch (e) {
        // Fallback for plain text
        setContent((prev) => prev + event.data);
      }
    };

    es.onerror = () => {
      // Assuming stream completes or fails
      es.close();
      setIsStreaming(false);
      setIsComplete(true);
    };

    // Note: Most standard SSE for streaming completion ends when the connection closes.
    // We handle that in onerror/onclose if the server closes it cleanly.

    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, [runId]);

  return { content, isStreaming, isComplete, error };
}
