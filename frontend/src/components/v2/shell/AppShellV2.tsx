"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { useAuthStore } from "@/store/auth";
import { useKeyboardShortcuts, ShortcutsModal } from "@/components/KeyboardShortcuts";
import { OnboardingWalkthrough, useOnboarding } from "@/components/OnboardingWalkthrough";
import { useOnboardingGuard } from "@/hooks/useOnboardingGuard";
import { SidebarV2 } from "./SidebarV2";
import { TopbarV2 } from "./TopbarV2";
import { ImpersonationBanner } from "./ImpersonationBanner";
import { OpenTabsV2 } from "./OpenTabsV2";
import { CommandPaletteV2 } from "./CommandPaletteV2";
import { KidsMascot } from "./KidsMascot";
import { KidsBackdrop } from "./KidsBackdrop";
import type { QuickActionModal } from "./QuickActionsV2";

/**
 * AppShellV2 — Dynaminds redesign shell.
 *
 * Composition: SidebarV2 (plum chrome) + TopbarV2 + OpenTabsV2 + main content.
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

  const { showHelp, setShowHelp } = useKeyboardShortcuts({
    onNewCandidate: useCallback(() => setPendingModal("candidate"), []),
    onNewJob: useCallback(() => setPendingModal("job"), []),
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

  // /onboarding has its own dedicated layout (no sidebar); let it render
  // without the AppShell wrapper.
  const isOnboardingPage = pathname === "/onboarding" || pathname?.startsWith("/onboarding/");
  if (isOnboardingPage) return <>{children}</>;

  // User must finish onboarding before seeing app content — render a blank
  // shell while the redirect above takes effect.
  if (needsOnboarding) return null;

  return (
    <div className="app-shell-root flex h-screen overflow-hidden bg-background text-foreground">
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

        <OpenTabsV2 />

        <main className="flex-1 overflow-y-auto">
          <div className="p-4 md:p-6 animate-fadeIn">{children}</div>
        </main>
      </div>

      {/* Global ⌘K command palette */}
      <CommandPaletteV2
        open={commandOpen}
        onOpenChange={setCommandOpen}
        onNewCandidate={() => setPendingModal("candidate")}
        onNewJob={() => setPendingModal("job")}
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
