import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "../lib/api";

export interface GFileCompareJob {
  id: string;
  app_id: string;
  status: "queued" | "processing" | "completed" | "failed";
  created_at: string;
  updated_at: string;
  error_message?: string | null;
  d5000_file_name: string;
  new_gen_file_name: string;
  result_file_name?: string | null;
  download_url?: string | null;
}

interface CreateGFileCompareJobPayload {
  d5000File: File;
  newGenFile: File;
}

export function useGFileCompareJobs() {
  return useQuery<GFileCompareJob[]>({
    queryKey: ["g-file-compare", "jobs"],
    queryFn: () => api.get("/g-file-compare/jobs").then((response) => response.data),
    refetchInterval: (query) => {
      const jobs = query.state.data ?? [];
      return jobs.some((job) => job.status === "queued" || job.status === "processing") ? 3000 : false;
    },
  });
}

export function useCreateGFileCompareJob() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ d5000File, newGenFile }: CreateGFileCompareJobPayload) => {
      const formData = new FormData();
      formData.append("d5000_file", d5000File);
      formData.append("new_gen_file", newGenFile);
      const response = await api.post<GFileCompareJob>("/g-file-compare/jobs", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      return response.data;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["g-file-compare", "jobs"] });
    },
  });
}
