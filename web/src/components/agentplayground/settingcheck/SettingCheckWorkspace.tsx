import { useState, useEffect, useRef } from "react";
import { Download, Plus, Loader2, ChevronLeft, ChevronRight, Eye, Trash2, FileArchive, FileDown, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Button } from "../../ui/button";
import { Badge } from "../../ui/badge";
import { cn } from "../../../lib/utils";
import { withBasePath } from "../../../lib/basePath";
import { MarkdownRenderer } from "../../shared/MarkdownRenderer";

interface SettingCheckJob {
  id: string;
  status: "queued" | "processing" | "completed" | "failed";
  created_at: string;
  updated_at: string;
  error_message?: string;
  station: string;
  device: string;
  setting_files: string[];
  calc_file: string;
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
    const seconds = String(date.getSeconds()).padStart(2, "0");
    return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
  } catch {
    return isoString;
  }
}

function statusBadgeClass(status: SettingCheckJob["status"]) {
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

async function fetchJobs(): Promise<SettingCheckJob[]> {
  const response = await fetch(withBasePath("/api/setting-check/jobs"));
  if (!response.ok) {
    throw new Error("Failed to fetch jobs");
  }
  return response.json();
}

const PAGE_SIZE = 20;

export function SettingCheckWorkspace() {
  const { t } = useTranslation();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [jobs, setJobs] = useState<SettingCheckJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewTitle, setPreviewTitle] = useState("");
  const [previewContent, setPreviewContent] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<SettingCheckJob | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [exporting, setExporting] = useState(false);

  const totalPages = Math.max(1, Math.ceil(jobs.length / PAGE_SIZE));
  const paginatedJobs = jobs.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

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

  useEffect(() => {
    if (currentPage > totalPages) {
      setCurrentPage(totalPages);
    }
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
        fetchJobs()
          .then((data) => setJobs(data))
          .catch(() => {});
      }, 1500);
      return () => clearInterval(interval);
    }
  }, [jobs]);

  const saveEvaluation = async (jobId: string, value: string) => {
    try {
      const res = await fetch(withBasePath(`/api/setting-check/jobs/${jobId}`), {
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
      const res = await fetch(withBasePath(`/api/setting-check/jobs/${deleteTarget.id}`), { method: "DELETE" });
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
      const res = await fetch(withBasePath("/api/setting-check/jobs/export"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_ids: ids }),
      });
      if (res.ok) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "定值校核报告导出.zip";
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
              {t("agentPlayground.apps.settingCheck.title")}
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
              onClick={() => setDialogOpen(true)}
              className="gap-2 bg-[#298c88] hover:bg-[#0d5d57] text-white border border-[#298c88]"
            >
              <Plus className="h-4 w-4" />
              {t("agentPlayground.create")}
            </Button>
          </div>
        </div>

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
          <div className="rounded-[28px] border border-[#e0e0e0] bg-white shadow-md overflow-hidden flex flex-col" style={{ height: "calc(100vh - 200px)" }}>
            <div className="flex-1 overflow-auto">
              <table className="w-full text-sm border-separate border-spacing-0" style={{ minWidth: 700 }}>
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
                      {t("agentPlayground.settingCheck.table.station")}
                    </th>
                    <th className="px-5 py-4 text-left font-medium text-[#dcecec]">
                      {t("agentPlayground.settingCheck.table.deviceName")}
                    </th>
                    <th className="px-5 py-4 text-left font-medium text-[#dcecec]">
                      {t("agentPlayground.settingCheck.table.status")}
                    </th>
                    <th className="px-5 py-4 text-left font-medium text-[#dcecec]">
                      {t("agentPlayground.settingCheck.table.createdAt")}
                    </th>
                    <th className="px-5 py-4 text-left font-medium text-[#dcecec]">
                      {t("agentPlayground.settingCheck.table.evaluation")}
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
                        {t("agentPlayground.noJobs")}
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
                        <td className="px-5 py-4">
                          <div className="flex flex-col gap-2">
                            <Badge className={cn("rounded-full px-2.5 py-1 font-medium w-fit", statusBadgeClass(job.status))}>
                              {t(`agentPlayground.status.${job.status}`)}
                            </Badge>
                            {job.status === "processing" && job.progress > 0 && (
                              <div className="flex flex-col gap-1 w-full max-w-[200px]">
                                <div className="h-2 bg-[#e8f0f0] rounded-full overflow-hidden">
                                  <div
                                    className="h-full bg-gradient-to-r from-[#298c88] to-[#00706b] transition-all duration-300"
                                    style={{ width: `${job.progress}%` }}
                                  />
                                </div>
                                <div className="flex justify-between items-center text-xs text-[#666]">
                                  <span>{job.progress}%</span>
                                  {job.progress_message && (
                                    <span className="truncate ml-2">{job.progress_message}</span>
                                  )}
                                </div>
                              </div>
                            )}
                            {job.error_message && (
                              <p className="mt-2 max-w-sm text-xs leading-5 text-[#cc3333]">
                                {job.error_message}
                              </p>
                            )}
                          </div>
                        </td>
                        <td className="px-5 py-4 text-[#555]">
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
                              title={job.evaluation || t("agentPlayground.settingCheck.table.evaluationPlaceholder")}
                            >
                              {job.evaluation || (
                                <span className="text-[#bbb]">{t("agentPlayground.settingCheck.table.evaluationPlaceholder")}</span>
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
                                  onClick={() => openPreview(job.preview_url!, job.station || "定值校核报告")}
                                  className="inline-flex items-center text-[#00706b] hover:text-[#298c88] transition-colors shrink-0"
                                  title={t("agentPlayground.settingCheck.preview")}
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
                        <td className="px-5 py-4 w-[80px]">
                          <button
                            type="button"
                            onClick={() => setDeleteTarget(job)}
                            className="inline-flex items-center text-[#999] hover:text-[#d44] transition-colors"
                            title={t("agentPlayground.table.delete")}
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
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
                <p className="text-xs text-[#666]">
                  共 {jobs.length} 条记录，第 {currentPage}/{totalPages} 页
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

      <CreateSettingCheckDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onSuccess={(newJob) => {
          setJobs((prev) => [newJob, ...prev]);
        }}
        onPreview={openPreview}
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
            {t("agentPlayground.table.deleteConfirmMessage", { name: deleteTarget?.station || deleteTarget?.id || "" })}
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

interface CreateSettingCheckDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: (job: SettingCheckJob) => void;
  onPreview: (url: string, title: string) => void;
}

const CHUNK_SIZE = 1 * 1024 * 1024; // 1MB

// 支持的文件格式
const SETTING_FILE_EXTENSIONS = [".xls", ".xlsx", ".doc", ".docx", ".pdf", ".txt", ".md"];
const CALC_FILE_EXTENSIONS = [".doc", ".docx", ".pdf", ".txt", ".md", ".xls", ".xlsx"];

function hasExtension(filename: string, extensions: string[]): boolean {
  const ext = filename.toLowerCase().slice(filename.lastIndexOf("."));
  return extensions.includes(ext);
}

async function uploadFile(
  file: File,
  onProgress?: (progress: number) => void,
): Promise<string> {
  const totalChunks = Math.ceil(file.size / CHUNK_SIZE);

  const initRes = await fetch(withBasePath("/api/setting-check/uploads/init"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      file_name: file.name,
      total_size: file.size,
      total_chunks: totalChunks,
    }),
  });
  if (!initRes.ok) throw new Error("Failed to initialize upload");
  const { upload_id } = await initRes.json();

  for (let j = 0; j < totalChunks; j++) {
    const start = j * CHUNK_SIZE;
    const end = Math.min(start + CHUNK_SIZE, file.size);
    const chunk = file.slice(start, end);

    const formData = new FormData();
    formData.append("chunk", chunk, file.name);

    const chunkRes = await fetch(
      withBasePath(`/api/setting-check/uploads/${upload_id}/chunks/${j}`),
      { method: "POST", body: formData },
    );
    if (!chunkRes.ok) throw new Error(`Failed to upload chunk ${j + 1}/${totalChunks}`);

    if (onProgress) {
      onProgress(Math.round(((j + 1) / totalChunks) * 100));
    }
  }

  return upload_id;
}

async function createJob(
  settingUploadIds: string[],
  calcUploadIds: string[],
  station: string,
  device: string,
): Promise<SettingCheckJob> {
  const completeRes = await fetch(
    withBasePath("/api/setting-check/uploads/complete"),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        station,
        device,
        setting_upload_ids: settingUploadIds,
        calc_upload_ids: calcUploadIds,
      }),
    },
  );
  if (!completeRes.ok) {
    const error = await completeRes.text();
    throw new Error(error || "Failed to complete upload");
  }
  return completeRes.json();
}

function CreateSettingCheckDialog({ open, onOpenChange, onSuccess, onPreview }: CreateSettingCheckDialogProps) {
  const { t } = useTranslation();
  const settingInputRef = useRef<HTMLInputElement>(null);
  const calcInputRef = useRef<HTMLInputElement>(null);
  const [settingFiles, setSettingFiles] = useState<File[]>([]);
  const [calcFiles, setCalcFiles] = useState<File[]>([]);
  const [station, setStation] = useState<string>("");
  const [device, setDevice] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState<number>(0);
  const [uploadingFileIndex, setUploadingFileIndex] = useState<string>("");

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!station) {
      setError(t("agentPlayground.settingCheck.stationRequired"));
      return;
    }
    if (!device) {
      setError(t("agentPlayground.settingCheck.deviceRequired"));
      return;
    }
    if (settingFiles.length === 0) {
      setError(t("agentPlayground.settingCheck.settingFilesRequired"));
      return;
    }
    if (calcFiles.length === 0) {
      setError(t("agentPlayground.settingCheck.calcFilesRequired"));
      return;
    }

    setSubmitting(true);
    setError(null);
    setUploadProgress(0);

    try {
      // Upload all setting files
      const settingUploadIds: string[] = [];
      for (let i = 0; i < settingFiles.length; i++) {
        const file = settingFiles[i];
        setUploadingFileIndex(`定值单 ${i + 1}/${settingFiles.length}: ${file.name}`);
        const uploadId = await uploadFile(file, (progress) => {
          const totalFiles = settingFiles.length + calcFiles.length;
          const baseProgress = (i / totalFiles) * 100;
          setUploadProgress(Math.round(baseProgress + (progress / totalFiles)));
        });
        settingUploadIds.push(uploadId);
      }

      // Upload all calc files
      const calcUploadIds: string[] = [];
      for (let i = 0; i < calcFiles.length; i++) {
        const file = calcFiles[i];
        setUploadingFileIndex(`计算书 ${i + 1}/${calcFiles.length}: ${file.name}`);
        const uploadId = await uploadFile(file, (progress) => {
          const totalFiles = settingFiles.length + calcFiles.length;
          const baseProgress = ((settingFiles.length + i) / totalFiles) * 100;
          setUploadProgress(Math.round(baseProgress + (progress / totalFiles)));
        });
        calcUploadIds.push(uploadId);
      }

      setUploadingFileIndex("正在创建任务...");
      const job = await createJob(settingUploadIds, calcUploadIds, station, device);
      onSuccess(job);
      onOpenChange(false);
      setSettingFiles([]);
      setCalcFiles([]);
      setStation("");
      setDevice("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
      setUploadingFileIndex("");
    }
  };

  const handleSettingFilesChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    const validFiles = files.filter(f => hasExtension(f.name, SETTING_FILE_EXTENSIONS));
    if (validFiles.length !== files.length) {
      setError(t("agentPlayground.settingCheck.invalidSettingFileType"));
    } else {
      setError(null);
    }
    setSettingFiles(validFiles);
    event.target.value = "";
  };

  const handleCalcFilesChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    const validFiles = files.filter(f => hasExtension(f.name, CALC_FILE_EXTENSIONS));
    if (validFiles.length !== files.length) {
      setError(t("agentPlayground.settingCheck.invalidCalcFileType"));
    } else {
      setError(null);
    }
    setCalcFiles(validFiles);
    event.target.value = "";
  };

  const removeSettingFile = (index: number) => {
    setSettingFiles(prev => prev.filter((_, i) => i !== index));
  };

  const removeCalcFile = (index: number) => {
    setCalcFiles(prev => prev.filter((_, i) => i !== index));
  };

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-white border-[#e0e0e0] sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="brand-display text-[#000]">
            {t("agentPlayground.settingCheck.createDialogTitle")}
          </DialogTitle>
          <DialogDescription className="leading-6 text-[#666]">
            {t("agentPlayground.settingCheck.createDialogDescription")}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="station" className="text-[#298c88]">
                {t("agentPlayground.settingCheck.station")} <span className="text-red-500">*</span>
              </Label>
              <Input
                id="station"
                type="text"
                value={station}
                onChange={(e) => setStation(e.target.value)}
                placeholder={t("agentPlayground.settingCheck.stationPlaceholder")}
                className="bg-[#f0f7fa] border-[#84aca9] text-[#000]"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="device" className="text-[#298c88]">
                {t("agentPlayground.settingCheck.deviceName")} <span className="text-red-500">*</span>
              </Label>
              <Input
                id="device"
                type="text"
                value={device}
                onChange={(e) => setDevice(e.target.value)}
                placeholder={t("agentPlayground.settingCheck.deviceNamePlaceholder")}
                className="bg-[#f0f7fa] border-[#84aca9] text-[#000]"
              />
            </div>
          </div>

          {/* 定值单文件上传 */}
          <div className="space-y-2">
            <Label className="text-[#298c88]">
              {t("agentPlayground.settingCheck.settingFiles")} <span className="text-red-500">*</span>
            </Label>
            <div className="flex items-center gap-3">
              <input
                ref={settingInputRef}
                type="file"
                multiple
                accept={SETTING_FILE_EXTENSIONS.join(",")}
                className="hidden"
                onChange={handleSettingFilesChange}
              />
              <Button
                type="button"
                variant="outline"
                onClick={() => settingInputRef.current?.click()}
                className="border-[#84aca9] bg-[#f0f7fa] text-[#000] hover:bg-[#e0f0f0]"
              >
                <Plus className="h-4 w-4 mr-1.5" />
                {t("agentPlayground.settingCheck.selectFiles")}
              </Button>
              <span className="text-xs text-[#888]">
                {t("agentPlayground.settingCheck.settingFilesHint")}
              </span>
            </div>
            {settingFiles.length > 0 && (
              <div className="space-y-1 mt-2">
                {settingFiles.map((file, index) => (
                  <div key={index} className="flex items-center justify-between bg-[#f0f7fa] rounded px-2 py-1">
                    <span className="text-sm text-[#555] truncate flex-1">
                      {file.name} ({formatFileSize(file.size)})
                    </span>
                    <button
                      type="button"
                      onClick={() => removeSettingFile(index)}
                      className="text-[#999] hover:text-[#d44] transition-colors ml-2"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 计算书文件上传 */}
          <div className="space-y-2">
            <Label className="text-[#298c88]">
              {t("agentPlayground.settingCheck.calcFiles")} <span className="text-red-500">*</span>
            </Label>
            <div className="flex items-center gap-3">
              <input
                ref={calcInputRef}
                type="file"
                multiple
                accept={CALC_FILE_EXTENSIONS.join(",")}
                className="hidden"
                onChange={handleCalcFilesChange}
              />
              <Button
                type="button"
                variant="outline"
                onClick={() => calcInputRef.current?.click()}
                className="border-[#84aca9] bg-[#f0f7fa] text-[#000] hover:bg-[#e0f0f0]"
              >
                <Plus className="h-4 w-4 mr-1.5" />
                {t("agentPlayground.settingCheck.selectFiles")}
              </Button>
              <span className="text-xs text-[#888]">
                {t("agentPlayground.settingCheck.calcFilesHint")}
              </span>
            </div>
            {calcFiles.length > 0 && (
              <div className="space-y-1 mt-2">
                {calcFiles.map((file, index) => (
                  <div key={index} className="flex items-center justify-between bg-[#f0f7fa] rounded px-2 py-1">
                    <span className="text-sm text-[#555] truncate flex-1">
                      {file.name} ({formatFileSize(file.size)})
                    </span>
                    <button
                      type="button"
                      onClick={() => removeCalcFile(index)}
                      className="text-[#999] hover:text-[#d44] transition-colors ml-2"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 手册链接 */}
          <div className="flex items-center gap-2 text-xs">
            <span className="text-[#888]">{t("agentPlayground.settingCheck.uploadHint")}</span>
            <div className="flex items-center gap-2">
              <span className="text-sm text-[#555]">{t("agentPlayground.settingCheck.uploadManual")}</span>
              <a
                href={withBasePath("/assets/定值校核上传手册.md")}
                download
                className="inline-flex items-center text-[#00706b] hover:text-[#298c88] transition-colors"
                title={t("agentPlayground.settingCheck.downloadManual")}
              >
                <FileDown className="h-3.5 w-3.5" />
              </a>
              <button
                type="button"
                onClick={() => onPreview("/assets/定值校核上传手册.md", t("agentPlayground.settingCheck.uploadManual"))}
                className="inline-flex items-center text-[#00706b] hover:text-[#298c88] transition-colors"
                title={t("agentPlayground.settingCheck.previewManual")}
              >
                <Eye className="h-3.5 w-3.5" />
              </button>
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
                <span>{uploadingFileIndex || t("agentPlayground.settingCheck.uploading")}</span>
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
                    ? t("agentPlayground.settingCheck.uploading")
                    : t("agentPlayground.settingCheck.processing")}
                </>
              ) : (
                t("agentPlayground.settingCheck.startCheck")
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
