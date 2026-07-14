import { useState, useEffect } from "react";
import { Loader2, ChevronLeft, ChevronRight, Search } from "lucide-react";
import { Badge } from "../../ui/badge";
import { cn } from "../../../lib/utils";
import { withBasePath } from "../../../lib/basePath";

export interface FaultAnalysisJob {
  id: string;
  status: "queued" | "processing" | "completed" | "failed";
  created_at: string;
  updated_at: string;
  error_message?: string;
  station: string;
  device: string;
  device_type: string;
  voltage_level: string;
  result_file_name?: string;
  download_url?: string;
  preview_url?: string;
  progress: number;
  progress_message?: string;
  evaluation?: string;
}

function formatDateTime(isoString: string): string {
  if (!isoString) return "";
  try {
    const date = new Date(isoString);
    if (isNaN(date.getTime())) return isoString;
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    const hours = String(date.getHours()).padStart(2, "0");
    const minutes = String(date.getMinutes()).padStart(2, "0");
    return `${year}-${month}-${day} ${hours}:${minutes}`;
  } catch {
    return isoString;
  }
}

function statusBadgeClass(status: FaultAnalysisJob["status"]) {
  if (status === "completed") return "bg-[#dcecec] text-[#0d5d57] hover:bg-[#dcecec]";
  if (status === "failed") return "bg-[#f5d5d5] text-[#cc3333] hover:bg-[#f5d5d5]";
  if (status === "processing") return "bg-[#d5e8f5] text-[#00706b] hover:bg-[#d5e8f5]";
  return "bg-[#f5f5f5] text-[#888] hover:bg-[#f5f5f5]";
}

function getDeviceName(job: FaultAnalysisJob): string {
  const s = job.station || "";
  const d = job.device || "";
  if (!s && !d) return "-";
  if (s === d) return s;
  if (!s) return d;
  if (!d) return s;
  return `${s} ${d}`;
}

async function fetchJobs(): Promise<FaultAnalysisJob[]> {
  const response = await fetch(withBasePath("/api/fault-analysis/jobs"));
  if (!response.ok) throw new Error("Failed to fetch jobs");
  return response.json();
}

interface FaultAnalysisJobListProps {
  selectedJobId: string | null;
  onSelect: (job: FaultAnalysisJob) => void;
}

export function FaultAnalysisJobList({ selectedJobId, onSelect }: FaultAnalysisJobListProps) {
  const [jobs, setJobs] = useState<FaultAnalysisJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [nameFilter, setNameFilter] = useState("");

  const PAGE_SIZE = 50;
  const filteredJobs = jobs.filter((j) => {
    if (!nameFilter) return true;
    const name = getDeviceName(j).toLowerCase();
    const station = (j.station || "").toLowerCase();
    const device = (j.device || "").toLowerCase();
    const query = nameFilter.toLowerCase();
    return name.includes(query) || station.includes(query) || device.includes(query);
  });
  const totalPages = Math.max(1, Math.ceil(filteredJobs.length / PAGE_SIZE));
  const paginatedJobs = filteredJobs.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  useEffect(() => {
    fetchJobs()
      .then((data) => { setJobs(data); setLoading(false); })
      .catch((err) => { setError(err.message); setLoading(false); });
  }, []);

  useEffect(() => {
    if (currentPage > totalPages) setCurrentPage(totalPages);
  }, [filteredJobs.length, totalPages, currentPage]);

  useEffect(() => {
    if (jobs.some((j) => j.status === "queued" || j.status === "processing")) {
      const interval = setInterval(() => {
        fetchJobs().then(setJobs).catch(() => {});
      }, 3000);
      return () => clearInterval(interval);
    }
  }, [jobs]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8 text-[#666]">
        <Loader2 className="h-5 w-5 animate-spin" />
        <span className="ml-2 text-sm">加载中...</span>
      </div>
    );
  }

  if (error) {
    return <div className="p-3 text-sm text-[#cc3333]">{error}</div>;
  }

  return (
    <div className="flex flex-col h-full">
      {/* Filter */}
      <div className="shrink-0 px-3 py-2">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-[#888]" />
          <input
            type="text"
            value={nameFilter}
            onChange={(e) => { setNameFilter(e.target.value); setCurrentPage(1); }}
            placeholder="筛选厂站/设备..."
            className="w-full h-8 pl-8 pr-3 rounded-lg border border-[#e0e0e0] bg-white text-xs text-[#333] placeholder:text-[#aaa] focus:outline-none focus:border-[#298c88] focus:ring-1 focus:ring-[#298c88]/30"
          />
        </div>
      </div>

      {/* Job list */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {paginatedJobs.length === 0 ? (
          <div className="flex items-center justify-center py-8 text-sm text-[#888]">
            {nameFilter ? "没有匹配的任务" : "暂无任务"}
          </div>
        ) : (
          <div className="space-y-0.5 px-2">
            {paginatedJobs.map((job) => {
              const isSelected = job.id === selectedJobId;
              return (
                <div
                  key={job.id}
                  onClick={() => onSelect(job)}
                  className={cn(
                    "flex flex-col gap-1 rounded-xl px-3 py-2.5 cursor-pointer transition-colors",
                    isSelected
                      ? "bg-[#dcecec] text-[#0d5d57]"
                      : "hover:bg-[#f0f7fa] text-[#555]"
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-medium truncate flex-1" title={getDeviceName(job)}>
                      {getDeviceName(job)}
                    </span>
                    <Badge className={cn("rounded-full px-1.5 py-0.5 text-[10px] font-medium shrink-0", statusBadgeClass(job.status))}>
                      {job.status === "completed" ? "完成" : job.status === "processing" ? "处理中" : job.status === "failed" ? "失败" : "排队中"}
                    </Badge>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] text-[#888]">{job.device_type || ""}</span>
                    <span className="text-[10px] text-[#888]">{formatDateTime(job.created_at)}</span>
                  </div>
                  {job.status === "processing" && job.progress > 0 && (
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-1 bg-[#e8f0f0] rounded-full overflow-hidden">
                        <div
                          className="h-full bg-[#298c88] transition-all duration-300"
                          style={{ width: `${job.progress}%` }}
                        />
                      </div>
                      <span className="text-[10px] text-[#298c88]">{job.progress}%</span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Pagination */}
      {filteredJobs.length > PAGE_SIZE && (
        <div className="shrink-0 flex items-center justify-between border-t border-[#e8f0f0] px-3 py-2">
          <span className="text-[10px] text-[#888]">{filteredJobs.length} 条</span>
          <div className="flex items-center gap-1">
            <button
              disabled={currentPage <= 1}
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              className="inline-flex h-6 w-6 items-center justify-center rounded border border-[#e0e0e0] bg-white text-[#555] disabled:opacity-40"
            >
              <ChevronLeft className="h-3 w-3" />
            </button>
            <span className="text-[10px] text-[#666]">{currentPage}/{totalPages}</span>
            <button
              disabled={currentPage >= totalPages}
              onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
              className="inline-flex h-6 w-6 items-center justify-center rounded border border-[#e0e0e0] bg-white text-[#555] disabled:opacity-40"
            >
              <ChevronRight className="h-3 w-3" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
