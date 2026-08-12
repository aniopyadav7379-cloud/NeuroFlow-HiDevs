"use client";

const RADIUS = 26;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

function colorFor(score: number) {
  if (score > 0.8) return "#34D399";
  if (score >= 0.6) return "#FBBF24";
  return "#F87171";
}

export function EvaluationGauge({ label, score }: { label: string; score: number | null }) {
  const pct = score ?? 0;
  const offset = CIRCUMFERENCE * (1 - pct);

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative h-16 w-16">
        <svg viewBox="0 0 64 64" className="h-16 w-16 -rotate-90">
          <circle cx="32" cy="32" r={RADIUS} fill="none" stroke="#262B31" strokeWidth="5" />
          {score !== null && (
            <circle
              cx="32"
              cy="32"
              r={RADIUS}
              fill="none"
              stroke={colorFor(pct)}
              strokeWidth="5"
              strokeLinecap="round"
              strokeDasharray={CIRCUMFERENCE}
              strokeDashoffset={offset}
              style={{ transition: "stroke-dashoffset 700ms ease-out, stroke 300ms" }}
            />
          )}
        </svg>
        <div className="absolute inset-0 flex items-center justify-center font-mono text-[13px] tabular-nums text-ink">
          {score === null ? (
            <span className="h-2 w-2 animate-pulse-dot rounded-full bg-ink-faint" />
          ) : (
            score.toFixed(2)
          )}
        </div>
      </div>
      <span className="text-center text-[11px] leading-tight text-ink-muted">{label}</span>
    </div>
  );
}
