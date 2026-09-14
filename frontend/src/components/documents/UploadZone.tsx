"use client";

import { useCallback, useRef, useState } from "react";
import { uploadDocument } from "@/lib/api";

interface UploadItem {
  file: File;
  progress: number;
  status: "uploading" | "done" | "error";
}

const EXT_ICON: Record<string, string> = {
  pdf: "📄", docx: "📝", csv: "📊", png: "🖼️", jpg: "🖼️", jpeg: "🖼️", webp: "🖼️", pptx: "📽️",
};

function iconFor(filename: string) {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  return EXT_ICON[ext] ?? "📁";
}

export function UploadZone({ onUploaded }: { onUploaded: () => void }) {
  const [dragActive, setDragActive] = useState(false);
  const [items, setItems] = useState<UploadItem[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFiles = useCallback(
    (files: FileList) => {
      Array.from(files).forEach((file) => {
        setItems((prev) => [...prev, { file, progress: 0, status: "uploading" }]);
        uploadDocument(file, (pct) => {
          setItems((prev) => prev.map((it) => (it.file === file ? { ...it, progress: pct } : it)));
        })
          .then(() => {
            setItems((prev) => prev.map((it) => (it.file === file ? { ...it, status: "done", progress: 100 } : it)));
            onUploaded();
          })
          .catch(() => {
            setItems((prev) => prev.map((it) => (it.file === file ? { ...it, status: "error" } : it)));
          });
      });
    },
    [onUploaded]
  );

  return (
    <div>
      <div
        onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragActive(false);
          if (e.dataTransfer.files.length) handleFiles(e.dataTransfer.files);
        }}
        onClick={() => inputRef.current?.click()}
        className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors ${
          dragActive ? "border-accent bg-accent/5" : "border-border hover:border-border-strong"
        }`}
      >
        <span className="text-2xl">⇪</span>
        <p className="text-sm text-ink">Drag & drop files, or click to browse</p>
        <p className="text-xs text-ink-faint">PDF, DOCX, CSV, images, PPTX — multiple files supported</p>
        <input
          ref={inputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => e.target.files && handleFiles(e.target.files)}
        />
      </div>

      {items.length > 0 && (
        <div className="mt-4 flex flex-col gap-2">
          {items.map((it, idx) => (
            <div key={idx} className="flex items-center gap-3 rounded-lg border border-border bg-surface-raised px-3 py-2">
              <span>{iconFor(it.file.name)}</span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-xs text-ink">{it.file.name}</div>
                <div className="mt-1 h-1 overflow-hidden rounded-full bg-surface">
                  <div
                    className={`h-full rounded-full transition-all ${it.status === "error" ? "bg-score-bad" : "bg-accent"}`}
                    style={{ width: `${it.progress}%` }}
                  />
                </div>
              </div>
              <span className="w-16 shrink-0 text-right text-[10px] text-ink-faint">
                {(it.file.size / 1024).toFixed(0)} KB
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
