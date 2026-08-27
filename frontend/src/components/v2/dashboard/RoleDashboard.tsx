"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { BarChart3, ChevronDown, FolderKanban, Wrench } from "lucide-react"

import { TabbedNav } from "@/components/ds"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  DASHBOARD_PRESETS,
  getAvailableDashboardPresets,
  getDefaultDashboardPreset,
  isDashboardPeriod,
  isDashboardPreset,
  isDashboardTab,
  type DashboardPeriod,
  type DashboardPreset,
  type DashboardTab,
} from "@/lib/dashboard-presets"
import type { FinanceDashboardTab } from "@/lib/dashboard-v2-api"
import { getUserRoles, useAuthStore, type UserRole } from "@/store/auth"
import { ContactOversightPanel } from "@/components/candidate-contact/ContactOversightPanel"
import { MyContactQueueWidget } from "@/components/candidate-contact/MyContactQueueWidget"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { Button } from "@/components/ui/button"
import { TabsContent } from "@/components/ui/tabs"
import { cn } from "@/lib/utils"

import { DashboardShell } from "./DashboardShell"
import { DashboardV2Preset } from "./DashboardV2Preset"
import { DailyRecruiterKpi } from "./DailyRecruiterKpi"
import {
  RecruitmentOperationsDashboard,
  RecruitmentOperationsKpis,
} from "./RecruitmentOperationsDashboard"
import {
  MyPriorityQueue,
  TeamAllocationBoard,
} from "@/components/v2/priority-work"

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

// Kto może wołać `/api/candidate-contact/queue` (backendowe `ContactCaller`).
// Admin świadomie NIE jest na tej liście — swoją powierzchnią do kolejki ma
// panel nadzoru niżej, a zamontowanie mu widgetu „moja kolejka" dałoby kartę
// błędu 403 zamiast danych.
const CONTACT_CALLER_ROLES: UserRole[] = ["recruiter", "sourcer", "tac"]

function OperationalTools({
  preset,
  roles,
}: {
  preset: DashboardPreset
  roles: UserRole[]
}) {
  const [open, setOpen] = useState(false)
  const toolsRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const openLinkedTool = () => {
      if (
        window.location.hash === "#nadzor-kontaktu" &&
        (preset === "head-of-recruitment" || preset === "admin-ops")
      ) {
        setOpen(true)
        window.requestAnimationFrame(() => {
          toolsRef.current?.scrollIntoView?.({ block: "start" })
        })
      }
    }

    openLinkedTool()
    window.addEventListener("hashchange", openLinkedTool)
    return () => window.removeEventListener("hashchange", openLinkedTool)
  }, [preset])

  // Te narzędzia zachowujemy jako drugorzędne, zwijane wejścia. Ich własne
  // bramki ról i feature flagi nadal są źródłem prawdy.
  const oversight =
    preset === "head-of-recruitment" || preset === "admin-ops" ? (
      <ContactOversightPanel />
    ) : null
  const myQueue =
    preset === "my-work" &&
    roles.some((role) => CONTACT_CALLER_ROLES.includes(role)) ? (
      <MyContactQueueWidget />
    ) : null
  const teamAllocation =
    preset === "head-of-recruitment" ? <TeamAllocationBoard /> : null
  const priorityQueue = preset === "my-work" ? <MyPriorityQueue /> : null

  if (!oversight && !myQueue && !teamAllocation && !priorityQueue) return null

  return (
    <div ref={toolsRef} className="scroll-mt-24">
      <Collapsible open={open} onOpenChange={setOpen}>
        <Card>
          <CollapsibleTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              className="h-auto w-full justify-between rounded-xl p-4"
            >
              <span className="flex items-center gap-2">
                <Wrench className="h-4 w-4 text-muted-foreground" />
                Pozostałe narzędzia operacyjne
              </span>
              <ChevronDown
                className={cn(
                  "h-4 w-4 transition-transform",
                  open && "rotate-180",
                )}
              />
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <CardContent className="space-y-6 border-t border-border pt-5">
              {oversight}
              {myQueue}
              {teamAllocation}
              {priorityQueue}
            </CardContent>
          </CollapsibleContent>
        </Card>
      </Collapsible>
    </div>
  )
}

function RecruitmentDashboardContent({
  tab,
  preset,
  roles,
}: {
  tab: DashboardTab
  preset: Exclude<DashboardPreset, "finance">
  roles: UserRole[]
}) {
  if (tab === "kpi") {
    return (
      <div className="space-y-4">
        <DailyRecruiterKpi />
        <RecruitmentOperationsKpis preset={preset} />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <RecruitmentOperationsDashboard preset={preset} />
      <OperationalTools preset={preset} roles={roles} />
    </div>
  )
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
  const requestedTab = searchParams.get("tab")
  const tab: DashboardTab = isDashboardTab(requestedTab)
    ? requestedTab
    : "processes"

  useEffect(() => {
    if (!hydrated) return
    if (!user) {
      router.replace("/login")
      return
    }
    if (!preset) return
    const tabIsCanonical =
      preset === "finance" ? requestedTab === null : requestedTab === tab
    if (
      requestedPreset === preset &&
      requestedPeriod === period &&
      !legacyView &&
      tabIsCanonical
    ) {
      return
    }
    const next = new URLSearchParams(searchParams.toString())
    next.set("preset", preset)
    next.set("period", period)
    next.delete("view")
    if (preset === "finance") next.delete("tab")
    else next.set("tab", tab)
    router.replace(`/dashboard?${next.toString()}${window.location.hash}`)
  }, [
    hydrated,
    legacyView,
    period,
    preset,
    requestedPeriod,
    requestedPreset,
    requestedTab,
    router,
    searchParams,
    tab,
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
    nextTab: DashboardTab = "processes",
  ) => {
    const next = new URLSearchParams(searchParams.toString())
    next.set("preset", nextPreset)
    next.set("period", nextPeriod)
    next.delete("view")
    if (nextPreset === "finance") next.delete("tab")
    else next.set("tab", nextTab)
    router.push(`/dashboard?${next.toString()}`)
  }

  return (
    <DashboardShell
      preset={preset}
      period={period}
      availablePresets={availablePresets}
      showPeriod={preset === "finance"}
      onPresetChange={(nextPreset) =>
        updateParams(
          nextPreset,
          DASHBOARD_PRESETS[nextPreset].defaultPeriod,
          "processes",
        )
      }
      onPeriodChange={(nextPeriod) => updateParams(preset, nextPeriod, tab)}
    >
      {preset === "finance" ? (
        <FinancePreset period={period} />
      ) : (
        <TabbedNav
          ariaLabel="Widok dashboardu rekrutacji"
          value={tab}
          onValueChange={(value) =>
            updateParams(preset, period, value as DashboardTab)
          }
          tabs={[
            { value: "kpi", label: "KPI", icon: BarChart3 },
            { value: "processes", label: "Procesy", icon: FolderKanban },
          ]}
          listClassName="sm:w-auto"
        >
          <TabsContent
            value="kpi"
            forceMount
            hidden={tab !== "kpi"}
            className="mt-6"
          >
            {tab === "kpi" ? (
              <RecruitmentDashboardContent
                tab="kpi"
                preset={preset}
                roles={getUserRoles(user)}
              />
            ) : null}
          </TabsContent>
          <TabsContent
            value="processes"
            forceMount
            hidden={tab !== "processes"}
            className="mt-6"
          >
            {tab === "processes" ? (
              <RecruitmentDashboardContent
                tab="processes"
                preset={preset}
                roles={getUserRoles(user)}
              />
            ) : null}
          </TabsContent>
        </TabbedNav>
      )}
    </DashboardShell>
  )
}
