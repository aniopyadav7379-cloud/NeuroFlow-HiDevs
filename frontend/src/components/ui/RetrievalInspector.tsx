"use client";

import { useMemo } from "react";
import {
  ReactFlow,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  Handle,
  Position,
  BackgroundVariant
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

// Custom Node Component
function CustomNode({ data }: { data: any }) {
  return (
    <div className="px-4 py-3 shadow-xl rounded-xl border border-white/10 glass-card min-w-[150px]">
      <Handle type="target" position={Position.Top} className="w-2 h-2 bg-primary/50" />
      <div className="flex flex-col items-center">
        <span className="font-bold text-xs uppercase tracking-wider text-white/70 mb-1">{data.label}</span>
        {data.chunks !== undefined && (
          <span className="text-xl font-black text-primary">{data.chunks} <span className="text-xs text-white/40 font-normal">chunks</span></span>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} className="w-2 h-2 bg-primary/50" />
    </div>
  );
}

const nodeTypes = {
  custom: CustomNode,
};

export function RetrievalInspector() {
  const initialNodes = [
    { id: "1", type: "custom", position: { x: 300, y: 50 }, data: { label: "Query" } },
    { id: "2", type: "custom", position: { x: 100, y: 200 }, data: { label: "Dense Search", chunks: 50 } },
    { id: "3", type: "custom", position: { x: 300, y: 200 }, data: { label: "Sparse Search", chunks: 50 } },
    { id: "4", type: "custom", position: { x: 500, y: 200 }, data: { label: "Keyword", chunks: 20 } },
    { id: "5", type: "custom", position: { x: 300, y: 350 }, data: { label: "RRF Fusion", chunks: 60 } },
    { id: "6", type: "custom", position: { x: 300, y: 500 }, data: { label: "Reranker", chunks: 10 } },
    { id: "7", type: "custom", position: { x: 300, y: 650 }, data: { label: "Final Context", chunks: 5 } },
  ];

  const initialEdges = [
    { id: "e1-2", source: "1", target: "2", animated: true, style: { stroke: '#3b82f6', strokeWidth: 2 } },
    { id: "e1-3", source: "1", target: "3", animated: true, style: { stroke: '#3b82f6', strokeWidth: 2 } },
    { id: "e1-4", source: "1", target: "4", animated: true, style: { stroke: '#3b82f6', strokeWidth: 2 } },
    { id: "e2-5", source: "2", target: "5", animated: true, style: { stroke: '#8b5cf6', strokeWidth: 2 } },
    { id: "e3-5", source: "3", target: "5", animated: true, style: { stroke: '#8b5cf6', strokeWidth: 2 } },
    { id: "e4-5", source: "4", target: "5", animated: true, style: { stroke: '#8b5cf6', strokeWidth: 2 } },
    { id: "e5-6", source: "5", target: "6", animated: true, style: { stroke: '#10b981', strokeWidth: 2 } },
    { id: "e6-7", source: "6", target: "7", animated: true, style: { stroke: '#10b981', strokeWidth: 2 } },
  ];

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  return (
    <div className="w-full h-[600px] bg-black/20 rounded-xl border border-white/5 overflow-hidden">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        colorMode="dark"
      >
        <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="#ffffff20" />
        <Controls showInteractive={false} className="bg-white/5 border-white/10 fill-white" />
      </ReactFlow>
    </div>
  );
}
