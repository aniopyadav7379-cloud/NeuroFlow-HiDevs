"use client";

import { useState, useEffect } from "react";
import { ThumbsUp, ThumbsDown, ChevronRight, Activity, GitCompare, Network } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useSSEStream } from "@/hooks/useSSEStream";
import { AnimatedGauge } from "@/components/ui/AnimatedGauge";
import { RetrievalInspector } from "@/components/ui/RetrievalInspector";

const pipelines = [
  { id: "default", name: "RAG Default", score: 0.92 },
  { id: "semantic", name: "Semantic Router", score: 0.88 },
  { id: "hybrid", name: "Hybrid Search", score: 0.75 },
];

export default function Playground() {
  const [query, setQuery] = useState("");
  const [selectedPipeline1, setSelectedPipeline1] = useState("default");
  const [selectedPipeline2, setSelectedPipeline2] = useState("semantic");
  const [compareMode, setCompareMode] = useState(false);
  const [runId1, setRunId1] = useState<string | null>(null);
  const [runId2, setRunId2] = useState<string | null>(null);
  const [evalScores1, setEvalScores1] = useState<any>(null);
  const [evalScores2, setEvalScores2] = useState<any>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedCitation, setSelectedCitation] = useState<any>(null);

  const stream1 = useSSEStream(runId1);
  const stream2 = useSSEStream(runId2);

  const handleQuery = () => {
    // In a real app, this would POST /query to get the runId
    // For now, we simulate starting a stream by setting a runId
    setRunId1(Date.now().toString() + "1");
    setEvalScores1(null);
    if (compareMode) {
      setRunId2(Date.now().toString() + "2");
      setEvalScores2(null);
    }
  };

  // Simulate async evaluation arriving after streaming completes
  useEffect(() => {
    if (stream1.isComplete && !evalScores1) {
      const timer = setTimeout(() => {
        setEvalScores1({
          faithfulness: 0.95,
          answer_relevance: 0.89,
          context_precision: 0.92,
          context_recall: 0.85
        });
      }, 2000);
      return () => clearTimeout(timer);
    }
  }, [stream1.isComplete, evalScores1]);

  useEffect(() => {
    if (compareMode && stream2.isComplete && !evalScores2) {
      const timer = setTimeout(() => {
        setEvalScores2({
          faithfulness: 0.75,
          answer_relevance: 0.82,
          context_precision: 0.65,
          context_recall: 0.70
        });
      }, 2000);
      return () => clearTimeout(timer);
    }
  }, [compareMode, stream2.isComplete, evalScores2]);

  const handleCitationClick = (citation: any) => {
    setSelectedCitation(citation);
    setDrawerOpen(true);
  };

  return (
    <div className="h-full p-8 flex flex-col gap-6 relative">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Query Playground</h1>
          <p className="text-white/50 mt-1">Test and compare pipeline performance interactively.</p>
        </div>
      </div>

      {/* Query Input Section */}
      <div className="glass-card p-6 rounded-xl flex flex-col gap-4">
        <div className="flex gap-4 items-center">
          <div className="flex-1">
            <label className="text-xs font-semibold text-white/50 uppercase tracking-wider mb-2 block">Primary Pipeline</label>
            <select 
              className="w-full bg-white/5 border border-white/10 rounded-lg p-2.5 text-sm focus:outline-none focus:border-primary/50"
              value={selectedPipeline1}
              onChange={(e) => setSelectedPipeline1(e.target.value)}
            >
              {pipelines.map(p => (
                <option key={p.id} value={p.id} className="bg-secondary">{p.name} (Avg Eval: {p.score})</option>
              ))}
            </select>
          </div>
          {compareMode && (
            <motion.div 
              initial={{ opacity: 0, x: -20 }} 
              animate={{ opacity: 1, x: 0 }} 
              className="flex-1"
            >
              <label className="text-xs font-semibold text-white/50 uppercase tracking-wider mb-2 block">Secondary Pipeline</label>
              <select 
                className="w-full bg-white/5 border border-white/10 rounded-lg p-2.5 text-sm focus:outline-none focus:border-primary/50"
                value={selectedPipeline2}
                onChange={(e) => setSelectedPipeline2(e.target.value)}
              >
                {pipelines.map(p => (
                  <option key={p.id} value={p.id} className="bg-secondary">{p.name} (Avg Eval: {p.score})</option>
                ))}
              </select>
            </motion.div>
          )}
        </div>

        <div className="relative">
          <textarea 
            className="w-full bg-black/40 border border-white/10 rounded-xl p-4 min-h-[120px] text-sm focus:outline-none focus:ring-2 focus:ring-primary/50 placeholder:text-white/30 resize-none transition-all"
            placeholder="Enter your query here..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="absolute bottom-4 right-4 text-xs text-white/40">
            {query.length} chars
          </div>
        </div>

        <div className="flex justify-between items-center">
          <label className="flex items-center gap-2 cursor-pointer text-sm font-medium text-white/70 hover:text-white transition-colors">
            <input 
              type="checkbox" 
              className="sr-only" 
              checked={compareMode}
              onChange={() => setCompareMode(!compareMode)}
            />
            <div className={`w-10 h-5 rounded-full p-1 transition-colors ${compareMode ? 'bg-primary' : 'bg-white/10'}`}>
              <motion.div 
                className="w-3 h-3 bg-white rounded-full shadow-sm"
                animate={{ x: compareMode ? 20 : 0 }}
                transition={{ type: "spring", stiffness: 500, damping: 30 }}
              />
            </div>
            <GitCompare size={16} className={compareMode ? "text-primary" : "text-white/40"} />
            Compare Mode
          </label>
          <button 
            onClick={handleQuery}
            disabled={!query.trim() || stream1.isStreaming || stream2.isStreaming}
            className="bg-primary hover:bg-primary/90 disabled:opacity-50 disabled:hover:bg-primary text-white px-6 py-2.5 rounded-lg font-medium text-sm flex items-center gap-2 transition-all shadow-[0_0_20px_rgba(59,130,246,0.3)] hover:shadow-[0_0_25px_rgba(59,130,246,0.5)]"
          >
            <Activity size={16} />
            {stream1.isStreaming ? "Generating..." : "Run Query"}
          </button>
        </div>
      </div>

      {/* Response Section */}
      <AnimatePresence>
        {(runId1 || runId2) && (
          <>
          <motion.div 
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className={`grid gap-6 flex-1 ${compareMode ? 'grid-cols-2' : 'grid-cols-1'}`}
          >
            {/* Panel 1 */}
            {runId1 && (
              <ResponsePanel 
                runId={runId1}
                title={pipelines.find(p => p.id === selectedPipeline1)?.name}
                stream={stream1} 
                evalScores={evalScores1}
                onCitationClick={handleCitationClick}
              />
            )}
            {/* Panel 2 */}
            {compareMode && runId2 && (
              <ResponsePanel 
                runId={runId2}
                title={pipelines.find(p => p.id === selectedPipeline2)?.name}
                stream={stream2} 
                evalScores={evalScores2}
                onCitationClick={handleCitationClick}
                isCompare
              />
            )}
          </motion.div>
          
          {compareMode && stream1.isComplete && stream2.isComplete && (
            <motion.div 
              initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}
              className="glass-card rounded-xl border border-white/5 p-6 mt-6"
            >
              <h3 className="font-semibold mb-4 text-lg">Response Divergence (Diff View)</h3>
              <div className="grid grid-cols-2 gap-4 text-sm font-mono leading-relaxed bg-black/40 p-4 rounded-lg">
                <div className="text-red-400 p-2 border-r border-white/10">
                  <del className="bg-red-500/20 no-underline">- {stream1.content?.substring(0, 50)}</del>
                  <span>{stream1.content?.substring(50)}</span>
                </div>
                <div className="text-green-400 p-2">
                  <ins className="bg-green-500/20 no-underline">+ {stream2.content?.substring(0, 50)}</ins>
                  <span>{stream2.content?.substring(50)}</span>
                </div>
              </div>
            </motion.div>
          )}
          </>
        )}
      </AnimatePresence>

      {/* Citation Drawer */}
      <AnimatePresence>
        {drawerOpen && (
          <>
            <motion.div 
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="absolute inset-0 bg-black/60 backdrop-blur-sm z-40 rounded-xl"
              onClick={() => setDrawerOpen(false)}
            />
            <motion.div 
              initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }}
              transition={{ type: "spring", damping: 25, stiffness: 200 }}
              className="absolute top-0 right-0 bottom-0 w-[400px] glass-card border-l border-white/10 z-50 p-6 flex flex-col"
            >
              <div className="flex justify-between items-center mb-6">
                <h3 className="text-lg font-semibold">Citation Details</h3>
                <button onClick={() => setDrawerOpen(false)} className="text-white/50 hover:text-white">
                  <ChevronRight size={20} />
                </button>
              </div>
              <div className="flex-1 overflow-y-auto">
                <div className="bg-black/30 p-4 rounded-lg text-sm text-white/80 leading-relaxed border border-white/5">
                  "This is the simulated chunk content that the LLM used to generate the answer. In a real system, this would display the exact text passage retrieved from the vector database, along with its metadata."
                </div>
                <div className="mt-6">
                  <h4 className="text-xs font-semibold text-white/50 uppercase tracking-wider mb-3">Metadata</h4>
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between border-b border-white/5 pb-2">
                      <span className="text-white/40">File</span>
                      <span className="text-white/80">document_v2.pdf</span>
                    </div>
                    <div className="flex justify-between border-b border-white/5 pb-2">
                      <span className="text-white/40">Relevance</span>
                      <span className="text-primary font-medium">0.89</span>
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

function ResponsePanel({ runId, stream, evalScores, title, onCitationClick, isCompare = false }: any) {
  const [showInspector, setShowInspector] = useState(false);

  // Mock citations
  const citations = [
    { id: 1, name: "source_doc.pdf", relevance: 0.89 },
    { id: 2, name: "financials.csv", relevance: 0.72 }
  ];

  const handleRating = async (rating: number) => {
    try {
      await fetch(`http://localhost:8000/runs/${runId}/rating`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rating })
      });
      console.log(`Rating ${rating} submitted for ${runId}`);
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="glass-card rounded-xl flex flex-col h-full border border-white/5 relative overflow-hidden">
      {/* Decorative top border glow */}
      <div className="absolute top-0 left-0 right-0 h-[1px] bg-gradient-to-r from-transparent via-primary/50 to-transparent opacity-50" />
      
      <div className="p-4 border-b border-white/5 flex justify-between items-center bg-white/[0.02]">
        <h3 className="font-medium text-sm text-white/80 flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${stream.isStreaming ? 'bg-primary animate-pulse' : 'bg-green-500'}`} />
          {title}
        </h3>
        {stream.isComplete && (
          <div className="flex gap-2">
            <button onClick={() => handleRating(5)} className="p-1.5 text-white/40 hover:text-green-500 hover:bg-green-500/10 rounded-md transition-colors">
              <ThumbsUp size={14} />
            </button>
            <button onClick={() => handleRating(1)} className="p-1.5 text-white/40 hover:text-red-500 hover:bg-red-500/10 rounded-md transition-colors">
              <ThumbsDown size={14} />
            </button>
          </div>
        )}
      </div>
      
      <div className="p-5 flex-1 overflow-y-auto">
        {/* Retrieved Sources (Shows immediately) */}
        {(stream.isStreaming || stream.isComplete) && (
          <div className="mb-4 bg-black/30 p-3 rounded-lg border border-white/5">
            <h4 className="text-[10px] uppercase tracking-wider text-white/40 mb-2 font-bold">Retrieved Sources</h4>
            <div className="space-y-1.5">
              {citations.map(c => (
                <div key={c.id} className="flex justify-between items-center text-xs">
                  <span className="text-white/70 font-mono truncate">{c.name}</span>
                  <span className="text-primary font-medium">{c.relevance.toFixed(2)} score</span>
                </div>
              ))}
            </div>
          </div>
        )}
        {/* Answer streaming */}
        <div className="text-sm leading-relaxed text-white/90 whitespace-pre-wrap font-medium">
          {stream.content || (stream.isStreaming ? "Thinking..." : "Waiting to generate...")}
          {stream.isStreaming && (
            <motion.span 
              animate={{ opacity: [1, 0] }} 
              transition={{ repeat: Infinity, duration: 0.8 }}
              className="inline-block w-1.5 h-4 ml-1 align-middle bg-primary"
            />
          )}
        </div>

        {/* Citations (Chips after streaming) */}
        {stream.isComplete && stream.content && (
          <motion.div 
            initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}
            className="mt-6 flex flex-wrap gap-2"
          >
            <span className="text-xs text-white/40 flex items-center mr-2">Citations:</span>
            {citations.map((c) => (
              <button 
                key={c.id}
                onClick={() => onCitationClick(c)}
                className="text-xs bg-primary/10 border border-primary/20 text-primary hover:bg-primary/20 px-2 py-1 rounded-md transition-colors flex items-center gap-1"
              >
                [{c.id}] {c.name}
              </button>
            ))}
          </motion.div>
        )}

        {/* Evaluation Scores */}
        <AnimatePresence>
          {evalScores && (
            <motion.div 
              initial={{ opacity: 0, height: 0 }} 
              animate={{ opacity: 1, height: 'auto' }} 
              className="mt-8 pt-6 border-t border-white/10"
            >
              <div className="flex justify-between items-center mb-4">
                <h4 className="text-xs font-semibold text-white/50 uppercase tracking-wider">Real-time Evaluation</h4>
                <button 
                  onClick={() => setShowInspector(!showInspector)}
                  className={`text-xs px-3 py-1.5 rounded flex items-center gap-2 transition-colors ${showInspector ? 'bg-primary/20 text-primary border border-primary/30' : 'bg-white/5 text-white/60 hover:text-white hover:bg-white/10'}`}
                >
                  <Network size={14} />
                  {showInspector ? 'Hide Retrieval Inspector' : 'View Retrieval Inspector'}
                </button>
              </div>
              
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
                <AnimatedGauge value={evalScores.faithfulness} label="Faithful" />
                <AnimatedGauge value={evalScores.answer_relevance} label="Relevance" />
                <AnimatedGauge value={evalScores.context_precision} label="Precision" />
                <AnimatedGauge value={evalScores.context_recall} label="Recall" />
              </div>
              
              {showInspector && (
                <motion.div 
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="mt-6 border-t border-white/10 pt-6"
                >
                  <h4 className="text-xs font-semibold text-white/50 uppercase tracking-wider mb-4">Retrieval Pipeline Execution</h4>
                  <RetrievalInspector />
                </motion.div>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
