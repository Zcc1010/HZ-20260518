import { useTranslation } from "react-i18next";
import { cn } from "../../lib/utils";
import type { AgentPlaygroundAppDefinition } from "../../lib/agentplayground/registry";

interface AppListProps {
  apps: AgentPlaygroundAppDefinition[];
  selectedAppId: string | null;
  onSelect: (appId: string) => void;
}

export function AppList({ apps, selectedAppId, onSelect }: AppListProps) {
  const { t } = useTranslation();

  return (
    <div className="space-y-2">
      {apps.map((app) => {
        const Icon = app.icon;
        const active = app.id === selectedAppId;

        return (
          <button
            key={app.id}
            type="button"
            onClick={() => onSelect(app.id)}
            className={cn(
              "w-full rounded-[22px] border px-4 py-3 text-left transition-all",
              active
                ? "border-[#84aca9] bg-[#f0f7fa] text-[#000] shadow-sm shadow-[rgba(13,93,87,0.12)]"
                : "border-[#e0e0e0] bg-white/80 text-[#555] hover:border-[#ccc] hover:bg-[#f0f7fa]/80"
            )}
          >
            <div className="flex items-start gap-3">
              <div
                className={cn(
                  "mt-0.5 flex h-10 w-10 items-center justify-center rounded-2xl border",
                  active
                    ? "border-[#84aca9] bg-gradient-to-br from-[#f0f7fa] to-[#e8f0f0] text-[#298c88]"
                    : "border-[#e0e0e0] bg-[#f5f5f5] text-[#666]"
                )}
              >
                <Icon className="h-4.5 w-4.5" />
              </div>
              <div className="min-w-0">
                <p className="brand-display text-sm text-[#000]">{t(app.titleKey)}</p>
                <p className="mt-1 line-clamp-2 text-xs leading-5 text-[#666]">
                  {t(app.descriptionKey)}
                </p>
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}
