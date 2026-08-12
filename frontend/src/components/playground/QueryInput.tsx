"use client";

const MAX_CHARS = 2000;

export function QueryInput({
  value,
  onChange,
  compareMode,
  onCompareModeChange,
}: {
  value: string;
  onChange: (v: string) => void;
  compareMode: boolean;
  onCompareModeChange: (v: boolean) => void;
}) {
  return (
    <div className="flex flex-col gap-2">
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value.slice(0, MAX_CHARS))}
        placeholder="Ask NeuroFlow something…"
        rows={4}
        className="w-full resize-none rounded-lg border border-border bg-surface-raised px-3 py-2.5 text-sm text-ink outline-none transition-colors placeholder:text-ink-faint focus:border-accent"
      />
      <div className="flex items-center justify-between">
        <label className="flex cursor-pointer items-center gap-2 text-xs text-ink-muted">
          <button
            type="button"
            role="switch"
            aria-checked={compareMode}
            onClick={() => onCompareModeChange(!compareMode)}
            className={`relative h-5 w-9 rounded-full transition-colors ${compareMode ? "bg-accent" : "bg-border-strong"}`}
          >
            <span
              className={`absolute top-0.5 h-4 w-4 rounded-full bg-canvas transition-transform ${
                compareMode ? "translate-x-[18px]" : "translate-x-0.5"
              }`}
            />
          </button>
          Compare mode
        </label>
        <span className="font-mono text-[11px] text-ink-faint">
          {value.length} / {MAX_CHARS}
        </span>
      </div>
    </div>
  );
}
