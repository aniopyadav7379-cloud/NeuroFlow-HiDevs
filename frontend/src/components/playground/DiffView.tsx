"use client";

/** Word-level diff, computed client-side with a simple LCS — no need for
 * a diff library dependency for this scope. Highlights words unique to
 * each side so engineers can see where two pipeline configs produced
 * genuinely different answers, not just re-read both in full. */
function diffWords(a: string, b: string) {
  const aw = a.split(/(\s+)/);
  const bw = b.split(/(\s+)/);
  const dp: number[][] = Array.from({ length: aw.length + 1 }, () => new Array(bw.length + 1).fill(0));
  for (let i = aw.length - 1; i >= 0; i--) {
    for (let j = bw.length - 1; j >= 0; j--) {
      dp[i][j] = aw[i] === bw[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const aOut: { text: string; changed: boolean }[] = [];
  const bOut: { text: string; changed: boolean }[] = [];
  let i = 0, j = 0;
  while (i < aw.length && j < bw.length) {
    if (aw[i] === bw[j]) {
      aOut.push({ text: aw[i], changed: false });
      bOut.push({ text: bw[j], changed: false });
      i++; j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      aOut.push({ text: aw[i], changed: true });
      i++;
    } else {
      bOut.push({ text: bw[j], changed: true });
      j++;
    }
  }
  while (i < aw.length) { aOut.push({ text: aw[i], changed: true }); i++; }
  while (j < bw.length) { bOut.push({ text: bw[j], changed: true }); j++; }
  return { aOut, bOut };
}

export function DiffView({ textA, textB }: { textA: string; textB: string }) {
  const { aOut, bOut } = diffWords(textA, textB);
  return (
    <div className="grid grid-cols-2 gap-4 rounded-xl border border-border bg-surface p-4">
      <div>
        <div className="mb-2 text-xs font-medium uppercase tracking-wider text-ink-faint">Pipeline A — unique</div>
        <p className="whitespace-pre-wrap text-sm leading-relaxed">
          {aOut.map((w, idx) => (
            <span key={idx} className={w.changed ? "rounded bg-score-bad/20 text-score-bad" : "text-ink-muted"}>
              {w.text}
            </span>
          ))}
        </p>
      </div>
      <div>
        <div className="mb-2 text-xs font-medium uppercase tracking-wider text-ink-faint">Pipeline B — unique</div>
        <p className="whitespace-pre-wrap text-sm leading-relaxed">
          {bOut.map((w, idx) => (
            <span key={idx} className={w.changed ? "rounded bg-score-good/20 text-score-good" : "text-ink-muted"}>
              {w.text}
            </span>
          ))}
        </p>
      </div>
    </div>
  );
}
