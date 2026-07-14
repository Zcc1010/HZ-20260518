import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import api from "../lib/api";
import i18n from "../i18n";

export interface ToolMemory {
  tool: string;
  memory: string;
}

export function useToolMemories() {
  return useQuery<string[]>({
    queryKey: ["tool-memories"],
    queryFn: () => api.get("/sessions/tools/memory").then((r) => r.data),
  });
}

export function useToolMemory(toolName: string) {
  return useQuery<ToolMemory>({
    queryKey: ["tool-memory", toolName],
    queryFn: () =>
      api.get(`/sessions/tools/${encodeURIComponent(toolName)}/memory`).then((r) => r.data),
    enabled: !!toolName,
  });
}

export function useUpdateToolMemory(toolName: string) {
  const qc = useQueryClient();
  return mutationWithToast({
    mutationFn: (content: string) =>
      api.put(`/sessions/tools/${encodeURIComponent(toolName)}/memory`, { content }).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tool-memory", toolName] });
      qc.invalidateQueries({ queryKey: ["tool-memories"] });
    },
  });
}

function mutationWithToast<TData, TVariables>(config: {
  mutationFn: (variables: TVariables) => Promise<TData>;
  onSuccess?: (data: TData, variables: TVariables) => void;
}) {
  return useMutation({
    ...config,
    onSuccess: (data, variables) => {
      toast.success(i18n.t("memory.saveSuccess", "Memory saved"));
      config.onSuccess?.(data, variables);
    },
    onError: () => {
      toast.error(i18n.t("memory.saveError", "Failed to save memory"));
    },
  });
}
