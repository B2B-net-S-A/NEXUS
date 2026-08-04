"use client";

/**
 * StatsBoundary — pełny zestaw stanów jakości dla widgetów Analytics v1
 * (plan PR 5). Rozszerza filozofię WidgetState o stany wynikające z koperty
 * §4.5 (quality: complete|partial|unavailable) i z gatingu (forbidden,
 * disabled).
 *
 * ŻELAZNA ZASADA (plan §3.5): error/unavailable NIGDY nie renderuje "0" —
 * brak danych to komunikat, nie liczba.
 */

import * as React from "react";
import { AlertTriangle, Ban, CloudOff, Info, Loader2, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import type { AnalyticsQuality } from "@/lib/stats-api";

export type StatsBoundaryState =
  | "loading"
  | "refreshing"
  | "error"
  | "forbidden"
  | "empty"
  | "stale"
  | "partial"
  | "disabled"
  | "unconfigured"
  | "unavailable"
  | "ready";

export interface StatsBoundaryProps {
  /** Stan wyliczony przez hooka/rodzica (deriveBoundaryState pomaga). */
  state: StatsBoundaryState;
  /** Ostrzeżenia z koperty (quality.warnings) — pokazywane przy partial. */
  warnings?: string[];
  onRetry?: () => void;
  /** Zawartość renderowana dla ready/refreshing/partial/stale. */
  children?: React.ReactNode;
  className?: string;
  loadingFallback?: React.ReactNode;
}

const MESSAGES: Record<
  Exclude<StatsBoundaryState, "ready" | "refreshing" | "partial" | "stale">,
  { icon: React.ComponentType<{ className?: string }>; text: string }
> = {
  loading: { icon: Loader2, text: "Ładowanie…" },
  error: { icon: AlertTriangle, text: "Nie udało się załadować danych." },
  forbidden: { icon: Ban, text: "Brak uprawnień do tych danych." },
  empty: { icon: Info, text: "Brak danych w wybranym okresie." },
  disabled: { icon: CloudOff, text: "Moduł statystyk nie jest jeszcze aktywny." },
  unconfigured: {
    icon: CloudOff,
    text: "Integracja nie jest skonfigurowana.",
  },
  unavailable: {
    icon: CloudOff,
    text: "Dane są chwilowo niedostępne (to NIE jest zero).",
  },
};

export function StatsBoundary({
  state,
  warnings,
  onRetry,
  children,
  className,
  loadingFallback,
}: StatsBoundaryProps) {
  if (state === "ready") return <>{children}</>;

  if (state === "refreshing" || state === "stale") {
    return (
      <div className={cn("relative", className)}>
        <div className="absolute right-2 top-2 z-10 inline-flex items-center gap-1 rounded-md bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">
          <RefreshCw className="h-3 w-3 animate-spin" />
          {state === "stale" ? "dane mogą być nieaktualne" : "odświeżanie…"}
        </div>
        <div className={state === "stale" ? "opacity-70" : undefined}>{children}</div>
      </div>
    );
  }

  if (state === "partial") {
    return (
      <div className={className}>
        <div className="mb-2 flex items-start gap-2 rounded-md border border-warning/30 bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <div>
            <p className="font-semibold">Dane częściowe</p>
            {(warnings ?? []).map((w) => (
              <p key={w}>{w}</p>
            ))}
          </div>
        </div>
        {children}
      </div>
    );
  }

  if (state === "loading" && loadingFallback) {
    return <div className={className}>{loadingFallback}</div>;
  }

  const { icon: Icon, text } = MESSAGES[state];
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border px-4 py-8 text-center",
        className
      )}
    >
      <Icon
        className={cn(
          "h-5 w-5 text-muted-foreground",
          state === "loading" && "animate-spin"
        )}
      />
      <p className="text-sm text-muted-foreground">{text}</p>
      {(warnings ?? []).map((w) => (
        <p key={w} className="text-xs text-muted-foreground">
          {w}
        </p>
      ))}
      {onRetry && state === "error" && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-1 inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-xs font-medium text-foreground hover:bg-muted"
        >
          <RefreshCw className="h-3 w-3" /> Spróbuj ponownie
        </button>
      )}
    </div>
  );
}

/**
 * Wyprowadź stan boundary z React Query + koperty. Fail-closed:
 * - !allowed (brak capability / tryb != live)   → "disabled"
 * - 403 z backendu                              → "forbidden"
 * - quality.status unavailable                  → "unavailable"
 * - quality.status partial                      → "partial"
 */
export function deriveBoundaryState(opts: {
  allowed: boolean;
  isLoading: boolean;
  isFetching?: boolean;
  isError: boolean;
  errorStatus?: number;
  quality?: AnalyticsQuality;
  isEmpty?: boolean;
}): StatsBoundaryState {
  if (!opts.allowed) return "disabled";
  if (opts.isLoading) return "loading";
  if (opts.isError) {
    return opts.errorStatus === 403 ? "forbidden" : "error";
  }
  if (opts.quality?.status === "unavailable") return "unavailable";
  if (opts.quality?.status === "partial") return "partial";
  if (opts.isEmpty) return "empty";
  if (opts.isFetching) return "refreshing";
  return "ready";
}
