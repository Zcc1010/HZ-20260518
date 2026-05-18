import { useState } from "react";
import { Download, Plus } from "lucide-react";
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
import { useGFileCompareJobs, type GFileCompareJob } from "../../../hooks/useGFileCompare";
import { CreateGCompareDialog } from "./CreateGCompareDialog";
import { cn } from "../../../lib/utils";
import { withBasePath } from "../../../lib/basePath";

function statusBadgeClass(status: GFileCompareJob["status"]) {
  if (status === "completed") {
    return "bg-[#1a3a2a] text-[#4ade80] hover:bg-[#1a3a2a]";
  }
  if (status === "failed") {
    return "bg-[#3a1a1a] text-[#f87171] hover:bg-[#3a1a1a]";
  }
  if (status === "processing") {
    return "bg-[#1a2a3a] text-[#60a5fa] hover:bg-[#1a2a3a]";
  }
  return "bg-[#2a2a2a] text-[#888] hover:bg-[#2a2a2a]";
}

export function GFileCompareWorkspace() {
  const { t } = useTranslation();
  const [dialogOpen, setDialogOpen] = useState(false);
  const { data: jobs = [], isLoading } = useGFileCompareJobs();

  return (
    <>
      <div className="space-y-5">
        <div className="flex flex-col gap-4 rounded-[24px] border border-white/10 bg-[#2a2a2a]/80 p-4 shadow-lg shadow-black/20 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.18em] text-[#666]">
              {t("agentPlayground.title")}
            </p>
            <h2 className="brand-display mt-2 text-2xl text-white">
              {t("agentPlayground.apps.gFileCompare.title")}
            </h2>
          </div>

          <Button onClick={() => setDialogOpen(true)} className="gap-2 self-start sm:self-auto bg-[#3a3a3a] hover:bg-[#4a4a4a] text-white border border-white/10">
            <Plus className="h-4 w-4" />
            {t("agentPlayground.create")}
          </Button>
        </div>

        <div className="overflow-hidden rounded-[28px] border border-white/10 bg-[#2a2a2a]/80 shadow-lg shadow-black/20">
          <Table>
            <TableHeader className="bg-[#1a1a1a]">
              <TableRow className="border-white/10 hover:bg-[#1a1a1a]">
                <TableHead className="px-5 py-4 text-[#888]">{t("agentPlayground.table.d5000File")}</TableHead>
                <TableHead className="px-5 py-4 text-[#888]">{t("agentPlayground.table.newGenFile")}</TableHead>
                <TableHead className="px-5 py-4 text-[#888]">{t("agentPlayground.table.status")}</TableHead>
                <TableHead className="px-5 py-4 text-[#888]">{t("agentPlayground.table.download")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell className="px-5 py-8 text-sm text-[#666]" colSpan={4}>
                    {t("common.loading")}
                  </TableCell>
                </TableRow>
              ) : jobs.length === 0 ? (
                <TableRow>
                  <TableCell className="px-5 py-10 text-sm text-[#666]" colSpan={4}>
                    {t("agentPlayground.noJobs")}
                  </TableCell>
                </TableRow>
              ) : (
                jobs.map((job) => (
                  <TableRow key={job.id} className="border-white/10 hover:bg-[#3a3a3a]/50">
                    <TableCell className="px-5 py-4 font-medium text-white">
                      {job.d5000_file_name}
                    </TableCell>
                    <TableCell className="px-5 py-4 text-[#aaa]">
                      {job.new_gen_file_name}
                    </TableCell>
                    <TableCell className="px-5 py-4">
                      <Badge className={cn("rounded-full px-2.5 py-1 font-medium", statusBadgeClass(job.status))}>
                        {t(`agentPlayground.status.${job.status}`)}
                      </Badge>
                      {job.error_message && (
                        <p className="mt-2 max-w-sm text-xs leading-5 text-[#f87171]">
                          {job.error_message}
                        </p>
                      )}
                    </TableCell>
                    <TableCell className="px-5 py-4">
                      {job.status === "completed" && job.download_url ? (
                        <a
                          href={withBasePath(job.download_url)}
                          className="inline-flex items-center gap-2 text-sm font-medium text-[#60a5fa] transition-colors hover:text-[#93c5fd]"
                        >
                          <Download className="h-4 w-4" />
                          {job.result_file_name ?? t("agentPlayground.download")}
                        </a>
                      ) : (
                        <span className="text-sm text-[#666]">
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
      </div>

      <CreateGCompareDialog open={dialogOpen} onOpenChange={setDialogOpen} />
    </>
  );
}
