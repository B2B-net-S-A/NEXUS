"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Users,
  Briefcase,
  Building2,
  FileText,
  LogOut,
  Zap,
  BarChart3,
  FileBarChart,
  Shield,
  Settings,
  Star,
  Calendar,
  UserSquare2,
  Sun,
  Moon,
  X,
  ChevronLeft,
  ChevronRight,
  GitBranch,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuthStore, hasRole, ROLE_LABELS, UserRole } from "@/store/auth";
import { useTabsStore } from "@/store/tabs";
import { useThemeStore } from "@/store/theme";
import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";

// Badge count type for sidebar items
type BadgeCounts = {
  candidates?: number;
  jobs?: number;
  contacts?: number;
};

type NavItem = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  badgeKey?: keyof BadgeCounts;
  /** Jeśli obecne — link widoczny tylko dla userów z którąkolwiek z ról. */
  roles?: UserRole[];
};

type NavSection = {
  title: string;
  items: NavItem[];
};

const NAV_SECTIONS: NavSection[] = [
  {
    title: "REKRUTACJA",
    items: [
      { href: "/", label: "Dashboard", icon: LayoutDashboard },
      { href: "/candidates", label: "Kandydaci", icon: Users, badgeKey: "candidates" },
      { href: "/jobs", label: "Oferty pracy", icon: Briefcase, badgeKey: "jobs" },
      { href: "/talents", label: "Talenty", icon: Star },
    ],
  },
  {
    title: "KLIENCI",
    items: [
      { href: "/clients", label: "Klienci", icon: Building2 },
      { href: "/contacts", label: "Kontakty", icon: UserSquare2, badgeKey: "contacts" },
      { href: "/contracts", label: "Kontrakty", icon: FileText },
    ],
  },
  {
    title: "ZARZĄDZANIE",
    items: [
      {
        href: "/manager",
        label: "Panel Managera",
        icon: BarChart3,
        roles: ["admin", "delivery_lead"],
      },
    ],
  },
  {
    title: "NARZĘDZIA",
    items: [
      { href: "/calendar", label: "Kalendarz", icon: Calendar },
      {
        href: "/reports",
        label: "Raporty",
        icon: FileBarChart,
        roles: ["admin", "delivery_lead", "tac"],
      },
      { href: "/analytics", label: "Analityka", icon: BarChart3 },
    ],
  },
  {
    title: "SYSTEM",
    items: [
      { href: "/settings", label: "Ustawienia", icon: Settings },
      {
        href: "/settings/pipeline-templates",
        label: "Procesy rekrutacyjne",
        icon: GitBranch,
        roles: ["admin", "delivery_lead"],
      },
      {
        href: "/analytics/pipeline",
        label: "Analityka pipeline",
        icon: BarChart3,
        roles: ["admin", "delivery_lead", "tac"],
      },
      {
        href: "/settings/diagnostics",
        label: "Diagnostyka AI",
        icon: Shield,
        roles: ["admin"],
      },
    ],
  },
];

function Badge({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <span className="ml-auto flex-shrink-0 bg-blue-500 text-white text-[10px] font-bold rounded-full min-w-[18px] h-[18px] flex items-center justify-center px-1 leading-none">
      {count > 99 ? "99+" : count}
    </span>
  );
}

function NavItemComponent({
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
  return (
    <Link
      href={href}
      title={label}
      onClick={onClick}
      tabIndex={0}
      aria-label={label}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex items-center rounded-lg text-sm transition-all duration-150 group relative focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-1 focus-visible:ring-offset-gray-900",
        collapsed ? "justify-center px-0 py-2.5 mx-1" : "gap-3 px-3 py-2.5",
        active
          ? "bg-blue-600/15 text-white font-bold border-l-4 border-blue-500 pl-[8px]"
          : "text-gray-300 hover:bg-gray-700/60 hover:text-white font-medium border-l-4 border-transparent"
      )}
    >
      <Icon className={cn("flex-shrink-0", collapsed ? "w-5 h-5" : "w-4 h-4")} />
      {!collapsed && (
        <>
          <span className="truncate flex-1">{label}</span>
          {badgeCount !== undefined && <Badge count={badgeCount} />}
        </>
      )}
      {collapsed && badgeCount !== undefined && badgeCount > 0 && (
        <span className="absolute top-0.5 right-0.5 w-2 h-2 bg-blue-500 rounded-full" aria-label={`${badgeCount} nowych`} />
      )}
      {collapsed && (
        <div className="absolute left-full ml-2 px-2 py-1 bg-gray-800 text-white text-xs rounded-md
                        opacity-0 group-hover:opacity-100 pointer-events-none whitespace-nowrap z-50
                        transition-opacity duration-150 shadow-lg border border-gray-700">
          {label}{badgeCount !== undefined && badgeCount > 0 ? ` (${badgeCount})` : ""}
        </div>
      )}
    </Link>
  );
}

const SIDEBAR_PINNED_KEY = "sidebar_pinned";

// ── Desktop sidebar (collapsible, pinnable) ──────────────────────────────────
export function Sidebar({ onClose, mobileOpen }: { onClose?: () => void; mobileOpen?: boolean }) {
  const pathname = usePathname();
  const { user, logout } = useAuthStore();
  const { theme, toggleTheme } = useThemeStore();
  const tabsStore = useTabsStore();

  const handleLogout = () => {
    tabsStore.tabs.forEach(tab => tabsStore.closeTab(tab.id));
    logout();
  };

  const [hovered, setHovered] = useState(false);
  const [pinned, setPinned] = useState<boolean>(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem(SIDEBAR_PINNED_KEY) !== "false";
    }
    return true;
  });

  const togglePinned = () => {
    const next = !pinned;
    setPinned(next);
    if (typeof window !== "undefined") {
      localStorage.setItem(SIDEBAR_PINNED_KEY, String(next));
    }
  };

  const expanded = hovered || pinned || mobileOpen;
  const collapsed = !expanded;

  // Badge counts from API
  const { data: stats } = useQuery({
    queryKey: ["sidebar-badges"],
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

  const badgeCounts: BadgeCounts = stats ?? {};

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(href + "/");

  const initials = user?.name
    ? user.name.split(" ").map((w: string) => w[0]).slice(0, 2).join("").toUpperCase()
    : "?";

  return (
    <aside
      className={cn(
        "bg-gray-900 dark:bg-gray-900 text-white flex flex-col h-full flex-shrink-0 overflow-hidden",
        "transition-[width] duration-200 ease-in-out",
        mobileOpen ? "w-64" : collapsed ? "w-[60px]" : "w-60"
      )}
      onMouseEnter={() => !mobileOpen && setHovered(true)}
      onMouseLeave={() => !mobileOpen && setHovered(false)}
      aria-label="Nawigacja boczna"
    >
      {/* Logo + collapse toggle */}
      <div
        className={cn(
          "flex items-center border-b border-gray-700/60 flex-shrink-0",
          collapsed && !mobileOpen ? "justify-center py-4 px-0" : "px-4 py-4 gap-2"
        )}
      >
        <Link
          href="/"
          className="flex items-center gap-1.5 flex-1 min-w-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 rounded"
          aria-label="Nexus — strona główna"
        >
          <Zap className="w-5 h-5 text-blue-400 flex-shrink-0" aria-hidden="true" />
          {(!collapsed || mobileOpen) && (
            <div className="min-w-0">
              <div className="font-bold text-base leading-tight tracking-tight">Nexus</div>
              <div className="text-[10px] text-gray-400 leading-none">ATS · B2B.net</div>
            </div>
          )}
        </Link>

        {/* Desktop collapse toggle */}
        {!mobileOpen && (
          <button
            onClick={togglePinned}
            title={pinned ? "Zwiń sidebar" : "Rozwiń sidebar"}
            aria-label={pinned ? "Zwiń sidebar" : "Rozwiń sidebar"}
            className={cn(
              "text-gray-400 hover:text-white transition-all duration-150 p-1 rounded hover:bg-gray-700",
              collapsed ? "opacity-0 group-hover:opacity-100" : "opacity-100",
              "ml-auto flex-shrink-0"
            )}
          >
            {pinned ? <ChevronLeft className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          </button>
        )}

        {/* Mobile close button */}
        {mobileOpen && onClose && (
          <button
            onClick={onClose}
            title="Zamknij menu"
            aria-label="Zamknij menu"
            className="text-gray-400 hover:text-white transition-colors p-1 rounded ml-auto"
          >
            <X className="w-5 h-5" />
          </button>
        )}
      </div>

      {/* Navigation */}
      <nav
        className={cn("flex-1 overflow-y-auto py-3", (collapsed && !mobileOpen) ? "px-0" : "px-2")}
        aria-label="Nawigacja główna"
      >
        {NAV_SECTIONS.map((section) => {
          // Przefiltruj elementy sekcji przez role usera (jeśli item ma `roles`).
          const visibleItems = section.items.filter(
            (item) => !item.roles || hasRole(user, ...item.roles)
          );
          // Jeśli po filtrze sekcja jest pusta — nie renderuj nagłówka.
          if (visibleItems.length === 0) return null;
          return (
            <div key={section.title} className="mb-1">
              {(!collapsed || mobileOpen) && (
                <p className="px-3 pt-3 pb-1 text-[10px] font-semibold text-gray-500 uppercase tracking-wider select-none">
                  {section.title}
                </p>
              )}
              {(collapsed && !mobileOpen) && <div className="my-2 border-t border-gray-800 mx-2" />}
              {visibleItems.map(({ href, label, icon, badgeKey }) => (
                <NavItemComponent
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
          );
        })}

        {/* Admin — admins only */}
        {user?.role === "admin" && (
          <NavItemComponent
            href="/admin"
            label="Admin"
            icon={Shield}
            active={isActive("/admin")}
            collapsed={collapsed && !mobileOpen}
            onClick={onClose}
          />
        )}
      </nav>

      {/* Bottom: theme toggle + user + logout */}
      <div className={cn("border-t border-gray-700/60 flex-shrink-0 py-2", (collapsed && !mobileOpen) ? "px-1" : "px-3")}>
        {/* Theme toggle */}
        {(collapsed && !mobileOpen) ? (
          <div className="flex justify-center mb-2">
            <button
              onClick={toggleTheme}
              title={theme === "dark" ? "Tryb jasny" : "Tryb ciemny"}
              aria-label={theme === "dark" ? "Przełącz na tryb jasny" : "Przełącz na tryb ciemny"}
              className="p-2 rounded-lg text-gray-400 hover:text-white hover:bg-gray-700 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
            >
              {theme === "dark" ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            </button>
          </div>
        ) : (
          <button
            onClick={toggleTheme}
            title={theme === "dark" ? "Tryb jasny" : "Tryb ciemny"}
            aria-label={theme === "dark" ? "Przełącz na tryb jasny" : "Przełącz na tryb ciemny"}
            className="flex items-center gap-3 w-full px-2 py-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-gray-700 transition-colors text-sm mb-1 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
          >
            {theme === "dark" ? <Sun className="w-4 h-4" aria-hidden="true" /> : <Moon className="w-4 h-4" aria-hidden="true" />}
            <span>{theme === "dark" ? "Tryb jasny" : "Tryb ciemny"}</span>
          </button>
        )}

        {user && (
          <>
            {(collapsed && !mobileOpen) ? (
              <div className="flex justify-center">
                <Link
                  href="/profile"
                  title={`${user.name} — profil`}
                  aria-label={`Otwórz profil: ${user.name}`}
                  className="w-9 h-9 rounded-full bg-blue-600 flex items-center justify-center text-sm font-semibold cursor-pointer hover:bg-blue-500 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
                >
                  {initials}
                </Link>
              </div>
            ) : (
              <div className="flex items-center gap-3 px-2 py-1.5 rounded-lg">
                <Link
                  href="/profile"
                  className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center text-sm font-semibold flex-shrink-0 hover:bg-blue-500 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
                  title="Twój profil"
                  aria-label="Otwórz profil użytkownika"
                >
                  {initials}
                </Link>
                <div className="flex-1 min-w-0">
                  <Link
                    href="/profile"
                    className="text-sm font-medium truncate block hover:text-blue-300 transition-colors focus:outline-none focus-visible:ring-1 focus-visible:ring-blue-400 rounded"
                  >
                    {user.name}
                  </Link>
                  <span className={cn(
                    "text-[10px] px-1.5 py-0.5 rounded font-medium",
                    user.role === "admin"
                      ? "bg-blue-900 text-blue-300"
                      : user.role === "delivery_lead"
                        ? "bg-purple-900 text-purple-300"
                        : "bg-gray-700 text-gray-400"
                  )}>
                    {ROLE_LABELS[user.role]}
                  </span>
                </div>
                <button
                  onClick={handleLogout}
                  title="Wyloguj"
                  aria-label="Wyloguj się"
                  className="text-gray-400 hover:text-white transition-colors p-1 rounded hover:bg-gray-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
                >
                  <LogOut className="w-4 h-4" aria-hidden="true" />
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </aside>
  );
}
