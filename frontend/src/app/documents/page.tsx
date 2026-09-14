"use client";

import { useState, useCallback } from "react";
import { Upload, File, FileText, Search, ChevronRight, CheckCircle2, Clock, Image as ImageIcon } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

const mockDocs = [
  { id: "1", name: "Q3_Financial_Report.pdf", type: "pdf", status: "completed", chunks: 45, date: "2026-06-28T10:00:00Z" },
  { id: "2", name: "Product_Roadmap_v2.docx", type: "docx", status: "processing", chunks: null, date: "2026-06-29T14:30:00Z" },
  { id: "3", name: "architecture_diagram.png", type: "image", status: "completed", chunks: 5, date: "2026-06-25T09:15:00Z" },
];

const mockChunks = [
  { id: "c1", content: "Revenue for Q3 exceeded expectations by 15%, driven primarily by the new enterprise tier.", similarity: 0.95 },
  { id: "c2", content: "Operating costs were reduced by optimizing cloud infrastructure allocations.", similarity: 0.62 },
  { id: "c3", content: "The enterprise tier adoption rate was highest in the EMEA region.", similarity: 0.88 },
];

export default function DocumentsPage() {
  const [isDragging, setIsDragging] = useState(false);
  const [uploads, setUploads] = useState<any[]>([]);
  const [selectedDoc, setSelectedDoc] = useState<any>(null);
  const [searchActive, setSearchActive] = useState(false);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    
    const files = Array.from(e.dataTransfer.files);
    const newUploads = files.map(f => ({
      id: Math.random().toString(),
      file: f,
      progress: 0,
    }));
    
    setUploads(prev => [...prev, ...newUploads]);
    
    // Simulate upload progress
    newUploads.forEach(u => {
      let prog = 0;
      const interval = setInterval(() => {
        prog += Math.random() * 20;
        if (prog >= 100) {
          prog = 100;
          clearInterval(interval);
        }
        setUploads(current => current.map(curr => 
          curr.id === u.id ? { ...curr, progress: prog } : curr
        ));
      }, 300);
    });
  };

  const getFileIcon = (type: string) => {
    switch (type) {
      case 'pdf': return <FileText className="text-red-400" size={20} />;
      case 'image': return <ImageIcon className="text-blue-400" size={20} />;
      default: return <File className="text-blue-400" size={20} />;
    }
  };

  return (
    <div className="h-full p-8 flex flex-col gap-8 relative overflow-hidden">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Document Knowledge Base</h1>
        <p className="text-white/50 mt-1">Ingest, manage, and inspect vectorized documents.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 flex-1 min-h-0">
        
        {/* Left Column: Upload & List */}
        <div className="lg:col-span-2 flex flex-col gap-6 overflow-hidden">
          
          {/* Upload Zone */}
          <div 
            className={`border-2 border-dashed rounded-xl p-8 flex flex-col items-center justify-center transition-all ${
              isDragging ? 'border-primary bg-primary/10' : 'border-white/20 bg-black/20 hover:border-white/40 hover:bg-black/40'
            }`}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <div className="p-4 bg-white/5 rounded-full mb-4">
              <Upload className={isDragging ? "text-primary" : "text-white/40"} size={32} />
            </div>
            <p className="text-sm font-medium mb-1">Drag and drop files here</p>
            <p className="text-xs text-white/50 mb-4">Supports PDF, DOCX, TXT, CSV, PNG (max 50MB)</p>
            <button className="text-xs bg-white/10 hover:bg-white/20 px-4 py-2 rounded-lg font-medium transition-colors">
              Browse Files
            </button>
          </div>

          {/* Active Uploads */}
          {uploads.length > 0 && (
            <div className="space-y-3">
              <h3 className="text-sm font-semibold text-white/70">Uploading ({uploads.length})</h3>
              {uploads.map(u => (
                <div key={u.id} className="glass-card p-3 rounded-lg flex items-center gap-4">
                  <div className="p-2 bg-white/5 rounded-md">
                    <File size={16} className="text-white/60" />
                  </div>
                  <div className="flex-1">
                    <div className="flex justify-between text-sm mb-1">
                      <span className="font-medium line-clamp-1">{u.file.name}</span>
                      <span className="text-white/50">{(u.file.size / 1024 / 1024).toFixed(1)} MB</span>
                    </div>
                    <div className="h-1.5 bg-white/10 rounded-full overflow-hidden">
                      <motion.div 
                        className="h-full bg-primary" 
                        initial={{ width: 0 }}
                        animate={{ width: `${u.progress}%` }}
                      />
                    </div>
                  </div>
                  {u.progress >= 100 ? (
                    <CheckCircle2 size={18} className="text-green-500" />
                  ) : (
                    <span className="text-xs font-medium text-white/50 w-8 text-right">{Math.round(u.progress)}%</span>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Document Table */}
          <div className="glass-card rounded-xl border border-white/5 flex-1 flex flex-col overflow-hidden">
            <div className="p-4 border-b border-white/10 bg-white/5">
              <h3 className="font-semibold">Ingested Documents</h3>
            </div>
            <div className="flex-1 overflow-y-auto p-4">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="text-white/40 uppercase tracking-wider text-[10px] border-b border-white/10">
                    <th className="pb-3 font-medium">Name</th>
                    <th className="pb-3 font-medium">Status</th>
                    <th className="pb-3 font-medium text-right">Chunks</th>
                    <th className="pb-3 font-medium text-right">Ingested At</th>
                  </tr>
                </thead>
                <tbody>
                  {mockDocs.map(doc => (
                    <tr 
                      key={doc.id} 
                      onClick={() => setSelectedDoc(doc)}
                      className={`border-b border-white/5 cursor-pointer hover:bg-white/5 transition-colors ${
                        selectedDoc?.id === doc.id ? 'bg-white/5' : ''
                      }`}
                    >
                      <td className="py-4 flex items-center gap-3">
                        {getFileIcon(doc.type)}
                        <span className="font-medium text-white/90">{doc.name}</span>
                      </td>
                      <td className="py-4">
                        {doc.status === 'processing' ? (
                          <span className="inline-flex items-center gap-1.5 text-xs text-blue-400 bg-blue-400/10 px-2 py-1 rounded border border-blue-400/20">
                            <span className="relative flex h-2 w-2">
                              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>
                              <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-500"></span>
                            </span>
                            Processing
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 text-xs text-green-400 bg-green-400/10 px-2 py-1 rounded border border-green-400/20">
                            <div className="w-1.5 h-1.5 rounded-full bg-green-400" />
                            Completed
                          </span>
                        )}
                      </td>
                      <td className="py-4 text-right text-white/60">{doc.chunks || '-'}</td>
                      <td className="py-4 text-right text-white/50 text-xs">
                        {new Date(doc.date).toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Right Column: Chunk Inspector */}
        <AnimatePresence mode="wait">
          {selectedDoc ? (
            <motion.div 
              key="inspector"
              initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 20 }}
              className="glass-card rounded-xl border border-white/5 flex flex-col overflow-hidden h-full"
            >
              <div className="p-5 border-b border-white/10 bg-black/20">
                <div className="flex items-center gap-3 mb-2">
                  {getFileIcon(selectedDoc.type)}
                  <h3 className="font-semibold line-clamp-1">{selectedDoc.name}</h3>
                </div>
                <div className="flex gap-4 text-xs text-white/50">
                  <span className="flex items-center gap-1"><Clock size={12}/> {new Date(selectedDoc.date).toLocaleDateString()}</span>
                  <span>{selectedDoc.chunks} Chunks Vectorized</span>
                </div>
              </div>
              
              <div className="p-4 border-b border-white/5">
                <button 
                  onClick={() => setSearchActive(!searchActive)}
                  className={`w-full py-2.5 rounded-lg text-sm font-medium flex items-center justify-center gap-2 transition-all ${
                    searchActive 
                      ? 'bg-primary/20 text-primary border border-primary/30' 
                      : 'bg-white/5 hover:bg-white/10 border border-transparent'
                  }`}
                >
                  <Search size={16} />
                  {searchActive ? 'Showing Similar Chunks' : 'Find Similar Chunks'}
                </button>
              </div>

              <div className="flex-1 overflow-y-auto p-4 space-y-3">
                {mockChunks.map((chunk, i) => (
                  <motion.div 
                    key={chunk.id}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.1 }}
                    className={`p-4 rounded-lg text-sm leading-relaxed border ${
                      searchActive && chunk.similarity > 0.8
                        ? 'bg-primary/10 border-primary/30'
                        : 'bg-black/40 border-white/5'
                    }`}
                  >
                    {searchActive && (
                      <div className="flex justify-between items-center mb-2">
                        <span className="text-[10px] uppercase font-bold tracking-wider text-primary">Similarity Score</span>
                        <span className="text-xs font-bold text-primary bg-primary/20 px-2 py-0.5 rounded">{(chunk.similarity * 100).toFixed(1)}%</span>
                      </div>
                    )}
                    <span className="text-white/80">{chunk.content}</span>
                  </motion.div>
                ))}
              </div>
            </motion.div>
          ) : (
            <motion.div 
              key="empty"
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="glass-card rounded-xl border border-white/5 border-dashed flex flex-col items-center justify-center h-full text-white/40 p-8 text-center"
            >
              <FileText size={48} className="mb-4 opacity-20" />
              <p className="font-medium mb-1">Select a document</p>
              <p className="text-sm opacity-60">Click on any document in the list to inspect its vectorized chunks and run similarity searches.</p>
            </motion.div>
          )}
        </AnimatePresence>

      </div>
    </div>
  );
}
