"use client";

import { useState } from "react";
import { rateRun } from "@/lib/api";

export function FeedbackButtons({ runId }: { runId: string | null }) {
  const [rated, setRated] = useState<"up" | "down" | null>(null);
  const [pending, setPending] = useState(false);

  if (!runId) return null;

  const submit = async (kind: "up" | "down") => {
    setPending(true);
    try {
      await rateRun(runId, kind === "up" ? 5 : 1);
      setRated(kind);
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="flex items-center gap-1.5">
      <button
        onClick={() => submit("up")}
        disabled={pending || rated !== null}
        aria-label="Good response"
        className={`rounded-md border p-1.5 transition-colors disabled:cursor-default ${
          rated === "up"
            ? "border-score-good/50 bg-score-good/15 text-score-good"
            : "border-border text-ink-faint hover:border-border-strong hover:text-ink"
        }`}
      >
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
          <path
            d="M6 14H3.5a1 1 0 01-1-1V8a1 1 0 011-1H6m0 7V7m0 7h5.5a1.5 1.5 0 001.45-1.86l-1-4A1.5 1.5 0 0010.5 7H8l.5-3.5A1.5 1.5 0 007 2L6 4.5V7"
            stroke="currentColor"
            strokeWidth="1.3"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
      <button
        onClick={() => submit("down")}
        disabled={pending || rated !== null}
        aria-label="Bad response"
        className={`rounded-md border p-1.5 transition-colors disabled:cursor-default ${
          rated === "down"
            ? "border-score-bad/50 bg-score-bad/15 text-score-bad"
            : "border-border text-ink-faint hover:border-border-strong hover:text-ink"
        }`}
      >
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" className="rotate-180">
          <path
            d="M6 14H3.5a1 1 0 01-1-1V8a1 1 0 011-1H6m0 7V7m0 7h5.5a1.5 1.5 0 001.45-1.86l-1-4A1.5 1.5 0 0010.5 7H8l.5-3.5A1.5 1.5 0 007 2L6 4.5V7"
            stroke="currentColor"
            strokeWidth="1.3"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
      {rated && <span className="text-[11px] text-ink-faint">Thanks for the feedback</span>}
    </div>
  );
}
