"use client";

import type { DocumentSummary } from "@/lib/types";
import { StatusBadge } from "./StatusBadge";

export function DocumentList({ documents, onSelect }: { documents: DocumentSummary[]; onSelect: (id: string) => void }) {
  if (documents.length === 0) {
    return <p className="mt-6 text-sm text-ink-faint">No documents ingested yet.</p>;
  }
  return (
    <table className="mt-6 w-full border-separate border-spacing-y-1.5 text-sm">
      <thead>
        <tr className="text-left text-[11px] uppercase tracking-wider text-ink-faint">
          <th className="px-3 py-1 font-medium">Filename</th>
          <th className="px-3 py-1 font-medium">Type</th>
          <th className="px-3 py-1 font-medium">Status</th>
          <th className="px-3 py-1 font-medium">Chunks</th>
          <th className="px-3 py-1 font-medium">Ingested</th>
        </tr>
      </thead>
      <tbody>
        {documents.map((doc) => (
          <tr
            key={doc.document_id}
            onClick={() => onSelect(doc.document_id)}
            className="cursor-pointer rounded-lg bg-surface transition-colors hover:bg-surface-hover"
          >
            <td className="truncate rounded-l-lg px-3 py-2.5 text-ink">{doc.filename}</td>
            <td className="px-3 py-2.5 font-mono text-xs text-ink-muted">{doc.source_type}</td>
            <td className="px-3 py-2.5"><StatusBadge status={doc.status} /></td>
            <td className="px-3 py-2.5 font-mono text-xs text-ink-muted">{doc.chunk_count ?? "—"}</td>
            <td className="rounded-r-lg px-3 py-2.5 text-xs text-ink-faint">
              {new Date(doc.created_at).toLocaleString()}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
