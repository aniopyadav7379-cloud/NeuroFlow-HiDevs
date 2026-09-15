"use client";

import { useState } from "react";
import { Plus, Activity, Settings2, X, AlertTriangle } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import Editor from "@monaco-editor/react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, LineChart, Line, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar } from "recharts";

const mockPipelines = [
  { id: "default", name: "RAG Default", version: "v1.2", queryCount: 1450, score: 0.92, status: 'good' },
  { id: "semantic", name: "Semantic Router", version: "v2.0", queryCount: 320, score: 0.75, status: 'warning' },
  { id: "hybrid", name: "Hybrid Search", version: "v1.0", queryCount: 89, score: 0.55, status: 'critical' },
];

const mockLatencyData = [
  { name: 'P50', ms: 450 },
  { name: 'P95', ms: 1200 },
  { name: 'P99', ms: 2100 },
];

const mockCostData = Array.from({ length: 30 }, (_, i) => ({
  day: i, cost: Math.random() * 0.05 + 0.01
}));

const mockRadarData = [
  { metric: 'Faithfulness', value: 0.95 },
  { metric: 'Relevance', value: 0.89 },
  { metric: 'Precision', value: 0.92 },
  { metric: 'Recall', value: 0.85 },
];

export default function PipelinesManager() {
  const [editorOpen, setEditorOpen] = useState(false);
  const [analyticsOpen, setAnalyticsOpen] = useState(false);
  const [selectedPipeline, setSelectedPipeline] = useState<any>(null);
  
  const [configJson, setConfigJson] = useState('{\n  "name": "New Pipeline",\n  "retriever": {\n    "type": "vector",\n    "top_k": 5\n  },\n  "generator": {\n    "model": "gpt-4o"\n  }\n}');

  const openAnalytics = (pipeline: any) => {
    setSelectedPipeline(pipeline);
    setAnalyticsOpen(true);
  };

  const handleEditorMount = (editor: any, monaco: any) => {
    monaco.languages.json.jsonDefaults.setDiagnosticsOptions({
      validate: true,
      schemas: [
        {
          uri: "http://internal/pipeline-schema.json",
          fileMatch: ["*"],
          schema: {
            type: "object",
            properties: {
              name: { type: "string" },
              retriever: {
                type: "object",
                properties: {
                  type: { type: "string", enum: ["vector", "hybrid", "keyword"] },
                  top_k: { type: "number", minimum: 1, maximum: 20 }
                },
                required: ["type"]
              },
              generator: {
                type: "object",
                properties: {
                  model: { type: "string" }
                },
                required: ["model"]
              }
            },
            required: ["name", "retriever", "generator"]
          }
        }
      ]
    });
  };

  return (
    <div className="h-full p-8 flex flex-col gap-6 relative">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Pipeline Manager</h1>
          <p className="text-white/50 mt-1">Configure routing, chunking, and generation logic.</p>
        </div>
        <button 
          onClick={() => setEditorOpen(true)}
          className="bg-primary hover:bg-primary/90 text-white px-4 py-2 rounded-lg font-medium text-sm flex items-center gap-2 transition-all shadow-lg shadow-primary/20"
        >
          <Plus size={16} />
          Create Pipeline
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {mockPipelines.map((p) => (
          <div 
            key={p.id} 
            className="glass-card p-6 rounded-xl border border-white/5 cursor-pointer hover:border-primary/50 transition-colors group"
            onClick={() => openAnalytics(p)}
          >
            <div className="flex justify-between items-start mb-4">
              <div>
                <h3 className="font-semibold text-lg">{p.name}</h3>
                <span className="text-xs bg-white/10 px-2 py-0.5 rounded text-white/70">{p.version}</span>
              </div>
              <div className="p-2 bg-white/5 rounded-lg group-hover:bg-primary/20 transition-colors">
                <Settings2 size={18} className="text-white/60 group-hover:text-primary transition-colors" />
              </div>
            </div>
            
            <div className="grid grid-cols-2 gap-4 mt-6">
              <div>
                <p className="text-xs text-white/40 uppercase tracking-wider mb-1">7d Queries</p>
                <p className="font-medium text-lg">{p.queryCount.toLocaleString()}</p>
              </div>
              <div>
                <p className="text-xs text-white/40 uppercase tracking-wider mb-1">Avg Score</p>
                <p className={`font-bold text-lg ${
                  p.status === 'good' ? 'text-green-500' : p.status === 'warning' ? 'text-yellow-500' : 'text-red-500'
                }`}>
                  {(p.score * 100).toFixed(1)}%
                </p>
              </div>
            </div>

            {/* Mock Sparkline */}
            <div className="mt-6 h-10 w-full flex items-end gap-1 opacity-70 group-hover:opacity-100 transition-opacity">
              {Array.from({ length: 20 }).map((_, i) => (
                <div 
                  key={i} 
                  className={`w-full rounded-t-sm ${
                    p.status === 'good' ? 'bg-green-500' : p.status === 'warning' ? 'bg-yellow-500' : 'bg-red-500'
                  }`}
                  style={{ height: `${Math.max(20, Math.random() * 100)}%` }}
                />
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Editor Modal */}
      <AnimatePresence>
        {editorOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-8">
            <motion.div 
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="absolute inset-0 bg-black/60 backdrop-blur-md"
              onClick={() => setEditorOpen(false)}
            />
            <motion.div 
              initial={{ opacity: 0, scale: 0.95, y: 20 }} 
              animate={{ opacity: 1, scale: 1, y: 0 }} 
              exit={{ opacity: 0, scale: 0.95, y: 20 }}
              className="relative w-full max-w-4xl h-[80vh] glass-card border border-white/10 rounded-2xl flex flex-col overflow-hidden shadow-2xl"
            >
              <div className="p-4 border-b border-white/10 flex justify-between items-center bg-white/5">
                <h2 className="font-semibold text-lg flex items-center gap-2">
                  <Settings2 className="text-primary" size={20} />
                  Pipeline Configuration
                </h2>
                <button onClick={() => setEditorOpen(false)} className="text-white/50 hover:text-white transition-colors">
                  <X size={20} />
                </button>
              </div>
              <div className="flex-1">
                <Editor
                  height="100%"
                  defaultLanguage="json"
                  theme="vs-dark"
                  value={configJson}
                  onChange={(val) => setConfigJson(val || "")}
                  onMount={handleEditorMount}
                  options={{
                    minimap: { enabled: false },
                    fontSize: 14,
                    padding: { top: 16 },
                    scrollBeyondLastLine: false,
                    smoothScrolling: true,
                  }}
                />
              </div>
              <div className="p-4 border-t border-white/10 flex justify-end gap-3 bg-black/20">
                <button onClick={() => setEditorOpen(false)} className="px-4 py-2 text-sm font-medium hover:bg-white/5 rounded-lg transition-colors">
                  Cancel
                </button>
                <button className="bg-primary hover:bg-primary/90 text-white px-6 py-2 rounded-lg text-sm font-medium shadow-lg shadow-primary/20">
                  Save Pipeline
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* Analytics Drawer */}
      <AnimatePresence>
        {analyticsOpen && selectedPipeline && (
          <>
            <motion.div 
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="absolute inset-0 bg-black/40 backdrop-blur-sm z-40"
              onClick={() => setAnalyticsOpen(false)}
            />
            <motion.div 
              initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }}
              transition={{ type: "spring", damping: 25, stiffness: 200 }}
              className="absolute top-0 right-0 bottom-0 w-[500px] glass-card border-l border-white/10 z-50 p-6 overflow-y-auto"
            >
              <div className="flex justify-between items-center mb-8">
                <div>
                  <h2 className="text-2xl font-bold tracking-tight">{selectedPipeline.name}</h2>
                  <p className="text-white/50 text-sm">Performance Analytics</p>
                </div>
                <button onClick={() => setAnalyticsOpen(false)} className="text-white/50 hover:text-white p-2 rounded-full hover:bg-white/10 transition-colors">
                  <X size={20} />
                </button>
              </div>

              <div className="space-y-8">
                {/* Radar Chart */}
                <div className="bg-black/20 p-4 rounded-xl border border-white/5">
                  <h3 className="text-sm font-semibold text-white/60 uppercase tracking-wider mb-4">Evaluation Matrix</h3>
                  <div className="h-64">
                    <ResponsiveContainer width="100%" height="100%">
                      <RadarChart cx="50%" cy="50%" outerRadius="70%" data={mockRadarData}>
                        <PolarGrid stroke="rgba(255,255,255,0.1)" />
                        <PolarAngleAxis dataKey="metric" tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 12 }} />
                        <PolarRadiusAxis angle={30} domain={[0, 1]} tick={false} axisLine={false} />
                        <Radar name="Pipeline" dataKey="value" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.4} />
                      </RadarChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                {/* Latency */}
                <div className="bg-black/20 p-4 rounded-xl border border-white/5">
                  <h3 className="text-sm font-semibold text-white/60 uppercase tracking-wider mb-4">Latency (ms)</h3>
                  <div className="h-48">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={mockLatencyData}>
                        <XAxis dataKey="name" stroke="rgba(255,255,255,0.2)" tick={{ fill: 'rgba(255,255,255,0.5)' }} />
                        <Tooltip cursor={{ fill: 'rgba(255,255,255,0.05)' }} contentStyle={{ backgroundColor: '#18181b', borderColor: '#27272a' }} />
                        <Bar dataKey="ms" fill="#8b5cf6" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                {/* Cost Trend */}
                <div className="bg-black/20 p-4 rounded-xl border border-white/5">
                  <h3 className="text-sm font-semibold text-white/60 uppercase tracking-wider mb-4">Cost per Query ($)</h3>
                  <div className="h-48">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={mockCostData}>
                        <Line type="monotone" dataKey="cost" stroke="#10b981" strokeWidth={2} dot={false} />
                        <Tooltip contentStyle={{ backgroundColor: '#18181b', borderColor: '#27272a' }} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </div>
                
                {/* Failed Runs */}
                <div>
                  <h3 className="text-sm font-semibold text-white/60 uppercase tracking-wider mb-4 flex items-center gap-2">
                    <AlertTriangle size={16} className="text-red-500" />
                    Recent Failures
                  </h3>
                  <div className="space-y-3">
                    <div className="bg-red-500/10 border border-red-500/20 p-3 rounded-lg text-sm text-red-200">
                      <p className="font-medium">CircuitOpenError: openai</p>
                      <p className="text-xs opacity-70 mt-1">2 minutes ago • ID: 8f4a-9b2e</p>
                    </div>
                  </div>
                </div>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  );
}
