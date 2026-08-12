"use client";

import type { DocumentStatus } from "@/lib/types";

const CONFIG: Record<DocumentStatus, { label: string; className: string; pulse: boolean }> = {
  queued: { label: "queued", className: "text-ink-faint border-border", pulse: false },
  processing: { label: "processing", className: "text-accent border-accent/40 bg-accent/10", pulse: true },
  complete: { label: "complete", className: "text-score-good border-score-good/40 bg-score-good/10", pulse: false },
  failed: { label: "failed", className: "text-score-bad border-score-bad/40 bg-score-bad/10", pulse: false },
};

export function StatusBadge({ status }: { status: DocumentStatus }) {
  const cfg = CONFIG[status] ?? CONFIG.queued;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-[11px] ${cfg.className}`}>
      <span className={`h-1.5 w-1.5 rounded-full bg-current ${cfg.pulse ? "animate-pulse-dot" : ""}`} />
      {cfg.label}
    </span>
  );
}
