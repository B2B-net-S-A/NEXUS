"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Users,
  Briefcase,
  Building2,
  FileText,
  Star,
  Calendar,
  UserSquare2,
  UserCog,
  BarChart3,
  FileBarChart,
  GitBranch,
  Handshake,
  HelpCircle,
  Lightbulb,
  Search,
  Settings,
  Shield,
  Sparkles,
  Store,
  X,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import { hasRole, ROLE_LABELS, UserRole, useAuthStore } from "@/store/auth";
import { useUiStore } from "@/store/ui";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

/**
 * SidebarV2 — Dynaminds verb-grouped IA.
 * Groups: Sourcing · Pipeline · Delivery · Insights · System.
 * Chrome: plum-700 bg, cream-200 text, burgundy accent for active.
 */

type BadgeCounts = { candidates?: number; jobs?: number; contacts?: number };

type NavItem = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  badgeKey?: keyof BadgeCounts;
  roles?: UserRole[];
};

type NavSection = {
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  items: NavItem[];
};

const NAV_SECTIONS: NavSection[] = [
  {
    title: "Sourcing",
    icon: Users,
    items: [
      { href: "/", label: "Dashboard", icon: LayoutDashboard },
      { href: "/candidates", label: "Kandydaci", icon: Users, badgeKey: "candidates" },
      { href: "/talents", label: "Talenty", icon: Star },
      {
        href: "/sourcing/seeking-contractors",
        label: "Szukają projektu",
        icon: Search,
      },
      { href: "/marketplace", label: "Targ", icon: Store },
      { href: "/contacts", label: "Kontakty", icon: UserSquare2, badgeKey: "contacts" },
    ],
  },
  {
    title: "Pipeline",
    icon: GitBranch,
    items: [
      { href: "/jobs", label: "Oferty", icon: Briefcase, badgeKey: "jobs" },
      { href: "/calendar", label: "Kalendarz", icon: Calendar },
    ],
  },
  {
    title: "Delivery",
    icon: Handshake,
    items: [
      { href: "/clients", label: "Klienci", icon: Building2 },
      { href: "/contracts", label: "Kontrakty", icon: FileText },
      {
        href: "/contractors",
        label: "Kontraktorzy",
        icon: UserCog,
        roles: ["admin", "delivery_lead", "tac", "head_of_recruitment"],
      },
      {
        href: "/manager",
        label: "Panel Managera",
        icon: BarChart3,
        roles: ["admin", "delivery_lead"],
      },
    ],
  },
  {
    title: "Insights",
    icon: Lightbulb,
    items: [
      { href: "/analytics", label: "Analityka", icon: BarChart3 },
      {
        href: "/analytics/pipeline",
        label: "Pipeline (AI)",
        icon: Sparkles,
        roles: ["admin", "delivery_lead", "tac"],
      },
      {
        href: "/reports",
        label: "Raporty",
        icon: FileBarChart,
        roles: ["admin", "delivery_lead", "tac"],
      },
    ],
  },
  {
    title: "System",
    icon: Settings,
    items: [
      { href: "/help", label: "Pomoc", icon: HelpCircle },
      { href: "/settings", label: "Ustawienia", icon: Settings },
      {
        href: "/settings/pipeline-templates",
        label: "Procesy",
        icon: GitBranch,
        roles: ["admin", "delivery_lead"],
      },
      {
        href: "/settings/diagnostics/v2",
        label: "UI Showcase",
        icon: Sparkles,
        roles: ["admin"],
      },
      {
        href: "/admin",
        label: "Admin",
        icon: Shield,
        roles: ["admin"],
      },
    ],
  },
];

function CountBadge({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <span className="ml-auto shrink-0 rounded-full bg-[hsl(var(--accent))] text-white text-[10px] font-bold min-w-[18px] h-[18px] px-1.5 flex items-center justify-center leading-none">
      {count > 99 ? "99+" : count}
    </span>
  );
}

function NavLink({
  href,
  label,
  icon: Icon,
  active,
  collapsed,
  badgeCount,
  onClick,
}: {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  active: boolean;
  collapsed: boolean;
  badgeCount?: number;
  onClick?: () => void;
}) {
  const link = (
    <Link
      href={href}
      onClick={onClick}
      aria-label={label}
      aria-current={active ? "page" : undefined}
      className={cn(
        "relative flex items-center text-sm transition-all duration-150",
        "rounded-v2-s focus:outline-none",
        collapsed ? "justify-center h-10 w-10 mx-auto" : "gap-3 px-3 h-9",
        active
          ? "bg-[hsl(var(--accent))]/15 text-[hsl(var(--text-onchrome))] font-semibold"
          : "text-[hsl(var(--text-onchrome))]/70 hover:bg-white/5 hover:text-[hsl(var(--text-onchrome))]"
      )}
    >
      {active && (
        <span
          className="absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-r-full bg-[hsl(var(--accent))]"
          aria-hidden="true"
        />
      )}
      <Icon className={cn("shrink-0", collapsed ? "h-4 w-4" : "h-4 w-4")} />
      {!collapsed && (
        <>
          <span className="truncate flex-1">{label}</span>
          {badgeCount !== undefined && <CountBadge count={badgeCount} />}
        </>
      )}
      {collapsed && badgeCount !== undefined && badgeCount > 0 && (
        <span
          className="absolute top-1 right-1 w-2 h-2 bg-[hsl(var(--accent))] rounded-full"
          aria-label={`${badgeCount} nowych`}
        />
      )}
    </Link>
  );

  if (!collapsed) return link;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{link}</TooltipTrigger>
      <TooltipContent side="right">
        {label}
        {badgeCount !== undefined && badgeCount > 0 ? ` (${badgeCount})` : ""}
      </TooltipContent>
    </Tooltip>
  );
}

const SIDEBAR_PINNED_KEY = "sidebar_pinned_v2";

export function SidebarV2({
  mobileOpen,
  onClose,
}: {
  mobileOpen?: boolean;
  onClose?: () => void;
}) {
  const pathname = usePathname();
  const { user, logout } = useAuthStore();
  const setSidebarCollapsed = useUiStore((s) => s.setSidebarCollapsed);

  const [hovered, setHovered] = useState(false);
  const [pinned, setPinned] = useState<boolean>(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem(SIDEBAR_PINNED_KEY) !== "false";
    }
    return true;
  });

  useEffect(() => {
    setSidebarCollapsed(!pinned);
  }, [pinned, setSidebarCollapsed]);

  const togglePinned = () => {
    const next = !pinned;
    setPinned(next);
    if (typeof window !== "undefined") {
      localStorage.setItem(SIDEBAR_PINNED_KEY, String(next));
    }
  };

  const expanded = hovered || pinned || mobileOpen;
  const collapsed = !expanded;

  const { data: stats } = useQuery({
    queryKey: ["sidebar-badges-v2"],
    queryFn: async () => {
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      const todayIso = today.toISOString().slice(0, 10);
      const [candidatesRes, jobsRes] = await Promise.allSettled([
        api.get("/api/candidates", { params: { page_size: 1, created_after: todayIso } }),
        api.get("/api/jobs", { params: { page_size: 1, status: "published" } }),
      ]);
      return {
        candidates: candidatesRes.status === "fulfilled" ? (candidatesRes.value.data?.total ?? 0) : 0,
        jobs: jobsRes.status === "fulfilled" ? (jobsRes.value.data?.total ?? 0) : 0,
        contacts: 0,
      } as BadgeCounts;
    },
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
  });

  const badgeCounts = stats ?? {};
  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(href + "/");
  const initials = user?.name
    ? user.name.split(" ").map((w) => w[0]).slice(0, 2).join("").toUpperCase()
    : "?";

  return (
    <aside
      aria-label="Nawigacja boczna"
      onMouseEnter={() => !mobileOpen && setHovered(true)}
      onMouseLeave={() => !mobileOpen && setHovered(false)}
      className={cn(
        "bg-[hsl(var(--bg-chrome))] text-[hsl(var(--text-onchrome))]",
        "flex flex-col h-full shrink-0 overflow-hidden",
        "transition-[width] duration-200 ease-in-out",
        "border-r border-white/5",
        mobileOpen ? "w-64" : collapsed ? "w-[60px]" : "w-60"
      )}
    >
      {/* Logo + collapse toggle */}
      <div
        className={cn(
          "flex items-center border-b border-white/5 shrink-0 h-14",
          collapsed && !mobileOpen ? "justify-center px-0" : "px-4 gap-2"
        )}
      >
        <Link
          href="/"
          aria-label="Nexus — strona główna"
          className={cn(
            "flex items-center gap-2 flex-1 min-w-0 rounded-v2-s",
            "focus:outline-none"
          )}
        >
          <span className="inline-flex items-center justify-center w-8 h-8 rounded-v2-s bg-[hsl(var(--accent))] text-white font-extrabold text-sm shrink-0">
            N
          </span>
          {(!collapsed || mobileOpen) && (
            <div className="min-w-0">
              <div className="font-display font-bold text-sm leading-tight tracking-[-0.01em]">
                Nexus
              </div>
              <div className="text-[10px] opacity-60 leading-none">ATS · B2B.net</div>
            </div>
          )}
        </Link>

        {!mobileOpen && (
          <button
            onClick={togglePinned}
            aria-label={pinned ? "Zwiń sidebar" : "Rozwiń sidebar"}
            className={cn(
              "text-[hsl(var(--text-onchrome))]/60 hover:text-[hsl(var(--text-onchrome))]",
              "p-1 rounded-v2-s hover:bg-white/5 transition-all",
              collapsed ? "opacity-0" : "opacity-100"
            )}
          >
            {pinned ? <ChevronLeft className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          </button>
        )}

        {mobileOpen && onClose && (
          <button
            onClick={onClose}
            aria-label="Zamknij menu"
            className="p-1 rounded-v2-s hover:bg-white/5"
          >
            <X className="h-5 w-5" />
          </button>
        )}
      </div>

      {/* Nav sections */}
      <nav
        aria-label="Nawigacja główna"
        className={cn(
          "flex-1 overflow-y-auto py-3",
          collapsed && !mobileOpen ? "px-2 space-y-1" : "px-2 space-y-0.5"
        )}
      >
        {NAV_SECTIONS.map((section) => {
          const visibleItems = section.items.filter(
            (item) => !item.roles || hasRole(user, ...item.roles)
          );
          if (visibleItems.length === 0) return null;
          return (
            <div key={section.title} className="mb-3">
              {(!collapsed || mobileOpen) && (
                <p className="px-3 pt-2 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-[hsl(var(--text-onchrome))]/40 select-none">
                  {section.title}
                </p>
              )}
              {collapsed && !mobileOpen && <div className="my-2 border-t border-white/5 mx-2" />}
              <div className={cn(collapsed && !mobileOpen ? "space-y-1" : "space-y-0.5")}>
                {visibleItems.map(({ href, label, icon, badgeKey }) => (
                  <NavLink
                    key={href}
                    href={href}
                    label={label}
                    icon={icon}
                    active={isActive(href)}
                    collapsed={collapsed && !mobileOpen}
                    badgeCount={badgeKey ? badgeCounts[badgeKey] : undefined}
                    onClick={onClose}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </nav>

      {/* Bottom: user */}
      {user && (
        <div
          className={cn(
            "border-t border-white/5 shrink-0 py-3",
            collapsed && !mobileOpen ? "px-2" : "px-3"
          )}
        >
          {collapsed && !mobileOpen ? (
            <Link
              href="/profile"
              aria-label={`Profil: ${user.name}`}
              className="mx-auto flex h-9 w-9 items-center justify-center rounded-full bg-[hsl(var(--accent))] text-white text-sm font-semibold hover:bg-[hsl(var(--accent-strong))] transition-colors"
            >
              {initials}
            </Link>
          ) : (
            <div className="flex items-center gap-2.5 rounded-v2-s px-2 py-1.5 hover:bg-white/5">
              <Link
                href="/profile"
                className="h-8 w-8 rounded-full bg-[hsl(var(--accent))] flex items-center justify-center text-sm font-semibold shrink-0 hover:bg-[hsl(var(--accent-strong))] transition-colors"
                aria-label="Profil"
              >
                {initials}
              </Link>
              <div className="flex-1 min-w-0">
                <Link href="/profile" className="text-sm font-medium truncate block hover:text-[hsl(var(--accent))]">
                  {user.name}
                </Link>
                <span className="text-[10px] opacity-60">{ROLE_LABELS[user.role]}</span>
              </div>
              <button
                onClick={logout}
                aria-label="Wyloguj"
                className="text-[hsl(var(--text-onchrome))]/60 hover:text-[hsl(var(--text-onchrome))] p-1 rounded-v2-s hover:bg-white/5"
              >
                <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                  <polyline points="16 17 21 12 16 7" />
                  <line x1="21" y1="12" x2="9" y2="12" />
                </svg>
              </button>
            </div>
          )}
        </div>
      )}
    </aside>
  );
}
