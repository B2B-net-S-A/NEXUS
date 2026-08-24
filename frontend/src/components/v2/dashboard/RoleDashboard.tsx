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
import { getUserRoles, useAuthStore, type UserRole } from "@/store/auth"
import { ContactOversightPanel } from "@/components/candidate-contact/ContactOversightPanel"
import { MyContactQueueWidget } from "@/components/candidate-contact/MyContactQueueWidget"

import { DashboardShell } from "./DashboardShell"
import { DashboardV2Preset } from "./DashboardV2Preset"
import { RecruitmentStatsSection } from "./RecruitmentStatsSection"
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

function presetContent(
  preset: DashboardPreset,
  period: DashboardPeriod,
  roles: UserRole[],
) {
  if (preset === "finance") return <FinancePreset period={period} />

  // Nadzór nad kolejką pierwszego kontaktu. Head of Recruitment i admin nie
  // mieli po #1031 ŻADNEJ powierzchni do tej kolejki: middleware odbija ich
  // z `/candidates/contact-queue` na /403, wpis w sidebarze jest ograniczony
  // do zespołu wykonawczego, a panel dashboardu został odmontowany razem
  // z przepisaniem dashboardów — mimo że alerty SLA generowane w
  // `dashboard_v2.py` linkują dokładnie tam. Osoba, której zadaniem jest
  // wyłapywanie utkniętej pracy, latała na ślepo.
  //
  // Komponent jest fail-closed na fladze `CANDIDATE_CONTACT_ENABLED`
  // (`useCandidateContactFeature` → `enabled === true`), więc przy wyłączonej
  // funkcji nie renderuje ani nie pyta o nic poza samym statusem.
  const oversight =
    preset === "head-of-recruitment" || preset === "admin-ops" ? (
      <ContactOversightPanel />
    ) : null

  // Wykonawcy stracili swój skrót do kolejki w tym samym PR-ze. Do kolejki
  // dochodzą przez sidebar, więc to była regresja odkrywalności, nie odcięcie.
  const myQueue =
    preset === "my-work" &&
    roles.some((role) => CONTACT_CALLER_ROLES.includes(role)) ? (
      <MyContactQueueWidget />
    ) : null

  // Konsola Priority Work wróciła (#101, decyzja Artura 24.08). Cutover RBAC
  // z #1031 odmontował te dwa boardy i nie zamontował ich nigdzie indziej —
  // `grep` po `TeamAllocationBoard|MyPriorityQueue` poza ich własnym katalogiem
  // nie zwracał NICZEGO. Utrzymywaliśmy 1743 linie routera, 1131 serwisu,
  // 817 polityki, 9 tabel i pętlę w lifespanie dla funkcji bez jednego wejścia,
  // a bezpieczny rollout (`off -> shadow -> enforce`) był nie tylko nieużywany,
  // ale NIEWYKONALNY: przestawienie trybu na `enforce` bez opublikowanego planu
  // zablokowałoby rekruterom otwieranie nowych par, bez UI do odblokowania.
  //
  // Oba komponenty bramkują się SAME (`if (!hydrated || !canManage) return null`,
  // odpowiednio na `head_of_recruitment` i na rolach wykonawczych) i same
  // renderują `ModeNotice` dla aktualnego `RECRUITMENT_PRIORITY_MODE`. Montaż
  // jest więc fail-closed: przy trybie `off` nie pytają o nic poza statusem,
  // a zapytania mają `enabled` związane z tą samą rolą.
  const teamAllocation =
    preset === "head-of-recruitment" ? <TeamAllocationBoard /> : null

  const priorityQueue = preset === "my-work" ? <MyPriorityQueue /> : null

  // CompactGamification usunięty — pełny blok rywalizacji (hero ligi,
  // wyścigi, Hall of Fame) renderuje RecruitmentStatsSection pod każdym
  // presetem; skrót dublowałby requesty do /api/competitions.
  if (!oversight && !myQueue && !teamAllocation && !priorityQueue) {
    return <DashboardV2Preset preset={preset} period={period} />
  }
  return (
    <div className="space-y-6">
      {oversight}
      {myQueue}
      {teamAllocation}
      {priorityQueue}
      <DashboardV2Preset preset={preset} period={period} />
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
        {presetContent(preset, period, getUserRoles(user))}
        {/* Sekcja wspólna dla WSZYSTKICH presetów (także finance, gdy ogląda
            ją admin multi-preset); role bez dostępu (finance-only, viewer)
            nie montują jej wcale — zero requestów i 403 w konsoli. */}
        <RecruitmentStatsSection />
      </div>
    </DashboardShell>
  )
}
