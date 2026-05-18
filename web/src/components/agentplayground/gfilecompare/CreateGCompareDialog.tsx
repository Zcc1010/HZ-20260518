import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Button } from "../../ui/button";
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
import { useCreateGFileCompareJob } from "../../../hooks/useGFileCompare";

interface CreateGCompareDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CreateGCompareDialog({ open, onOpenChange }: CreateGCompareDialogProps) {
  const { t } = useTranslation();
  const createJob = useCreateGFileCompareJob();
  const [d5000File, setD5000File] = useState<File | null>(null);
  const [newGenFile, setNewGenFile] = useState<File | null>(null);

  const reset = () => {
    setD5000File(null);
    setNewGenFile(null);
  };

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) {
      reset();
    }
    onOpenChange(nextOpen);
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (!d5000File || !newGenFile) {
      toast.error(t("agentPlayground.noFileSelected"));
      return;
    }

    try {
      await createJob.mutateAsync({ d5000File, newGenFile });
      toast.success(t("agentPlayground.createSuccess"));
      handleOpenChange(false);
    } catch (error: unknown) {
      const detail =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        t("agentPlayground.createFailed");
      toast.error(detail);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="bg-[#2a2a2a] border-white/10 sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="brand-display text-white">
            {t("agentPlayground.createDialogTitle")}
          </DialogTitle>
          <DialogDescription className="leading-6 text-[#888]">
            {t("agentPlayground.createDialogDescription")}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="space-y-2">
            <Label htmlFor="g-compare-d5000" className="text-[#aaa]">{t("agentPlayground.d5000File")}</Label>
            <Input
              id="g-compare-d5000"
              type="file"
              className="bg-[#1a1a1a] border-white/10 text-white file:text-white file:bg-[#3a3a3a] file:border-0 file:rounded-md file:px-3 file:py-1.5"
              onChange={(event) => setD5000File(event.target.files?.[0] ?? null)}
            />
            {d5000File && <p className="text-xs text-[#888]">{d5000File.name}</p>}
          </div>

          <div className="space-y-2">
            <Label htmlFor="g-compare-new-gen" className="text-[#aaa]">{t("agentPlayground.newGenFile")}</Label>
            <Input
              id="g-compare-new-gen"
              type="file"
              className="bg-[#1a1a1a] border-white/10 text-white file:text-white file:bg-[#3a3a3a] file:border-0 file:rounded-md file:px-3 file:py-1.5"
              onChange={(event) => setNewGenFile(event.target.files?.[0] ?? null)}
            />
            {newGenFile && <p className="text-xs text-[#888]">{newGenFile.name}</p>}
          </div>

          <DialogFooter className="gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => handleOpenChange(false)}
              disabled={createJob.isPending}
              className="border-white/10 bg-[#1a1a1a] text-white hover:bg-[#3a3a3a]"
            >
              {t("agentPlayground.cancel")}
            </Button>
            <Button type="submit" disabled={createJob.isPending} className="bg-[#3a3a3a] hover:bg-[#4a4a4a] text-white border border-white/10">
              {createJob.isPending ? t("agentPlayground.status.processing") : t("agentPlayground.startGenerate")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
