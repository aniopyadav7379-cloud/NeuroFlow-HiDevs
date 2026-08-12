"use client";

import { useMemo } from "react";
import { ReactFlow, Background, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";

export interface RetrievalInspectorData {
  denseCount: number;
  sparseCount: number;
  metadataCount: number;
  fusedCount: number;
  rerankedCount: number;
  finalCount: number;
}

const nodeStyle = {
  background: "#1B1F24",
  border: "1px solid #262B31",
  borderRadius: 8,
  color: "#E7EAEE",
  fontSize: 11,
  fontFamily: "var(--font-geist-mono)",
  padding: 8,
  width: 150,
};

/** Stretch goal: after a query completes, visualize the retrieval
 * pipeline (docs/architecture.md §2) as a flow diagram — one node per
 * stage, each annotated with how many chunks it contributed, so a poor
 * result is debuggable ("was it dense retrieval that missed, or did the
 * reranker throw away something good?") without reading logs. */
export function RetrievalInspector({ data }: { data: RetrievalInspectorData }) {
  const nodes: Node[] = useMemo(
    () => [
      { id: "query", position: { x: 0, y: 140 }, data: { label: "Query" }, style: nodeStyle },
      { id: "dense", position: { x: 220, y: 0 }, data: { label: `Dense retrieval\n${data.denseCount} chunks` }, style: nodeStyle },
      { id: "sparse", position: { x: 220, y: 140 }, data: { label: `Sparse retrieval\n${data.sparseCount} chunks` }, style: nodeStyle },
      { id: "metadata", position: { x: 220, y: 280 }, data: { label: `Metadata retrieval\n${data.metadataCount} chunks` }, style: nodeStyle },
      { id: "fusion", position: { x: 460, y: 140 }, data: { label: `RRF fusion\n${data.fusedCount} chunks` }, style: nodeStyle },
      { id: "rerank", position: { x: 680, y: 140 }, data: { label: `Reranker\n${data.rerankedCount} chunks` }, style: nodeStyle },
      { id: "context", position: { x: 900, y: 140 }, data: { label: `Final context\n${data.finalCount} chunks` }, style: { ...nodeStyle, border: "1px solid #4FD1C5" } },
    ],
    [data]
  );

  const edges: Edge[] = useMemo(
    () => [
      { id: "q-d", source: "query", target: "dense", animated: true, style: { stroke: "#4FD1C5" } },
      { id: "q-s", source: "query", target: "sparse", animated: true, style: { stroke: "#4FD1C5" } },
      { id: "q-m", source: "query", target: "metadata", animated: true, style: { stroke: "#4FD1C5" } },
      { id: "d-f", source: "dense", target: "fusion", style: { stroke: "#343B43" } },
      { id: "s-f", source: "sparse", target: "fusion", style: { stroke: "#343B43" } },
      { id: "m-f", source: "metadata", target: "fusion", style: { stroke: "#343B43" } },
      { id: "f-r", source: "fusion", target: "rerank", style: { stroke: "#343B43" } },
      { id: "r-c", source: "rerank", target: "context", style: { stroke: "#343B43" } },
    ],
    []
  );

  return (
    <div className="h-[360px] w-full rounded-xl border border-border bg-surface">
      <ReactFlow nodes={nodes} edges={edges} fitView proOptions={{ hideAttribution: true }}>
        <Background color="#20252B" gap={16} />
      </ReactFlow>
    </div>
  );
}
