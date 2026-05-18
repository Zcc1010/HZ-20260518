import { useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AppList } from "../components/agentplayground/AppList";
import { WelcomePanel } from "../components/agentplayground/WelcomePanel";
import { WaveRecordWorkspace } from "../components/agentplayground/waverecord/WaveRecordWorkspace";
import { AGENT_PLAYGROUND_APPS, getAgentPlaygroundApp } from "../lib/agentplayground/registry";
import { BRAND_ASSETS, BRAND_NAME } from "../lib/branding";

export default function AgentPlayground() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { appId } = useParams();
  const selectedApp = getAgentPlaygroundApp(appId);

  useEffect(() => {
    if (!appId) {
      return;
    }
    if (!selectedApp) {
      navigate("/agentplayground", { replace: true });
    }
  }, [appId, navigate, selectedApp]);

  const openApp = (nextAppId: string) => {
    navigate(`/agentplayground/${nextAppId}`, { replace: true });
  };

  return (
    <div className="min-h-screen bg-[#f2f3f7] px-3 py-4 sm:px-4 sm:py-5 lg:px-5">
      <div className="mx-auto flex max-w-[1600px] flex-col gap-4 lg:h-[calc(100vh-2.5rem)] lg:flex-row">
        <aside className="flex w-full flex-col rounded-[30px] border border-[#e0e0e0] bg-white/95 p-5 shadow-[0_4px_20px_rgba(13,93,87,0.08)] lg:w-[290px] lg:shrink-0 lg:p-6">
          <div className="flex items-start gap-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-[24px] bg-gradient-to-br from-[#f0f7fa] to-[#e8f0f0] shadow-md">
              <img src={BRAND_ASSETS.logoSmall} alt={BRAND_NAME} className="h-8 w-8 object-contain" />
            </div>
            <div className="min-w-0">
              <p className="brand-display text-2xl leading-none text-[#000]">{BRAND_NAME}</p>
              <p className="mt-2 text-sm text-[#666]">{t("agentPlayground.subtitle")}</p>
            </div>
          </div>

          <div className="mt-6 rounded-[24px] bg-gradient-to-b from-[#f0f7fa]/80 to-[#e8f0f0]/60 p-4 border border-[#e8f0f0]">
            <p className="text-xs uppercase tracking-[0.18em] text-[#888]">
              {t("agentPlayground.title")}
            </p>
            <p className="mt-2 text-sm leading-6 text-[#555]">
              {t("agentPlayground.sidebarDescription")}
            </p>
          </div>

          <div className="mt-5 flex-1 overflow-y-auto">
            <AppList
              apps={AGENT_PLAYGROUND_APPS}
              selectedAppId={selectedApp?.id ?? null}
              onSelect={openApp}
            />
          </div>
        </aside>

        <main className="min-h-[540px] flex-1 rounded-[30px] border border-[#e0e0e0] bg-white/95 p-4 shadow-[0_4px_20px_rgba(13,93,87,0.08)] sm:p-5 lg:overflow-auto lg:p-6">
          {selectedApp?.id === "wave-record-parser" ? (
            <WaveRecordWorkspace />
          ) : (
            <WelcomePanel apps={AGENT_PLAYGROUND_APPS} onSelect={openApp} />
          )}
        </main>
      </div>
    </div>
  );
}
