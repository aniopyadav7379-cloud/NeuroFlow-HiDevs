import { create } from "zustand";

interface PlaygroundState {
  pipelineAId: string | null;
  pipelineBId: string | null;
  compareMode: boolean;
  query: string;
  setPipelineA: (id: string | null) => void;
  setPipelineB: (id: string | null) => void;
  setCompareMode: (v: boolean) => void;
  setQuery: (q: string) => void;
}

export const usePlaygroundStore = create<PlaygroundState>((set) => ({
  pipelineAId: null,
  pipelineBId: null,
  compareMode: false,
  query: "",
  setPipelineA: (id) => set({ pipelineAId: id }),
  setPipelineB: (id) => set({ pipelineBId: id }),
  setCompareMode: (v) => set({ compareMode: v }),
  setQuery: (q) => set({ query: q }),
}));
