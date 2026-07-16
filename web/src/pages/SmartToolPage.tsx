import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useIsMobile } from "../hooks/useIsMobile";
import { Button } from "../components/ui/button";
import { ArrowLeft } from "lucide-react";
import { cn } from "../lib/utils";

interface SmartToolPageProps<T extends { id: string }> {
  title: string;
  titleKey?: string;
  showSidebar?: boolean;
  JobListComponent: React.ComponentType<{ selectedJobId: string | null; onSelect: (job: T) => void }>;
  WorkspaceComponent: React.ComponentType<{ selectedJob: T | null }>;
}

export default function SmartToolPage<T extends { id: string }>({
  title,
  titleKey,
  showSidebar = true,
  JobListComponent,
  WorkspaceComponent,
}: SmartToolPageProps<T>) {
  const { t } = useTranslation();
  const isMobile = useIsMobile();
  const [selectedJob, setSelectedJob] = useState<T | null>(null);
  const [mobileShowDetail, setMobileShowDetail] = useState(false);

  const displayTitle = titleKey ? t(titleKey, title) : title;

  const handleSelect = (job: T) => {
    setSelectedJob(job);
    if (isMobile) setMobileShowDetail(true);
  };

  return (
    <div className={cn(
      "flex min-h-0",
      isMobile ? "flex-1 flex-col" : "h-full gap-4 p-5"
    )}>
      {/* Left Panel - Job List */}
      {showSidebar && <aside
        className={cn(
          "flex shrink-0 flex-col overflow-hidden",
          isMobile
            ? cn("w-full flex-1 min-h-0 pt-14 bg-background", mobileShowDetail && "hidden")
            : "w-64 min-w-0 rounded-[24px] brand-panel"
        )}
        style={isMobile ? undefined : { width: "16rem", minWidth: 0, maxWidth: "16rem", boxShadow: "var(--shadow-card)" }}
      >
        {/* Header */}
        <div className={cn(
          "shrink-0 flex items-center border-b border-[#e8f0f0]",
          isMobile ? "px-4 py-3" : "px-3 py-2.5"
        )}>
          <h3 className={cn(
            "font-semibold text-[#0d5d57]",
            isMobile ? "text-base" : "text-sm"
          )}>
            {displayTitle}
          </h3>
        </div>

        {/* Job List */}
        <div className="flex-1 min-h-0 overflow-hidden">
          <JobListComponent
            selectedJobId={selectedJob?.id ?? null}
            onSelect={handleSelect}
          />
        </div>
      </aside>}

      {/* Right Panel - Workspace */}
      <div
        className={cn(
          "flex flex-col overflow-hidden",
          isMobile
            ? cn("w-full flex-1 min-h-0", !mobileShowDetail && "hidden")
            : "flex-1 rounded-[28px] brand-panel"
        )}
        style={isMobile ? undefined : { boxShadow: "var(--shadow-card)" }}
      >
        {/* Mobile back button */}
        {isMobile && (
          <div className="flex h-12 shrink-0 items-center gap-2 px-3">
            <Button
              size="icon"
              variant="ghost"
              className="h-9 w-9"
              onClick={() => setMobileShowDetail(false)}
            >
              <ArrowLeft className="h-5 w-5" />
            </Button>
            <span className="flex-1 truncate text-sm font-medium">
              {displayTitle}
            </span>
          </div>
        )}

        {/* Workspace Content */}
        <div className="flex flex-col flex-1 overflow-hidden">
          <WorkspaceComponent selectedJob={selectedJob} />
        </div>
      </div>
    </div>
  );
}
