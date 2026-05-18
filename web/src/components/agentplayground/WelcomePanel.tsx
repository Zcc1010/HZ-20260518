import { ArrowRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { BRAND_ASSETS, BRAND_NAME } from "../../lib/branding";
import type { AgentPlaygroundAppDefinition } from "../../lib/agentplayground/registry";

interface WelcomePanelProps {
  apps: AgentPlaygroundAppDefinition[];
  onSelect: (appId: string) => void;
}

export function WelcomePanel({ apps, onSelect }: WelcomePanelProps) {
  const { t } = useTranslation();

  return (
    <div className="flex h-full min-h-[420px] flex-col justify-between gap-8 rounded-[28px] bg-gradient-to-b from-white to-[#f0f7fa]/70 p-6 sm:p-8 border border-[#e8f0f0]">
      <div className="flex flex-col gap-8 lg:flex-row lg:items-start lg:justify-between">
        <div className="max-w-2xl">
          <div className="inline-flex items-center gap-3 rounded-full border border-[#e0e0e0] bg-[#f0f7fa]/80 px-4 py-2 text-xs text-[#666]">
            <img src={BRAND_ASSETS.logoSmall} alt={BRAND_NAME} className="h-5 w-5 object-contain" />
            <span>{t("agentPlayground.title")}</span>
          </div>
          <h1 className="brand-display mt-5 text-3xl leading-tight text-[#000] sm:text-4xl">
            {t("agentPlayground.welcomeTitle")}
          </h1>
          <p className="mt-4 max-w-xl text-sm leading-7 text-[#555] sm:text-base">
            {t("agentPlayground.welcomeDescription")}
          </p>
          <p className="mt-3 text-sm text-[#888]">
            {t("agentPlayground.welcomeHint")}
          </p>
        </div>

        <div className="rounded-[26px] border border-[#e0e0e0] bg-white p-5 shadow-md">
          <img
            src={BRAND_ASSETS.logoLarge}
            alt={BRAND_NAME}
            className="h-24 w-24 object-contain sm:h-28 sm:w-28"
          />
        </div>
      </div>

      <div className="grid gap-3 xl:grid-cols-2">
        {apps.map((app) => {
          const Icon = app.icon;

          return (
            <button
              key={app.id}
              type="button"
              onClick={() => onSelect(app.id)}
              className="group flex items-center justify-between rounded-[24px] border border-[#e0e0e0] bg-white p-5 text-left transition-all hover:-translate-y-0.5 hover:border-[#84aca9] hover:shadow-lg hover:shadow-[rgba(13,93,87,0.12)]"
            >
              <div className="flex min-w-0 items-center gap-4">
                <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-[#f0f7fa] to-[#e8f0f0] text-[#298c88] border border-[#e0e0e0]">
                  <Icon className="h-5 w-5" />
                </div>
                <div className="min-w-0">
                  <p className="brand-display text-base text-[#000]">{t(app.titleKey)}</p>
                  <p className="mt-1 text-sm leading-6 text-[#666]">{t(app.descriptionKey)}</p>
                </div>
              </div>
              <ArrowRight className="h-4 w-4 shrink-0 text-[#888] transition-transform group-hover:translate-x-0.5" />
            </button>
          );
        })}
      </div>
    </div>
  );
}
