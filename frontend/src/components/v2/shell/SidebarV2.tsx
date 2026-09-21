"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { X, ChevronLeft, ChevronRight, LogOut } from "lucide-react";
import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import {
  hasRole,
  ROLE_LABELS,
  useAuthStore,
} from "@/store/auth";
import { useUiStore } from "@/store/ui";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { DynamindsMark } from "@/components/brand/DynamindsMark";
import { useCandidateContactFeature } from "@/hooks/useCandidateContactFeature";
import { dashboardHref } from "@/lib/dashboard-presets";
import { useSidebarPinned } from "./useSidebarPinned";
import { hasSectionAccess } from "@/lib/section-access";
import {
  resolveNavHref,
  visibleNavSections,
  type NavBadgeKey,
} from "@/lib/nav-registry";

type BadgeCounts = Partial<Record<NavBadgeKey, number>>;

/**
 * Czy pozycja menu świeci się dla bieżącej ścieżki. Podstrony modułu
 * kandydatów z własną pozycją w menu („Do przedzwonienia”, „Wyszukiwarka”)
 * nie zapalają jednocześnie „Kandydaci”.
 */
export function isNavItemActive(pathname: string, href: string): boolean {
  const hrefPath = href.split("?")[0];
  if (
    hrefPath === "/candidates" &&
    CANDIDATES_SUBPAGES_WITH_OWN_ITEM.some(
      (sub) => pathname === sub || pathname.startsWith(sub + "/"),
    )
  ) {
    return false;
  }
  return pathname === hrefPath || pathname.startsWith(hrefPath + "/");
}

const CANDIDATES_SUBPAGES_WITH_OWN_ITEM = [
  "/candidates/contact-queue",
  "/candidates/search",
];

// Pozycje menu żyją w `lib/nav-registry.ts` — wspólnym źródle dla sidebara
// i palety ⌘K. Re-eksport zostaje, bo testy i inne moduły importują
// `visibleNavSections` z tej ścieżki.
export { visibleNavSections };

function CountBadge({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <span className="ml-auto shrink-0 rounded-md bg-primary text-primary-foreground text-[10px] font-semibold tabular-nums min-w-[18px] h-[18px] px-1.5 flex items-center justify-center leading-none">
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
  external,
}: {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  active: boolean;
  collapsed: boolean;
  badgeCount?: number;
  onClick?: () => void;
  external?: boolean;
}) {
  const sharedClassName = cn(
    "relative flex items-center text-sm transition-colors duration-150",
    "rounded-md focus:outline-hidden focus-visible:ring-2 focus-visible:ring-sidebar-ring focus-visible:ring-offset-1 focus-visible:ring-offset-sidebar",
    collapsed ? "justify-center h-9 w-9 mx-auto" : "gap-3 px-3 h-9",
    active
      ? collapsed
        ? "bg-primary/10 text-primary font-medium"
        : "bg-primary/10 text-primary font-medium before:absolute before:left-0 before:top-1/2 before:-translate-y-1/2 before:h-5 before:w-[3px] before:rounded-r-full before:bg-primary"
      : "text-sidebar-muted hover:bg-sidebar-accent hover:text-sidebar-foreground",
  );
  const inner = (
    <>
      <Icon className="shrink-0 h-4 w-4" />
      {!collapsed && (
        <>
          <span className="truncate flex-1">{label}</span>
          {badgeCount !== undefined && <CountBadge count={badgeCount} />}
        </>
      )}
      {collapsed && badgeCount !== undefined && badgeCount > 0 && (
        <span
          className="absolute top-1 right-1 w-1.5 h-1.5 bg-primary rounded-full"
          aria-label={`${badgeCount} nowych`}
        />
      )}
    </>
  );
  const link = external ? (
    <a
      href={href}
      onClick={onClick}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={`${label} (otwiera się w nowej karcie)`}
      className={sharedClassName}
    >
      {inner}
    </a>
  ) : (
    <Link
      href={href}
      onClick={onClick}
      aria-label={label}
      aria-current={active ? "page" : undefined}
      className={sharedClassName}
    >
      {inner}
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

/**
 * Pionowe wymiary szyny są takie same w stanie zwiniętym i rozwiniętym (UAT B57).
 *
 * Rozwinięcie pod kursorem zamieniało kreskę sekcji (17 px) na nagłówek (29 px)
 * i `space-y-1` na `space-y-0.5`, więc ikony przesuwały się w dół w trakcie
 * kliknięcia i klik trafiał w sąsiedni link. Nagłówek sekcji ma teraz stały
 * slot, a odstępy nie zależą od stanu — zmienia się tylko szerokość.
 */
export const SIDEBAR_VERTICAL_LAYOUT = {
  navSpacing: "space-y-0.5",
  itemSpacing: "space-y-0.5",
  sectionSlot: "h-7 flex items-end",
} as const;

export function SidebarV2({
  mobileOpen,
  onClose,
}: {
  mobileOpen?: boolean;
  onClose?: () => void;
}) {
  const pathname = usePathname();
  const { user, logout } = useAuthStore();
  const defaultDashboardHref = dashboardHref(user);
  const setSidebarCollapsed = useUiStore((s) => s.setSidebarCollapsed);
  const canReadCandidates =
    hasSectionAccess(user, "sourcing") &&
    hasRole(
      user,
      "admin",
      "head_of_recruitment",
      "delivery_lead",
      "talent_community_manager",
      "tac",
      "recruiter",
      "finance",
      "sourcer",
    );
  const canReviewApplications =
    hasSectionAccess(user, "sourcing", "write") &&
    hasRole(
      user,
      "admin",
      "delivery_lead",
      "talent_community_manager",
      "tac",
      "recruiter",
      "finance",
      "sourcer",
    );
  const canReadJobs = hasSectionAccess(user, "pipeline");
  const canUseContactQueue =
    hasSectionAccess(user, "sourcing") &&
    hasRole(
      user,
      "talent_community_manager",
      "tac",
      "recruiter",
      "sourcer",
    );
  const contactFeature = useCandidateContactFeature({
    queryEnabled: canUseContactQueue,
  });
  const navSections = visibleNavSections(user, {
    contactQueueEnabled: contactFeature.enabled,
  });

  const [hovered, setHovered] = useState(false);
  const [pinned, setPinned] = useSidebarPinned();

  useEffect(() => {
    setSidebarCollapsed(!pinned);
  }, [pinned, setSidebarCollapsed]);

  const togglePinned = () => {
    const next = !pinned;
    setPinned(next);
    // Gdy zwijamy (unpin), kursor wciąż jest nad sidebarem → `hovered` byłby
    // true i `expanded = hovered || pinned` trzymałby pasek rozwinięty, więc
    // wizualnie nic by się nie działo ("klikam strzałkę, a się nie chowa").
    // Zerujemy hover, żeby pasek od razu zwęził się do szyny 60px. Sidebar
    // skurczy się spod kursora (chevron jest przy prawej krawędzi szerokiego
    // paska, poza szyną 60px), więc mouseenter nie odpali się natychmiast.
    if (!next) {
      setHovered(false);
    }
  };

  const expanded = hovered || pinned || mobileOpen;
  const collapsed = !expanded;

  const { data: stats } = useQuery({
    queryKey: [
      "sidebar-badges-v2",
      user?.id,
      canReadCandidates,
      canReadJobs,
      canReviewApplications,
    ],
    // Czekamy na rozstrzygnięcie auth, zanim strzelimy — bez tej bramki
    // liczniki (/candidates, /jobs) lecą raz przed hydracją store'u i drugi
    // raz po niej, na każdym wejściu na stronę.
    enabled:
      !!user && (canReadCandidates || canReadJobs || canReviewApplications),
    queryFn: async () => {
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      const todayIso = today.toISOString().slice(0, 10);
      const promises: Promise<unknown>[] = [];
      const slots: string[] = [];
      if (canReadCandidates) {
        promises.push(
          api.get("/api/candidates", {
            params: { page_size: 1, created_after: todayIso },
          }),
        );
        slots.push("candidates");
      }
      if (canReadJobs) {
        promises.push(
          api.get("/api/jobs", {
            params: { page_size: 1, status: "published" },
          }),
        );
        slots.push("jobs");
      }
      // Indeksy nazwane zamiast pozycyjnych: `settled[2]` wymagało ręcznego
      // śledzenia, gdzie w tablicy wylądowało dane zapytanie, więc dołożenie
      // kolejnego licznika cicho przesunęłoby odczyt o jeden.
      // Zgłoszenia z publicznych aplikacji czekające na decyzję. Bez licznika
      // ekran kolejki istnieje, ale nikt na niego nie wchodzi — a zgłoszenie,
      // którego nikt nie widzi, jest tym samym co zgłoszenie utracone.
      if (canReviewApplications) {
        promises.push(
          api.get("/api/application-submissions", {
            params: { status: "pending_review", limit: 200 },
          }),
        );
        slots.push("applicationSubmissions");
      }
      const settled = await Promise.allSettled(promises);
      const bySlot = Object.fromEntries(
        slots.map((name, i) => [name, settled[i]]),
      ) as Record<string, (typeof settled)[number] | undefined>;
      const candidatesRes = bySlot.candidates;
      const jobsRes = bySlot.jobs;
      const submissionsRes = bySlot.applicationSubmissions;

      return {
        candidates:
          candidatesRes?.status === "fulfilled"
            ? ((candidatesRes.value as { data?: { total?: number } }).data
                ?.total ?? 0)
            : 0,
        jobs:
          jobsRes?.status === "fulfilled"
            ? ((jobsRes.value as { data?: { total?: number } }).data?.total ??
              0)
            : 0,
        applicationSubmissions:
          submissionsRes && submissionsRes.status === "fulfilled"
            ? ((submissionsRes.value as { data?: unknown[] }).data ?? []).length
            : 0,
      } as BadgeCounts;
    },
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
  });

  const badgeCounts = stats ?? {};
  const isActive = (href: string) => isNavItemActive(pathname, href);
  const initials = user?.name
    ? user.name
        .split(" ")
        .map((w) => w[0])
        .slice(0, 2)
        .join("")
        .toUpperCase()
    : "?";

  // Rozwinięcie pod kursorem (bez przypięcia) idzie NAD treścią — miejsce
  // w układzie zajmuje tylko szyna 60 px, więc strona nie przeskakuje w bok.
  const overlayExpanded = !mobileOpen && hovered && !pinned;
  const rail = (
    <aside
      aria-label="Nawigacja boczna"
      onMouseEnter={() => !mobileOpen && setHovered(true)}
      onMouseLeave={() => !mobileOpen && setHovered(false)}
      className={cn(
        "bg-sidebar text-sidebar-foreground",
        "flex flex-col h-full shrink-0 overflow-hidden",
        "transition-[width] duration-200 ease-in-out",
        "border-r border-sidebar-border",
        mobileOpen ? "w-64" : collapsed ? "w-[60px]" : "w-60",
        !mobileOpen && "absolute inset-y-0 left-0 z-40",
        overlayExpanded && "shadow-xl",
      )}
    >
      <div
        className={cn(
          "flex items-center border-b border-sidebar-border shrink-0 h-12",
          collapsed && !mobileOpen ? "justify-center px-0" : "px-3 gap-2",
        )}
      >
        <Link
          href={defaultDashboardHref}
          aria-label="Nexus — strona główna"
          className="flex items-center gap-2 flex-1 min-w-0 rounded-md focus:outline-hidden"
        >
          <span className="inline-flex items-center justify-center h-7 shrink-0 text-sidebar-foreground">
            <DynamindsMark className="h-[26px] w-auto" />
          </span>
          {(!collapsed || mobileOpen) && (
            <div className="min-w-0">
              <div className="font-semibold text-sm leading-tight tracking-tight">
                Nexus
              </div>
              <div className="text-[10px] text-sidebar-muted leading-none">
                ATS · B2B.net
              </div>
            </div>
          )}
        </Link>

        {!mobileOpen && (
          <button
            onClick={togglePinned}
            aria-label={pinned ? "Zwiń sidebar" : "Rozwiń sidebar"}
            className={cn(
              "text-sidebar-muted hover:text-sidebar-foreground",
              "p-1 rounded-md hover:bg-sidebar-accent transition-colors",
              collapsed ? "opacity-0" : "opacity-100",
            )}
          >
            {pinned ? (
              <ChevronLeft className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
          </button>
        )}

        {mobileOpen && onClose && (
          <button
            onClick={onClose}
            aria-label="Zamknij menu"
            className="p-1 rounded-md text-sidebar-muted hover:text-sidebar-foreground hover:bg-sidebar-accent"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      <nav
        aria-label="Nawigacja główna"
        className={cn("flex-1 overflow-y-auto py-3 px-2", SIDEBAR_VERTICAL_LAYOUT.navSpacing)}
      >
        {navSections.map((section) => {
          // Filtr ról i bramka kolejki telefonów siedzą w `visibleNavSections`
          // (sekcje bez widocznych pozycji tu w ogóle nie docierają).
          const visibleItems = section.items;
          return (
            <div key={section.title} className="mb-3">
              <div className={SIDEBAR_VERTICAL_LAYOUT.sectionSlot}>
                {!collapsed || mobileOpen ? (
                  <p className="w-full truncate px-3 pb-1.5 text-[10px] font-medium uppercase tracking-wider text-sidebar-muted select-none">
                    {section.title}
                  </p>
                ) : (
                  <div className="mx-2 mb-3 w-full border-t border-sidebar-border" />
                )}
              </div>
              <div className={SIDEBAR_VERTICAL_LAYOUT.itemSpacing}>
                {visibleItems.map(
                  (item) => {
                    const { href, label, icon, badgeKey, external } = item;
                    const resolvedHref = resolveNavHref(item, user);
                    return (
                      <NavLink
                        key={href}
                        href={resolvedHref}
                        label={label}
                        icon={icon}
                        active={isActive(resolvedHref)}
                        collapsed={collapsed && !mobileOpen}
                        badgeCount={
                          badgeKey ? badgeCounts[badgeKey] : undefined
                        }
                        onClick={onClose}
                        external={external}
                      />
                    );
                  },
                )}
              </div>
            </div>
          );
        })}
      </nav>

      {/*
        Footer is ALWAYS rendered, even when `user === null` (e.g. /api/auth/me
        just returned 403 because the JWT expired). In that case the
        avatar/profile link is replaced with a "Zaloguj się ponownie" CTA and
        a still-functional logout button, so the user is never locked out of
        the app without a clear recovery path. The api.ts interceptor will
        auto-redirect them within a few seconds anyway, but the visible button
        gives them an immediate manual escape hatch.
      */}
      <div
        className={cn(
          "border-t border-sidebar-border shrink-0 py-3",
          collapsed && !mobileOpen ? "px-2" : "px-3",
        )}
      >
        {collapsed && !mobileOpen ? (
          user ? (
            <Link
              href="/profile"
              aria-label={`Profil: ${user.name}`}
              className="mx-auto flex h-9 w-9 items-center justify-center rounded-full bg-primary text-primary-foreground text-sm font-semibold hover:bg-primary/90 transition-colors"
            >
              {initials}
            </Link>
          ) : (
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  onClick={logout}
                  aria-label="Wyloguj — sesja wygasła"
                  className="mx-auto flex h-9 w-9 items-center justify-center rounded-full bg-foreground/6 text-sidebar-foreground hover:bg-foreground/10 hover:text-sidebar-foreground transition-colors"
                >
                  <LogOut className="h-4 w-4" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="right">Wyloguj się</TooltipContent>
            </Tooltip>
          )
        ) : user ? (
          <div className="flex items-center gap-2.5 rounded-md px-2 py-1.5 hover:bg-sidebar-accent">
            <Link
              href="/profile"
              className="h-8 w-8 rounded-full bg-primary flex items-center justify-center text-primary-foreground text-sm font-semibold shrink-0 hover:bg-primary/90 transition-colors"
              aria-label="Profil"
            >
              {initials}
            </Link>
            <div className="flex-1 min-w-0">
              <Link
                href="/profile"
                className="text-sm font-medium truncate block text-sidebar-foreground hover:text-foreground"
              >
                {user.name}
              </Link>
              <span className="text-[10px] text-sidebar-muted">
                {ROLE_LABELS[user.role]}
              </span>
            </div>
            <button
              onClick={logout}
              aria-label="Wyloguj"
              className="text-sidebar-muted hover:text-sidebar-foreground p-1 rounded-md hover:bg-sidebar-accent"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2.5 rounded-md px-2 py-1.5">
            <div className="h-8 w-8 rounded-full bg-foreground/6 flex items-center justify-center text-sidebar-foreground shrink-0">
              <LogOut className="h-4 w-4" />
            </div>
            <div className="flex-1 min-w-0">
              <Link
                href="/login"
                className="text-sm font-medium truncate block text-sidebar-foreground hover:text-foreground"
              >
                Zaloguj się ponownie
              </Link>
              <span className="text-[10px] text-sidebar-muted">
                Sesja wygasła
              </span>
            </div>
            <button
              onClick={logout}
              aria-label="Wyloguj"
              className="text-sidebar-muted hover:text-sidebar-foreground p-1 rounded-md hover:bg-sidebar-accent"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        )}
      </div>
    </aside>
  );
  if (mobileOpen) return rail;
  return (
    <div
      className={cn(
        "relative h-full shrink-0 transition-[width] duration-200 ease-in-out",
        pinned ? "w-60" : "w-[60px]",
      )}
    >
      {rail}
    </div>
  );
}
