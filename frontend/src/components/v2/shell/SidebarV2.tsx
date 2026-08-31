"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Users,
  Briefcase,
  Building2,
  FileText,
  FileSignature,
  Star,
  Calendar,
  Brain,
  GitBranch,
  Handshake,
  Heart,
  HelpCircle,
  Inbox,
  Lightbulb,
  PhoneCall,
  Settings,
  Sparkles,
  Store,
  Radar,
  Wallet,
  X,
  ChevronLeft,
  ChevronRight,
  LogOut,
} from "lucide-react";
import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import { hasRole, ROLE_LABELS, UserRole, useAuthStore } from "@/store/auth";
import { useUiStore } from "@/store/ui";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { DynamindsMark } from "@/components/brand/DynamindsMark";
import { useCandidateContactFeature } from "@/hooks/useCandidateContactFeature";
import { dashboardHref } from "@/lib/dashboard-presets";

type BadgeCounts = {
  candidates?: number;
  jobs?: number;
  applicationSubmissions?: number;
};

type NavItem = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  badgeKey?: keyof BadgeCounts;
  roles?: UserRole[];
  /**
   * Renderuje pozycję jako `<a href target="_blank" rel="noopener noreferrer">`
   * zamiast Next.js `<Link>`. Używane dla zewnętrznych dashboardów
   * (np. DynaReporter standalone — patrz sekcja "Raporty KPI").
   */
  external?: boolean;
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
      { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
      // Moduł kandydatów (audyt M2 PR1): rola `user` (viewer/klient) nie ma
      // dostępu — backend 403 + middleware /403; chowamy linki żeby nie
      // prowadzić w ślepy zaułek.
      {
        href: "/candidates",
        label: "Kandydaci",
        icon: Users,
        badgeKey: "candidates",
        roles: [
          "admin",
          "head_of_recruitment",
          "delivery_lead",
          "tac",
          "recruiter",
          "finance",
          "sourcer",
        ],
      },
      {
        href: "/candidates/contact-queue",
        label: "Do przedzwonienia",
        icon: PhoneCall,
        roles: ["tac", "recruiter", "sourcer"],
      },
      { href: "/cv-generator", label: "Generator CV", icon: Sparkles },
      // Generator Umów B2B — dostępny dla wszystkich ról (sourcing tooling).
      // Wcześniej w sekcji Delivery z gate'em tac+; przeniesiony tu 2026-06-08
      // na prośbę usera. Edycja katalogu 29 ról nadal admin-only (zakładka
      // "Zakresy ról (admin)" w komponencie, gate `isAdmin`).
      {
        href: "/contracts/b2b-generator",
        label: "Generator Umów B2B",
        icon: FileSignature,
      },
      {
        href: "/talents",
        label: "Talenty",
        icon: Star,
        roles: [
          "admin",
          "head_of_recruitment",
          "delivery_lead",
          "tac",
          "recruiter",
          "finance",
          "sourcer",
        ],
      },
      {
        // BEZ `roles`: radar i powiązane funkcje są dostępne dla KAŻDEJ
        // zalogowanej roli (decyzja produktowa Artura 19.08). Lustrzane
        // z backendem (CurrentUser), middleware (brak wpisu = brak
        // zawężenia) i `nav.talent_radar` w lib/capabilities.ts.
        href: "/talent-radar",
        label: "Talent Radar",
        icon: Radar,
      },
      {
        href: "/sourcing/marketplace",
        label: "Targ / Dostępni",
        icon: Store,
        roles: [
          "admin",
          "head_of_recruitment",
          "delivery_lead",
          "tac",
          "recruiter",
          "finance",
          "sourcer",
        ],
      },
      {
        href: "/applications",
        label: "Zgłoszenia",
        icon: Inbox,
        badgeKey: "applicationSubmissions",
        roles: [
          "admin",
          "head_of_recruitment",
          "delivery_lead",
          "tac",
          "recruiter",
          "finance",
          "sourcer",
        ],
      },
    ],
  },
  {
    title: "Pipeline",
    icon: GitBranch,
    items: [
      { href: "/jobs", label: "Rekrutacje", icon: Briefcase, badgeKey: "jobs" },
      { href: "/calendar", label: "Kalendarz", icon: Calendar },
    ],
  },
  {
    title: "Delivery",
    icon: Handshake,
    items: [
      // R0 (plan analytics 2026-07-16): backend odcina rolę `user` od bazy
      // klientów (OperationalUser) — nie pokazujemy linku, do którego 403.
      {
        href: "/clients",
        label: "Klienci",
        icon: Building2,
        roles: [
          "admin",
          "head_of_recruitment",
          "delivery_lead",
          "tac",
          "recruiter",
          "finance",
          "sourcer",
        ],
      },
      {
        href: "/my-clients",
        label: "Moi klienci",
        icon: Briefcase,
        roles: ["delivery_lead", "admin", "head_of_recruitment", "finance"],
      },
      {
        href: "/my-relationships",
        label: "Moje relacje",
        icon: Heart,
        roles: [
          "delivery_lead",
          "admin",
          "head_of_recruitment",
          "tac",
          "finance",
        ],
      },
      // "Kontrakty" is now a single workspace with two modes (Obsługa
      // kontraktorów / Rejestr kontraktów). The former standalone
      // "Kontraktorzy" item was folded in — /contractors redirects to
      // /contracts?view=operations. Operations mode is role-gated inside
      // the page (same roles the old nav item used).
      // R0: odczyty kontraktów (stawki!) = TacPlus na backendzie.
      {
        href: "/contracts",
        label: "Kontrakty",
        icon: FileText,
        roles: ["admin", "delivery_lead", "tac", "finance"],
      },
      // ── HIDDEN 2026-05-28: Panel Managera (DL Hub) schowany z sidebara
      //    na prośbę usera ("wylacz z UI na razie"). Route
      //    `/dashboard/delivery-lead` nadal działa — tylko link w nawigacji
      //    ukryty. Żeby przywrócić, odkomentuj poniższy obiekt.
      //
      //    UWAGA przy przywracaniu: slot `pendingVerifications` w
      //    `BadgeCounts` został usunięty razem z fetchem, bo przez trzy
      //    miesiące liczył licznik, którego nikt nie renderował — a robił to
      //    zapytaniem admin-only (`GET /api/pipeline/pending-verifications`),
      //    więc dla DL i HoR było to gwarantowane 403 co refetch. Przywracając
      //    link, przywróć licznik jako zapytanie ZLICZAJĄCE (`?page_size=1` →
      //    `total`), nie pełną listę, i zawęź bramkę do faktycznego
      //    `AdminUser` z endpointu — inaczej wraca oba defekty naraz.
      /*
      {
        // DL Hub (PR #225/#229) — łączy widget weryfikacji + KPI + 3 taby
        // (klienci/zespół/aktywne joby). Stara osobna zakładka "Weryfikacje"
        // została zwinięta do widgeta na górze panelu — link do pełnej
        // listy (`/pending-verifications`) jest w widgecie.
        href: "/dashboard/delivery-lead",
        label: "Panel Managera",
        icon: BarChart3,
        badgeKey: "pendingVerifications",
        roles: ["admin", "delivery_lead", "head_of_recruitment"],
      },
      */
    ],
  },
  {
    title: "Insights",
    icon: Lightbulb,
    items: [
      { href: "/insights", label: "Insights", icon: Lightbulb },
      {
        href: "/cortex",
        label: "Cortex",
        icon: Brain,
        roles: [
          "admin",
          "head_of_recruitment",
          "delivery_lead",
          "tac",
          "finance",
        ],
      },
    ],
  },
  // ── HIDDEN 2026-05-22: cała sekcja "Raporty KPI" schowana z sidebara
  //    na prośbę usera ("zajmiemy się tym później").
  //
  // ── NIEAKTUALNE 2026-07-20: NIE ODKOMENTOWUJ tego bloku. Strony
  //    /dynareporter/{rekrutacja,delivery-lead-dashboard,board-dashboard,...}
  //    zostały USUNIĘTE — te ścieżki tylko przekierowują (308) do /insights.
  //    Odkomentowanie dałoby pozycje w nawigacji, które odbijają użytkownika
  //    gdzie indziej. Następcą jest moduł Insights; przy przywracaniu grupy
  //    linkuj wprost do /insights?tab=…, a nie do /dynareporter/*.
  //    Nadal istnieją (i nie przekierowują): /dynareporter/admin-dashboard,
  //    /dynareporter/profile, /dynareporter/mindy.
  /*
  {
    title: "Raporty KPI",
    icon: BarChart3,
    items: [
      {
        href: "/dynareporter/rekrutacja",
        label: "Rekrutacja",
        icon: Users,
      },
      {
        href: "/dynareporter/delivery-lead-dashboard",
        label: "Delivery Lead",
        icon: Handshake,
      },
      {
        href: "/dynareporter/board-dashboard",
        label: "Rada Nadzorcza",
        icon: BarChart3,
        roles: ["admin", "delivery_lead", "head_of_recruitment"],
      },
      {
        href: "/dynareporter/admin-dashboard",
        label: "Admin DR",
        icon: Settings,
        roles: ["admin"],
      },
    ],
  },
  */
  // Moduł „Finanse". Jedna pozycja, bo `/finance` to jedna strona z trzema
  // zakładkami (wyniki miesięczne · archiwum · import zużycia MD) — osobny
  // link „Import MD" prowadziłby do tej samej trasy i otwierał ją na innej
  // zakładce niż podpowiada etykieta.
  {
    title: "Finanse",
    icon: Wallet,
    items: [
      {
        href: "/finance",
        label: "Finanse",
        icon: Wallet,
        roles: ["admin", "finance"],
      },
    ],
  },
  {
    title: "System",
    icon: Settings,
    items: [
      { href: "/help", label: "Pomoc", icon: HelpCircle },
      { href: "/settings", label: "Ustawienia", icon: Settings },
    ],
  },
];

/**
 * Pozycje menu widoczne dla danego użytkownika — czysta funkcja, żeby dało się
 * to udowodnić testem bez montowania sidebara (a więc bez mocków `next/
 * navigation`, react-query, `api` i `useUiStore`).
 *
 * Zastępuje drugie, równoległe drzewo `FINANCE_NAV_SECTIONS`: rola `finance`
 * dostawała cztery pozycje (Dashboard · Finanse · Pomoc · Ustawienia), mimo że
 * KAŻDA lista `roles` w `NAV_SECTIONS` już ją wymienia — backend przepuszcza ją
 * wszędzie tam, gdzie recruitera (decyzja 19.08), więc menu było jedyną
 * warstwą, która ją odcinała. Własny moduł „Finanse" zostaje: wpis `/finance`
 * ma `roles: ["admin", "finance"]`.
 */
export function visibleNavSections(
  user: Parameters<typeof hasRole>[0],
  opts: { contactQueueEnabled: boolean },
): NavSection[] {
  return NAV_SECTIONS.map((section) => ({
    ...section,
    items: section.items.filter(
      (item) =>
        (!item.roles || hasRole(user, ...item.roles)) &&
        (item.href !== "/candidates/contact-queue" || opts.contactQueueEnabled),
    ),
  })).filter((section) => section.items.length > 0);
}

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
  const defaultDashboardHref = dashboardHref(user);
  const setSidebarCollapsed = useUiStore((s) => s.setSidebarCollapsed);
  const canUseContactQueue = hasRole(user, "tac", "recruiter", "sourcer");
  const contactFeature = useCandidateContactFeature({
    queryEnabled: canUseContactQueue,
  });
  const navSections = visibleNavSections(user, {
    contactQueueEnabled: contactFeature.enabled,
  });

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
    // Gdy zwijamy (unpin), kursor wciąż jest nad sidebarem → `hovered` byłby
    // true i `expanded = hovered || pinned` trzymałby pasek rozwinięty, więc
    // wizualnie nic by się nie działo ("klikam strzałkę, a się nie chowa").
    // Zerujemy hover, żeby pasek od razu zwęził się do szyny 60px. Sidebar
    // skurczy się spod kursora (chevron jest przy prawej krawędzi szerokiego
    // paska, poza szyną 60px), więc mouseenter nie odpali się natychmiast.
    if (!next) {
      setHovered(false);
    }
    if (typeof window !== "undefined") {
      localStorage.setItem(SIDEBAR_PINNED_KEY, String(next));
    }
  };

  const expanded = hovered || pinned || mobileOpen;
  const collapsed = !expanded;

  const { data: stats } = useQuery({
    queryKey: ["sidebar-badges-v2"],
    // Czekamy na rozstrzygnięcie auth, zanim strzelimy — bez tej bramki
    // liczniki (/candidates, /jobs) lecą raz przed hydracją store'u i drugi
    // raz po niej, na każdym wejściu na stronę.
    enabled: !!user,
    queryFn: async () => {
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      const todayIso = today.toISOString().slice(0, 10);
      const promises: Promise<unknown>[] = [
        api.get("/api/candidates", {
          params: { page_size: 1, created_after: todayIso },
        }),
        api.get("/api/jobs", { params: { page_size: 1, status: "published" } }),
      ];
      // Indeksy nazwane zamiast pozycyjnych: `settled[2]` wymagało ręcznego
      // śledzenia, gdzie w tablicy wylądowało dane zapytanie, więc dołożenie
      // kolejnego licznika cicho przesunęłoby odczyt o jeden.
      const slots: string[] = ["candidates", "jobs"];
      // Zgłoszenia z publicznych aplikacji czekające na decyzję. Bez licznika
      // ekran kolejki istnieje, ale nikt na niego nie wchodzi — a zgłoszenie,
      // którego nikt nie widzi, jest tym samym co zgłoszenie utracone.
      promises.push(
        api.get("/api/application-submissions", {
          params: { status: "pending_review", limit: 200 },
        }),
      );
      slots.push("applicationSubmissions");
      const settled = await Promise.allSettled(promises);
      const bySlot = Object.fromEntries(
        slots.map((name, i) => [name, settled[i]]),
      ) as Record<string, (typeof settled)[number] | undefined>;
      const candidatesRes = bySlot.candidates!;
      const jobsRes = bySlot.jobs!;
      const submissionsRes = bySlot.applicationSubmissions;

      return {
        candidates:
          candidatesRes.status === "fulfilled"
            ? ((candidatesRes.value as { data?: { total?: number } }).data
                ?.total ?? 0)
            : 0,
        jobs:
          jobsRes.status === "fulfilled"
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
  const isActive = (href: string) => {
    const hrefPath = href.split("?")[0];
    if (
      pathname.startsWith("/candidates/contact-queue") &&
      hrefPath === "/candidates"
    ) {
      return false;
    }
    return pathname === hrefPath || pathname.startsWith(hrefPath + "/");
  };
  const initials = user?.name
    ? user.name
        .split(" ")
        .map((w) => w[0])
        .slice(0, 2)
        .join("")
        .toUpperCase()
    : "?";

  return (
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
        className={cn(
          "flex-1 overflow-y-auto py-3",
          collapsed && !mobileOpen ? "px-2 space-y-1" : "px-2 space-y-0.5",
        )}
      >
        {navSections.map((section) => {
          // Filtr ról i bramka kolejki telefonów siedzą w `visibleNavSections`
          // (sekcje bez widocznych pozycji tu w ogóle nie docierają).
          const visibleItems = section.items;
          return (
            <div key={section.title} className="mb-3">
              {(!collapsed || mobileOpen) && (
                <p className="px-3 pt-2 pb-1.5 text-[10px] font-medium uppercase tracking-wider text-sidebar-muted select-none">
                  {section.title}
                </p>
              )}
              {collapsed && !mobileOpen && (
                <div className="my-2 border-t border-sidebar-border mx-2" />
              )}
              <div
                className={cn(
                  collapsed && !mobileOpen ? "space-y-1" : "space-y-0.5",
                )}
              >
                {visibleItems.map(
                  ({ href, label, icon, badgeKey, external }) => {
                    const resolvedHref =
                      href === "/dashboard" ? defaultDashboardHref : href;
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
}
