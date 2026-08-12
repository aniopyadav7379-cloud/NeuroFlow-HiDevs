"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { listDocuments } from "@/lib/api";
import { UploadZone } from "@/components/documents/UploadZone";
import { DocumentList } from "@/components/documents/DocumentList";
import { DocumentDetail } from "@/components/documents/DocumentDetail";

export default function DocumentsPage() {
  const [selected, setSelected] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data: documents } = useQuery({
    queryKey: ["documents"],
    queryFn: listDocuments,
    // Documents in "processing" state should show a live pulse; poll
    // while anything is still in flight so the badge actually animates
    // toward "complete" without a manual refresh.
    refetchInterval: (query) => {
      const docs = query.state.data ?? [];
      return docs.some((d) => d.status === "queued" || d.status === "processing") ? 3000 : false;
    },
  });

  return (
    <div className="mx-auto max-w-4xl px-8 py-10">
      <h1 className="text-lg font-semibold text-ink">Documents</h1>
      <p className="mt-1 text-sm text-ink-muted">Upload and inspect NeuroFlow's ingested corpus.</p>

      <div className="mt-6">
        <UploadZone onUploaded={() => queryClient.invalidateQueries({ queryKey: ["documents"] })} />
      </div>

      <DocumentList documents={documents ?? []} onSelect={setSelected} />

      <DocumentDetail documentId={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
