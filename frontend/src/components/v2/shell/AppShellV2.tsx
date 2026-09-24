"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useSelectedLayoutSegment } from "next/navigation";
import { isCareerHost } from "@/lib/career/host";
import { api } from "@/lib/api";
import { isTraineeOnly, useAuthStore } from "@/store/auth";
import { useCapabilities } from "@/hooks/useCapability";
import { useKeyboardShortcuts, ShortcutsModal } from "@/components/KeyboardShortcuts";
import { useOnboardingGuard } from "@/hooks/useOnboardingGuard";
import { SidebarV2 } from "./SidebarV2";
import { TopbarV2 } from "./TopbarV2";
import { ImpersonationBanner } from "./ImpersonationBanner";
import { CommandPaletteV2 } from "./CommandPaletteV2";
import { JarvisRoot } from "@/components/jarvis/JarvisRoot";
import { KidsBackdrop } from "./KidsBackdrop";
import { MyPeopleRoot } from "@/components/v2/my-people/MyPeopleLauncher";
import { useMyPeoplePanel } from "@/store/my-people";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { TraineeShell } from "@/components/trainee/TraineeShell";
import type { QuickActionModal } from "./QuickActionsV2";

/**
 * AppShellV2 — Dynaminds redesign shell.
 *
 * Composition: SidebarV2 (plum chrome) + TopbarV2 + main content.
 * Bypasses: /login (bare form) and /share/* (public client-facing portal).
 *
 * Key behaviors replicated from v1 AppShell:
 * - Auth store hydration on mount
 * - Mobile sidebar drawer toggle
 * - ⌘K / Ctrl+K opens command palette (not a global search anymore)
 * - n/j keyboard shortcuts for new candidate / new job
 * - ? shows shortcuts help
 * - Onboarding walkthrough for first-time users
 */
export function AppShellV2({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  // `/login`, `/login/forgot-password`, `/login/reset` — wszystkie bare-form
  // strony bez sidebaru. startsWith zamiast === żeby pokryć subpaths.
  const isLoginPage = pathname?.startsWith("/login") ?? false;
  const isSharePage = pathname?.startsWith("/share/") ?? false;
  const isApplyPage = pathname?.startsWith("/apply/") ?? false;
  // `/sign/{token}` — public consultant signing page, no internal app shell.
  const isSignPage = pathname?.startsWith("/sign/") ?? false;
  // `/register`, `/register/verify` — public self-service registration (bare form).
  const isRegisterPage = pathname?.startsWith("/register") ?? false;
  // `/cv/{token}` — public CV preview. `startsWith("/cv/")` (trailing slash) żeby
  // NIE złapać authed `/cv-generator`.
  const isCvPreviewPage = pathname?.startsWith("/cv/") ?? false;
  // `/engagement/{token}` — public magic-link engagement page, no internal shell.
  const isEngagementPage = pathname?.startsWith("/engagement/") ?? false;
  // Strona kariery dla kandydatów (`/kariera/*`, host `kariera.dynaminds.pl`).
  // Na hoście kariery middleware PRZEPISUJE adres (`/r/x` → `/kariera/r/x`),
  // a `usePathname()` zwraca adres WIDOCZNY — samo `startsWith("/kariera")`
  // zamontowałoby tam pełny shell z zapytaniami kończącymi się 401. Segment
  // layoutu pochodzi z dopasowanej trasy (po rewrite), więc działa także w SSR;
  // host okna to zabezpieczenie po stronie przeglądarki.
  const topSegment = useSelectedLayoutSegment();
  const isCareerPage =
    topSegment === "kariera" ||
    (pathname === "/kariera" || (pathname?.startsWith("/kariera/") ?? false)) ||
    (typeof window !== "undefined" && isCareerHost(window.location.hostname));

  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [pendingModal, setPendingModal] = useState<QuickActionModal>(null);
  const [commandOpen, setCommandOpen] = useState(false);

  // Hydrate auth from localStorage post-mount (SSR-safe)
  const hydrateAuth = useAuthStore((s) => s.hydrate);
  const hydrated = useAuthStore((s) => s.hydrated);
  const traineeOnly = useAuthStore((s) => isTraineeOnly(s.user));
  useEffect(() => {
    if (!hydrated) hydrateAuth();
  }, [hydrated, hydrateAuth]);

  // Raz na załadowanie aplikacji dociągamy autorytatywny profil z
  // `/api/auth/me` i nadpisujemy nim zapamiętany `nexus_user`. Bez tego
  // uprawnienie nadane przez admina (rola, sekcje, „może usuwać klientów")
  // nie miało widocznego skutku, dopóki osoba się nie wylogowała.
  //
  // Bramka na tokenie jest load-bearing: shell montuje się także na stronach
  // publicznych (`/share/*`, `/cv/*`, `/sign/*`, `/apply/*`), gdzie authed
  // żądanie skończyłoby się 401 dla anonimowego odwiedzającego. Podgląd jako
  // inny użytkownik pomijamy — tam profil ustawia `impersonate`.
  const syncUser = useAuthStore((s) => s.syncUser);
  const hasOwnSession = useAuthStore((s) => !!s.token && !s.realUser);
  const userSynced = useRef(false);
  useEffect(() => {
    if (!hydrated || !hasOwnSession || userSynced.current) return;
    userSynced.current = true;
    api
      .get("/api/auth/me")
      .then((r) => syncUser(r.data))
      .catch(() => {
        // Best-effort: przy błędzie zostaje zapamiętany profil. Martwą sesję
        // (401) obsługuje interceptor w lib/api.ts.
      });
  }, [hydrated, hasOwnSession, syncUser]);

  // Close mobile sidebar on route change
  useEffect(() => {
    setMobileSidebarOpen(false);
  }, [pathname]);

  // ⌘K global shortcut → open command palette
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setCommandOpen(true);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  const focusSearch = useCallback(() => {
    setCommandOpen(true);
  }, []);

  // Skróty klawiszowe `n` / `j` i akcje w Command Palette to alternatywne
  // wejścia do tych samych operacji co Quick Actions — muszą przechodzić przez
  // TEN SAM rejestr capability (audyt F-19), inaczej omijają bramkę.
  const can = useCapabilities();
  const openNewCandidate = useCallback(() => setPendingModal("candidate"), []);
  const openNewJob = useCallback(() => setPendingModal("job"), []);
  const toggleMyPeople = useMyPeoplePanel((s) => s.toggle);

  const { showHelp, setShowHelp } = useKeyboardShortcuts({
    onNewCandidate: can["candidate.create"] ? openNewCandidate : undefined,
    onNewJob: can["job.create"] ? openNewJob : undefined,
    onToggleMyPeople: can["nav.my_people"] ? toggleMyPeople : undefined,
    onFocusSearch: focusSearch,
  });

  // Blocks DL/recruiter first-login: if profile not completed, redirect
  // to /onboarding before the shell renders. Runs after hydration so we
  // don't bounce on initial SSR paint.
  const { needsOnboarding } = useOnboardingGuard();

  if (isLoginPage) return <>{children}</>;
  if (isSharePage) return <>{children}</>;
  if (isApplyPage) return <>{children}</>;
  if (isSignPage) return <>{children}</>;
  // Public/standalone routes — render children bare so the authed shell
  // (sidebar, presence, notifications) never mounts and fires 401-noisy fetches
  // for unauthenticated visitors.
  if (isRegisterPage) return <>{children}</>;
  if (isCvPreviewPage) return <>{children}</>;
  if (isEngagementPage) return <>{children}</>;
  if (isCareerPage) return <>{children}</>;
  // /preview/* — design-system prototype pages, rendered bare (no shell/auth).
  if (pathname?.startsWith("/preview")) return <>{children}</>;

  // /onboarding has its own dedicated layout (no sidebar); let it render
  // without the AppShell wrapper.
  const isOnboardingPage = pathname === "/onboarding" || pathname?.startsWith("/onboarding/");
  if (isOnboardingPage) return <>{children}</>;

  // User must finish onboarding before seeing app content — render a blank
  // shell while the redirect above takes effect.
  if (needsOnboarding) return null;

  // Praktykant (0372) ma jeden ekran: cienki pasek zamiast sidebara, bez
  // palety ⌘K, dzwonka, „Moich ludzi” i Jarvisa (każde z nich pytałoby API,
  // które praktykantowi odmawia).
  if (traineeOnly) return <TraineeShell>{children}</TraineeShell>;

  // Dokument NIE może się przewijać — przewija się wyłącznie `<main>`.
  // `relative` na roocie i na `<main>` jest nośne: element `absolute` bez
  // pozycjonowanego przodka (`sr-only`, ukryte inputy Radixa) liczy się
  // względem całego dokumentu, więc wychodził spod `overflow` i wydłużał
  // stronę do swojej pozycji w treści — puste tło pod kartą i urwany sidebar
  // (zgłoszenie 09.2026, zakładka Zamówienia). `h-dvh`, nie `h-screen`: na
  // telefonie 100vh jest wyższe niż widoczny obszar.
  return (
    <div className="app-shell-root relative flex h-dvh overflow-hidden bg-background text-foreground">
      {/* Skip link — pierwszy element w kolejności tabulacji; widoczny dopiero
          po sfokusowaniu. Pozwala ominąć sidebar i topbar klawiaturą. */}
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-100 focus:rounded-md focus:bg-primary focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-primary-foreground focus:outline-hidden focus:ring-2 focus:ring-ring focus:ring-offset-2"
      >
        Przejdź do treści
      </a>

      {/* Desktop sidebar */}
      <div className="hidden md:flex h-full">
        <SidebarV2 />
      </div>

      {/* Mobile sidebar drawer — Radix Dialog (Sheet): Esc zamyka, fokus
          zostaje w szufladzie i wraca na hamburger po zamknięciu. */}
      <Sheet open={mobileSidebarOpen} onOpenChange={setMobileSidebarOpen}>
        <SheetContent
          side="left"
          hideClose
          aria-describedby={undefined}
          className="w-64 max-w-none sm:max-w-none border-r-0 bg-sidebar p-0 md:hidden"
        >
          <SheetTitle className="sr-only">Menu nawigacji</SheetTitle>
          <SidebarV2 mobileOpen onClose={() => setMobileSidebarOpen(false)} />
        </SheetContent>
      </Sheet>

      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        <ImpersonationBanner />
        <TopbarV2
          onOpenMobileSidebar={() => setMobileSidebarOpen(true)}
          pendingModal={pendingModal}
          onClearPendingModal={() => setPendingModal(null)}
          onOpenCommandPalette={() => setCommandOpen(true)}
        />

        {/* `tabIndex={-1}` — bez tego część przeglądarek przewinie do kotwicy,
            ale nie przeniesie fokusu, więc skip link byłby pozorny. */}
        <main id="main" tabIndex={-1} className="relative flex-1 overflow-y-auto focus:outline-hidden">
          {/* `pb-24` na telefonie: zapas pod pływającą maskotką w prawym
              dolnym rogu — ostatnie przyciski strony dają się wyprzewijać
              spod niej. */}
          <div className="p-4 pb-24 md:p-6 animate-fadeIn">{children}</div>
        </main>
      </div>

      {/* Global ⌘K command palette */}
      <CommandPaletteV2
        open={commandOpen}
        onOpenChange={setCommandOpen}
        onNewCandidate={can["candidate.create"] ? openNewCandidate : undefined}
        onNewJob={can["job.create"] ? openNewJob : undefined}
      />

      {/* Keyboard shortcuts help */}
      {showHelp && <ShortcutsModal onClose={() => setShowHelp(false)} />}

      {/* „Moi ludzie" — panel rekrutera, postać w rogu, `?people=1` z dzwonka */}
      <MyPeopleRoot />

      {/* Game-mode decorations — only in Kids mode (inert otherwise) */}
      <KidsBackdrop />
      <JarvisRoot />
    </div>
  );
}
