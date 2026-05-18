import { useState, useEffect, useRef } from "react";
import { Download, Plus, FileText, Loader2, FileDown, ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "../../ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../../ui/table";
import { Badge } from "../../ui/badge";
import { cn } from "../../../lib/utils";
import { withBasePath } from "../../../lib/basePath";

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
  station?: string;
  device?: string;
  progress: number;
  progress_message?: string;
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

const PAGE_SIZE = 10;

export function WaveRecordWorkspace() {
  const { t } = useTranslation();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [jobs, setJobs] = useState<WaveRecordJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);

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

  // 确保当前页不超出范围
  useEffect(() => {
    if (currentPage > totalPages) {
      setCurrentPage(totalPages);
    }
  }, [jobs.length, totalPages, currentPage]);

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

          <Button
            onClick={() => setDialogOpen(true)}
            className="gap-2 self-start sm:self-auto bg-[#298c88] hover:bg-[#0d5d57] text-white border border-[#298c88]"
          >
            <Plus className="h-4 w-4" />
            {t("agentPlayground.create")}
          </Button>
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
          <div className="rounded-[28px] border border-[#e0e0e0] bg-white shadow-md overflow-hidden">
            <div className="overflow-auto max-h-[calc(100vh-340px)]">
              <Table className="min-w-[800px]">
                <TableHeader className="bg-[#0d5d57] sticky top-0 z-10">
                  <TableRow className="border-[#e8f0f0] hover:bg-[#0d5d57]">
                    <TableHead className="px-5 py-4 text-[#dcecec]">
                      {t("agentPlayground.waveRecord.table.fileName")}
                    </TableHead>
                    <TableHead className="px-5 py-4 text-[#dcecec]">
                      {t("agentPlayground.waveRecord.table.station")}
                    </TableHead>
                    <TableHead className="px-5 py-4 text-[#dcecec]">
                      {t("agentPlayground.waveRecord.table.device")}
                    </TableHead>
                    <TableHead className="px-5 py-4 text-[#dcecec]">
                      {t("agentPlayground.waveRecord.table.status")}
                    </TableHead>
                    <TableHead className="px-5 py-4 text-[#dcecec]">
                      {t("agentPlayground.waveRecord.table.createdAt")}
                    </TableHead>
                    <TableHead className="px-5 py-4 text-[#dcecec]">
                      {t("agentPlayground.table.download")}
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {paginatedJobs.length === 0 ? (
                    <TableRow>
                      <TableCell className="px-5 py-10 text-sm text-[#888]" colSpan={6}>
                        {t("agentPlayground.noJobs")}
                      </TableCell>
                    </TableRow>
                  ) : (
                    paginatedJobs.map((job) => (
                      <TableRow key={job.id} className="border-[#e8f0f0] hover:bg-[#dcecec]/50">
                        <TableCell className="px-5 py-4 font-medium text-[#000]">
                          <div className="flex items-center gap-2 max-w-[200px]">
                            <FileText className="h-4 w-4 text-[#666] shrink-0" />
                            <span className="truncate" title={job.file_name}>{job.file_name}</span>
                          </div>
                        </TableCell>
                        <TableCell className="px-5 py-4 text-[#555]">
                          <span className="truncate max-w-[150px] block" title={job.station || "-"}>{job.station || "-"}</span>
                        </TableCell>
                        <TableCell className="px-5 py-4 text-[#555]">
                          <span className="truncate max-w-[150px] block" title={job.device || "-"}>{job.device || "-"}</span>
                        </TableCell>
                        <TableCell className="px-5 py-4">
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
                        </TableCell>
                        <TableCell className="px-5 py-4 text-[#555]">
                          {formatDateTime(job.created_at)}
                        </TableCell>
                        <TableCell className="px-5 py-4">
                          {job.status === "completed" && job.download_url ? (
                            <a
                              href={withBasePath(job.download_url)}
                              className="inline-flex items-center gap-2 text-sm font-medium text-[#00706b] transition-colors hover:text-[#298c88]"
                            >
                              <Download className="h-4 w-4" />
                              <span className="truncate max-w-[150px]" title={job.result_file_name ?? t("agentPlayground.download")}>{job.result_file_name ?? t("agentPlayground.download")}</span>
                            </a>
                          ) : (
                            <span className="text-sm text-[#888]">
                              {t("agentPlayground.downloadUnavailable")}
                            </span>
                          )}
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>

            {/* 分页控件 */}
            {jobs.length > PAGE_SIZE && (
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
                  {Array.from({ length: totalPages }, (_, i) => i + 1).map((page) => (
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
                  ))}
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
      />
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
}

function CreateWaveRecordDialog({ open, onOpenChange, onSuccess }: CreateWaveRecordDialogProps) {
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
              <a
                href={withBasePath("/assets/录波文件上传手册.md")}
                download
                className="inline-flex items-center gap-1.5 text-[#00706b] hover:text-[#298c88] transition-colors"
              >
                <FileDown className="h-3.5 w-3.5" />
                下载上传手册
              </a>
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
