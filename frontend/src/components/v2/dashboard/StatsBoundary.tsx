"use client"

import type { ReactNode } from "react"
import {
  AlertCircle,
  Ban,
  Clock3,
  DatabaseZap,
  Loader2,
  RefreshCw,
  Settings2,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

export type StatsQuality = {
  status: "complete" | "partial" | "unavailable"
  warnings?: string[]
}

export type StatsUnavailableReason =
  | "disabled"
  | "unconfigured"
  | "unavailable"

export type StatsBoundaryState =
  | "loading"
  | "forbidden"
  | "disabled"
  | "unconfigured"
  | "error"
  | "unavailable"
  | "empty"
  | "ready"

type ResolveStatsBoundaryStateInput = {
  isLoading?: boolean
  isError?: boolean
  error?: unknown
  isEmpty?: boolean
  quality?: StatsQuality | null
  unavailableReason?: StatsUnavailableReason
}

function responseStatus(error: unknown): number | undefined {
  if (!error || typeof error !== "object") return undefined
  const response = (error as { response?: unknown }).response
  if (!response || typeof response !== "object") return undefined
  const status = (response as { status?: unknown }).status
  return typeof status === "number" ? status : undefined
}

export function inferStatsUnavailableReason(
  quality?: StatsQuality | null,
): StatsUnavailableReason {
  const warnings = (quality?.warnings ?? []).join(" ").toLocaleLowerCase("pl")
  if (warnings.includes("unconfigured") || warnings.includes("nieskonfigurow")) {
    return "unconfigured"
  }
  if (warnings.includes("disabled") || warnings.includes("wyłącz")) {
    return "disabled"
  }
  return "unavailable"
}

export function resolveStatsBoundaryState({
  isLoading,
  isError,
  error,
  isEmpty,
  quality,
  unavailableReason,
}: ResolveStatsBoundaryStateInput): StatsBoundaryState {
  if (isLoading) return "loading"
  if (isError && responseStatus(error) === 403) return "forbidden"
  if (unavailableReason === "disabled") return "disabled"
  if (unavailableReason === "unconfigured") return "unconfigured"
  if (isError) return "error"
  if (quality?.status === "unavailable") {
    return inferStatsUnavailableReason(quality)
  }
  if (isEmpty) return "empty"
  return "ready"
}

function isGeneratedDataStale(
  generatedAt: string | null | undefined,
  staleAfterMs: number,
): boolean {
  if (!generatedAt) return false
  const timestamp = Date.parse(generatedAt)
  return Number.isFinite(timestamp) && Date.now() - timestamp > staleAfterMs
}

function warningsIndicateStale(quality?: StatsQuality | null): boolean {
  return (quality?.warnings ?? []).some((warning) => {
    const normalized = warning.toLocaleLowerCase("pl")
    return normalized.includes("stale") || normalized.includes("nieaktual")
  })
}

function StateBlock({
  state,
  onRetry,
  emptyTitle,
}: {
  state: Exclude<StatsBoundaryState, "ready">
  onRetry?: () => void
  emptyTitle: string
}) {
  const content = {
    loading: {
      icon: Loader2,
      title: "Ładowanie statystyk…",
      description: "Pobieramy aktualne dane.",
      iconClassName: "animate-spin text-muted-foreground",
    },
    forbidden: {
      icon: Ban,
      title: "Brak dostępu",
      description: "To konto nie ma uprawnień do tych statystyk.",
      iconClassName: "text-destructive",
    },
    disabled: {
      icon: Settings2,
      title: "Moduł jest wyłączony",
      description: "Statystyki pojawią się po ponownym włączeniu modułu.",
      iconClassName: "text-muted-foreground",
    },
    unconfigured: {
      icon: Settings2,
      title: "Moduł nie jest skonfigurowany",
      description: "Administrator musi dokończyć konfigurację źródła danych.",
      iconClassName: "text-warning-muted-foreground",
    },
    error: {
      icon: AlertCircle,
      title: "Nie udało się załadować statystyk",
      description: "Spróbuj ponownie. Jeśli problem wróci, zgłoś go administratorowi.",
      iconClassName: "text-destructive",
    },
    unavailable: {
      icon: DatabaseZap,
      title: "Statystyki są niedostępne",
      description: "Źródło danych nie zwróciło wiarygodnego wyniku.",
      iconClassName: "text-warning-muted-foreground",
    },
    empty: {
      icon: DatabaseZap,
      title: emptyTitle,
      description: "Zmień okres lub wróć, gdy pojawią się nowe zdarzenia.",
      iconClassName: "text-muted-foreground",
    },
  }[state]
  const Icon = content.icon

  return (
    <div
      role={state === "error" || state === "forbidden" ? "alert" : "status"}
      className="flex min-h-28 flex-col items-center justify-center rounded-lg border border-dashed border-border bg-muted/20 px-4 py-6 text-center"
    >
      <Icon className={cn("mb-2 h-6 w-6", content.iconClassName)} />
      <p className="text-sm font-medium text-foreground">{content.title}</p>
      <p className="mt-1 max-w-lg text-xs text-muted-foreground">
        {content.description}
      </p>
      {onRetry && (state === "error" || state === "unavailable") && (
        <Button type="button" variant="outline" size="sm" onClick={onRetry} className="mt-3">
          <RefreshCw className="h-3.5 w-3.5" />
          Spróbuj ponownie
        </Button>
      )}
    </div>
  )
}

export interface StatsBoundaryProps {
  children: ReactNode
  isLoading?: boolean
  isFetching?: boolean
  isError?: boolean
  error?: unknown
  isEmpty?: boolean
  quality?: StatsQuality | null
  generatedAt?: string | null
  staleAfterMs?: number
  isStale?: boolean
  unavailableReason?: StatsUnavailableReason
  onRetry?: () => void
  loadingFallback?: ReactNode
  emptyFallback?: ReactNode
  emptyTitle?: string
  className?: string
}

/**
 * Shared state contract for analytics widgets. It distinguishes access,
 * availability and freshness, so an error or disabled source can never look
 * like a real numeric zero.
 */
export function StatsBoundary({
  children,
  isLoading = false,
  isFetching = false,
  isError = false,
  error,
  isEmpty = false,
  quality,
  generatedAt,
  staleAfterMs = 5 * 60_000,
  isStale = false,
  unavailableReason,
  onRetry,
  loadingFallback,
  emptyFallback,
  emptyTitle = "Brak danych dla wybranego okresu",
  className,
}: StatsBoundaryProps) {
  const state = resolveStatsBoundaryState({
    isLoading,
    isError,
    error,
    isEmpty,
    quality,
    unavailableReason,
  })

  if (state === "loading" && loadingFallback) return <>{loadingFallback}</>
  if (state === "empty" && emptyFallback) return <>{emptyFallback}</>
  if (state !== "ready") {
    return <StateBlock state={state} onRetry={onRetry} emptyTitle={emptyTitle} />
  }

  const stale =
    isStale ||
    warningsIndicateStale(quality) ||
    isGeneratedDataStale(generatedAt, staleAfterMs)
  const partialWarnings = quality?.status === "partial" ? quality.warnings ?? [] : []

  return (
    <div className={cn("relative", className)} aria-busy={isFetching || undefined}>
      {(isFetching || stale || partialWarnings.length > 0) && (
        <div className="mb-3 space-y-2" aria-live="polite">
          {isFetching && (
            <div className="flex items-center gap-2 rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Odświeżanie danych…
            </div>
          )}
          {stale && (
            <div className="flex items-center gap-2 rounded-md bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground">
              <Clock3 className="h-3.5 w-3.5" />
              Dane mogą być nieaktualne.
              {onRetry && (
                <button type="button" onClick={onRetry} className="ml-auto font-medium underline-offset-2 hover:underline">
                  Odśwież
                </button>
              )}
            </div>
          )}
          {partialWarnings.length > 0 && (
            <div className="rounded-md bg-info-muted px-3 py-2 text-xs text-info-muted-foreground">
              Część danych jest niedostępna: {partialWarnings.join(" · ")}
            </div>
          )}
        </div>
      )}
      {children}
    </div>
  )
}

export default StatsBoundary
