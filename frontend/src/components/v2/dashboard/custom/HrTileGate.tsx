"use client"

// Wspólne wejście kafelków „Ludzi w NEXUSIE” (17.10.2026): czeka na stan
// modułów z `/api/hr/config` i rozstrzyga go tą samą regułą co katalog
// (`hrTileGate`). Kafelek zapisany, zanim moduł wyłączono, mówi o tym zdaniem
// zamiast serii błędów 404; awaria odczytu stanu modułów to blok błędu, nie
// pusty kafelek.

import type { ReactNode } from "react"
import { Lock } from "lucide-react"

import { Skeleton } from "@/components/ui/skeleton"
import { WidgetErrorBlock } from "@/components/v2/dashboard/WidgetState"
import { useHrConfig, type HrConfig } from "@/lib/api/hr"
import type { TileType } from "@/lib/api/userDashboard"
import { hrTileGate } from "@/lib/dashboard-tiles/catalog"
import { resolveViewState } from "@/lib/view-state"

export function HrTileGate({
  type,
  children,
}: {
  type: TileType
  children: (config: HrConfig) => ReactNode
}) {
  const config = useHrConfig()
  const state = resolveViewState({
    isLoading: config.isLoading,
    isError: config.isError,
    error: config.error,
    isSuccess: config.isSuccess,
  })
  if (state === "loading") return <Skeleton className="h-full min-h-[48px] w-full" />
  if (state !== "ready" || !config.data) {
    return <WidgetErrorBlock error={config.error} onRetry={() => config.refetch()} />
  }
  const gate = hrTileGate(type, config.data)
  if (gate === "hidden") {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        Ten moduł „Ludzi w NEXUSIE” jest wyłączony. Usuń kafelek albo poproś
        administratora o włączenie modułu.
      </p>
    )
  }
  if (!gate.ok) {
    return (
      <div
        role="status"
        className="flex h-full flex-col items-center justify-center gap-2 px-2 text-center"
      >
        <Lock className="h-5 w-5 text-muted-foreground" aria-hidden />
        <p className="text-sm font-medium text-foreground">Brak dostępu</p>
        <p className="text-xs text-muted-foreground">{gate.reason}</p>
      </div>
    )
  }
  return <>{children(config.data)}</>
}

/** Awaria jednej części kafelka — zdanie z ponowieniem zamiast zera. */
export function TilePartError({ label, onRetry }: { label: string; onRetry: () => void }) {
  return (
    <p role="alert" className="text-sm text-destructive">
      {label}{" "}
      <button
        type="button"
        onClick={onRetry}
        className="font-medium text-primary underline-offset-2 hover:underline"
      >
        Spróbuj ponownie
      </button>
    </p>
  )
}
