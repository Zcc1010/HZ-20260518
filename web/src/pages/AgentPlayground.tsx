import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AudioWaveform, FileCheck, Activity, MessageSquare, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { WaveRecordWorkspace } from "../components/agentplayground/waverecord/WaveRecordWorkspace";
import { SettingCheckWorkspace } from "../components/agentplayground/settingcheck/SettingCheckWorkspace";
import { BRAND_NAME } from "../lib/branding";
import { cn } from "../lib/utils";

type AppId = "wave-record-parser" | "setting-check" | "comtrade";

interface AppItem {
  id: AppId;
  titleKey: string;
  descriptionKey: string;
  icon: React.ElementType;
}

const APPS: AppItem[] = [
  { id: "wave-record-parser", titleKey: "agentPlayground.apps.waveRecordParser.title", descriptionKey: "agentPlayground.apps.waveRecordParser.description", icon: AudioWaveform },
  { id: "setting-check", titleKey: "agentPlayground.apps.settingCheck.title", descriptionKey: "agentPlayground.apps.settingCheck.description", icon: FileCheck },
  { id: "comtrade", titleKey: "nav.comtrade", descriptionKey: "agentPlayground.apps.comtrade.description", icon: Activity },
];

export default function AgentPlayground() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [selectedAppId, setSelectedAppId] = useState<AppId>("wave-record-parser");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  return (
    <div className="h-screen bg-[#f2f3f7] px-3 py-4 sm:px-4 sm:py-5 lg:px-5">
      <div className="mx-auto flex h-[calc(100vh-2.5rem)] max-w-[1600px] gap-4">
        {/* Sidebar */}
        <aside className={cn(
          "flex flex-col rounded-[30px] border border-[#e0e0e0] bg-white/95 shadow-[0_4px_20px_rgba(13,93,87,0.08)] transition-all duration-300 shrink-0 overflow-hidden",
          sidebarCollapsed ? "w-[72px] p-3" : "w-[290px] p-5 lg:p-6"
        )}>
          {/* Header */}
          <div className={cn("flex items-center gap-3", sidebarCollapsed && "justify-center")}>
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[20px] bg-gradient-to-br from-[#298c88] to-[#00706b] shadow-md">
              <Activity className="h-6 w-6 text-white" />
            </div>
            {!sidebarCollapsed && (
              <div className="min-w-0">
                <p className="brand-display text-xl leading-none text-[#000]">{BRAND_NAME}</p>
                <p className="mt-1 text-xs text-[#888]">{t("agentPlayground.subtitle")}</p>
              </div>
            )}
          </div>

          {/* Description - hidden when collapsed */}
          {!sidebarCollapsed && (
            <div className="mt-5 rounded-[20px] bg-gradient-to-b from-[#f0f7fa]/80 to-[#e8f0f0]/60 p-4 border border-[#e8f0f0]">
              <p className="text-xs uppercase tracking-[0.15em] text-[#888]">
                {t("agentPlayground.title")}
              </p>
              <p className="mt-1.5 text-xs leading-5 text-[#666]">
                {t("agentPlayground.sidebarDescription")}
              </p>
            </div>
          )}

          {/* App List */}
          <div className={cn("flex-1 overflow-y-auto", sidebarCollapsed ? "mt-3" : "mt-4")}>
            <div className={cn("space-y-1", sidebarCollapsed && "flex flex-col items-center")}>
              {APPS.map((app) => {
                const Icon = app.icon;
                const isActive = selectedAppId === app.id;
                return (
                  <button
                    key={app.id}
                    onClick={() => setSelectedAppId(app.id)}
                    className={cn(
                      "flex items-center rounded-xl text-left transition-all duration-200",
                      sidebarCollapsed ? "w-12 h-12 justify-center p-0" : "w-full gap-3 px-3 py-2.5",
                      isActive
                        ? "bg-[#298c88] text-white shadow-sm"
                        : "text-[#555] hover:bg-[#e8f0f0] hover:text-[#0d5d57]"
                    )}
                    title={t(app.titleKey)}
                  >
                    <Icon className={cn("h-5 w-5 shrink-0", isActive ? "text-white" : "text-[#298c88]")} />
                    {!sidebarCollapsed && (
                      <span className="text-sm font-medium truncate">{t(app.titleKey)}</span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Bottom actions */}
          <div className={cn("mt-auto pt-3 border-t border-[#e8f0f0]", sidebarCollapsed ? "flex flex-col items-center gap-2" : "space-y-2")}>
            {/* Chat button */}
            <button
              onClick={() => navigate("/chat")}
              className={cn(
                "flex items-center rounded-xl border border-[#e0e0e0] bg-white text-sm font-medium text-[#555] hover:bg-[#e8f0f0] hover:text-[#0d5d57] transition-all duration-200",
                sidebarCollapsed ? "w-12 h-12 justify-center p-0" : "w-full gap-2.5 px-3 py-2.5"
              )}
              title={t("nav.chat")}
            >
              <MessageSquare className="h-4 w-4 shrink-0" />
              {!sidebarCollapsed && <span>{t("nav.chat")}</span>}
            </button>

            {/* Collapse toggle */}
            <button
              onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
              className={cn(
                "flex items-center rounded-xl text-xs text-[#888] hover:bg-[#e8f0f0] hover:text-[#0d5d57] transition-all duration-200",
                sidebarCollapsed ? "w-12 h-12 justify-center p-0" : "w-full gap-2 px-3 py-2"
              )}
              title={sidebarCollapsed ? t("nav.expand") : t("nav.collapse")}
            >
              {sidebarCollapsed ? (
                <PanelLeftOpen className="h-4 w-4" />
              ) : (
                <>
                  <PanelLeftClose className="h-4 w-4" />
                  <span>{t("nav.collapse")}</span>
                </>
              )}
            </button>
          </div>
        </aside>

        {/* Main content */}
        <main className="flex-1 min-w-0 rounded-[30px] border border-[#e0e0e0] bg-white/95 p-4 shadow-[0_4px_20px_rgba(13,93,87,0.08)] sm:p-5 overflow-auto lg:p-6">
          {selectedAppId === "wave-record-parser" && <WaveRecordWorkspace />}
          {selectedAppId === "setting-check" && <SettingCheckWorkspace />}
          {selectedAppId === "comtrade" && <ComtradeContent />}
        </main>
      </div>
    </div>
  );
}

function ComtradeContent() {
  return (
    <iframe
      src="/protection/comtrade-app/index.html"
      style={{ width: "100%", height: "100%", border: "none", borderRadius: "12px" }}
      title="故障录波简报生成器"
    />
  );
}
