const scoreColor = (score: number | null | undefined) => {
  if (score == null) return "text-ink-faint border-border";
  if (score > 0.8) return "text-score-good border-score-good/40 bg-score-good/10";
  if (score >= 0.6) return "text-score-mid border-score-mid/40 bg-score-mid/10";
  return "text-score-bad border-score-bad/40 bg-score-bad/10";
};

export function ScoreBadge({ score, label }: { score: number | null | undefined; label?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-xs tabular-nums ${scoreColor(
        score
      )}`}
    >
      {label && <span className="text-ink-faint">{label}</span>}
      {score == null ? "—" : score.toFixed(2)}
    </span>
  );
}
