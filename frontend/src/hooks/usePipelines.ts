import { useQuery } from "@tanstack/react-query";
import { listPipelines } from "@/lib/api";

export function usePipelines() {
  return useQuery({
    queryKey: ["pipelines"],
    queryFn: listPipelines,
  });
}
