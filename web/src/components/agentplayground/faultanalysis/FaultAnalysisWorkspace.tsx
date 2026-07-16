import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Download, Plus, Loader2, ChevronLeft, ChevronRight, Eye, Trash2, FileArchive, Zap, Search, Upload } from "lucide-react";
import { toast } from "sonner";
import { Button } from "../../ui/button";
import { Badge } from "../../ui/badge";
import { Label } from "../../ui/label";
import { cn } from "../../../lib/utils";
import { withBasePath } from "../../../lib/basePath";
import { MarkdownRenderer } from "../../shared/MarkdownRenderer";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "../../ui/dialog";

interface FaultAnalysisJob {
  id: string;
  status: "queued" | "processing" | "completed" | "failed";
  created_at: string;
  updated_at: string;
  error_message?: string;
  station: string;
  device: string;
  device_type: string;
  voltage_level: string;
  folder_path?: string;
  result_file_name?: string;
  download_url?: string;
  preview_url?: string;
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

const CHUNK_SIZE = 1 * 1024 * 1024; // 1MB

async function createJobChunked(
  files: File[],
  onProgress?: (fileIndex: number, fileProgress: number) => void,
): Promise<FaultAnalysisJob> {
  const zipFile = files.find((f) => /\.(zip|rar|7z|zwav)$/i.test(f.name));
  if (!zipFile) throw new Error("No archive file found");

  const totalChunks = Math.ceil(zipFile.size / CHUNK_SIZE);

  // Step 1: Init upload
  const initRes = await fetch(withBasePath("/api/fault-analysis/uploads/init"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      file_name: zipFile.name,
      total_size: zipFile.size,
      total_chunks: totalChunks,
    }),
  });
  if (!initRes.ok) throw new Error("Failed to initialize upload");
  const { upload_id } = await initRes.json();

  // Step 2: Upload chunks
  for (let i = 0; i < totalChunks; i++) {
    const start = i * CHUNK_SIZE;
    const end = Math.min(start + CHUNK_SIZE, zipFile.size);
    const chunk = zipFile.slice(start, end);

    const formData = new FormData();
    formData.append("chunk", chunk, zipFile.name);

    const chunkRes = await fetch(
      withBasePath(`/api/fault-analysis/uploads/${upload_id}/chunks/${i}`),
      { method: "POST", body: formData },
    );
    if (!chunkRes.ok) throw new Error(`Failed to upload chunk ${i + 1}/${totalChunks}`);

    if (onProgress) onProgress(0, Math.round(((i + 1) / totalChunks) * 100));
  }

  // Step 3: Complete upload
  const completeRes = await fetch(
    withBasePath(`/api/fault-analysis/uploads/${upload_id}/complete`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ station: "", device: "", device_type: "", voltage_level: "" }),
    },
  );
  if (!completeRes.ok) {
    const error = await completeRes.text();
    throw new Error(error || "Failed to complete upload");
  }
  return completeRes.json();
}

const PAGE_SIZE = 20;

interface FaultAnalysisWorkspaceProps {
  selectedJob?: FaultAnalysisJob | null;
}

export function FaultAnalysisWorkspace({ selectedJob }: FaultAnalysisWorkspaceProps) {
  const navigate = useNavigate();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [jobs, setJobs] = useState<FaultAnalysisJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewTitle, setPreviewTitle] = useState("");
  const [previewContent, setPreviewContent] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<FaultAnalysisJob | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [exporting, setExporting] = useState(false);
  const [batchDialogOpen, setBatchDialogOpen] = useState(false);
  const [nameFilter, setNameFilter] = useState("");

  const filteredJobs = jobs.filter((j) => {
    if (!nameFilter) return true;
    const name = getDeviceName(j).toLowerCase();
    return name.includes(nameFilter.toLowerCase());
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
  }, [jobs.length, totalPages, currentPage]);

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
        fetchJobs().then(setJobs).catch(() => {});
      }, 1500);
      return () => clearInterval(interval);
    }
  }, [jobs]);

  const saveEvaluation = async (jobId: string, value: string) => {
    try {
      const res = await fetch(withBasePath(`/api/fault-analysis/jobs/${jobId}`), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ evaluation: value }),
      });
      if (res.ok) {
        const updated = await res.json();
        setJobs((prev) => prev.map((j) => (j.id === jobId ? { ...j, evaluation: updated.evaluation } : j)));
      }
    } catch { /* ignore */ }
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
        const fenceIdx = text.indexOf("```markdown\n");
        if (fenceIdx !== -1) {
          text = text.slice(fenceIdx + 12);
          const closeIdx = text.lastIndexOf("\n```");
          if (closeIdx !== -1) text = text.slice(0, closeIdx);
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
      const res = await fetch(withBasePath(`/api/fault-analysis/jobs/${deleteTarget.id}`), { method: "DELETE" });
      if (res.ok) {
        setJobs((prev) => prev.filter((j) => j.id !== deleteTarget.id));
        toast.success(`已删除 ${getDeviceName(deleteTarget)}`);
        setDeleteTarget(null);
      } else {
        toast.error("删除失败");
      }
    } catch {
      toast.error("删除失败");
    } finally {
      setDeleting(false);
    }
  };

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    const selectable = paginatedJobs.filter((j) => j.status === "completed" && j.download_url);
    if (selectable.length === 0) return;
    const allSelected = selectable.every((j) => selectedIds.has(j.id));
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allSelected) selectable.forEach((j) => next.delete(j.id));
      else selectable.forEach((j) => next.add(j.id));
      return next;
    });
  };

  const handleExport = async () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) { toast.error("请先选择要导出的任务"); return; }
    setExporting(true);
    try {
      const res = await fetch(withBasePath("/api/fault-analysis/jobs/export"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_ids: ids }),
      });
      if (res.ok) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "故障分析报告导出.zip";
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

  // If a job is selected from the sidebar, show job details
  if (selectedJob) {
    return (
      <>
        <div className="flex flex-col h-full gap-3 overflow-hidden px-4 py-3">
          <div className="flex flex-col gap-3 rounded-[20px] border border-[#e0e0e0] bg-white p-3 shadow-sm sm:flex-row sm:items-center sm:justify-between shrink-0">
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-[#888]">智能工具</p>
              <h2 className="brand-display mt-2 text-2xl text-[#000]">电网故障智能分析</h2>
            </div>
            <div className="flex items-center gap-2 self-start sm:self-auto">
              <Button onClick={() => setBatchDialogOpen(true)} className="gap-2 bg-[#298c88] hover:bg-[#0d5d57] text-white border border-[#298c88]">
                <Upload className="h-4 w-4" />
                批量上传
              </Button>
              <Button onClick={() => setDialogOpen(true)} className="gap-2 bg-[#298c88] hover:bg-[#0d5d57] text-white border border-[#298c88]">
                <Plus className="h-4 w-4" />
                新建分析
              </Button>
            </div>
          </div>

          {/* Job Details Card */}
          <div className="rounded-[20px] border border-[#e0e0e0] bg-white shadow-sm overflow-hidden flex flex-col flex-1 min-h-0">
            <div className="flex-1 overflow-auto min-h-0 p-6">
              <div className="max-w-2xl mx-auto space-y-6">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <h3 className="text-lg font-semibold text-[#0d5d57]">{getDeviceName(selectedJob)}</h3>
                    <p className="text-sm text-[#888] mt-1">创建时间: {formatDateTime(selectedJob.created_at)}</p>
                  </div>
                  <Badge className={cn("rounded-full px-3 py-1 font-medium", statusBadgeClass(selectedJob.status))}>
                    {selectedJob.status === "completed" ? "完成" : selectedJob.status === "processing" ? "处理中" : selectedJob.status === "failed" ? "失败" : "排队中"}
                  </Badge>
                </div>

                {selectedJob.status === "processing" && selectedJob.progress > 0 && (
                  <div className="space-y-2">
                    <div className="h-2 bg-[#e8f0f0] rounded-full overflow-hidden">
                      <div className="h-full bg-gradient-to-r from-[#298c88] to-[#00706b] transition-all duration-300" style={{ width: `${selectedJob.progress}%` }} />
                    </div>
                    <span className="text-xs text-[#666]">{selectedJob.progress}%</span>
                    {selectedJob.progress_message && <p className="text-sm text-[#298c88]">{selectedJob.progress_message}</p>}
                  </div>
                )}

                {selectedJob.error_message && (
                  <div className="rounded-lg border border-red-300 bg-[#f5d5d5]/50 p-4 text-sm text-[#cc3333]">{selectedJob.error_message}</div>
                )}

                <div className="space-y-2">
                  <Label className="text-[#298c88]">评价</Label>
                  {editingId === selectedJob.id ? (
                    <textarea
                      value={editValue}
                      onChange={(e) => setEditValue(e.target.value)}
                      onBlur={() => saveEvaluation(selectedJob.id, editValue)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); saveEvaluation(selectedJob.id, editValue); }
                        if (e.key === "Escape") setEditingId(null);
                      }}
                      autoFocus
                      rows={3}
                      className="w-full rounded-lg border border-[#298c88] bg-[#f0f7fa] px-3 py-2 text-sm text-[#000] outline-none resize-none"
                    />
                  ) : (
                    <div
                      onClick={() => { setEditingId(selectedJob.id); setEditValue(selectedJob.evaluation || ""); }}
                      className="min-h-[60px] cursor-pointer whitespace-pre-wrap break-words rounded-lg border border-[#e0e0e0] bg-[#f0f7fa] px-3 py-2 text-sm text-[#555] hover:bg-[#e0f0f0]"
                    >
                      {selectedJob.evaluation || <span className="text-[#bbb]">点击添加评价...</span>}
                    </div>
                  )}
                </div>

                <div className="flex items-center gap-3 pt-4 border-t border-[#e8f0f0]">
                  {selectedJob.status === "completed" && selectedJob.download_url && (
                    <a href={withBasePath(selectedJob.download_url)} className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-[#00706b] hover:bg-[#0d5d57] text-white text-sm transition-colors">
                      <Download className="h-4 w-4" /> 下载报告
                    </a>
                  )}
                  {selectedJob.status === "completed" && selectedJob.preview_url && (
                    <Button variant="outline" onClick={() => openPreview(selectedJob.preview_url!, getDeviceName(selectedJob))} className="gap-2 border-[#84aca9] text-[#00706b]">
                      <Eye className="h-4 w-4" /> 预览
                    </Button>
                  )}
                  <Button variant="outline" onClick={() => setDeleteTarget(selectedJob)} className="gap-2 border-[#d44] text-[#d44] hover:bg-[#f5d5d5]">
                    <Trash2 className="h-4 w-4" /> 删除
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <CreateFaultAnalysisDialog open={dialogOpen} onOpenChange={setDialogOpen} onSuccess={(newJob) => setJobs((prev) => [newJob, ...prev])} />

        <BatchUploadDialog open={batchDialogOpen} onOpenChange={setBatchDialogOpen} onSuccess={(newJobs) => setJobs((prev) => [...newJobs, ...prev])} />

        <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
          <DialogContent className="bg-white border-[#e0e0e0] sm:max-w-3xl max-h-[85vh] flex flex-col">
            <DialogHeader><DialogTitle className="brand-display text-[#000]">{previewTitle}</DialogTitle></DialogHeader>
            <div className="flex-1 overflow-auto min-h-0 min-w-0 -mx-6 px-6">
              {previewLoading ? (
                <div className="flex items-center justify-center py-10 text-[#666]"><Loader2 className="h-6 w-6 animate-spin" /><span className="ml-2">加载中...</span></div>
              ) : (
                <MarkdownRenderer content={previewContent} />
              )}
            </div>
          </DialogContent>
        </Dialog>

        <Dialog open={!!deleteTarget} onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}>
          <DialogContent className="bg-white border-[#e0e0e0] sm:max-w-md">
            <DialogHeader><DialogTitle className="text-[#000]">确认删除</DialogTitle></DialogHeader>
            <p className="text-sm text-[#555]">确定要删除任务 {deleteTarget ? getDeviceName(deleteTarget) : ""} 吗？</p>
            <DialogFooter>
              <Button variant="outline" onClick={() => setDeleteTarget(null)} className="border-[#e0e0e0] text-[#555]">取消</Button>
              <Button onClick={handleDelete} disabled={deleting} className="bg-[#d44] hover:bg-[#b33] text-white">
                {deleting ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : null} 确认删除
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </>
    );
  }

  // Default: show full table view
  return (
    <>
      <div className="flex flex-col h-full gap-3 overflow-hidden px-4 py-3">
        <div className="flex flex-col gap-3 rounded-[20px] border border-[#e0e0e0] bg-white p-3 shadow-sm sm:flex-row sm:items-center sm:justify-between shrink-0">
          <div>
            <p className="text-xs uppercase tracking-[0.18em] text-[#888]">智能工具</p>
            <h2 className="brand-display mt-2 text-2xl text-[#000]">电网故障智能分析</h2>
          </div>
          <div className="flex items-center gap-2 self-start sm:self-auto">
            <Button onClick={handleExport} disabled={exporting} className="gap-2 bg-[#00706b] hover:bg-[#0d5d57] text-white border border-[#00706b]">
              {exporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileArchive className="h-4 w-4" />}
              导出{selectedCount > 0 ? ` (${selectedCount})` : ""}
            </Button>
            <Button onClick={() => setBatchDialogOpen(true)} className="gap-2 bg-[#298c88] hover:bg-[#0d5d57] text-white border border-[#298c88]">
              <Upload className="h-4 w-4" /> 批量上传
            </Button>
            <Button onClick={() => setDialogOpen(true)} className="gap-2 bg-[#298c88] hover:bg-[#0d5d57] text-white border border-[#298c88]">
              <Plus className="h-4 w-4" /> 新建分析
            </Button>
          </div>
        </div>

        {!loading && !error && jobs.length > 0 && (
          <div className="flex items-center gap-3 shrink-0">
            <div className="relative flex-1 max-w-[320px]">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[#888]" />
              <input type="text" value={nameFilter} onChange={(e) => { setNameFilter(e.target.value); setCurrentPage(1); }}
                placeholder="筛选厂站/设备..." className="w-full h-9 pl-9 pr-3 rounded-lg border border-[#e0e0e0] bg-white text-sm text-[#333] placeholder:text-[#aaa] focus:outline-none focus:border-[#298c88] focus:ring-1 focus:ring-[#298c88]/30" />
            </div>
            {nameFilter && (
              <Button variant="ghost" size="sm" onClick={() => { setNameFilter(""); setCurrentPage(1); }} className="text-[#888] hover:text-[#333] h-9 px-3">清除</Button>
            )}
            <span className="text-xs text-[#888] ml-auto">{filteredJobs.length} / {jobs.length} 条</span>
          </div>
        )}

        {loading && (
          <div className="flex items-center justify-center py-10 text-[#666]"><Loader2 className="h-6 w-6 animate-spin" /><span className="ml-2">加载中...</span></div>
        )}

        {error && (
          <div className="rounded-[24px] border border-red-300 bg-[#f5d5d5]/50 p-4 text-[#cc3333]">{error}</div>
        )}

        {!loading && !error && (
          <div className="rounded-[20px] border border-[#e0e0e0] bg-white shadow-sm overflow-hidden flex flex-col flex-1 min-h-0">
            <div className="flex-1 overflow-auto min-h-0">
              <table className="w-full text-sm border-separate border-spacing-0" style={{ minWidth: 800 }}>
                <thead className="bg-[#0d5d57] sticky top-0 z-10">
                  <tr className="border-b border-[#e8f0f0]">
                    <th className="px-3 py-4 text-center w-[40px]">
                      <input type="checkbox" checked={paginatedJobs.filter((j) => j.status === "completed" && j.download_url).length > 0 && paginatedJobs.filter((j) => j.status === "completed" && j.download_url).every((j) => selectedIds.has(j.id))}
                        onChange={toggleSelectAll} className="h-4 w-4 accent-[#298c88] cursor-pointer" />
                    </th>
                    <th className="px-5 py-4 text-left font-medium text-[#dcecec]">厂站/设备</th>
                    <th className="px-5 py-4 text-left font-medium text-[#dcecec] w-[140px]">状态</th>
                    <th className="px-5 py-4 text-left font-medium text-[#dcecec] w-[180px]">创建时间</th>
                    <th className="px-5 py-4 text-left font-medium text-[#dcecec]">评价</th>
                    <th className="px-5 py-4 text-left font-medium text-[#dcecec] w-[140px]">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {paginatedJobs.length === 0 ? (
                    <tr><td className="px-5 py-10 text-sm text-[#888] text-center" colSpan={6}>{nameFilter ? "没有匹配的任务" : "暂无任务"}</td></tr>
                  ) : (
                    paginatedJobs.map((job) => {
                      const selectable = job.status === "completed" && !!job.download_url;
                      return (
                        <tr key={job.id} className="border-b border-[#e8f0f0] hover:bg-[#dcecec]/50 transition-colors">
                          <td className="px-3 py-4 text-center w-[40px]">
                            {selectable ? (
                              <input type="checkbox" checked={selectedIds.has(job.id)} onChange={() => toggleSelect(job.id)} className="h-4 w-4 accent-[#298c88] cursor-pointer" />
                            ) : (<span className="inline-block h-4 w-4" />)}
                          </td>
                          <td className="px-5 py-4 text-[#555]"><span className="truncate max-w-[400px] block" title={getDeviceName(job)}>{getDeviceName(job)}</span></td>
                          <td className="px-5 py-4 w-[140px]">
                            <div className="flex flex-col gap-2">
                              <Badge className={cn("rounded-full px-2.5 py-1 font-medium w-fit", statusBadgeClass(job.status))}>
                                {job.status === "completed" ? "完成" : job.status === "processing" ? "处理中" : job.status === "failed" ? "失败" : "排队中"}
                              </Badge>
                              {job.status === "processing" && job.progress > 0 && (
                                <div className="flex flex-col gap-1 w-full">
                                  <div className="h-2 bg-[#e8f0f0] rounded-full overflow-hidden">
                                    <div className="h-full bg-gradient-to-r from-[#298c88] to-[#00706b] transition-all duration-300" style={{ width: `${job.progress}%` }} />
                                  </div>
                                  <span className="text-xs text-[#666]">{job.progress}%</span>
                                </div>
                              )}
                              {job.error_message && <p className="text-xs text-[#cc3333] truncate" title={job.error_message}>{job.error_message}</p>}
                            </div>
                          </td>
                          <td className="px-5 py-4 text-[#555] w-[180px] whitespace-nowrap">{formatDateTime(job.created_at)}</td>
                          <td className="px-5 py-4 w-[200px]">
                            {editingId === job.id ? (
                              <textarea value={editValue} onChange={(e) => setEditValue(e.target.value)} onBlur={() => saveEvaluation(job.id, editValue)}
                                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); saveEvaluation(job.id, editValue); } if (e.key === "Escape") setEditingId(null); }}
                                autoFocus rows={2} className="w-full rounded border border-[#298c88] bg-[#f0f7fa] px-2 py-1 text-sm text-[#000] outline-none resize-none" />
                            ) : (
                              <div onClick={() => { setEditingId(job.id); setEditValue(job.evaluation || ""); }}
                                className="w-[200px] min-h-[28px] cursor-pointer whitespace-pre-wrap break-words rounded px-1 py-0.5 text-sm text-[#555] hover:bg-[#f0f7fa]">
                                {job.evaluation || <span className="text-[#bbb]">点击添加评价...</span>}
                              </div>
                            )}
                          </td>
                          <td className="px-5 py-4 w-[140px]">
                            <div className="flex items-center gap-2">
                              {job.status === "completed" && job.download_url && (
                                <a href={withBasePath(job.download_url)} className="inline-flex items-center text-[#00706b] hover:text-[#0d5d57] transition-colors" title="下载报告">
                                  <Download className="h-4 w-4" />
                                </a>
                              )}
                              {job.status === "completed" && job.preview_url && (
                                <button type="button" onClick={() => openPreview(job.preview_url!, getDeviceName(job))} className="inline-flex items-center text-[#298c88] hover:text-[#0d5d57] transition-colors" title="预览报告">
                                  <Eye className="h-4 w-4" />
                                </button>
                              )}
                              {job.status === "completed" && job.preview_url && (
                                <button type="button" onClick={() => {
                                  const eq = [job.station, job.device].filter(Boolean).join(" ");
                                  navigate(`/fault-analysis/${job.id}${eq ? `?equipmentName=${encodeURIComponent(eq)}` : ""}`);
                                }} className="inline-flex items-center text-[#298c88] hover:text-[#0d5d57] transition-colors" title="AI 对话分析">
                                  <Zap className="h-4 w-4" />
                                </button>
                              )}
                              <button type="button" onClick={() => setDeleteTarget(job)} className="inline-flex items-center text-[#999] hover:text-[#d44] transition-colors" title="删除">
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

            {jobs.length > 0 && (
              <div className="flex items-center justify-between border-t border-[#e8f0f0] bg-[#f0f7fa]/50 px-5 py-3">
                <p className="text-xs text-[#666]">共 {filteredJobs.length} 条记录，第 {currentPage}/{totalPages} 页</p>
                <div className="flex items-center gap-1">
                  <button type="button" disabled={currentPage <= 1} onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                    className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-[#e0e0e0] bg-white text-[#555] transition-colors hover:bg-[#f0f7fa] disabled:opacity-40 disabled:cursor-not-allowed">
                    <ChevronLeft className="h-4 w-4" />
                  </button>
                  {(() => {
                    const pages: (number | "...")[] = [];
                    if (totalPages <= 7) { for (let i = 1; i <= totalPages; i++) pages.push(i); }
                    else {
                      pages.push(1);
                      if (currentPage > 3) pages.push("...");
                      for (let i = Math.max(2, currentPage - 1); i <= Math.min(totalPages - 1, currentPage + 1); i++) pages.push(i);
                      if (currentPage < totalPages - 2) pages.push("...");
                      pages.push(totalPages);
                    }
                    return pages.map((page, idx) =>
                      page === "..." ? (<span key={`ellipsis-${idx}`} className="inline-flex h-8 w-8 items-center justify-center text-sm text-[#888]">...</span>) : (
                        <button key={page} type="button" onClick={() => setCurrentPage(page)}
                          className={cn("inline-flex h-8 w-8 items-center justify-center rounded-lg border text-sm font-medium transition-colors",
                            page === currentPage ? "border-[#298c88] bg-[#298c88] text-white" : "border-[#e0e0e0] bg-white text-[#555] hover:bg-[#f0f7fa]")}>
                          {page}
                        </button>
                      )
                    );
                  })()}
                  <button type="button" disabled={currentPage >= totalPages} onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                    className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-[#e0e0e0] bg-white text-[#555] transition-colors hover:bg-[#f0f7fa] disabled:opacity-40 disabled:cursor-not-allowed">
                    <ChevronRight className="h-4 w-4" />
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <CreateFaultAnalysisDialog open={dialogOpen} onOpenChange={setDialogOpen} onSuccess={(newJob) => setJobs((prev) => [newJob, ...prev])} />

      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogContent className="bg-white border-[#e0e0e0] sm:max-w-3xl max-h-[85vh] flex flex-col">
          <DialogHeader><DialogTitle className="brand-display text-[#000]">{previewTitle}</DialogTitle></DialogHeader>
          <div className="flex-1 overflow-auto min-h-0 min-w-0 -mx-6 px-6">
            {previewLoading ? (
              <div className="flex items-center justify-center py-10 text-[#666]"><Loader2 className="h-6 w-6 animate-spin" /><span className="ml-2">加载中...</span></div>
            ) : (
              <MarkdownRenderer content={previewContent} />
            )}
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={!!deleteTarget} onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}>
        <DialogContent className="bg-white border-[#e0e0e0] sm:max-w-md">
          <DialogHeader><DialogTitle className="text-[#000]">确认删除</DialogTitle></DialogHeader>
          <p className="text-sm text-[#555]">确定要删除任务 {deleteTarget ? getDeviceName(deleteTarget) : ""} 吗？</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)} className="border-[#e0e0e0] text-[#555]">取消</Button>
            <Button onClick={handleDelete} disabled={deleting} className="bg-[#d44] hover:bg-[#b33] text-white">
              {deleting ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : null} 确认删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

interface CreateFaultAnalysisDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: (job: FaultAnalysisJob) => void;
}

function CreateFaultAnalysisDialog({ open, onOpenChange, onSuccess }: CreateFaultAnalysisDialogProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number>(0);

  const handleSubmit = async () => {
    if (files.length === 0) { setError("请选择录波压缩包"); return; }

    setSubmitting(true);
    setError(null);
    setUploadProgress(0);

    try {
      const job = await createJobChunked(files, (_, progress) => {
        setUploadProgress(progress);
      });
      onSuccess(job);
      onOpenChange(false);
      setFiles([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files ? Array.from(e.target.files) : [];
    setFiles(selected);
    setError(null);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const dropped = Array.from(e.dataTransfer.files).filter((f) =>
      /\.(zip|rar|7z|zwav)$/i.test(f.name)
    );
    if (dropped.length > 0) {
      setFiles(dropped);
      setError(null);
    }
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-white border-[#e0e0e0] sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="brand-display text-[#000]">新建故障分析</DialogTitle>
          <DialogDescription className="leading-6 text-[#666]">
            上传录波压缩包，系统将自动解析厂站、设备等信息并生成故障分析报告
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Drop zone */}
          <div
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={cn(
              "flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed p-8 cursor-pointer transition-colors",
              dragOver ? "border-[#298c88] bg-[#f0f7fa]" : "border-[#d0d0d0] bg-[#fafafa] hover:border-[#298c88] hover:bg-[#f0f7fa]",
            )}
          >
            <input ref={fileInputRef} type="file" multiple accept=".zip,.rar,.7z,.zwav" className="hidden" onChange={handleFileChange} />
            <FileArchive className={cn("h-10 w-10", dragOver ? "text-[#298c88]" : "text-[#aaa]")} />
            <div className="text-center">
              <p className="text-sm font-medium text-[#333]">点击或拖拽压缩包到此处</p>
              <p className="text-xs text-[#888] mt-1">支持 .zip / .rar / .7z / .zwav 格式</p>
            </div>
          </div>

          {/* Selected files */}
          {files.length > 0 && (
            <div className="space-y-1.5">
              {files.map((f, i) => (
                <div key={i} className="flex items-center gap-2 rounded-lg bg-[#f0f7fa] px-3 py-2">
                  <FileArchive className="h-4 w-4 text-[#298c88] shrink-0" />
                  <span className="text-sm text-[#333] truncate flex-1">{f.name}</span>
                  <span className="text-xs text-[#888] shrink-0">{formatSize(f.size)}</span>
                </div>
              ))}
            </div>
          )}

          {error && (
            <div className="rounded-md border border-red-300 bg-[#f5d5d5]/50 p-3 text-sm text-[#cc3333]">{error}</div>
          )}

          {submitting && (
            <div className="space-y-2">
              <div className="flex justify-between text-xs text-[#666]">
                <span>上传中...</span>
                <span>{uploadProgress}%</span>
              </div>
              <div className="h-2 bg-[#e8f0f0] rounded-full overflow-hidden">
                <div className="h-full bg-gradient-to-r from-[#298c88] to-[#00706b] transition-all duration-300" style={{ width: `${uploadProgress}%` }} />
              </div>
            </div>
          )}
        </div>

        <DialogFooter className="gap-2">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={submitting} className="border-[#e0e0e0] bg-white text-[#000] hover:bg-[#f5f5f5]">取消</Button>
          <Button onClick={handleSubmit} disabled={submitting || files.length === 0} className="bg-[#298c88] hover:bg-[#0d5d57] text-white border border-[#298c88]">
            {submitting ? <><Loader2 className="h-4 w-4 animate-spin" /> {uploadProgress < 100 ? "上传中..." : "分析中..."}</> : "开始分析"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface BatchFileEntry {
  file: File;
  station: string;
  device: string;
  status: "pending" | "uploading" | "done" | "failed";
  progress: number;
  error?: string;
  job?: FaultAnalysisJob;
}

interface BatchUploadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: (jobs: FaultAnalysisJob[]) => void;
}

function BatchUploadDialog({ open, onOpenChange, onSuccess }: BatchUploadDialogProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [entries, setEntries] = useState<BatchFileEntry[]>([]);
  const [submitting, setSubmitting] = useState(false);

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = event.target.files ? Array.from(event.target.files) : [];
    const archiveFiles = selectedFiles.filter((f) => /\.(zip|rar|7z|zwav)$/i.test(f.name));
    if (archiveFiles.length === 0 && selectedFiles.length > 0) {
      toast.error("请选择压缩包文件");
    }

    const newEntries: BatchFileEntry[] = archiveFiles.map((f) => {
      const name = f.name.replace(/\.(zip|rar|7z|zwav)$/i, "").trim();
      return { file: f, station: name, device: name, status: "pending" as const, progress: 0 };
    });
    setEntries(newEntries);
    if (event.target) event.target.value = "";
  };

  const updateEntry = (index: number, updates: Partial<BatchFileEntry>) => {
    setEntries((prev) => prev.map((e, i) => (i === index ? { ...e, ...updates } : e)));
  };

  const handleSubmit = async () => {
    if (entries.length === 0) {
      toast.error("请先选择文件");
      return;
    }
    setSubmitting(true);

    const createdJobs: FaultAnalysisJob[] = [];

    await Promise.allSettled(
      entries.map(async (entry, idx) => {
        updateEntry(idx, { status: "uploading", progress: 0 });
        try {
          const job = await createJobChunked([entry.file], (_, progress) => {
            updateEntry(idx, { progress });
          });
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
          <DialogTitle className="brand-display text-[#000]">批量上传</DialogTitle>
          <DialogDescription className="leading-6 text-[#666]">
            选择多个压缩包文件，系统将并行上传并创建分析任务
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <input
              ref={fileInputRef}
              type="file"
              accept=".zip,.rar,.7z,.zwav"
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
                    <th className="px-3 py-2.5 text-left font-medium text-[#555] w-[55%]">文件名</th>
                    <th className="px-3 py-2.5 text-left font-medium text-[#555] w-[15%]">大小</th>
                    <th className="px-3 py-2.5 text-center font-medium text-[#555] w-[15%]">状态</th>
                  </tr>
                </thead>
                <tbody>
                  {entries.map((entry, idx) => (
                    <tr key={idx} className="border-t border-[#e8f0f0]">
                      <td className="px-3 py-2 text-[#333] truncate max-w-[300px]" title={entry.file.name}>
                        {entry.file.name}
                      </td>
                      <td className="px-3 py-2 text-[#888]">
                        {(entry.file.size / 1024).toFixed(0)} KB
                      </td>
                      <td className="px-3 py-2 text-center">
                        {entry.status === "pending" && (
                          <span className="text-xs text-[#888]">等待中</span>
                        )}
                        {entry.status === "uploading" && (
                          <div className="flex flex-col items-center gap-1">
                            <span className="text-xs text-[#00706b]">{entry.progress}%</span>
                            <div className="w-full h-1.5 bg-[#e8f0f0] rounded-full overflow-hidden">
                              <div className="h-full bg-[#298c88] transition-all duration-300" style={{ width: `${entry.progress}%` }} />
                            </div>
                          </div>
                        )}
                        {entry.status === "done" && (
                          <span className="text-xs text-[#0d5d57]">完成</span>
                        )}
                        {entry.status === "failed" && (
                          <span className="text-xs text-[#cc3333]" title={entry.error}>失败</span>
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
            {allDone ? "关闭" : "取消"}
          </Button>
          {!allDone && (
            <Button
              onClick={handleSubmit}
              disabled={submitting || entries.length === 0}
              className="bg-[#298c88] hover:bg-[#0d5d57] text-white border border-[#298c88]"
            >
              {submitting ? (
                <><Loader2 className="h-4 w-4 animate-spin" /> 上传中...</>
              ) : (
                "开始上传"
              )}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
