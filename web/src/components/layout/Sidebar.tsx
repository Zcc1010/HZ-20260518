import { useLocation, useNavigate } from "react-router-dom";
import { TransitionLink as Link } from "../shared/TransitionLink";
import { useTranslation } from "react-i18next";
import { useTheme } from "next-themes";
import { useAuthStore } from "../../stores/authStore";
import { BRAND_ASSETS, BRAND_NAME } from "../../lib/branding";
import { cn } from "../../lib/utils";
import { Radio, Puzzle, Clock, Settings, Users, FileJson, Sun, Moon, Languages, LogOut, KeyRound, PanelLeftClose, PanelLeftOpen, MessageSquare, ChevronDown, BrainCircuit, FileCheck, Zap, FileText, ShieldAlert, ClipboardCheck } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";
import { useState } from "react";
import { ChangePasswordDialog } from "./ChangePasswordDialog";
import { LANGUAGE_OPTIONS, getLanguageLabel } from "../../i18n/languages";

interface NavItem {
  path: string;
  label: string;
  icon?: React.ElementType;
  asset?: string;
  activeAsset?: string;
  adminOnly?: boolean;
  children?: NavItem[];
}

const GENERAL_ITEMS: NavItem[] = [
  { path: "/chat", label: "nav.chat", icon: MessageSquare },
  {
    path: "/chat/tools",
    label: "nav.agentPlayground",
    icon: Puzzle,
    children: [
      { path: "/fault-analysis", label: "nav.faultAnalysis", icon: Zap },
      { path: "/setting-check", label: "nav.settingCheck", icon: FileCheck },
      { path: "/setting-parser", label: "nav.settingParser", icon: FileText },
      { path: "/risk-assessment", label: "nav.riskAssessment", icon: ShieldAlert },
      { path: "/safety-ticket-review", label: "nav.safetyTicketReview", icon: ClipboardCheck },
    ],
  },
];

const ADMIN_ITEMS: NavItem[] = [
  { path: "/settings", label: "nav.settings", icon: Settings },
  { path: "/channels", label: "nav.channels", icon: Radio },
  { path: "/tools", label: "nav.tools", icon: Puzzle, asset: BRAND_ASSETS.askIcon },
  { path: "/users", label: "nav.users", icon: Users, asset: BRAND_ASSETS.robot },
  { path: "/cron", label: "nav.cron", icon: Clock },
  { path: "/system-config", label: "nav.systemConfig", icon: FileJson },
];

function NavLink({ item, active, collapsed, isActive, location, onToggle }: { item: NavItem; active: boolean; collapsed: boolean; isActive: (item: NavItem) => boolean; location: { pathname: string }; onToggle?: () => void }) {
  const { t } = useTranslation();
  const Icon = item.icon;
  const hasChildren = item.children && item.children.length > 0;
  // Auto-expand if any child is active
  const hasActiveChild = item.children?.some(child => isActive(child)) ?? false;
  const [expanded, setExpanded] = useState(hasActiveChild);

  if (hasChildren) {
    return (
      <div>
        <button
          onClick={() => {
            if (collapsed && onToggle) {
              onToggle();
              setExpanded(true);
            } else {
              setExpanded(!expanded);
            }
          }}
          title={collapsed ? t(item.label) : undefined}
          className={cn(
            "group flex w-full items-center rounded-2xl text-sm font-medium transition-all duration-200",
            collapsed
              ? "justify-center py-2.5 mx-auto w-10"
              : "gap-3 px-3 py-2.5 hover:translate-x-0.5",
            active
              ? collapsed
                ? "bg-[hsl(var(--sidebar-active-bg))] text-[hsl(var(--sidebar-active-fg))] shadow-sm"
                : "brand-hover-border bg-[hsl(var(--sidebar-active-bg))] text-[hsl(var(--sidebar-active-fg))] shadow-sm"
              : collapsed
                ? "text-[hsl(var(--sidebar-fg))] hover:bg-[hsl(var(--sidebar-hover-bg))]"
                : "text-[hsl(var(--sidebar-fg))] hover:bg-[hsl(var(--sidebar-hover-bg))]"
          )}
        >
          {Icon && (
            <Icon
              className={cn(
                "h-4 w-4 shrink-0 transition-colors",
                active
                  ? "text-[hsl(var(--sidebar-active-fg))]"
                  : "text-[hsl(var(--sidebar-muted))] group-hover:text-[hsl(var(--sidebar-fg))]"
              )}
            />
          )}
          {!collapsed && (
            <>
              <span className="flex-1 truncate text-left">{t(item.label)}</span>
              <ChevronDown className={cn("h-3.5 w-3.5 shrink-0 transition-transform", expanded && "rotate-180")} />
            </>
          )}
        </button>
        {!collapsed && expanded && item.children && (
          <div className="ml-4 mt-0.5 space-y-0.5 border-l border-[hsl(var(--sidebar-border))] pl-2">
            {item.children.map((child) => (
              <NavLink key={child.path} item={child} active={isActive(child)} collapsed={false} isActive={isActive} location={location} />
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <Link
      to={item.path}
      title={collapsed ? t(item.label) : undefined}
      className={cn(
        "group flex items-center rounded-2xl text-sm font-medium transition-all duration-200",
        collapsed
          ? "justify-center py-2.5 mx-auto w-10"
          : "gap-3 px-3 py-2.5 hover:translate-x-0.5",
        active
          ? collapsed
            ? "bg-[hsl(var(--sidebar-active-bg))] text-[hsl(var(--sidebar-active-fg))] shadow-sm"
            : "brand-hover-border bg-[hsl(var(--sidebar-active-bg))] text-[hsl(var(--sidebar-active-fg))] shadow-sm"
          : collapsed
            ? "text-[hsl(var(--sidebar-fg))] hover:bg-[hsl(var(--sidebar-hover-bg))]"
            : "text-[hsl(var(--sidebar-fg))] hover:bg-[hsl(var(--sidebar-hover-bg))]"
      )}
    >
      {item.asset ? (
        <img
          src={active && item.activeAsset ? item.activeAsset : item.asset}
          alt={t(item.label)}
          className={cn("shrink-0 object-contain", collapsed ? "h-4 w-4" : "h-5 w-5")}
        />
      ) : Icon ? (
        <Icon
          className={cn(
            "h-4 w-4 shrink-0 transition-colors",
            active
              ? "text-[hsl(var(--sidebar-active-fg))]"
              : "text-[hsl(var(--sidebar-muted))] group-hover:text-[hsl(var(--sidebar-fg))]"
          )}
        />
      ) : null}
      {!collapsed && <span className="truncate">{t(item.label)}</span>}
    </Link>
  );
}

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const { t, i18n } = useTranslation();
  const { resolvedTheme, setTheme } = useTheme();
  const location = useLocation();
  const navigate = useNavigate();
  const { user, clearAuth, authlessEnabled } = useAuthStore((s) => ({
    user: s.user,
    clearAuth: s.clearAuth,
    authlessEnabled: s.authlessEnabled,
  }));
  const isAdmin = !authlessEnabled && user?.role === "admin";
  const navItems = GENERAL_ITEMS;
  const [showChangePwd, setShowChangePwd] = useState(false);

  const isActive = (item: NavItem) => {
    const currentPath = location.pathname;
    const itemPath = item.path.split("?")[0]; // Remove query params if any

    return currentPath === itemPath ||
      (itemPath !== "/dashboard" && itemPath !== "/chat" && currentPath.startsWith(itemPath));
  };

  const currentLangLabel = getLanguageLabel(i18n.language);

  return (
    <aside
      className={cn(
        "flex h-full flex-col transition-[width] duration-300 ease-in-out overflow-hidden",
        collapsed ? "w-14" : "w-56"
      )}
      style={{
        width: collapsed ? undefined : "232px",
        background: "hsl(var(--sidebar-bg))",
        boxShadow: "var(--sidebar-edge-shadow)",
      }}
    >
      {/* Logo + collapse toggle */}
      <div className={cn(
        "group flex shrink-0 items-center border-b border-white/40",
        collapsed ? "justify-center px-1 py-3" : "justify-between px-4 py-4"
      )}>
        {collapsed ? (
          <div
            className="flex h-9 w-9 items-center justify-center rounded-2xl bg-gradient-to-br from-[#298c88] to-[#00706b] shadow-sm cursor-default select-none"
            onDoubleClick={() => navigate("/feedback")}
          >
            <BrainCircuit className="h-5 w-5 text-white" />
          </div>
        ) : (
          <div className="flex min-w-0 items-center gap-3">
            <div
              className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-[#298c88] to-[#00706b] shadow-sm cursor-default select-none"
              onDoubleClick={() => navigate("/feedback")}
            >
              <BrainCircuit className="h-6 w-6 text-white" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="brand-display brand-gradient-text text-xl leading-none truncate">{BRAND_NAME}</p>
              <p className="mt-1 truncate text-[11px] text-[hsl(var(--sidebar-muted))]">智能服务台</p>
            </div>
          </div>
        )}
        <button
          onClick={onToggle}
          title={collapsed ? t("nav.expand") : t("nav.collapse")}
          className={cn(
            "flex h-7 w-7 items-center justify-center rounded-md transition-all duration-200",
            "text-[hsl(var(--sidebar-muted))] hover:bg-[hsl(var(--sidebar-hover-bg))] hover:text-[hsl(var(--sidebar-fg))]"
          )}
        >
          {collapsed
            ? <PanelLeftOpen className="h-4 w-4" />
            : <PanelLeftClose className="h-4 w-4" />}
        </button>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto px-2 py-3">
        {/* General section */}
        <div className="mb-2">
          {!collapsed && (
            <p
              className="mb-1 px-3 text-xs font-semibold uppercase tracking-wider"
              style={{ color: "hsl(var(--sidebar-section-label))" }}
            >
              {t("nav.section.general")}
            </p>
          )}
          <div className="space-y-0.5">
            {navItems.map((item) => (
              <NavLink key={item.path} item={item} active={isActive(item)} collapsed={collapsed} isActive={isActive} location={location} onToggle={onToggle} />
            ))}
          </div>
        </div>

        {/* Admin section */}
        {isAdmin && (
          <div className={cn("mt-4", collapsed && "border-t border-[hsl(var(--sidebar-border))] pt-2")}>
            {!collapsed && (
              <p
                className="mb-1 px-3 text-xs font-semibold uppercase tracking-wider"
                style={{ color: "hsl(var(--sidebar-section-label))" }}
              >
                {t("nav.section.admin")}
              </p>
            )}
            <div className="space-y-0.5">
              {ADMIN_ITEMS.map((item) => (
                <NavLink key={item.path} item={item} active={isActive(item)} collapsed={collapsed} isActive={isActive} location={location} onToggle={onToggle} />
              ))}
            </div>
          </div>
        )}
      </nav>

      {/* Bottom: user + theme toggle */}
      {!authlessEnabled && (
      <div
        className="shrink-0 pb-3"
        style={{ borderTop: "1px solid hsl(var(--sidebar-border))" }}
      >
        {collapsed ? (
          <div className="mt-2 flex flex-col items-center gap-1">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  title={user?.username}
                  className="flex h-8 w-8 items-center justify-center overflow-hidden rounded-full bg-white shadow-sm transition-transform hover:scale-105"
                >
                  <img src={BRAND_ASSETS.robot} alt={user?.username ?? BRAND_NAME} className="h-7 w-7 object-cover" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent side="right" align="end" className="w-48">
                <DropdownMenuSub>
                  <DropdownMenuSubTrigger>
                    <Languages className="mr-2 h-4 w-4" />{currentLangLabel}
                  </DropdownMenuSubTrigger>
                  <DropdownMenuSubContent>
                    {LANGUAGE_OPTIONS.map(({ code, label }) => (
                      <DropdownMenuItem
                        key={code}
                        onClick={() => i18n.changeLanguage(code)}
                        className={i18n.language === code ? "font-semibold text-primary" : ""}
                      >
                        {label}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuSubContent>
                </DropdownMenuSub>
                {!authlessEnabled && (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem onClick={() => setShowChangePwd(true)}>
                      <KeyRound className="mr-2 h-4 w-4" />{t("auth.changePassword")}
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem onClick={clearAuth} className="text-destructive focus:text-destructive">
                      <LogOut className="mr-2 h-4 w-4" />{t("auth.logout")}
                    </DropdownMenuItem>
                  </>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
            <button
              onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
              title={resolvedTheme === "dark" ? t("common.lightMode") : t("common.darkMode")}
              className={cn(
                "flex h-8 w-8 items-center justify-center rounded-md transition-colors",
                "text-[hsl(var(--sidebar-muted))] hover:bg-[hsl(var(--sidebar-hover-bg))] hover:text-[hsl(var(--sidebar-fg))]"
              )}
            >
              {resolvedTheme === "dark" ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
            </button>
          </div>
        ) : (
          <div className="mt-1 px-2 flex items-center gap-1">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button className={cn(
                  "flex min-w-0 flex-1 items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-all duration-200",
                  "text-[hsl(var(--sidebar-fg))] hover:bg-[hsl(var(--sidebar-hover-bg))]"
                )}>
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center overflow-hidden rounded-full bg-white shadow-sm">
                    <img src={BRAND_ASSETS.robot} alt={user?.username ?? BRAND_NAME} className="h-6 w-6 object-cover" />
                  </div>
                  <span className="flex-1 truncate text-left">{user?.username}</span>
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent side="right" align="end" className="w-48">
                <DropdownMenuSub>
                  <DropdownMenuSubTrigger>
                    <Languages className="mr-2 h-4 w-4" />{currentLangLabel}
                  </DropdownMenuSubTrigger>
                  <DropdownMenuSubContent>
                    {LANGUAGE_OPTIONS.map(({ code, label }) => (
                      <DropdownMenuItem
                        key={code}
                        onClick={() => i18n.changeLanguage(code)}
                        className={i18n.language === code ? "font-semibold text-primary" : ""}
                      >
                        {label}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuSubContent>
                </DropdownMenuSub>
                {!authlessEnabled && (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem onClick={() => setShowChangePwd(true)}>
                      <KeyRound className="mr-2 h-4 w-4" />{t("auth.changePassword")}
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem onClick={clearAuth} className="text-destructive focus:text-destructive">
                      <LogOut className="mr-2 h-4 w-4" />{t("auth.logout")}
                    </DropdownMenuItem>
                  </>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
            <button
              onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
              title={resolvedTheme === "dark" ? t("common.lightMode") : t("common.darkMode")}
              className={cn(
                "flex h-8 w-8 shrink-0 items-center justify-center rounded-md transition-colors",
                "text-[hsl(var(--sidebar-muted))] hover:bg-[hsl(var(--sidebar-hover-bg))] hover:text-[hsl(var(--sidebar-fg))]"
              )}
            >
              {resolvedTheme === "dark" ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
            </button>
          </div>
        )}
      </div>
      )}

      <ChangePasswordDialog open={showChangePwd} onClose={() => setShowChangePwd(false)} />
    </aside>
  );
}
