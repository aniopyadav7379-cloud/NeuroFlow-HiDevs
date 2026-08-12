"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Citation } from "@/lib/types";

export function CitationChip({ citation, onClick }: { citation: Citation; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 font-mono text-[11px] transition-colors ${
        citation.invalid_citation
          ? "border-score-bad/40 bg-score-bad/10 text-score-bad hover:bg-score-bad/20"
          : "border-accent/30 bg-accent/10 text-accent hover:bg-accent/20"
      }`}
      title={citation.invalid_citation ? "This citation references a source that was not in the context" : citation.document ?? undefined}
    >
      {citation.source}
      {citation.invalid_citation && <span aria-hidden>⚠</span>}
    </button>
  );
}

interface ChunkDetail {
  id: string;
  content: string;
  metadata: Record<string, unknown>;
  document_id: string | null;
}

function useChunkDetail(chunkId: string | null) {
  return useQuery({
    queryKey: ["chunk", chunkId],
    queryFn: async () => {
      const { data } = await api.get<ChunkDetail>(`/chunks/${chunkId}`);
      return data;
    },
    enabled: !!chunkId,
  });
}

export function CitationDrawer({ citation, onClose }: { citation: Citation | null; onClose: () => void }) {
  const { data: chunk, isLoading, isError } = useChunkDetail(citation?.chunk_id ?? null);

  if (!citation) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        aria-label="Close citation detail"
        className="absolute inset-0 bg-black/50 backdrop-blur-[1px]"
        onClick={onClose}
      />
      <div className="relative flex h-full w-full max-w-md flex-col border-l border-border bg-surface shadow-panel">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div>
            <div className="font-mono text-xs text-accent">{citation.source}</div>
            <div className="mt-0.5 text-sm text-ink">{citation.document ?? "Unknown document"}</div>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1.5 text-ink-faint transition-colors hover:bg-surface-hover hover:text-ink"
            aria-label="Close"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M4 4L12 12M12 4L4 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {citation.invalid_citation ? (
            <div className="rounded-lg border border-score-bad/30 bg-score-bad/10 px-3 py-2.5 text-sm text-score-bad">
              This source number was referenced in the answer but doesn&apos;t correspond to any chunk
              that was actually in the context window — likely a hallucinated citation.
            </div>
          ) : (
            <>
              <dl className="mb-4 grid grid-cols-2 gap-3 text-xs">
                <div>
                  <dt className="text-ink-faint">Document</dt>
                  <dd className="mt-0.5 text-ink">{citation.document ?? "—"}</dd>
                </div>
                <div>
                  <dt className="text-ink-faint">Page</dt>
                  <dd className="mt-0.5 text-ink">{citation.page ?? "—"}</dd>
                </div>
                <div className="col-span-2">
                  <dt className="text-ink-faint">Chunk ID</dt>
                  <dd className="mt-0.5 truncate font-mono text-ink-muted">{citation.chunk_id ?? "—"}</dd>
                </div>
              </dl>

              <div className="mb-2 text-xs font-medium text-ink-muted">Chunk content</div>
              <div className="rounded-lg border border-border bg-surface-raised p-3 text-sm leading-relaxed text-ink">
                {isLoading && <span className="text-ink-faint">Loading chunk content…</span>}
                {isError && (
                  <span className="text-score-bad">Couldn&apos;t load this chunk (it may have been deleted).</span>
                )}
                {chunk && <p className="whitespace-pre-wrap">{chunk.content}</p>}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
