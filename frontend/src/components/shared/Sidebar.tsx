"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/playground", label: "Playground", hint: "run & compare" },
  { href: "/pipelines", label: "Pipelines", hint: "configure" },
  { href: "/evaluations", label: "Evaluations", hint: "live feed" },
  { href: "/documents", label: "Documents", hint: "corpus" },
] as const;

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex h-screen w-56 shrink-0 flex-col border-r border-border bg-surface">
      <div className="flex items-center gap-2 px-5 py-5">
        {/* Signature mark: a small signal-flow glyph, echoing the RRF/
            pipeline motif that runs through the whole product — three
            dots converging into one, standing in for hybrid retrieval
            fusing into a single ranked result. */}
        <svg width="22" height="22" viewBox="0 0 22 22" fill="none" aria-hidden="true">
          <circle cx="4" cy="5" r="2" fill="#4FD1C5" />
          <circle cx="4" cy="11" r="2" fill="#4FD1C5" opacity="0.6" />
          <circle cx="4" cy="17" r="2" fill="#4FD1C5" opacity="0.3" />
          <path d="M6 5H12C15 5 15 11 18 11" stroke="#4FD1C5" strokeWidth="1.2" opacity="0.5" />
          <path d="M6 11H14" stroke="#4FD1C5" strokeWidth="1.2" opacity="0.7" />
          <path d="M6 17H12C15 17 15 11 18 11" stroke="#4FD1C5" strokeWidth="1.2" opacity="0.5" />
          <circle cx="18" cy="11" r="2.4" fill="#0B0D10" stroke="#4FD1C5" strokeWidth="1.4" />
        </svg>
        <span className="font-mono text-[13px] font-semibold tracking-wide text-ink">
          NEUROFLOW
        </span>
      </div>

      <nav className="mt-2 flex flex-col gap-0.5 px-3">
        {NAV_ITEMS.map((item) => {
          const active = pathname?.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`group flex items-baseline justify-between rounded-md px-3 py-2 text-sm transition-colors ${
                active
                  ? "bg-surface-raised text-ink"
                  : "text-ink-muted hover:bg-surface-hover hover:text-ink"
              }`}
            >
              <span className="font-medium">{item.label}</span>
              <span
                className={`font-mono text-[10px] uppercase tracking-wider ${
                  active ? "text-accent" : "text-ink-faint group-hover:text-ink-muted"
                }`}
              >
                {item.hint}
              </span>
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto px-5 py-4">
        <div className="flex items-center gap-1.5 text-[11px] text-ink-faint">
          <span className="h-1.5 w-1.5 rounded-full bg-score-good" />
          <span className="font-mono">api reachable</span>
        </div>
      </div>
    </aside>
  );
}
