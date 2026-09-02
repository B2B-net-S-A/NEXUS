"use client"

import type { ReactNode } from "react"

import { PageHeader } from "@/components/ds"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import {
  DASHBOARD_PRESETS,
  type DashboardPresetDefinition,
  type DashboardPeriod,
  type DashboardPreset,
} from "@/lib/dashboard-presets"

const PERIODS: Array<{ value: DashboardPeriod; label: string }> = [
  { value: "day", label: "Dziś" },
  { value: "week", label: "Tydzień" },
  { value: "month", label: "Miesiąc" },
  { value: "quarter", label: "Kwartał" },
  { value: "year", label: "Rok" },
]

interface DashboardShellProps {
  preset: DashboardPreset
  period: DashboardPeriod
  availablePresets: DashboardPreset[]
  onPresetChange: (preset: DashboardPreset) => void
  onPeriodChange: (period: DashboardPeriod) => void
  showPeriod?: boolean
  definitionOverrides?: Partial<
    Record<DashboardPreset, DashboardPresetDefinition>
  >
  children: ReactNode
}

export function DashboardShell({
  preset,
  period,
  availablePresets,
  onPresetChange,
  onPeriodChange,
  showPeriod = true,
  definitionOverrides,
  children,
}: DashboardShellProps) {
  const definition = definitionOverrides?.[preset] ?? DASHBOARD_PRESETS[preset]

  return (
    <div className="mx-auto max-w-[1400px] space-y-6 p-4 md:p-6">
      <PageHeader
        eyebrow="Nexus · dashboard"
        title={definition.title}
        description={definition.description}
        density="compact"
      />

      <div className="flex flex-col gap-3 border-b border-border pb-4 lg:flex-row lg:items-center lg:justify-between">
        {availablePresets.length > 1 ? (
          <nav
            aria-label="Kontekst dashboardu"
            className="flex max-w-full gap-1 overflow-x-auto"
          >
            {availablePresets.map((candidate) => (
              <Button
                key={candidate}
                type="button"
                size="sm"
                variant={candidate === preset ? "primary" : "ghost"}
                aria-pressed={candidate === preset}
                onClick={() => onPresetChange(candidate)}
                className="shrink-0"
              >
                {(definitionOverrides?.[candidate] ?? DASHBOARD_PRESETS[candidate]).label}
              </Button>
            ))}
          </nav>
        ) : (
          <p className="text-sm font-medium text-foreground">
            {definition.label}
          </p>
        )}

        {showPeriod ? (
          <nav
            aria-label="Okres dashboardu"
            className="flex max-w-full gap-1 overflow-x-auto"
          >
            {PERIODS.map((item) => (
              <button
                key={item.value}
                type="button"
                aria-pressed={item.value === period}
                onClick={() => onPeriodChange(item.value)}
                className={cn(
                  "shrink-0 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                  "focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
                  item.value === period
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                {item.label}
              </button>
            ))}
          </nav>
        ) : null}
      </div>

      {children}
    </div>
  )
}
