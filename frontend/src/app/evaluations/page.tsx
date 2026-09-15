"use client";

import { useState, useEffect } from "react";
import { Filter, Search, ChevronDown, ChevronUp, Clock } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

interface Evaluation {
  id: string;
  run_id: string;
  pipeline_name: string;
  query: string;
  faithfulness: number;
  answer_relevance: number;
  context_precision: number;
  context_recall: number;
  overall_score: number;
  evaluated_at: string;
  retrieved_chunks: string[];
  generated_answer: string;
}

export default function EvaluationsFeed() {
  const [evaluations, setEvaluations] = useState<Evaluation[]>([]);
  const [filterPipeline, setFilterPipeline] = useState("all");
  const [filterMetric, setFilterMetric] = useState("all");
  const [filterDate, setFilterDate] = useState("all");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    // Connect to backend SSE endpoint
    const es = new EventSource("http://localhost:8000/evaluations/stream");
    
    es.addEventListener("message", (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.id) {
          setEvaluations(prev => [data, ...prev].slice(0, 50)); // Keep last 50
        }
      } catch (e) {
        console.error("SSE parse error", e);
      }
    });

    return () => {
      es.close();
    };
  }, []);

  const filteredEvals = evaluations.filter(e => {
    // Pipeline filter
    if (filterPipeline !== "all" && e.pipeline_name !== filterPipeline) return false;
    
    // Date filter
    if (filterDate !== "all") {
      const evalDate = new Date(e.evaluated_at);
      const today = new Date();
      const diffTime = Math.abs(today.getTime() - evalDate.getTime());
      const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
      
      if (filterDate === "today" && diffDays > 1) return false;
      if (filterDate === "week" && diffDays > 7) return false;
    }
    
    // Metric filter
    if (filterMetric !== "all") {
      if (filterMetric === "faithfulness<0.7" && e.faithfulness >= 0.7) return false;
      if (filterMetric === "relevance<0.7" && e.answer_relevance >= 0.7) return false;
      if (filterMetric === "precision<0.7" && e.context_precision >= 0.7) return false;
      if (filterMetric === "recall<0.7" && e.context_recall >= 0.7) return false;
    }
    
    return true;
  });

  return (
    <div className="h-full p-8 flex flex-col gap-6 relative">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
            Evaluation Feed
            <span className="relative flex h-3 w-3">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-3 w-3 bg-green-500"></span>
            </span>
          </h1>
          <p className="text-white/50 mt-1">Real-time incoming evaluation metrics from production runs.</p>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="glass-card p-4 rounded-xl flex gap-4 items-center border border-white/5">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-white/40" size={16} />
          <input 
            type="text" 
            placeholder="Search queries..." 
            className="w-full bg-black/40 border border-white/10 rounded-lg py-2 pl-10 pr-4 text-sm focus:outline-none focus:border-primary/50"
          />
        </div>
        <div className="h-6 w-px bg-white/10" />
        <div className="flex items-center gap-2">
          <Filter size={16} className="text-white/40" />
          <select 
            value={filterPipeline}
            onChange={(e) => setFilterPipeline(e.target.value)}
            className="bg-black/40 border border-white/10 rounded-lg p-2 text-sm focus:outline-none focus:border-primary/50"
          >
            <option value="all">All Pipelines</option>
            <option value="RAG Default">RAG Default</option>
            <option value="Semantic Router">Semantic Router</option>
          </select>

          <select 
            value={filterMetric}
            onChange={(e) => setFilterMetric(e.target.value)}
            className="bg-black/40 border border-white/10 rounded-lg p-2 text-sm focus:outline-none focus:border-primary/50"
          >
            <option value="all">Any Metric Score</option>
            <option value="faithfulness<0.7">Faithfulness &lt; 0.7</option>
            <option value="relevance<0.7">Relevance &lt; 0.7</option>
            <option value="precision<0.7">Precision &lt; 0.7</option>
            <option value="recall<0.7">Recall &lt; 0.7</option>
          </select>

          <select 
            value={filterDate}
            onChange={(e) => setFilterDate(e.target.value)}
            className="bg-black/40 border border-white/10 rounded-lg p-2 text-sm focus:outline-none focus:border-primary/50"
          >
            <option value="all">All Time</option>
            <option value="today">Today</option>
            <option value="week">Past 7 Days</option>
          </select>
        </div>
      </div>

      {/* Feed List */}
      <div className="flex-1 overflow-y-auto space-y-4 pr-2">
        <AnimatePresence>
          {filteredEvals.length === 0 ? (
            <motion.div 
              initial={{ opacity: 0 }} animate={{ opacity: 1 }}
              className="flex flex-col items-center justify-center h-64 text-white/40 border border-dashed border-white/10 rounded-xl"
            >
              <Clock size={32} className="mb-2 opacity-50" />
              <p>Waiting for evaluations...</p>
              <p className="text-xs mt-1">Run a query in the playground to trigger an evaluation.</p>
            </motion.div>
          ) : (
            filteredEvals.map((ev) => (
              <motion.div 
                key={ev.id}
                layout
                initial={{ opacity: 0, y: -20, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                className="glass-card rounded-xl border border-white/5 overflow-hidden group"
              >
                <div 
                  className="p-5 cursor-pointer flex flex-col md:flex-row gap-4 justify-between items-start md:items-center hover:bg-white/[0.02] transition-colors"
                  onClick={() => setExpandedId(expandedId === ev.id ? null : ev.id)}
                >
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-xs bg-primary/20 text-primary px-2 py-0.5 rounded font-medium">{ev.pipeline_name}</span>
                      <span className="text-xs text-white/40 flex items-center gap-1">
                        <Clock size={12} />
                        {new Date(ev.evaluated_at).toLocaleTimeString()}
                      </span>
                    </div>
                    <p className="text-sm text-white/90 font-medium line-clamp-1">{ev.query}</p>
                  </div>
                  
                  <div className="flex items-center gap-6">
                    <div className="flex gap-4">
                      <MetricBar label="Faithful" value={ev.faithfulness} />
                      <MetricBar label="Relevant" value={ev.answer_relevance} />
                    </div>
                    <div className={`px-3 py-1.5 rounded-lg text-sm font-bold border ${
                      ev.overall_score > 0.8 ? 'bg-green-500/10 text-green-500 border-green-500/20' : 
                      ev.overall_score > 0.6 ? 'bg-yellow-500/10 text-yellow-500 border-yellow-500/20' : 
                      'bg-red-500/10 text-red-500 border-red-500/20'
                    }`}>
                      {(ev.overall_score * 100).toFixed(1)}
                    </div>
                    {expandedId === ev.id ? <ChevronUp size={20} className="text-white/40" /> : <ChevronDown size={20} className="text-white/40" />}
                  </div>
                </div>

                <AnimatePresence>
                  {expandedId === ev.id && (
                    <motion.div 
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      className="border-t border-white/5 bg-black/20"
                    >
                      <div className="p-5 space-y-6">
                        <div>
                          <h4 className="text-xs font-semibold text-white/50 uppercase tracking-wider mb-2">Full Query</h4>
                          <p className="text-sm text-white/90 bg-black/40 p-3 rounded-lg border border-white/5">{ev.query}</p>
                        </div>
                        <div>
                          <h4 className="text-xs font-semibold text-white/50 uppercase tracking-wider mb-2">Generated Answer</h4>
                          <p className="text-sm text-white/90 bg-black/40 p-3 rounded-lg border border-white/5 leading-relaxed">{ev.generated_answer}</p>
                        </div>
                        <div>
                          <h4 className="text-xs font-semibold text-white/50 uppercase tracking-wider mb-2">Retrieved Chunks</h4>
                          <div className="space-y-2">
                            {ev.retrieved_chunks.map((chunk, i) => (
                              <div key={i} className="text-sm text-white/70 bg-black/40 p-3 rounded-lg border border-white/5">
                                {chunk}
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>
            ))
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

function MetricBar({ label, value }: { label: string; value: number }) {
  const percentage = value * 100;
  const color = value > 0.8 ? 'bg-green-500' : value > 0.6 ? 'bg-yellow-500' : 'bg-red-500';
  
  return (
    <div className="flex flex-col w-20">
      <div className="flex justify-between items-center mb-1">
        <span className="text-[10px] text-white/50 uppercase">{label}</span>
        <span className="text-[10px] font-medium">{percentage.toFixed(0)}</span>
      </div>
      <div className="h-1.5 w-full bg-white/10 rounded-full overflow-hidden">
        <div className={`h-full ${color}`} style={{ width: `${percentage}%` }} />
      </div>
    </div>
  );
}
