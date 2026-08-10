"use client"

import { useEffect, useMemo, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"

import { TabbedNav } from "@/components/ds"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  DASHBOARD_PRESETS,
  getAvailableDashboardPresets,
  getDefaultDashboardPreset,
  isDashboardPeriod,
  isDashboardPreset,
  type DashboardPeriod,
  type DashboardPreset,
} from "@/lib/dashboard-presets"
import type { FinanceDashboardTab } from "@/lib/dashboard-v2-api"
import { useAuthStore } from "@/store/auth"

import { DashboardShell } from "./DashboardShell"
import { DashboardV2Preset } from "./DashboardV2Preset"
import { RecruitmentStatsSection } from "./RecruitmentStatsSection"

const LEGACY_VIEW_PRESET: Partial<Record<string, DashboardPreset>> = {
  operations: "admin-ops",
  delivery: "delivery-lead",
  executive: "finance",
}

function FinancePreset({ period }: { period: DashboardPeriod }) {
  const [tab, setTab] = useState<FinanceDashboardTab>("operations")

  return (
    <div className="space-y-6">
      <TabbedNav
        ariaLabel="Widok finansów"
        value={tab}
        onValueChange={(value) => setTab(value as FinanceDashboardTab)}
        tabs={[
          { value: "operations", label: "Operations" },
          { value: "executive", label: "Executive" },
        ]}
        listClassName="sm:w-auto"
      />
      <DashboardV2Preset preset="finance" period={period} financeTab={tab} />
    </div>
  )
}

function presetContent(preset: DashboardPreset, period: DashboardPeriod) {
  if (preset === "finance") return <FinancePreset period={period} />

  // CompactGamification usunięty — pełny blok rywalizacji (hero ligi,
  // wyścigi, Hall of Fame) renderuje RecruitmentStatsSection pod każdym
  // presetem; skrót dublowałby requesty do /api/competitions.
  return <DashboardV2Preset preset={preset} period={period} />
}

export function RoleDashboard() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const user = useAuthStore((state) => state.user)
  const hydrated = useAuthStore((state) => state.hydrated)

  const availablePresets = useMemo(
    () => getAvailableDashboardPresets(user),
    [user],
  )
  const defaultPreset = getDefaultDashboardPreset(user)
  const requestedPreset = searchParams.get("preset")
  const legacyView = searchParams.get("view")
  const legacyPreset =
    legacyView === "recruitment"
      ? availablePresets.includes("head-of-recruitment")
        ? "head-of-recruitment"
        : "my-work"
      : legacyView
        ? LEGACY_VIEW_PRESET[legacyView]
        : undefined
  const preset =
    (isDashboardPreset(requestedPreset) &&
    availablePresets.includes(requestedPreset)
      ? requestedPreset
      : legacyPreset && availablePresets.includes(legacyPreset)
        ? legacyPreset
        : defaultPreset) ?? null
  const requestedPeriod = searchParams.get("period")
  const period =
    isDashboardPeriod(requestedPeriod) && preset
      ? requestedPeriod
      : preset
        ? DASHBOARD_PRESETS[preset].defaultPeriod
        : "month"

  useEffect(() => {
    if (!hydrated) return
    if (!user) {
      router.replace("/login")
      return
    }
    if (!preset) return
    if (
      requestedPreset === preset &&
      requestedPeriod === period &&
      !legacyView
    ) {
      return
    }
    const next = new URLSearchParams(searchParams.toString())
    next.set("preset", preset)
    next.set("period", period)
    next.delete("view")
    router.replace(`/dashboard?${next.toString()}`)
  }, [
    hydrated,
    legacyView,
    period,
    preset,
    requestedPeriod,
    requestedPreset,
    router,
    searchParams,
    user,
  ])

  if (!hydrated || !user) {
    return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>
  }

  if (!preset) {
    return (
      <div className="mx-auto max-w-2xl p-6">
        <Card>
          <CardHeader>
            <CardTitle>Brak przypisanego dashboardu</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            Konto nie ma dostępnego presetu. Administrator musi przypisać rolę
            docelową; rola legacy User nie jest automatycznie mapowana na
            Finanse.
          </CardContent>
        </Card>
      </div>
    )
  }

  const updateParams = (
    nextPreset: DashboardPreset,
    nextPeriod: DashboardPeriod,
  ) => {
    const next = new URLSearchParams(searchParams.toString())
    next.set("preset", nextPreset)
    next.set("period", nextPeriod)
    next.delete("view")
    router.push(`/dashboard?${next.toString()}`)
  }

  return (
    <DashboardShell
      preset={preset}
      period={period}
      availablePresets={availablePresets}
      onPresetChange={(nextPreset) =>
        updateParams(nextPreset, DASHBOARD_PRESETS[nextPreset].defaultPeriod)
      }
      onPeriodChange={(nextPeriod) => updateParams(preset, nextPeriod)}
    >
      <div className="space-y-6">
        {presetContent(preset, period)}
        {/* Sekcja wspólna dla WSZYSTKICH presetów (także finance, gdy ogląda
            ją admin multi-preset); role bez dostępu (finance-only, viewer)
            nie montują jej wcale — zero requestów i 403 w konsoli. */}
        <RecruitmentStatsSection />
      </div>
    </DashboardShell>
  )
}
