"use client"

import { useQuery } from "@tanstack/react-query"
import { CheckCircle2, Filter, Target, Trophy, Users } from "lucide-react"

import api from "@/lib/api"
import { cn } from "@/lib/utils"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { ChampionsPodium } from "@/components/v2/gamification/ChampionsPodium"
import { ROLE_LABELS, useAuthStore } from "@/store/auth"

// ── Types ────────────────────────────────────────────────────────────────

interface RecruitmentReport {
  period: string
  funnel: {
    weryfikacje_count: number
    rekomendacje_count: number
    interviews_count: number
    placements_count: number
  }
  funnel_efficiency: {
    weryfikacje_to_rekomendacje: number
    rekomendacje_to_interviews: number
    interviews_to_placements: number
  }
  per_recruiter: Array<{
    user_id: number
    user_name: string
    weryfikacje: number
    rekomendacje: number
    interviews: number
    placements: number
    hit_ratio: number
  }>
  top3_liga_mistrzow: RecruitmentReport["per_recruiter"]
}

interface CompetitionResponse {
  type: string
  period: string
  top3: Array<{
    rank: number
    user_id: number
    name: string
    metric_value: number
    hit_ratio?: number | null
    prize_pln?: number
  }>
  target_pct?: number | null
}

interface MyPositionResponse {
  type: string
  period: string
  rank: number | null
  me: {
    user_id: number
    name: string
    metric_value: number
  } | null
  context: Array<{
    rank: number
    user_id: number
    name: string
    metric_value: number
  }>
  total: number
}

// ── KPI card (copy z DL panel) ──────────────────────────────────────────

function KpiCard({
  title,
  value,
  subtitle,
  icon: Icon,
  accent,
}: {
  title: string
  value: React.ReactNode
  subtitle?: string
  icon: React.ComponentType<{ className?: string }>
  accent?: "green" | "amber" | "default"
}) {
  const accentClass =
    accent === "green"
      ? "text-[#1d5e31]"
      : accent === "amber"
      ? "text-amber-600"
      : "text-[hsl(var(--text-title))]"
  return (
    <Card>
      <div className="flex items-start justify-between gap-2 mb-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[hsl(var(--text-muted))]">
          {title}
        </p>
        <span className="inline-flex items-center justify-center h-8 w-8 rounded-v2-s bg-[hsl(var(--accent-soft))] text-[hsl(var(--accent))]">
          <Icon className="h-4 w-4" />
        </span>
      </div>
      <div className={cn("font-display text-3xl font-extrabold tracking-[-0.02em] leading-none", accentClass)}>
        {value}
      </div>
      {subtitle && <p className="text-xs text-[hsl(var(--text-muted))] mt-2">{subtitle}</p>}
    </Card>
  )
}

// ── Page ────────────────────────────────────────────────────────────────

export default function RecruiterDashboard() {
  const user = useAuthStore((s) => s.user)
  const hydrated = useAuthStore((s) => s.hydrated)

  const allowedRoles = ["sourcer", "tac", "recruiter"] as const
  const isAllowed = !!user && (allowedRoles as readonly string[]).includes(user.role)

  const { data: report } = useQuery<RecruitmentReport>({
    queryKey: ["report-recruitment", "month"],
    queryFn: () =>
      api.get("/api/reports/recruitment?period=month").then((r) => r.data),
    enabled: hydrated && isAllowed,
    staleTime: 5 * 60 * 1000,
  })

  const myStats = report?.per_recruiter.find((r) => r.user_id === user?.id)

  const { data: quarterChampions } = useQuery<CompetitionResponse>({
    queryKey: ["competitions-current", "quarterly_champions_recruiter"],
    queryFn: () =>
      api
        .get("/api/competitions/current?type=quarterly_champions_recruiter")
        .then((r) => r.data),
    enabled: hydrated && isAllowed,
    staleTime: 5 * 60 * 1000,
  })

  const { data: hallOfFame } = useQuery<CompetitionResponse>({
    queryKey: ["competitions-current", "hall_of_fame"],
    queryFn: () =>
      api.get("/api/competitions/current?type=hall_of_fame").then((r) => r.data),
    enabled: hydrated && isAllowed,
    staleTime: 30 * 60 * 1000,
  })

  const { data: myPlacementsPosition } = useQuery<MyPositionResponse>({
    queryKey: ["my-competition-position", "monthly_placements"],
    queryFn: () =>
      api
        .get("/api/competitions/my-position?type=monthly_placements")
        .then((r) => r.data),
    enabled: hydrated && isAllowed,
    staleTime: 5 * 60 * 1000,
  })

  const { data: myRecPosition } = useQuery<MyPositionResponse>({
    queryKey: ["my-competition-position", "monthly_recommendations"],
    queryFn: () =>
      api
        .get("/api/competitions/my-position?type=monthly_recommendations")
        .then((r) => r.data),
    enabled: hydrated && isAllowed,
    staleTime: 5 * 60 * 1000,
  })

  if (!hydrated) {
    return <div className="p-6 text-[hsl(var(--text-muted))]">Ładowanie…</div>
  }

  if (!user || !isAllowed) {
    return (
      <div className="p-6">
        <Card>
          <CardHeader>
            <CardTitle>Brak dostępu</CardTitle>
            <CardDescription>
              Panel dla ról: sourcer, TAC, rekruter. Twoja rola:{" "}
              {user ? ROLE_LABELS[user.role] : "—"}.
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    )
  }

  const qualityScore =
    myStats && myStats.rekomendacje
      ? ((myStats.interviews / myStats.rekomendacje) * 100).toFixed(1)
      : "0.0"
  const placementConv =
    myStats && myStats.interviews
      ? ((myStats.placements / myStats.interviews) * 100).toFixed(1)
      : "0.0"

  return (
    <div className="max-w-[1400px] mx-auto space-y-6 p-4 md:p-6">
      {/* Hero */}
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[hsl(var(--accent))]">
          Panel {ROLE_LABELS[user.role]} · bieżący miesiąc
        </p>
        <h1 className="font-display text-3xl md:text-4xl font-extrabold tracking-[-0.025em] text-[hsl(var(--text-title))] mt-1">
          Cześć, {user.name.split(" ")[0]}
        </h1>
        <p className="text-sm text-[hsl(var(--text-muted))] mt-1">
          Twoje KPI body leasing + pozycja w konkursach.
        </p>
      </div>

      {/* KPI cards */}
      <section className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard
          title="Weryfikacje"
          value={myStats?.weryfikacje ?? 0}
          subtitle="CV przesortowane"
          icon={Filter}
        />
        <KpiCard
          title="Rekomendacje"
          value={myStats?.rekomendacje ?? 0}
          subtitle="do klienta"
          icon={Users}
        />
        <KpiCard
          title="Interviews (klient)"
          value={myStats?.interviews ?? 0}
          subtitle={`quality score: ${qualityScore}%`}
          icon={CheckCircle2}
        />
        <KpiCard
          title="Placements"
          value={myStats?.placements ?? 0}
          subtitle={`hit ratio: ${(myStats?.hit_ratio ?? 0).toFixed(1)}%`}
          icon={Target}
          accent="green"
        />
      </section>

      {/* Lejek konwersji */}
      <section className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardHeader>
            <CardDescription>Weryfikacja → Rekomendacja</CardDescription>
            <CardTitle className="font-display text-2xl">
              {qualityScore}%
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>Rekomendacja → Interview u klienta</CardDescription>
            <CardTitle className="font-display text-2xl">
              {myStats && myStats.rekomendacje
                ? ((myStats.interviews / myStats.rekomendacje) * 100).toFixed(1)
                : "0.0"}
              %
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>Interview → Placement</CardDescription>
            <CardTitle className="font-display text-2xl">
              {placementConv}%
            </CardTitle>
          </CardHeader>
        </Card>
      </section>

      {/* Moja pozycja w wyścigach + Liga Mistrzów */}
      <section className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Trophy className="h-4 w-4 text-amber-500" />
              <CardTitle>Wyścig: placements</CardTitle>
            </div>
          </CardHeader>
          <CardContent>
            <p className="font-display text-3xl font-extrabold text-[hsl(var(--text-title))]">
              #{myPlacementsPosition?.rank ?? "—"}
            </p>
            <p className="text-xs text-[hsl(var(--text-muted))] mt-1">
              {myPlacementsPosition?.me?.metric_value ?? 0} placementów ·{" "}
              {myPlacementsPosition?.total ?? 0} osób w rankingu
            </p>
            {myPlacementsPosition?.context && myPlacementsPosition.context.length > 0 && (
              <div className="mt-4 space-y-1.5 text-sm">
                {myPlacementsPosition.context.map((c) => (
                  <div
                    key={c.user_id}
                    className={cn(
                      "flex items-center justify-between py-1 px-2 rounded-v2-s",
                      c.user_id === user.id &&
                        "bg-[hsl(var(--accent-soft))] font-semibold",
                    )}
                  >
                    <span>
                      #{c.rank} {c.name}
                    </span>
                    <span className="tabular-nums">{c.metric_value}</span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Trophy className="h-4 w-4 text-amber-500" />
              <CardTitle>Wyścig: rekomendacje</CardTitle>
            </div>
          </CardHeader>
          <CardContent>
            <p className="font-display text-3xl font-extrabold text-[hsl(var(--text-title))]">
              #{myRecPosition?.rank ?? "—"}
            </p>
            <p className="text-xs text-[hsl(var(--text-muted))] mt-1">
              {myRecPosition?.me?.metric_value ?? 0} rekomendacji ·{" "}
              {myRecPosition?.total ?? 0} osób w rankingu
            </p>
            {myRecPosition?.context && myRecPosition.context.length > 0 && (
              <div className="mt-4 space-y-1.5 text-sm">
                {myRecPosition.context.map((c) => (
                  <div
                    key={c.user_id}
                    className={cn(
                      "flex items-center justify-between py-1 px-2 rounded-v2-s",
                      c.user_id === user.id &&
                        "bg-[hsl(var(--accent-soft))] font-semibold",
                    )}
                  >
                    <span>
                      #{c.rank} {c.name}
                    </span>
                    <span className="tabular-nums">{c.metric_value}</span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <ChampionsPodium
          title="Liga Mistrzów Q"
          subtitle="Kwartalni zwycięzcy (rekrutacja)"
          period={quarterChampions?.period ?? ""}
          top3={quarterChampions?.top3 ?? []}
          metricLabel="placementów"
          highlightUserId={user.id}
        />
      </section>

      {/* Hall of Fame */}
      {hallOfFame?.top3 && hallOfFame.top3.length > 0 && (
        <section>
          <ChampionsPodium
            title="Hall of Fame"
            subtitle="Wszech czasów TOP 3 po placementach"
            period="all time"
            top3={hallOfFame.top3}
            metricLabel="placementów all-time"
            highlightUserId={user.id}
          />
        </section>
      )}

      {/* Moja tabela vs zespół */}
      <Card>
        <CardHeader>
          <CardTitle>Zespół (bieżący miesiąc)</CardTitle>
          <CardDescription>Ranking po placementach</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-[hsl(var(--border-subtle))]">
                <tr>
                  <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-[hsl(var(--text-muted))] px-3 py-2 w-12">
                    #
                  </th>
                  <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-[hsl(var(--text-muted))] px-3 py-2">
                    Rekruter
                  </th>
                  <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-[hsl(var(--text-muted))] px-3 py-2">
                    Weryfikacje
                  </th>
                  <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-[hsl(var(--text-muted))] px-3 py-2">
                    Rekomendacje
                  </th>
                  <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-[hsl(var(--text-muted))] px-3 py-2">
                    Interviews
                  </th>
                  <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-[hsl(var(--text-muted))] px-3 py-2">
                    Placements
                  </th>
                  <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-[hsl(var(--text-muted))] px-3 py-2">
                    Hit %
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[hsl(var(--border-subtle))]">
                {(report?.per_recruiter ?? []).map((r, idx) => {
                  const isMe = r.user_id === user.id
                  return (
                    <tr
                      key={r.user_id}
                      className={cn(
                        "hover:bg-[hsl(var(--accent-soft))]/40 transition-colors",
                        isMe && "bg-[hsl(var(--accent-soft))]/60 font-semibold",
                      )}
                    >
                      <td className="px-3 py-2 text-[hsl(var(--text-muted))]">
                        {idx + 1}
                      </td>
                      <td className="px-3 py-2">
                        {r.user_name}
                        {isMe && (
                          <Badge variant="soft" size="sm" className="ml-2">
                            Ja
                          </Badge>
                        )}
                      </td>
                      <td className="px-3 py-2 tabular-nums">{r.weryfikacje}</td>
                      <td className="px-3 py-2 tabular-nums">{r.rekomendacje}</td>
                      <td className="px-3 py-2 tabular-nums">{r.interviews}</td>
                      <td className="px-3 py-2 tabular-nums font-semibold">
                        {r.placements}
                      </td>
                      <td className="px-3 py-2 tabular-nums">
                        {r.hit_ratio.toFixed(1)}%
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            {(!report?.per_recruiter || report.per_recruiter.length === 0) && (
              <p className="text-center text-sm text-[hsl(var(--text-muted))] py-6">
                Brak danych w tym miesiącu.
              </p>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
