"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { X, ChevronLeft, ChevronRight, LogOut } from "lucide-react";
import { useState, useEffect } from "react";
import { cn } from "@/lib/utils";
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
import { NavLink } from "./SidebarNavLink";
import {
  SIDEBAR_VERTICAL_LAYOUT,
  SidebarMoreFlyout,
  SidebarMoreInline,
  SidebarNavGroup,
  type BadgeCounts,
} from "./SidebarMore";
import { DynamindsMark } from "@/components/brand/DynamindsMark";
import { useCandidateContactFeature } from "@/hooks/useCandidateContactFeature";
import { dashboardHref } from "@/lib/dashboard-presets";
import { useSidebarPinned } from "./useSidebarPinned";
import { PaletteSwitcher } from "./PaletteSwitcher";
import { KidsModeToggleButton, ThemeToggleButton } from "./ThemeControls";
import { hasSectionAccess } from "@/lib/section-access";
import { hasCapability } from "@/lib/capabilities";
import { useOrderMailPendingCount } from "@/components/order-mail/useOrderMailPendingCount";
import {
  resolveNavHref,
  visibleMoreGroups,
  visibleNavSections,
  visiblePrimaryGroups,
  type NavEntry,
} from "@/lib/nav-registry";

/**
 * Czy pozycja menu świeci się dla bieżącej ścieżki. Podstrony modułu
 * kandydatów z własną pozycją w menu („Do przedzwonienia”) nie zapalają
 * jednocześnie „Kandydaci”. Wyszukiwarka od 21.09.2026 jest trybem ekranu
 * „Kandydaci” i nie ma własnej pozycji — na niej świeci się „Kandydaci”.
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

const CANDIDATES_SUBPAGES_WITH_OWN_ITEM = ["/candidates/contact-queue"];

// Pozycje menu żyją w `lib/nav-registry.ts` — wspólnym źródle dla sidebara
// i palety ⌘K. Re-eksport zostaje, bo testy i inne moduły importują
// `visibleNavSections` z tej ścieżki.
export { visibleNavSections };

// Kontrakt pionowego układu szyny (UAT B57) żyje obok nagłówka grupy
// w `SidebarMore.tsx`; re-eksport zostaje, bo testy czytają go stąd.
export { SIDEBAR_VERTICAL_LAYOUT };

export function SidebarV2({
  mobileOpen,
  onClose,
}: {
  mobileOpen?: boolean;
  onClose?: () => void;
}) {
  const pathname = usePathname();
  const { user, logout, hydrated } = useAuthStore();
  const defaultDashboardHref = dashboardHref(user);
  const setSidebarCollapsed = useUiStore((s) => s.setSidebarCollapsed);
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
  // Szyna = rdzeń pracy w grupach z nagłówkami, reszta pod „Więcej". Bramka
  // widoczności jest w rejestrze jedna — obie listy to ten sam zbiór, podzielony.
  const navOptions = { contactQueueEnabled: contactFeature.enabled };
  const primaryGroups = visiblePrimaryGroups(user, navOptions);
  const moreGroups = visibleMoreGroups(user, navOptions);

  const [hovered, setHovered] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [pinned, setPinned] = useSidebarPinned();

  useEffect(() => {
    setSidebarCollapsed(!pinned);
  }, [pinned, setSidebarCollapsed]);

  // Nawigacja zamyka rozwinięcie pod kursorem — inaczej nakładka 240 px
  // zostawała nad nową stroną, dopóki kursor (albo palec) jej nie opuścił.
  useEffect(() => {
    setHovered(false);
  }, [pathname]);

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

  // Rekrutacje i Kandydaci NIE mają licznika (22.09.2026): liczyły wszystkie
  // opublikowane rekrutacje i kandydatów dodanych dziś (głównie nocny import
  // Traffita), więc stale świeciły „99+" jak nieprzeczytane sprawy, choć nie
  // wymagały żadnej akcji. Licznik w menu ma znaczyć „masz coś do zrobienia".
  // Skrzynka zamówień jest trybem Kontraktów — jej licznik stoi przy nich.
  const orderMailPending = useOrderMailPendingCount(
    hasCapability(user, "nav.order_mail"),
  );
  const badgeCounts: BadgeCounts = {
    ...(orderMailPending ? { orderMail: orderMailPending } : {}),
  };
  const isActive = (href: string) => isNavItemActive(pathname, href);
  const isEntryActive = (entry: NavEntry) =>
    isActive(resolveNavHref(entry, user));
  const handleMoreOpenChange = (next: boolean) => {
    setMoreOpen(next);
    // Panel „Więcej" leży POZA szyną: `mouseleave` jest przy otwartym panelu
    // ignorowany (szyna nie może zwinąć się spod panelu), więc po zamknięciu
    // zdejmujemy hover ręcznie — inaczej szyna zostałaby rozwinięta na stałe.
    if (!next) setHovered(false);
  };
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
      // Rozwinięcie pod kursorem tylko dla MYSZY: stuknięcie na tablecie
      // emituje `mouseenter`, więc nakładka 240 px otwierała się na każde
      // dotknięcie ikony i zasłaniała treść.
      onPointerEnter={(e) => {
        if (e.pointerType === "mouse" && !mobileOpen) setHovered(true);
      }}
      onPointerLeave={(e) => {
        if (e.pointerType === "mouse" && !mobileOpen && !moreOpen) setHovered(false);
      }}
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
            className="flex h-10 w-10 items-center justify-center rounded-md text-sidebar-muted hover:text-sidebar-foreground hover:bg-sidebar-accent"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      <nav
        aria-label="Nawigacja główna"
        className={cn("flex-1 overflow-y-auto py-3 px-2", SIDEBAR_VERTICAL_LAYOUT.navSpacing)}
      >
        {/* Nagłówek każdej grupy ma stały slot w OBU stanach (tekst / kreska),
            więc rozwinięcie pod kursorem nie przesuwa ikon w pionie. */}
        {primaryGroups.map((group) => (
          <SidebarNavGroup
            key={group.key}
            id={group.key}
            title={group.title}
            collapsed={collapsed && !mobileOpen}
          >
            {group.items.map((item) => {
              const resolvedHref = resolveNavHref(item, user);
              return (
                <NavLink
                  key={item.id}
                  href={resolvedHref}
                  label={item.label}
                  icon={item.icon}
                  active={isActive(resolvedHref)}
                  collapsed={collapsed && !mobileOpen}
                  badgeCount={item.badgeKey ? badgeCounts[item.badgeKey] : undefined}
                  onClick={onClose}
                  external={item.external}
                />
              );
            })}
          </SidebarNavGroup>
        ))}
        {mobileOpen ? (
          <SidebarMoreInline
            groups={moreGroups}
            user={user}
            badgeCounts={badgeCounts}
            isActive={isEntryActive}
            onNavigate={onClose}
          />
        ) : moreGroups.length > 0 ? (
          <div className={SIDEBAR_VERTICAL_LAYOUT.groupSpacing}>
            {/* Stały slot z kreską w OBU stanach — zero przesunięć w pionie. */}
            <div className={SIDEBAR_VERTICAL_LAYOUT.sectionSlot}>
              <div className="mx-2 mb-3 w-full border-t border-sidebar-border" />
            </div>
            <div className={SIDEBAR_VERTICAL_LAYOUT.itemSpacing}>
              <SidebarMoreFlyout
                groups={moreGroups}
                user={user}
                collapsed={collapsed}
                open={moreOpen}
                onOpenChange={handleMoreOpenChange}
                badgeCounts={badgeCounts}
                isActive={isEntryActive}
              />
            </div>
          </div>
        ) : null}
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
        {/* Na telefonie pasek górny nie mieści przełączników wyglądu —
            w szufladzie są zawsze pod ręką. */}
        {mobileOpen && (
          <div className="mb-2 flex items-center gap-1 px-2">
            <span className="flex-1 text-xs text-sidebar-muted">Wygląd</span>
            <PaletteSwitcher />
            <KidsModeToggleButton />
            <ThemeToggleButton />
          </div>
        )}
        {!hydrated ? (
          // Przed wczytaniem sesji z pamięci przeglądarki NIE wiemy, czy ktoś
          // jest zalogowany — „Sesja wygasła" migało przy każdym przeładowaniu.
          <div
            aria-hidden="true"
            data-testid="sidebar-user-pending"
            className={cn(
              "flex items-center gap-2.5 rounded-md py-1.5",
              collapsed && !mobileOpen ? "justify-center" : "px-2",
            )}
          >
            <div className="h-8 w-8 shrink-0 animate-pulse rounded-full bg-foreground/6" />
            {!(collapsed && !mobileOpen) && (
              <div className="h-3 flex-1 animate-pulse rounded bg-foreground/6" />
            )}
          </div>
        ) : collapsed && !mobileOpen ? (
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
              className="text-sidebar-muted hover:text-sidebar-foreground p-1 rounded-md hover:bg-sidebar-accent pointer-coarse:p-3"
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
              className="text-sidebar-muted hover:text-sidebar-foreground p-1 rounded-md hover:bg-sidebar-accent pointer-coarse:p-3"
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
