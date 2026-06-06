import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Download, Plus, Loader2, FileDown, ChevronLeft, ChevronRight, Eye, Trash2, FileArchive, Upload, Zap, Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Button } from "../../ui/button";
import { Badge } from "../../ui/badge";
import { cn } from "../../../lib/utils";
import { withBasePath } from "../../../lib/basePath";
import { MarkdownRenderer } from "../../shared/MarkdownRenderer";

interface WaveRecordJob {
  id: string;
  app_id: string;
  status: "queued" | "processing" | "completed" | "failed";
  created_at: string;
  updated_at: string;
  error_message?: string;
  file_name: string;
  result_file_name?: string;
  download_url?: string;
  preview_url?: string;
  station?: string;
  device?: string;
  progress: number;
  progress_message?: string;
  evaluation?: string;
  external_id?: string;
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
    const seconds = String(date.getSeconds()).padStart(2, "0");
    return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
  } catch {
    return isoString;
  }
}

function statusBadgeClass(status: WaveRecordJob["status"]) {
  if (status === "completed") {
    return "bg-[#dcecec] text-[#0d5d57] hover:bg-[#dcecec]";
  }
  if (status === "failed") {
    return "bg-[#f5d5d5] text-[#cc3333] hover:bg-[#f5d5d5]";
  }
  if (status === "processing") {
    return "bg-[#d5e8f5] text-[#00706b] hover:bg-[#d5e8f5]";
  }
  return "bg-[#f5f5f5] text-[#888] hover:bg-[#f5f5f5]";
}

async function fetchJobs(): Promise<WaveRecordJob[]> {
  const response = await fetch(withBasePath("/api/wave-record-parser/jobs"));
  if (!response.ok) {
    throw new Error("Failed to fetch jobs");
  }
  return response.json();
}

const CHUNK_SIZE = 1 * 1024 * 1024; // 1MB

async function createJob(
  files: File[],
  station: string,
  device: string,
  deviceType: string,
  onProgress?: (fileIndex: number, fileProgress: number) => void,
): Promise<WaveRecordJob> {
  // Only one zip file is expected, but handle the first zip
  const zipFile = files.find((f) => f.name.toLowerCase().endsWith(".zip"));
  if (!zipFile) throw new Error("No zip file found");

  const totalChunks = Math.ceil(zipFile.size / CHUNK_SIZE);

  // Step 1: Init upload
  const initRes = await fetch(withBasePath("/api/wave-record-parser/uploads/init"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      file_name: zipFile.name,
      total_size: zipFile.size,
      total_chunks: totalChunks,
    }),
  });
  if (!initRes.ok) {
    throw new Error("Failed to initialize upload");
  }
  const { upload_id } = await initRes.json();

  // Step 2: Upload chunks
  for (let i = 0; i < totalChunks; i++) {
    const start = i * CHUNK_SIZE;
    const end = Math.min(start + CHUNK_SIZE, zipFile.size);
    const chunk = zipFile.slice(start, end);

    const formData = new FormData();
    formData.append("chunk", chunk, zipFile.name);

    const chunkRes = await fetch(
      withBasePath(`/api/wave-record-parser/uploads/${upload_id}/chunks/${i}`),
      { method: "POST", body: formData },
    );
    if (!chunkRes.ok) {
      throw new Error(`Failed to upload chunk ${i + 1}/${totalChunks}`);
    }

    if (onProgress) {
      onProgress(0, Math.round(((i + 1) / totalChunks) * 100));
    }
  }

  // Step 3: Complete upload and create job
  const completeRes = await fetch(
    withBasePath(`/api/wave-record-parser/uploads/${upload_id}/complete`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ station, device, device_type: deviceType }),
    },
  );
  if (!completeRes.ok) {
    const error = await completeRes.text();
    throw new Error(error || "Failed to complete upload");
  }
  return completeRes.json();
}

const PAGE_SIZE = 20;

export function WaveRecordWorkspace() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [jobs, setJobs] = useState<WaveRecordJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewTitle, setPreviewTitle] = useState("");
  const [previewContent, setPreviewContent] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<WaveRecordJob | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [exporting, setExporting] = useState(false);
  const [batchDialogOpen, setBatchDialogOpen] = useState(false);
  const [stationFilter, setStationFilter] = useState("");
  const [deviceFilter, setDeviceFilter] = useState("");

  const filteredJobs = jobs.filter((j) => {
    if (stationFilter && !(j.station || "").toLowerCase().includes(stationFilter.toLowerCase())) return false;
    if (deviceFilter && !(j.device || "").toLowerCase().includes(deviceFilter.toLowerCase())) return false;
    return true;
  });
  const totalPages = Math.max(1, Math.ceil(filteredJobs.length / PAGE_SIZE));
  const paginatedJobs = filteredJobs.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  useEffect(() => {
    fetchJobs()
      .then((data) => {
        setJobs(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, []);

  // 确保当前页不超出范围
  useEffect(() => {
    if (currentPage > totalPages) {
      setCurrentPage(totalPages);
    }
  }, [jobs.length, totalPages, currentPage]);

  // 清理已删除任务的选中状态
  useEffect(() => {
    const jobIds = new Set(jobs.map((j) => j.id));
    setSelectedIds((prev) => {
      const next = new Set(Array.from(prev).filter((id) => jobIds.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [jobs]);

  useEffect(() => {
    if (jobs.some((job) => job.status === "queued" || job.status === "processing")) {
      const interval = setInterval(() => {
        fetchJobs()
          .then((data) => setJobs(data))
          .catch(() => {});
      }, 1500);
      return () => clearInterval(interval);
    }
  }, [jobs]);

  const saveEvaluation = async (jobId: string, value: string) => {
    try {
      const res = await fetch(withBasePath(`/api/wave-record-parser/jobs/${jobId}`), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ evaluation: value }),
      });
      if (res.ok) {
        const updated = await res.json();
        setJobs((prev) => prev.map((j) => (j.id === jobId ? { ...j, evaluation: updated.evaluation } : j)));
      }
    } catch {
      // ignore
    }
    setEditingId(null);
  };

  const openPreview = async (url: string, title: string) => {
    setPreviewOpen(true);
    setPreviewTitle(title);
    setPreviewLoading(true);
    setPreviewContent("");
    try {
      const res = await fetch(withBasePath(url));
      if (res.ok) {
        const data = await res.json();
        let text = (data.content || "").replace(/\r\n/g, "\n");
        // Strip LLM preamble + ```markdown code block wrapper
        const fenceIdx = text.indexOf("```markdown\n");
        if (fenceIdx !== -1) {
          text = text.slice(fenceIdx + 12);
          const closeIdx = text.lastIndexOf("\n```");
          if (closeIdx !== -1) {
            text = text.slice(0, closeIdx);
          }
          text = text.trim();
        }
        setPreviewContent(text);
      } else {
        setPreviewContent("加载失败");
      }
    } catch {
      setPreviewContent("加载失败");
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      const res = await fetch(withBasePath(`/api/wave-record-parser/jobs/${deleteTarget.id}`), { method: "DELETE" });
      if (res.ok) {
        setJobs((prev) => prev.filter((j) => j.id !== deleteTarget.id));
        setDeleteTarget(null);
      }
    } finally {
      setDeleting(false);
    }
  };

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    const selectable = paginatedJobs.filter((j) => j.status === "completed" && j.download_url);
    if (selectable.length === 0) return;
    const allSelected = selectable.every((j) => selectedIds.has(j.id));
    if (allSelected) {
      setSelectedIds((prev) => {
        const next = new Set(prev);
        selectable.forEach((j) => next.delete(j.id));
        return next;
      });
    } else {
      setSelectedIds((prev) => {
        const next = new Set(prev);
        selectable.forEach((j) => next.add(j.id));
        return next;
      });
    }
  };

  const handleExport = async () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) {
      toast.error(t("agentPlayground.table.exportEmpty"));
      return;
    }
    setExporting(true);
    try {
      const res = await fetch(withBasePath("/api/wave-record-parser/jobs/export"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_ids: ids }),
      });
      if (res.ok) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "跳闸简报导出.zip";
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      }
    } finally {
      setExporting(false);
    }
  };

  const selectedCount = selectedIds.size;

  return (
    <>
      <div className="space-y-5">
        <div className="flex flex-col gap-4 rounded-[24px] border border-[#e0e0e0] bg-white p-4 shadow-md sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.18em] text-[#888]">
              {t("agentPlayground.title")}
            </p>
            <h2 className="brand-display mt-2 text-2xl text-[#000]">
              {t("agentPlayground.apps.waveRecordParser.title")}
            </h2>
          </div>

          <div className="flex items-center gap-2 self-start sm:self-auto">
            <Button
              onClick={handleExport}
              disabled={exporting}
              className="gap-2 bg-[#00706b] hover:bg-[#0d5d57] text-white border border-[#00706b]"
            >
              {exporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileArchive className="h-4 w-4" />}
              {t("agentPlayground.table.exportSelected")}{selectedCount > 0 ? ` (${selectedCount})` : ""}
            </Button>
            <Button
              onClick={() => setBatchDialogOpen(true)}
              className="gap-2 bg-[#298c88] hover:bg-[#0d5d57] text-white border border-[#298c88]"
            >
              <Upload className="h-4 w-4" />
              {t("agentPlayground.waveRecord.batchUpload")}
            </Button>
            <Button
              onClick={() => setDialogOpen(true)}
              className="gap-2 bg-[#298c88] hover:bg-[#0d5d57] text-white border border-[#298c88]"
            >
              <Plus className="h-4 w-4" />
              {t("agentPlayground.create")}
            </Button>
          </div>
        </div>

        {/* 筛选栏 */}
        {!loading && !error && jobs.length > 0 && (
          <div className="flex items-center gap-3 mt-3">
            <div className="relative flex-1 max-w-[240px]">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[#888]" />
              <input
                type="text"
                value={stationFilter}
                onChange={(e) => { setStationFilter(e.target.value); setCurrentPage(1); }}
                placeholder="筛选厂站..."
                className="w-full h-9 pl-9 pr-3 rounded-lg border border-[#e0e0e0] bg-white text-sm text-[#333] placeholder:text-[#aaa] focus:outline-none focus:border-[#298c88] focus:ring-1 focus:ring-[#298c88]/30"
              />
            </div>
            <div className="relative flex-1 max-w-[240px]">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[#888]" />
              <input
                type="text"
                value={deviceFilter}
                onChange={(e) => { setDeviceFilter(e.target.value); setCurrentPage(1); }}
                placeholder="筛选装置..."
                className="w-full h-9 pl-9 pr-3 rounded-lg border border-[#e0e0e0] bg-white text-sm text-[#333] placeholder:text-[#aaa] focus:outline-none focus:border-[#298c88] focus:ring-1 focus:ring-[#298c88]/30"
              />
            </div>
            {(stationFilter || deviceFilter) && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => { setStationFilter(""); setDeviceFilter(""); setCurrentPage(1); }}
                className="text-[#888] hover:text-[#333] h-9 px-3"
              >
                清除
              </Button>
            )}
            <span className="text-xs text-[#888] ml-auto">
              {filteredJobs.length} / {jobs.length} 条
            </span>
          </div>
        )}

        {loading && (
          <div className="flex items-center justify-center py-10 text-[#666]">
            <Loader2 className="h-6 w-6 animate-spin" />
            <span className="ml-2">{t("agentPlayground.loading")}</span>
          </div>
        )}

        {error && (
          <div className="rounded-[24px] border border-red-300 bg-[#f5d5d5]/50 p-4 text-[#cc3333]">
            {error}
          </div>
        )}

        {!loading && !error && (
          <div className="rounded-[28px] border border-[#e0e0e0] bg-white shadow-md overflow-hidden flex flex-col" style={{ height: "calc(100vh - 252px)" }}>
            <div className="flex-1 overflow-auto">
              <table className="w-full text-sm border-separate border-spacing-0" style={{ minWidth: 800 }}>
                <thead className="bg-[#0d5d57] sticky top-0 z-10">
                  <tr className="border-b border-[#e8f0f0]">
                    <th className="px-3 py-4 text-center w-[40px]">
                      <input
                        type="checkbox"
                        checked={paginatedJobs.filter((j) => j.status === "completed" && j.download_url).length > 0 && paginatedJobs.filter((j) => j.status === "completed" && j.download_url).every((j) => selectedIds.has(j.id))}
                        onChange={toggleSelectAll}
                        className="h-4 w-4 accent-[#298c88] cursor-pointer"
                      />
                    </th>
                    <th className="px-5 py-4 text-left font-medium text-[#dcecec]">
                      {t("agentPlayground.waveRecord.table.station")}
                    </th>
                    <th className="px-5 py-4 text-left font-medium text-[#dcecec]">
                      {t("agentPlayground.waveRecord.table.device")}
                    </th>
                    <th className="px-5 py-4 text-left font-medium text-[#dcecec] w-[140px] whitespace-nowrap">
                      {t("agentPlayground.waveRecord.table.status")}
                    </th>
                    <th className="px-5 py-4 text-left font-medium text-[#dcecec] w-[180px] whitespace-nowrap">
                      {t("agentPlayground.waveRecord.table.createdAt")}
                    </th>
                    <th className="px-5 py-4 text-left font-medium text-[#dcecec]">
                      {t("agentPlayground.waveRecord.table.evaluation")}
                    </th>
                    <th className="px-5 py-4 text-left font-medium text-[#dcecec]">
                      {t("agentPlayground.table.download")}
                    </th>
                    <th className="px-5 py-4 text-left font-medium text-[#dcecec] w-[100px] whitespace-nowrap">
                      {t("agentPlayground.table.actions")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {paginatedJobs.length === 0 ? (
                    <tr>
                      <td className="px-5 py-10 text-sm text-[#888] text-center" colSpan={8}>
                        {stationFilter || deviceFilter ? "没有匹配的任务" : t("agentPlayground.noJobs")}
                      </td>
                    </tr>
                  ) : (
                    paginatedJobs.map((job) => {
                      const selectable = job.status === "completed" && !!job.download_url;
                      return (
                      <tr key={job.id} className="border-b border-[#e8f0f0] hover:bg-[#dcecec]/50 transition-colors">
                        <td className="px-3 py-4 text-center w-[40px]">
                          {selectable ? (
                            <input
                              type="checkbox"
                              checked={selectedIds.has(job.id)}
                              onChange={() => toggleSelect(job.id)}
                              className="h-4 w-4 accent-[#298c88] cursor-pointer"
                            />
                          ) : (
                            <span className="inline-block h-4 w-4" />
                          )}
                        </td>
                        <td className="px-5 py-4 text-[#555]">
                          <span className="truncate max-w-[150px] block" title={job.station || "-"}>{job.station || "-"}</span>
                        </td>
                        <td className="px-5 py-4 text-[#555]">
                          <span className="truncate max-w-[150px] block" title={job.device || "-"}>{job.device || "-"}</span>
                        </td>
                        <td className="px-5 py-4 w-[140px] max-w-[140px]">
                          <div className="flex flex-col gap-2 overflow-hidden">
                            <Badge className={cn("rounded-full px-2.5 py-1 font-medium w-fit whitespace-nowrap", statusBadgeClass(job.status))}>
                              {t(`agentPlayground.status.${job.status}`)}
                            </Badge>
                            {job.status === "processing" && job.progress > 0 && (
                              <div className="flex flex-col gap-1 w-full">
                                <div className="h-2 bg-[#e8f0f0] rounded-full overflow-hidden">
                                  <div
                                    className="h-full bg-gradient-to-r from-[#298c88] to-[#00706b] transition-all duration-300"
                                    style={{ width: `${job.progress}%` }}
                                  />
                                </div>
                                <span className="text-xs text-[#666] whitespace-nowrap">{job.progress}%</span>
                                {job.progress_message && (
                                  <span className="text-xs text-[#298c88] truncate" title={job.progress_message}>
                                    {job.progress_message}
                                  </span>
                                )}
                              </div>
                            )}
                            {job.status === "queued" && job.progress_message && (
                              <span className="text-xs text-[#298c88] truncate" title={job.progress_message}>
                                {job.progress_message}
                              </span>
                            )}
                            {job.error_message && (
                              <p className="text-xs leading-5 text-[#cc3333] whitespace-nowrap truncate" title={job.error_message}>
                                {job.error_message}
                              </p>
                            )}
                          </div>
                        </td>
                        <td className="px-5 py-4 text-[#555] w-[180px] whitespace-nowrap">
                          {formatDateTime(job.created_at)}
                        </td>
                        <td className="px-5 py-4 w-[200px] min-w-[200px] max-w-[200px]">
                          {editingId === job.id ? (
                            <textarea
                              value={editValue}
                              onChange={(e) => setEditValue(e.target.value)}
                              onBlur={() => saveEvaluation(job.id, editValue)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter" && !e.shiftKey) {
                                  e.preventDefault();
                                  saveEvaluation(job.id, editValue);
                                }
                                if (e.key === "Escape") setEditingId(null);
                              }}
                              autoFocus
                              rows={2}
                              className="w-full rounded border border-[#298c88] bg-[#f0f7fa] px-2 py-1 text-sm text-[#000] outline-none resize-none"
                            />
                          ) : (
                            <div
                              onClick={() => {
                                setEditingId(job.id);
                                setEditValue(job.evaluation || "");
                              }}
                              className="w-[200px] min-h-[28px] cursor-pointer whitespace-pre-wrap break-words rounded px-1 py-0.5 text-sm text-[#555] hover:bg-[#f0f7fa]"
                              title={job.evaluation || t("agentPlayground.waveRecord.table.evaluationPlaceholder")}
                            >
                              {job.evaluation || (
                                <span className="text-[#bbb]">{t("agentPlayground.waveRecord.table.evaluationPlaceholder")}</span>
                              )}
                            </div>
                          )}
                        </td>
                        <td className="px-5 py-4">
                          {job.status === "completed" && job.download_url ? (
                            <div className="flex items-center gap-3">
                              <span className="text-sm text-[#555] truncate max-w-[120px]" title={job.result_file_name ?? ""}>
                                {job.result_file_name ?? ""}
                              </span>
                              <a
                                href={withBasePath(job.download_url)}
                                className="inline-flex items-center text-[#00706b] hover:text-[#298c88] transition-colors shrink-0"
                                title={t("agentPlayground.download")}
                              >
                                <Download className="h-4 w-4" />
                              </a>
                              {job.preview_url && (
                                <button
                                  type="button"
                                  onClick={() => openPreview(job.preview_url!, job.file_name)}
                                  className="inline-flex items-center text-[#00706b] hover:text-[#298c88] transition-colors shrink-0"
                                  title={t("agentPlayground.waveRecord.preview")}
                                >
                                  <Eye className="h-4 w-4" />
                                </button>
                              )}
                            </div>
                          ) : (
                            <span className="text-sm text-[#888]">
                              {t("agentPlayground.downloadUnavailable")}
                            </span>
                          )}
                        </td>
                        <td className="px-5 py-4 w-[100px]">
                          <div className="flex items-center gap-2">
                            {job.status === "completed" && job.preview_url && (
                              <button
                                type="button"
                                onClick={() => navigate(`/trip-briefing/${job.external_id || job.id}`)}
                                className="inline-flex items-center text-[#298c88] hover:text-[#0d5d57] transition-colors"
                                title="跳闸简报"
                              >
                                <Zap className="h-4 w-4" />
                              </button>
                            )}
                            <button
                              type="button"
                              onClick={() => setDeleteTarget(job)}
                              className="inline-flex items-center text-[#999] hover:text-[#d44] transition-colors"
                              title={t("agentPlayground.table.delete")}
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </div>
                        </td>
                      </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>

            {/* 分页控件 */}
            {jobs.length > 0 && (
              <div className="flex items-center justify-between border-t border-[#e8f0f0] bg-[#f0f7fa]/50 px-5 py-3">
                <p className="text-xs text-[#666]">
                  共 {filteredJobs.length} 条记录，第 {currentPage}/{totalPages} 页
                </p>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    disabled={currentPage <= 1}
                    onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                    className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-[#e0e0e0] bg-white text-[#555] transition-colors hover:bg-[#f0f7fa] disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </button>
                  {(() => {
                    const pages: (number | "...")[] = [];
                    if (totalPages <= 7) {
                      for (let i = 1; i <= totalPages; i++) pages.push(i);
                    } else {
                      pages.push(1);
                      if (currentPage > 3) pages.push("...");
                      for (let i = Math.max(2, currentPage - 1); i <= Math.min(totalPages - 1, currentPage + 1); i++) {
                        pages.push(i);
                      }
                      if (currentPage < totalPages - 2) pages.push("...");
                      pages.push(totalPages);
                    }
                    return pages.map((page, idx) =>
                      page === "..." ? (
                        <span key={`ellipsis-${idx}`} className="inline-flex h-8 w-8 items-center justify-center text-sm text-[#888]">
                          ...
                        </span>
                      ) : (
                        <button
                          key={page}
                          type="button"
                          onClick={() => setCurrentPage(page)}
                          className={cn(
                            "inline-flex h-8 w-8 items-center justify-center rounded-lg border text-sm font-medium transition-colors",
                            page === currentPage
                              ? "border-[#298c88] bg-[#298c88] text-white"
                              : "border-[#e0e0e0] bg-white text-[#555] hover:bg-[#f0f7fa]"
                          )}
                        >
                          {page}
                        </button>
                      )
                    );
                  })()}
                  <button
                    type="button"
                    disabled={currentPage >= totalPages}
                    onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                    className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-[#e0e0e0] bg-white text-[#555] transition-colors hover:bg-[#f0f7fa] disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    <ChevronRight className="h-4 w-4" />
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <CreateWaveRecordDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onSuccess={(newJob) => {
          setJobs((prev) => [newJob, ...prev]);
        }}
        onPreview={openPreview}
      />

      <BatchUploadDialog
        open={batchDialogOpen}
        onOpenChange={setBatchDialogOpen}
        onSuccess={(newJobs) => {
          setJobs((prev) => [...newJobs, ...prev]);
        }}
      />

      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogContent className="bg-white border-[#e0e0e0] sm:max-w-3xl max-h-[85vh] flex flex-col">
          <DialogHeader>
            <DialogTitle className="brand-display text-[#000]">{previewTitle}</DialogTitle>
          </DialogHeader>
          <div className="flex-1 overflow-auto min-h-0 min-w-0 -mx-6 px-6">
            {previewLoading ? (
              <div className="flex items-center justify-center py-10 text-[#666]">
                <Loader2 className="h-6 w-6 animate-spin" />
                <span className="ml-2">加载中...</span>
              </div>
            ) : (
              <MarkdownRenderer content={previewContent} />
            )}
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={!!deleteTarget} onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}>
        <DialogContent className="bg-white border-[#e0e0e0] sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-[#000]">{t("agentPlayground.table.deleteConfirmTitle")}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-[#555]">
            {t("agentPlayground.table.deleteConfirmMessage", { name: deleteTarget?.file_name ?? "" })}
          </p>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteTarget(null)}
              className="border-[#e0e0e0] text-[#555]"
            >
              {t("agentPlayground.table.deleteCancel")}
            </Button>
            <Button
              onClick={handleDelete}
              disabled={deleting}
              className="bg-[#d44] hover:bg-[#b33] text-white"
            >
              {deleting ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : null}
              {t("agentPlayground.table.deleteConfirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../../ui/dialog";
import { Input } from "../../ui/input";
import { Label } from "../../ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../ui/select";

interface CreateWaveRecordDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: (job: WaveRecordJob) => void;
  onPreview: (url: string, title: string) => void;
}

function CreateWaveRecordDialog({ open, onOpenChange, onSuccess, onPreview }: CreateWaveRecordDialogProps) {
  const { t } = useTranslation();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [station, setStation] = useState<string>("");
  const [device, setDevice] = useState<string>("");
  const [deviceType, setDeviceType] = useState<string>("line");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState<number>(0);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!station) {
      setError(t("agentPlayground.waveRecord.stationRequired"));
      return;
    }
    if (!device) {
      setError(t("agentPlayground.waveRecord.deviceRequired"));
      return;
    }
    if (files.length === 0) {
      setError(t("agentPlayground.waveRecord.selectFileRequired"));
      return;
    }

    const hasZip = files.some((f) => f.name.toLowerCase().endsWith(".zip"));
    if (!hasZip) {
      setError(t("agentPlayground.waveRecord.zipRequired"));
      return;
    }

    setSubmitting(true);
    setError(null);
    setUploadProgress(0);

    try {
      const job = await createJob(files, station, device, deviceType, (_, progress) => {
        setUploadProgress(progress);
      });
      onSuccess(job);
      onOpenChange(false);
      setFiles([]);
      setStation("");
      setDevice("");
      setDeviceType("line");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = event.target.files ? Array.from(event.target.files) : [];
    setFiles(selectedFiles);
    setError(null);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-white border-[#e0e0e0] sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="brand-display text-[#000]">
            {t("agentPlayground.waveRecord.createDialogTitle")}
          </DialogTitle>
          <DialogDescription className="leading-6 text-[#666]">
            {t("agentPlayground.waveRecord.createDialogDescription")}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-2">
              <Label htmlFor="station" className="text-[#298c88]">
                {t("agentPlayground.waveRecord.station")} <span className="text-red-500">*</span>
              </Label>
              <Input
                id="station"
                type="text"
                value={station}
                onChange={(e) => setStation(e.target.value)}
                placeholder={t("agentPlayground.waveRecord.stationPlaceholder")}
                className="bg-[#f0f7fa] border-[#84aca9] text-[#000]"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="device" className="text-[#298c88]">
                {t("agentPlayground.waveRecord.device")} <span className="text-red-500">*</span>
              </Label>
              <Input
                id="device"
                type="text"
                value={device}
                onChange={(e) => setDevice(e.target.value)}
                placeholder={t("agentPlayground.waveRecord.devicePlaceholder")}
                className="bg-[#f0f7fa] border-[#84aca9] text-[#000]"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="device-type" className="text-[#298c88]">
                {t("agentPlayground.waveRecord.deviceType")} <span className="text-red-500">*</span>
              </Label>
              <Select value={deviceType} onValueChange={setDeviceType}>
                <SelectTrigger className="bg-[#f0f7fa] border-[#84aca9] text-[#000]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-white border-[#e0e0e0]">
                  <SelectItem value="line" className="text-[#000] hover:bg-[#f0f7fa]">
                    {t("agentPlayground.waveRecord.deviceTypeLine")}
                  </SelectItem>
                  <SelectItem value="transformer" className="text-[#000] hover:bg-[#f0f7fa]">
                    {t("agentPlayground.waveRecord.deviceTypeTransformer")}
                  </SelectItem>
                  <SelectItem value="bus" className="text-[#000] hover:bg-[#f0f7fa]">
                    {t("agentPlayground.waveRecord.deviceTypeBus")}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-2">
            <Label className="text-[#298c88]">
              {t("agentPlayground.waveRecord.files")}
            </Label>
            <div className="flex items-center gap-3">
              <input
                ref={fileInputRef}
                type="file"
                accept=".zip"
                className="hidden"
                onChange={handleFileChange}
              />
              <Button
                type="button"
                variant="outline"
                onClick={() => fileInputRef.current?.click()}
                className="border-[#84aca9] bg-[#f0f7fa] text-[#000] hover:bg-[#e0f0f0]"
              >
                <Plus className="h-4 w-4 mr-1.5" />
                选择文件
              </Button>
              {files.length > 0 ? (
                <span className="text-sm text-[#555] truncate">
                  {files[0].name} ({(files[0].size / 1024).toFixed(1)} KB)
                </span>
              ) : (
                <span className="text-sm text-[#888]">未选择文件</span>
              )}
            </div>
            <div className="flex items-center gap-3 text-xs">
              <span className="text-[#888]">
                {t("agentPlayground.waveRecord.zipFileHint")}
              </span>
              <div className="flex items-center gap-2 ml-1">
                <span className="text-sm text-[#555]">录波文件上传手册</span>
                <a
                  href={withBasePath("/assets/录波文件上传手册.md")}
                  download
                  className="inline-flex items-center text-[#00706b] hover:text-[#298c88] transition-colors"
                  title="下载手册"
                >
                  <FileDown className="h-3.5 w-3.5" />
                </a>
                <button
                  type="button"
                  onClick={() => onPreview("/assets/录波文件上传手册.md", "录波文件上传手册")}
                  className="inline-flex items-center text-[#00706b] hover:text-[#298c88] transition-colors"
                  title="预览手册"
                >
                  <Eye className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          </div>

          {error && (
            <div className="rounded-md border border-red-300 bg-[#f5d5d5]/50 p-3 text-sm text-[#cc3333]">
              {error}
            </div>
          )}

          {submitting && (
            <div className="space-y-2">
              <div className="flex justify-between text-xs text-[#666]">
                <span>{t("agentPlayground.waveRecord.uploading")}</span>
                <span>{uploadProgress}%</span>
              </div>
              <div className="h-2 bg-[#e8f0f0] rounded-full overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-[#298c88] to-[#00706b] transition-all duration-300"
                  style={{ width: `${uploadProgress}%` }}
                />
              </div>
            </div>
          )}

          <DialogFooter className="gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={submitting}
              className="border-[#e0e0e0] bg-white text-[#000] hover:bg-[#f5f5f5]"
            >
              {t("agentPlayground.cancel")}
            </Button>
            <Button
              type="submit"
              disabled={submitting}
              className="bg-[#298c88] hover:bg-[#0d5d57] text-white border border-[#298c88]"
            >
              {submitting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {uploadProgress < 100
                    ? t("agentPlayground.waveRecord.uploading")
                    : t("agentPlayground.waveRecord.processing")}
                </>
              ) : (
                t("agentPlayground.waveRecord.startParse")
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function parseStationDevice(fileName: string): { station: string; device: string } {
  const name = fileName.replace(/\.zip$/i, "").trim();
  if (!name) return { station: "", device: "" };
  return { station: name, device: name };
}

interface BatchFileEntry {
  file: File;
  mdFile?: File;
  station: string;
  device: string;
  status: "pending" | "uploading" | "done" | "failed";
  progress: number;
  error?: string;
  job?: WaveRecordJob;
}

interface BatchUploadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: (jobs: WaveRecordJob[]) => void;
}

function BatchUploadDialog({ open, onOpenChange, onSuccess }: BatchUploadDialogProps) {
  const { t } = useTranslation();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [entries, setEntries] = useState<BatchFileEntry[]>([]);
  const [submitting, setSubmitting] = useState(false);

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = event.target.files ? Array.from(event.target.files) : [];
    const zipFiles = selectedFiles.filter((f) => f.name.toLowerCase().endsWith(".zip"));
    const mdFiles = selectedFiles.filter((f) => f.name.toLowerCase().endsWith(".md"));
    if (zipFiles.length === 0 && selectedFiles.length > 0) {
      toast.error("请选择 .zip 格式的压缩包");
    }

    // 尝试将 md 文件匹配到同目录的 zip 文件
    // webkitRelativePath 格式: "目录名/文件名"
    const mdByDir = new Map<string, File>();
    for (const md of mdFiles) {
      const dir = md.webkitRelativePath ? md.webkitRelativePath.split("/").slice(0, -1).join("/") : "";
      if (dir) mdByDir.set(dir, md);
    }

    const newEntries: BatchFileEntry[] = zipFiles.map((f) => {
      const { station, device } = parseStationDevice(f.name);
      // 尝试通过 webkitRelativePath 匹配 md 文件
      let matchedMd: File | undefined;
      if (f.webkitRelativePath) {
        const dir = f.webkitRelativePath.split("/").slice(0, -1).join("/");
        matchedMd = mdByDir.get(dir);
      }
      return { file: f, mdFile: matchedMd, station, device, status: "pending" as const, progress: 0 };
    });
    setEntries(newEntries);
    if (event.target) event.target.value = "";
  };

  const updateEntry = (index: number, updates: Partial<BatchFileEntry>) => {
    setEntries((prev) => prev.map((e, i) => (i === index ? { ...e, ...updates } : e)));
  };

  const handleSubmit = async () => {
    if (entries.length === 0) {
      toast.error(t("agentPlayground.waveRecord.batchNoFiles"));
      return;
    }
    setSubmitting(true);

    const createdJobs: WaveRecordJob[] = [];

    // Upload all files in parallel
    await Promise.allSettled(
      entries.map(async (entry, idx) => {
        updateEntry(idx, { status: "uploading", progress: 0 });
        try {
          let job: WaveRecordJob;
          if (entry.mdFile) {
            // 有 md 文件时，使用直接上传接口（支持多文件）
            const formData = new FormData();
            formData.append("files", entry.file);
            formData.append("files", entry.mdFile);
            formData.append("station", entry.station);
            formData.append("device", entry.device);
            formData.append("device_type", "line");
            const res = await fetch(withBasePath("/api/wave-record-parser/jobs"), {
              method: "POST",
              body: formData,
            });
            if (!res.ok) throw new Error("上传失败");
            job = await res.json();
          } else {
            job = await createJob(
              [entry.file],
              entry.station,
              entry.device,
              "line",
              (_, progress) => updateEntry(idx, { progress }),
            );
          }
          updateEntry(idx, { status: "done", progress: 100, job });
          createdJobs.push(job);
        } catch (err) {
          updateEntry(idx, { status: "failed", error: err instanceof Error ? err.message : String(err) });
        }
      }),
    );

    if (createdJobs.length > 0) {
      onSuccess(createdJobs);
      toast.success(`成功上传 ${createdJobs.length} 个文件`);
    }
    if (createdJobs.length === 0 && entries.length > 0) {
      toast.error("所有文件上传失败");
    }
    setSubmitting(false);
  };

  const handleClose = () => {
    if (!submitting) {
      setEntries([]);
      onOpenChange(false);
    }
  };

  const allDone = entries.length > 0 && entries.every((e) => e.status === "done" || e.status === "failed");
  const doneCount = entries.filter((e) => e.status === "done").length;
  const failedCount = entries.filter((e) => e.status === "failed").length;

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="bg-white border-[#e0e0e0] sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="brand-display text-[#000]">
            {t("agentPlayground.waveRecord.batchDialogTitle")}
          </DialogTitle>
          <DialogDescription className="leading-6 text-[#666]">
            {t("agentPlayground.waveRecord.batchDialogDescription")}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <input
              ref={fileInputRef}
              type="file"
              accept=".zip,.md"
              multiple
              className="hidden"
              onChange={handleFileChange}
            />
            <Button
              type="button"
              variant="outline"
              onClick={() => fileInputRef.current?.click()}
              disabled={submitting}
              className="border-[#84aca9] bg-[#f0f7fa] text-[#000] hover:bg-[#e0f0f0]"
            >
              <Plus className="h-4 w-4 mr-1.5" />
              选择文件
            </Button>
            {entries.length > 0 && (
              <span className="text-sm text-[#555]">{entries.length} 个文件</span>
            )}
          </div>

          {entries.length > 0 && (
            <div className="max-h-[360px] overflow-auto rounded-lg border border-[#e0e0e0]">
              <table className="w-full text-sm">
                <thead className="bg-[#f0f7fa] sticky top-0">
                  <tr>
                    <th className="px-3 py-2.5 text-left font-medium text-[#555] w-[55%]">
                      {t("agentPlayground.waveRecord.batchStationDevice")}
                    </th>
                    <th className="px-3 py-2.5 text-left font-medium text-[#555] w-[15%]">
                      {t("agentPlayground.waveRecord.batchSize")}
                    </th>
                    <th className="px-3 py-2.5 text-center font-medium text-[#555] w-[15%]">
                      {t("agentPlayground.waveRecord.batchStatus")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {entries.map((entry, idx) => (
                    <tr key={idx} className="border-t border-[#e8f0f0]">
                      <td className="px-3 py-2 text-[#333] truncate max-w-[300px]" title={entry.file.name.replace(/\.zip$/i, "")}>
                        {entry.file.name.replace(/\.zip$/i, "")}
                      </td>
                      <td className="px-3 py-2 text-[#888]">
                        {(entry.file.size / 1024).toFixed(0)} KB
                      </td>
                      <td className="px-3 py-2 text-center">
                        {entry.status === "pending" && (
                          <span className="text-xs text-[#888]">{t("agentPlayground.waveRecord.batchPending")}</span>
                        )}
                        {entry.status === "uploading" && (
                          <div className="flex flex-col items-center gap-1">
                            <span className="text-xs text-[#00706b]">{entry.progress}%</span>
                            <div className="w-full h-1.5 bg-[#e8f0f0] rounded-full overflow-hidden">
                              <div
                                className="h-full bg-[#298c88] transition-all duration-300"
                                style={{ width: `${entry.progress}%` }}
                              />
                            </div>
                          </div>
                        )}
                        {entry.status === "done" && (
                          <span className="text-xs text-[#0d5d57]">{t("agentPlayground.waveRecord.batchDone")}</span>
                        )}
                        {entry.status === "failed" && (
                          <span className="text-xs text-[#cc3333]" title={entry.error}>
                            {t("agentPlayground.waveRecord.batchFailed")}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {allDone && (
            <div className="rounded-md bg-[#f0f7fa] border border-[#84aca9] p-3 text-sm text-[#0d5d57]">
              上传完成：成功 {doneCount} 个{failedCount > 0 ? `，失败 ${failedCount} 个` : ""}
            </div>
          )}
        </div>

        <DialogFooter className="gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={handleClose}
            disabled={submitting}
            className="border-[#e0e0e0] bg-white text-[#000] hover:bg-[#f5f5f5]"
          >
            {allDone ? t("agentPlayground.cancel") : t("agentPlayground.cancel")}
          </Button>
          {!allDone && (
            <Button
              onClick={handleSubmit}
              disabled={submitting || entries.length === 0}
              className="bg-[#298c88] hover:bg-[#0d5d57] text-white border border-[#298c88]"
            >
              {submitting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t("agentPlayground.waveRecord.uploading")}
                </>
              ) : (
                t("agentPlayground.waveRecord.batchStartUpload")
              )}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
