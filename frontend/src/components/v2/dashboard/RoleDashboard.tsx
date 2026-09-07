"use client"

import { AllocationWorkloadBoard } from "@/components/v2/priority-work/AllocationWorkloadBoard"

import { useEffect, useMemo, useRef, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { ChevronDown, Wrench } from "lucide-react"

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
import { getUserRoles, useAuthStore, type UserRole } from "@/store/auth"
import { ContactOversightPanel } from "@/components/candidate-contact/ContactOversightPanel"
import { MyContactQueueWidget } from "@/components/candidate-contact/MyContactQueueWidget"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

import { DashboardShell } from "./DashboardShell"
import {
  MyAssignedRecruitments,
  RecruitmentCompetenceDashboard,
} from "./RecruitmentCompetenceDashboard"
import { MyTasksDashboard } from "./MyTasksDashboard"
import { RecruitmentActivityDashboard } from "./RecruitmentActivityDashboard"
import {
  MyPriorityQueue,
  TeamAllocationBoard,
} from "@/components/v2/priority-work"

const LEGACY_VIEW_PRESET: Partial<Record<string, DashboardPreset>> = {
  operations: "admin-ops",
  delivery: "delivery-lead",
  executive: "finance",
}

// Kto może wołać `/api/candidate-contact/queue` (backendowe `ContactCaller`).
// Admin świadomie NIE jest na tej liście — swoją powierzchnią do kolejki ma
// panel nadzoru niżej, a zamontowanie mu widgetu „moja kolejka" dałoby kartę
// błędu 403 zamiast danych.
const CONTACT_CALLER_ROLES: UserRole[] = [
  "talent_community_manager",
  "recruiter",
  "sourcer",
  "tac",
]

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
  const canUseRecruitmentOversight = roles.some((role) =>
    (["admin", "head_of_recruitment"] as UserRole[]).includes(role),
  )
  const oversight =
    canUseRecruitmentOversight &&
    (preset === "head-of-recruitment" || preset === "admin-ops") ? (
      <ContactOversightPanel />
    ) : null
  const myQueue =
    preset === "my-work" &&
    roles.some((role) => CONTACT_CALLER_ROLES.includes(role)) ? (
      <MyContactQueueWidget />
    ) : null
  const teamAllocation =
    canUseRecruitmentOversight && preset === "head-of-recruitment" ? (
      <TeamAllocationBoard />
    ) : null
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
  preset,
  roles,
}: {
  preset: DashboardPreset
  roles: UserRole[]
}) {
  return (
    <div className="space-y-6">
      {preset === "head-of-recruitment" && roles.includes("head_of_recruitment") && <AllocationWorkloadBoard />}
      <RecruitmentActivityDashboard />
      <MyAssignedRecruitments preset={preset} />
      <MyTasksDashboard />
      <RecruitmentCompetenceDashboard preset={preset} />
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
  const roles = useMemo(() => getUserRoles(user), [user])
  const definitionOverrides = useMemo(() => {
    if (
      !roles.includes("talent_community_manager") ||
      roles.includes("head_of_recruitment")
    ) {
      return undefined
    }
    return {
      "head-of-recruitment": {
        ...DASHBOARD_PRESETS["head-of-recruitment"],
        label: "Talent Community Manager",
        shortLabel: "TCM",
        title: "Talent Community Manager",
      },
    }
  }, [roles])
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
      !legacyView &&
      requestedTab === null
    ) {
      return
    }
    const next = new URLSearchParams(searchParams.toString())
    next.set("preset", preset)
    next.set("period", period)
    next.delete("view")
    next.delete("tab")
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
    next.delete("tab")
    router.push(`/dashboard?${next.toString()}`)
  }

  return (
    <DashboardShell
      preset={preset}
      period={period}
      availablePresets={availablePresets}
      definitionOverrides={definitionOverrides}
      showPeriod={false}
      onPresetChange={(nextPreset) =>
        updateParams(
          nextPreset,
          DASHBOARD_PRESETS[nextPreset].defaultPeriod,
        )
      }
      onPeriodChange={(nextPeriod) => updateParams(preset, nextPeriod)}
    >
      <RecruitmentDashboardContent
        preset={preset}
        roles={roles}
      />
    </DashboardShell>
  )
}
