"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

interface ChunkItem {
  id: string;
  content: string;
  chunk_index: number;
  similarity?: number;
}

export function DocumentDetail({ documentId, onClose }: { documentId: string | null; onClose: () => void }) {
  const [similarToChunkId, setSimilarToChunkId] = useState<string | null>(null);

  const { data: chunks } = useQuery({
    queryKey: ["document-chunks", documentId],
    queryFn: async () => (await api.get<{ chunks: ChunkItem[] }>(`/documents/${documentId}/chunks`)).data.chunks,
    enabled: !!documentId,
  });

  const { data: similar } = useQuery({
    queryKey: ["similar-chunks", similarToChunkId],
    queryFn: async () =>
      (await api.get<{ chunks: ChunkItem[] }>(`/chunks/${similarToChunkId}/similar`)).data.chunks,
    enabled: !!similarToChunkId,
  });

  if (!documentId) return null;
  const similarIds = new Set((similar ?? []).map((c) => c.id));

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button aria-label="Close" className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative flex h-full w-full max-w-lg flex-col overflow-y-auto border-l border-border bg-surface p-6 shadow-panel">
        <div className="mb-4 flex items-center justify-between">
          <span className="text-sm font-medium text-ink">Chunks</span>
          <button onClick={onClose} className="text-ink-faint hover:text-ink">✕</button>
        </div>

        <div className="flex flex-col gap-2">
          {(chunks ?? []).map((chunk) => (
            <div
              key={chunk.id}
              className={`rounded-lg border p-3 text-xs transition-colors ${
                similarIds.has(chunk.id)
                  ? "border-accent/50 bg-accent/10"
                  : "border-border bg-surface-raised"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-ink-faint">#{chunk.chunk_index}</span>
                <button
                  onClick={() => setSimilarToChunkId(chunk.id)}
                  className="text-accent hover:underline"
                >
                  Find similar chunks
                </button>
              </div>
              <p className="mt-1.5 line-clamp-3 text-ink-muted">{chunk.content}</p>
            </div>
          ))}
          {!chunks && <p className="text-ink-faint">Loading chunks…</p>}
        </div>
      </div>
    </div>
  );
}
