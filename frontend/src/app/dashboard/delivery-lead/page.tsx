"use client"

import { useQuery } from "@tanstack/react-query"

import api from "@/lib/api"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { HeroLigaMistrzow } from "@/components/v2/gamification/HeroLigaMistrzow"
import { hasRole, useAuthStore } from "@/store/auth"

import { DeliveryTabs } from "./_components/DeliveryTabs"
import { DlClientsTable } from "./_components/DlClientsTable"
import { DlHeader } from "./_components/DlHeader"
import { DlKpiRow } from "./_components/DlKpiRow"
import { DlRanking } from "./_components/DlRanking"
import { DlTrendChart } from "./_components/DlTrendChart"
import { PendingVerificationsWidget } from "./_components/PendingVerificationsWidget"
import type {
  CompetitionResponse,
  DlClientsSummary,
  DlReport,
  DlScope,
  MyDlReport,
  TrendPoint,
} from "./_components/types"

export default function DeliveryLeadDashboard() {
  const user = useAuthStore((s) => s.user)
  const hydrated = useAuthStore((s) => s.hydrated)

  const isAllowed = hasRole(
    user,
    "delivery_lead",
    "admin",
    "head_of_recruitment",
  )
  const isMeDl =
    hasRole(user, "delivery_lead") &&
    !hasRole(user, "admin", "head_of_recruitment")
  const scope: DlScope = isMeDl ? "me" : "team"

  // Team-wide report. Used for: team scope view + DL ranking + target threshold.
  const { data: teamReport, refetch: refetchTeam } = useQuery<DlReport>({
    queryKey: ["report-delivery-leads", "month"],
    queryFn: () =>
      api.get("/api/reports/delivery-leads?period=month").then((r) => r.data),
    enabled: hydrated && isAllowed,
    staleTime: 5 * 60 * 1000,
  })

  // Personal report — only fetched for DL (endpoint is role-gated to delivery_lead).
  const { data: myReport, refetch: refetchMine } = useQuery<MyDlReport | null>({
    queryKey: ["my-delivery-lead", "month"],
    queryFn: async () => {
      if (!isMeDl) return null
      const r = await api.get("/api/reports/my-delivery-lead?period=month")
      return r.data
    },
    enabled: hydrated && isAllowed && isMeDl,
    staleTime: 5 * 60 * 1000,
  })

  // Personal 6m trend (DL only — endpoint requires dl_id).
  const { data: trendAll } = useQuery<{ trend: TrendPoint[] } | null>({
    queryKey: ["dl-trend-all", "6m"],
    queryFn: async () => {
      if (!user || !isMeDl) return null
      const r = await api.get(
        `/api/reports/delivery-leads/${user.id}/trend?months=6`,
      )
      return r.data
    },
    enabled: hydrated && isAllowed && isMeDl,
    staleTime: 5 * 60 * 1000,
  })

  const { data: champions, refetch: refetchChampions } =
    useQuery<CompetitionResponse>({
      queryKey: ["competitions-current", "quarterly_champions_dl"],
      queryFn: () =>
        api
          .get("/api/competitions/current?type=quarterly_champions_dl")
          .then((r) => r.data),
      enabled: hydrated && isAllowed,
      staleTime: 5 * 60 * 1000,
    })

  const { data: dlClients } = useQuery<DlClientsSummary[]>({
    queryKey: ["team-structure-dl-clients"],
    queryFn: () =>
      api.get("/api/team-structure/dl-clients").then((r) => r.data),
    enabled: hydrated && isAllowed,
    staleTime: 5 * 60 * 1000,
  })

  if (!hydrated) {
    return <div className="p-6 text-muted-foreground">Ładowanie…</div>
  }

  if (!isAllowed) {
    return (
      <div className="p-6">
        <Card>
          <CardHeader>
            <CardTitle>Brak dostępu</CardTitle>
            <CardDescription>
              Panel dla ról: Delivery Lead, Admin, Head of Recruitment.
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    )
  }

  const targetPct = teamReport?.overall.hit_ratio_target_pct ?? 30

  const handleRefresh = () => {
    refetchTeam()
    refetchChampions()
    if (isMeDl) refetchMine()
  }

  return (
    <div className="max-w-[1400px] mx-auto space-y-5 p-4 md:p-6">
      <DlHeader scope={scope} onRefresh={handleRefresh} />

      {/* Action-first widget: DL widzi tylko swoje (mine=true), HoR/admin widzi
          wszystkie pending verifications (oversight). */}
      <PendingVerificationsWidget mine={isMeDl} />

      <DlKpiRow
        scope={scope}
        me={myReport?.me}
        rank={myReport?.rank}
        totalDls={myReport?.total_dls}
        teamOverall={teamReport?.overall}
      />

      {champions && (
        <HeroLigaMistrzow
          title="Liga Mistrzów DL"
          period={champions.period}
          daysRemaining={champions.days_remaining ?? 0}
          top3={champions.top3}
          fullRanking={champions.full_ranking}
          quarterlyPrizes={
            champions.quarterly_prizes_pln
              ? Object.fromEntries(
                  Object.entries(champions.quarterly_prizes_pln).map(
                    ([k, v]) => [Number(k), v],
                  ),
                )
              : { 1: 5000, 2: 3000, 3: 2000 }
          }
          metricLabel="placementów"
          metricUnit=""
          requirement={champions.requirement}
          highlightUserId={isMeDl ? user?.id : null}
        />
      )}

      {isMeDl && trendAll?.trend && trendAll.trend.length > 0 && (
        <DlTrendChart trend={trendAll.trend} />
      )}

      {/* DL Hub tabs — personal scope only (DL). HoR/admin widzi team aggregat
          niżej (ranking + DL→klienci) z osobnymi narzędziami. */}
      {isMeDl && user && <DeliveryTabs userId={user.id} />}

      <Card>
        <CardHeader>
          <CardTitle>Ranking Delivery Leadów</CardTitle>
          <CardDescription>
            Kliknij nagłówek kolumny aby posortować. Korona oznacza osiągnięcie
            progu {targetPct}% hit ratio.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <DlRanking
            rows={teamReport?.per_dl ?? []}
            highlightUserId={user?.id}
            targetPct={targetPct}
          />
        </CardContent>
      </Card>

      <DlClientsTable rows={dlClients ?? []} />
    </div>
  )
}
