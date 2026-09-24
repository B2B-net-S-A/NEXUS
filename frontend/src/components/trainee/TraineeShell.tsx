"use client";

import { LogOut } from "lucide-react";

import { DynamindsMark } from "@/components/brand/DynamindsMark";
import { ImpersonationBanner } from "@/components/v2/shell/ImpersonationBanner";
import { useTraineeToday } from "@/lib/api/trainee";
import { useAuthStore } from "@/store/auth";

function initials(name: string): string {
  return (
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase() ?? "")
      .join("") || "?"
  );
}

/** „czwartek, 24 września” — dzień listy, nie zegar przeglądarki. */
export function traineeDateLabel(isoDate: string | null | undefined): string {
  const date = isoDate ? new Date(`${isoDate}T12:00:00`) : new Date();
  const safe = Number.isNaN(date.getTime()) ? new Date() : date;
  return safe.toLocaleDateString("pl-PL", { weekday: "long", day: "numeric", month: "long" });
}

export interface TraineeTopBarProps {
  userName: string;
  dateLabel: string;
  /** `null` = program nieznany (brak listy albo błąd) — chip bez dnia. */
  programDay: { day: number; total: number } | null;
  onLogout: () => void;
}

/**
 * Pasek praktykanta (0371): logo, „Telefony na dziś”, data, osoba z dniem
 * programu i wylogowanie. Bez menu, palety ⌘K, dzwonka i Jarvisa —
 * praktykant ma jeden ekran.
 */
export function TraineeTopBar({ userName, dateLabel, programDay, onLogout }: TraineeTopBarProps) {
  return (
    <header className="flex min-h-14 shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b border-border bg-card px-4 py-2 md:px-6">
      <div className="flex items-center gap-2 text-foreground">
        <DynamindsMark className="h-[24px] w-auto" />
        <span className="text-sm font-semibold tracking-tight">Nexus</span>
      </div>
      <div className="hidden h-6 w-px bg-border sm:block" aria-hidden />
      <div className="flex min-w-0 items-baseline gap-3">
        <h1 className="text-base font-semibold text-foreground">Telefony na dziś</h1>
        <span className="truncate text-sm text-muted-foreground">{dateLabel}</span>
      </div>
      <div className="flex-1" />
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-2 rounded-full border border-border py-1 pl-1 pr-3">
          <span
            className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary"
            aria-hidden
          >
            {initials(userName)}
          </span>
          <span className="flex flex-col leading-tight">
            <span className="text-sm font-semibold text-foreground">{userName}</span>
            <span className="text-xs text-muted-foreground">
              Praktykant
              {programDay ? ` · dzień ${programDay.day} z ${programDay.total}` : ""}
            </span>
          </span>
        </div>
        <button
          type="button"
          onClick={onLogout}
          className="inline-flex min-h-10 items-center gap-1.5 rounded-md px-2.5 text-sm text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring pointer-coarse:min-h-11"
        >
          <LogOut className="h-4 w-4" aria-hidden />
          <span className="hidden sm:inline">Wyloguj</span>
          <span className="sr-only sm:hidden">Wyloguj</span>
        </button>
      </div>
    </header>
  );
}

/**
 * Powłoka aplikacji dla praktykanta — zamiast sidebara, topbara z paletą,
 * dzwonka i Jarvisa. Dzień programu czyta z tej samej listy co ekran
 * (ten sam klucz react-query, więc bez drugiego zapytania).
 */
export function TraineeShell({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const today = useTraineeToday();
  const program = today.data?.program ?? null;
  return (
    <div className="relative flex h-dvh flex-col overflow-hidden bg-background text-foreground">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-100 focus:rounded-md focus:bg-primary focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-primary-foreground"
      >
        Przejdź do treści
      </a>
      <ImpersonationBanner />
      <TraineeTopBar
        userName={user?.name ?? "Praktykant"}
        dateLabel={traineeDateLabel(today.data?.list_date)}
        programDay={program ? { day: program.day, total: program.total_days } : null}
        onLogout={logout}
      />
      <main id="main" tabIndex={-1} className="relative flex-1 overflow-y-auto focus:outline-hidden">
        <div className="p-4 md:p-6">{children}</div>
      </main>
    </div>
  );
}
