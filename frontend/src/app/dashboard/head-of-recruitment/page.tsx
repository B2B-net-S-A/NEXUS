"use client"

import { useQuery } from "@tanstack/react-query"
import { Crown, Link2, Trophy, Users, UserSquare2 } from "lucide-react"

import api from "@/lib/api"
import { cn } from "@/lib/utils"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { ChampionsPodium } from "@/components/v2/gamification/ChampionsPodium"
import { useAuthStore } from "@/store/auth"

// ── Types ──────────────────────────────────────────────────────────────

interface CategoryBrief {
  id: number
  slug: string
  name_pl: string
  name_en: string
}

interface SourcerInCategory {
  user_id: number
  name: string
  email?: string | null
  priority: number | null
  is_primary: boolean
}

interface SourcerCategoryRow {
  category: CategoryBrief
  first_priority: SourcerInCategory[]
  second_priority: SourcerInCategory[]
}

interface DlWithTacsRow {
  delivery_lead: { id: number; name: string }
  tacs: Array<{
    user_id: number
    name: string
    linkedin_farming: CategoryBrief[]
  }>
}

interface DlClientsRow {
  delivery_lead: { id: number; name: string }
  clients: Array<{ id: number; name: string; is_head: boolean }>
}

interface SummaryResponse {
  categories: SourcerCategoryRow[]
  delivery_leads: DlWithTacsRow[]
  dl_clients: DlClientsRow[]
  totals: Record<string, number>
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

// ── Stat card ────────────────────────────────────────────────────────

function StatCard({
  title,
  value,
  icon: Icon,
  subtitle,
}: {
  title: string
  value: React.ReactNode
  icon: React.ComponentType<{ className?: string }>
  subtitle?: string
}) {
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
      <div className="font-display text-3xl font-extrabold tracking-[-0.02em] text-[hsl(var(--text-title))] leading-none">
        {value}
      </div>
      {subtitle && <p className="text-xs text-[hsl(var(--text-muted))] mt-2">{subtitle}</p>}
    </Card>
  )
}

// ── Matrix: Sourcerzy × Kategorie ────────────────────────────────────

function SourcerCategoryMatrix({ rows }: { rows: SourcerCategoryRow[] }) {
  if (rows.length === 0) {
    return (
      <p className="text-sm text-[hsl(var(--text-muted))] py-4">
        Brak kategorii kompetencji. Dodaj je w /settings (admin).
      </p>
    )
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="border-b border-[hsl(var(--border-subtle))]">
          <tr>
            <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-[hsl(var(--text-muted))] px-3 py-2">
              Kategoria kompetencji
            </th>
            <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-[hsl(var(--text-muted))] px-3 py-2">
              1st priority
            </th>
            <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-[hsl(var(--text-muted))] px-3 py-2">
              2nd priority
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[hsl(var(--border-subtle))]">
          {rows.map((row) => (
            <tr key={row.category.id}>
              <td className="px-3 py-2 font-semibold text-[hsl(var(--text-title))]">
                {row.category.name_pl}
                <span className="text-[11px] text-[hsl(var(--text-muted))] ml-2">
                  ({row.category.slug})
                </span>
              </td>
              <td className="px-3 py-2">
                <div className="flex flex-wrap gap-1.5">
                  {row.first_priority.length === 0 && (
                    <span className="text-[hsl(var(--text-muted))] text-xs">—</span>
                  )}
                  {row.first_priority.map((s) => (
                    <Badge key={s.user_id} variant="soft" size="sm">
                      {s.name}
                    </Badge>
                  ))}
                </div>
              </td>
              <td className="px-3 py-2">
                <div className="flex flex-wrap gap-1.5">
                  {row.second_priority.length === 0 && (
                    <span className="text-[hsl(var(--text-muted))] text-xs">—</span>
                  )}
                  {row.second_priority.map((s) => (
                    <Badge key={s.user_id} size="sm">
                      {s.name}
                    </Badge>
                  ))}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Matrix: TAC → DL + LinkedIn farming ──────────────────────────────

function TacDlMatrix({ rows }: { rows: DlWithTacsRow[] }) {
  if (rows.length === 0) {
    return (
      <p className="text-sm text-[hsl(var(--text-muted))] py-4">
        Brak przypisań TAC → DL.
      </p>
    )
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="border-b border-[hsl(var(--border-subtle))]">
          <tr>
            <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-[hsl(var(--text-muted))] px-3 py-2">
              Delivery Lead
            </th>
            <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-[hsl(var(--text-muted))] px-3 py-2">
              TAC
            </th>
            <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-[hsl(var(--text-muted))] px-3 py-2">
              LinkedIn farming
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[hsl(var(--border-subtle))]">
          {rows.map((row) => {
            if (row.tacs.length === 0) {
              return (
                <tr key={row.delivery_lead.id}>
                  <td className="px-3 py-2 font-semibold text-[hsl(var(--text-title))]">
                    {row.delivery_lead.name}
                  </td>
                  <td colSpan={2} className="px-3 py-2 text-[hsl(var(--text-muted))] text-xs italic">
                    brak przypisanych TAC-ów
                  </td>
                </tr>
              )
            }
            return row.tacs.map((tac, tIdx) => (
              <tr key={`${row.delivery_lead.id}-${tac.user_id}`}>
                {tIdx === 0 && (
                  <td
                    rowSpan={row.tacs.length}
                    className="px-3 py-2 font-semibold text-[hsl(var(--text-title))] align-top border-r border-[hsl(var(--border-subtle))]"
                  >
                    {row.delivery_lead.name}
                  </td>
                )}
                <td className="px-3 py-2">{tac.name}</td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-1.5">
                    {tac.linkedin_farming.length === 0 && (
                      <span className="text-[hsl(var(--text-muted))] text-xs">—</span>
                    )}
                    {tac.linkedin_farming.map((c) => (
                      <Badge key={c.id} variant="soft" size="sm">
                        {c.name_pl}
                      </Badge>
                    ))}
                  </div>
                </td>
              </tr>
            ))
          })}
        </tbody>
      </table>
    </div>
  )
}

// ── Matrix: DL → Clients ─────────────────────────────────────────────

function DlClientsMatrix({ rows }: { rows: DlClientsRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="border-b border-[hsl(var(--border-subtle))]">
          <tr>
            <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-[hsl(var(--text-muted))] px-3 py-2">
              Delivery Lead
            </th>
            <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-[hsl(var(--text-muted))] px-3 py-2">
              Klienci
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[hsl(var(--border-subtle))]">
          {rows.map((row) => (
            <tr key={row.delivery_lead.id}>
              <td className="px-3 py-2 font-semibold text-[hsl(var(--text-title))] align-top">
                {row.delivery_lead.name}
              </td>
              <td className="px-3 py-2">
                {row.clients.length === 0 && (
                  <span className="text-[hsl(var(--text-muted))] text-xs">—</span>
                )}
                <div className="flex flex-wrap gap-1.5">
                  {row.clients.map((c) => (
                    <Badge
                      key={c.id}
                      variant={c.is_head ? "burgundy" : "soft"}
                      size="sm"
                      className={cn(c.is_head && "gap-1")}
                    >
                      {c.is_head && <Crown className="h-3 w-3" />}
                      {c.name}
                    </Badge>
                  ))}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && (
        <p className="text-center text-sm text-[hsl(var(--text-muted))] py-6">
          Brak przypisań DL → klient.
        </p>
      )}
    </div>
  )
}

// ── Page ────────────────────────────────────────────────────────────

export default function HeadOfRecruitmentDashboard() {
  const user = useAuthStore((s) => s.user)
  const hydrated = useAuthStore((s) => s.hydrated)

  const isAllowed = !!user && (user.role === "head_of_recruitment" || user.role === "admin")

  const { data: summary } = useQuery<SummaryResponse>({
    queryKey: ["team-structure-summary"],
    queryFn: () =>
      api.get("/api/team-structure/summary").then((r) => r.data),
    enabled: hydrated && isAllowed,
    staleTime: 5 * 60 * 1000,
  })

  const { data: dlChampions } = useQuery<CompetitionResponse>({
    queryKey: ["competitions-current", "quarterly_champions_dl"],
    queryFn: () =>
      api
        .get("/api/competitions/current?type=quarterly_champions_dl")
        .then((r) => r.data),
    enabled: hydrated && isAllowed,
    staleTime: 5 * 60 * 1000,
  })

  const { data: recruiterChampions } = useQuery<CompetitionResponse>({
    queryKey: ["competitions-current", "quarterly_champions_recruiter"],
    queryFn: () =>
      api
        .get("/api/competitions/current?type=quarterly_champions_recruiter")
        .then((r) => r.data),
    enabled: hydrated && isAllowed,
    staleTime: 5 * 60 * 1000,
  })

  if (!hydrated) {
    return <div className="p-6 text-[hsl(var(--text-muted))]">Ładowanie…</div>
  }

  if (!isAllowed) {
    return (
      <div className="p-6">
        <Card>
          <CardHeader>
            <CardTitle>Brak dostępu</CardTitle>
            <CardDescription>
              Panel dla roli Head of Recruitment lub Admin.
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    )
  }

  const t = summary?.totals ?? {}

  return (
    <div className="max-w-[1400px] mx-auto space-y-6 p-4 md:p-6">
      {/* Hero */}
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[hsl(var(--accent))]">
          Panel Head of Recruitment
        </p>
        <h1 className="font-display text-3xl md:text-4xl font-extrabold tracking-[-0.025em] text-[hsl(var(--text-title))] mt-1">
          Struktura zespołu rekrutacji
        </h1>
        <p className="text-sm text-[hsl(var(--text-muted))] mt-1">
          Macierze przypisań + aktualne wyniki konkursów.
        </p>
      </div>

      {/* Stats */}
      <section className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <StatCard title="Sourcerzy" value={t.sourcers ?? 0} icon={Users} />
        <StatCard title="TAC-y" value={t.tacs ?? 0} icon={Users} />
        <StatCard title="Rekruterzy" value={t.recruiters ?? 0} icon={Users} />
        <StatCard
          title="Delivery Leadów"
          value={t.delivery_leads ?? 0}
          icon={UserSquare2}
        />
        <StatCard title="Klienci" value={t.clients ?? 0} icon={Link2} />
      </section>

      {/* Matrix: Sourcerzy × Kategorie */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Users className="h-4 w-4 text-[hsl(var(--accent))]" />
            <CardTitle>Sourcerzy × Kategorie kompetencji</CardTitle>
          </div>
          <CardDescription>
            1st priority = główna odpowiedzialność; 2nd priority = wsparcie.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <SourcerCategoryMatrix rows={summary?.categories ?? []} />
        </CardContent>
      </Card>

      {/* Matrix: TAC → DL */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Link2 className="h-4 w-4 text-[hsl(var(--accent))]" />
            <CardTitle>TAC → Delivery Lead + LinkedIn farming</CardTitle>
          </div>
          <CardDescription>
            Każdy TAC raportuje do jednego DL. LinkedIn farming = kategorie na
            których TAC aktywnie pozyskuje kandydatów.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <TacDlMatrix rows={summary?.delivery_leads ?? []} />
        </CardContent>
      </Card>

      {/* Matrix: DL → Clients */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Crown className="h-4 w-4 text-amber-500" />
            <CardTitle>Delivery Lead → Klienci</CardTitle>
          </div>
          <CardDescription>
            Korona = główny opiekun (is_head). Reszta = wsparcie.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <DlClientsMatrix rows={summary?.dl_clients ?? []} />
        </CardContent>
      </Card>

      {/* Podia — DL + Recruiter */}
      <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChampionsPodium
          title="Liga Mistrzów DL"
          subtitle="Kwartalny podium"
          period={dlChampions?.period ?? ""}
          top3={dlChampions?.top3 ?? []}
          metricLabel="placementów"
          targetPct={dlChampions?.target_pct ?? 30}
        />
        <ChampionsPodium
          title="Liga Mistrzów Rekrutacja"
          subtitle="Kwartalny podium (sourcer/TAC/rekruter)"
          period={recruiterChampions?.period ?? ""}
          top3={recruiterChampions?.top3 ?? []}
          metricLabel="placementów"
        />
      </section>

      {/* Shortcut */}
      <Card>
        <CardContent className="py-4">
          <p className="text-sm text-[hsl(var(--text-body))]">
            <Trophy className="inline h-4 w-4 mr-1 text-amber-500" />
            Chcesz zamknąć kwartał? Admin może zamrozić wyniki przez{" "}
            <code className="font-mono text-xs bg-[hsl(var(--accent-soft))] px-1.5 py-0.5 rounded">
              POST /api/competitions/freeze?type=...&period=...
            </code>
            . Snapshot zostanie zapisany do tabeli{" "}
            <code className="font-mono text-xs">competition_winners</code>.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
