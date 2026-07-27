"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { useAuthStore } from "@/store/auth";
import { useCapabilities } from "@/hooks/useCapability";
import { useKeyboardShortcuts, ShortcutsModal } from "@/components/KeyboardShortcuts";
import { OnboardingWalkthrough, useOnboarding } from "@/components/OnboardingWalkthrough";
import { useOnboardingGuard } from "@/hooks/useOnboardingGuard";
import { SidebarV2 } from "./SidebarV2";
import { TopbarV2 } from "./TopbarV2";
import { ImpersonationBanner } from "./ImpersonationBanner";
import { CommandPaletteV2 } from "./CommandPaletteV2";
import { KidsMascot } from "./KidsMascot";
import { KidsBackdrop } from "./KidsBackdrop";
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

  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [pendingModal, setPendingModal] = useState<QuickActionModal>(null);
  const [commandOpen, setCommandOpen] = useState(false);

  // Hydrate auth from localStorage post-mount (SSR-safe)
  const hydrateAuth = useAuthStore((s) => s.hydrate);
  const hydrated = useAuthStore((s) => s.hydrated);
  useEffect(() => {
    if (!hydrated) hydrateAuth();
  }, [hydrated, hydrateAuth]);

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

  const { showHelp, setShowHelp } = useKeyboardShortcuts({
    onNewCandidate: can["candidate.create"] ? openNewCandidate : undefined,
    onNewJob: can["job.create"] ? openNewJob : undefined,
    onFocusSearch: focusSearch,
  });

  const { shouldShow: showOnboarding, dismiss: dismissOnboarding } = useOnboarding();

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
  // /preview/* — design-system prototype pages, rendered bare (no shell/auth).
  if (pathname?.startsWith("/preview")) return <>{children}</>;

  // /onboarding has its own dedicated layout (no sidebar); let it render
  // without the AppShell wrapper.
  const isOnboardingPage = pathname === "/onboarding" || pathname?.startsWith("/onboarding/");
  if (isOnboardingPage) return <>{children}</>;

  // User must finish onboarding before seeing app content — render a blank
  // shell while the redirect above takes effect.
  if (needsOnboarding) return null;

  return (
    <div className="app-shell-root flex h-screen overflow-hidden bg-background text-foreground">
      {/* Skip link — pierwszy element w kolejności tabulacji; widoczny dopiero
          po sfokusowaniu. Pozwala ominąć sidebar i topbar klawiaturą. */}
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100] focus:rounded-md focus:bg-primary focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-primary-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
      >
        Przejdź do treści
      </a>

      {/* Mobile backdrop */}
      {mobileSidebarOpen && (
        <div
          className="fixed inset-0 bg-foreground/50 z-40 md:hidden backdrop-blur-[2px]"
          onClick={() => setMobileSidebarOpen(false)}
        />
      )}

      {/* Desktop sidebar */}
      <div className="hidden md:flex h-full">
        <SidebarV2 />
      </div>

      {/* Mobile sidebar drawer */}
      {mobileSidebarOpen && (
        <div className="fixed inset-y-0 left-0 z-50 md:hidden">
          <SidebarV2 mobileOpen onClose={() => setMobileSidebarOpen(false)} />
        </div>
      )}

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
        <main id="main" tabIndex={-1} className="flex-1 overflow-y-auto focus:outline-none">
          <div className="p-4 md:p-6 animate-fadeIn">{children}</div>
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

      {/* Onboarding */}
      {showOnboarding && <OnboardingWalkthrough onDismiss={dismissOnboarding} />}

      {/* Game-mode decorations — only in Kids mode (inert otherwise) */}
      <KidsBackdrop />
      <KidsMascot />
    </div>
  );
}
