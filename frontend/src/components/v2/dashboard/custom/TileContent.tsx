"use client"

// Co rysuje kafelek danego typu. Gotowe kafelki to widżety ze starego pulpitu
// ról — opakowane, nie przepisane: każdy dalej pobiera dane sam i sam pilnuje
// swoich bramek. Kafelek, na który konto straciło uprawnienia, pokazuje
// powód zamiast serii błędów 403.

import { Lock } from "lucide-react"

import { ContactOversightPanel } from "@/components/candidate-contact/ContactOversightPanel"
import { MyContactQueueWidget } from "@/components/candidate-contact/MyContactQueueWidget"
import { DlAlertsSection } from "@/components/v2/dashboard/DlAlertsSection"
import { MyClientsAlertsPanel } from "@/components/v2/dashboard/MyClientsAlertsPanel"
import { MyNextStepsSection } from "@/components/v2/dashboard/MyNextStepsSection"
import { MyOnboardingTasks } from "@/components/v2/dashboard/MyOnboardingTasks"
import { MyTasksDashboard } from "@/components/v2/dashboard/MyTasksDashboard"
import { RecruitmentActivityDashboard } from "@/components/v2/dashboard/RecruitmentActivityDashboard"
import {
  MyAssignedRecruitments,
  RecruitmentCompetenceDashboard,
} from "@/components/v2/dashboard/RecruitmentCompetenceDashboard"
import { MyKpiWidget } from "@/components/v2/kpi/MyKpiWidget"
import { MyPriorityQueue, TeamAllocationBoard } from "@/components/v2/priority-work"
import { RequestBoard } from "@/components/v2/request-board/RequestBoard"
import { AllocationWorkloadBoard } from "@/components/v2/priority-work/AllocationWorkloadBoard"
import type { DashboardTile } from "@/lib/api/userDashboard"
import { TILE_DEFINITIONS } from "@/lib/dashboard-tiles/catalog"
import { getDefaultDashboardPreset } from "@/lib/dashboard-presets"
import { useAuthStore } from "@/store/auth"

import { MetricTileBody } from "./MetricTileBody"
import { CalendarTodayBody, MyPeopleBody, NoteBody } from "./SmallTiles"

function Unavailable({ reason }: { reason: string }) {
  return (
    <div
      role="status"
      className="flex h-full flex-col items-center justify-center gap-2 px-2 text-center"
    >
      <Lock className="h-5 w-5 text-muted-foreground" aria-hidden />
      <p className="text-sm font-medium text-foreground">Brak dostępu</p>
      <p className="text-xs text-muted-foreground">{reason}</p>
    </div>
  )
}

export function TileContent({ tile }: { tile: DashboardTile }) {
  const user = useAuthStore((s) => s.user)
  const availability = TILE_DEFINITIONS[tile.type].availability(user)
  if (!availability.ok) return <Unavailable reason={availability.reason} />

  // Procesy rekrutacyjne serwer liczy dla „presetu" konta — źródłem jest
  // `default_dashboard_preset` z /api/auth/me, nie wybór w interfejsie.
  const preset = getDefaultDashboardPreset(user) ?? "my-work"

  switch (tile.type) {
    case "my_tasks":
      // FE-N06 (regresja #1662): pulpit DL filtruje sprawy klientów z
      // „Moich zadań” — mają własny kafelek „Moi klienci — sprawy”.
      return (
        <MyTasksDashboard recruitmentNotificationsOnly={preset === "delivery-lead"} />
      )
    case "my_next_steps":
      return <MyNextStepsSection />
    case "my_contact_queue":
      return <MyContactQueueWidget />
    case "my_priority_queue":
      return <MyPriorityQueue />
    case "my_people":
      return <MyPeopleBody />
    case "my_kpis_today":
      return <MyKpiWidget variant="dashboard" />
    case "my_onboarding":
      return <MyOnboardingTasks />
    case "my_recruitments":
      return <MyAssignedRecruitments preset={preset} />
    case "recruitment_activity":
      return <RecruitmentActivityDashboard />
    case "recruitment_competence":
      return <RecruitmentCompetenceDashboard preset={preset} />
    case "team_workload":
      return <AllocationWorkloadBoard />
    case "team_allocation":
      return <TeamAllocationBoard />
    case "request_board":
      return <RequestBoard />
    case "contact_oversight":
      return <ContactOversightPanel />
    case "my_clients_alerts":
      return <MyClientsAlertsPanel />
    case "dl_alerts":
      return <DlAlertsSection />
    case "calendar_today":
      return <CalendarTodayBody />
    case "note":
      return <NoteBody config={tile.config} />
    case "metric_number":
    case "metric_chart":
    case "metric_funnel":
      return tile.config.metric ? (
        <MetricTileBody metric={tile.config.metric} type={tile.type} chart={tile.config.chart} />
      ) : (
        <p className="text-sm text-muted-foreground">Ustaw metrykę w ustawieniach kafelka.</p>
      )
  }
}
