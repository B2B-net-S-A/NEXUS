import { Briefcase, Target, TrendingUp, Users } from "lucide-react"

import { PastelKpi } from "./PastelKpi"
import type { DlOverall, DlRow, DlScope } from "./types"

interface DlKpiRowProps {
  scope: DlScope
  /** Personal row (DL, when scope=me). */
  me?: DlRow
  /** Personal rank in DL leaderboard (when scope=me). */
  rank?: number | null
  totalDls?: number
  /** Team overall (always present — used for target threshold + team headline when scope=team). */
  teamOverall?: DlOverall
}

export function DlKpiRow({
  scope,
  me,
  rank,
  totalDls,
  teamOverall,
}: DlKpiRowProps) {
  const targetPct = teamOverall?.hit_ratio_target_pct ?? 30

  if (scope === "me" && me) {
    return (
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <PastelKpi
          title="Moje zamknięte zapytania"
          value={me.total_requests}
          subtitle={`+${me.open_requests} otwartych`}
          icon={Briefcase}
          color="slate"
        />
        <PastelKpi
          title="Moje placements"
          value={me.placements}
          subtitle={`${me.total_vacancies} wakatów łącznie`}
          icon={Target}
          color="amber"
        />
        <PastelKpi
          title="Mój Hit Ratio"
          value={`${me.hit_ratio.toFixed(1)}%`}
          subtitle={`cel: ${targetPct}%`}
          icon={TrendingUp}
          color="purple"
        />
        <PastelKpi
          title="Mój ranking"
          value={
            <>
              {rank ?? "—"}
              <span className="text-muted-foreground text-2xl">
                /{totalDls ?? 0}
              </span>
            </>
          }
          subtitle={`Fill Rate: ${me.fill_rate.toFixed(1)}%`}
          icon={Users}
          color="emerald"
        />
      </div>
    )
  }

  const ov = teamOverall
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      <PastelKpi
        title="Zamknięte zapytania"
        value={ov?.total_requests ?? 0}
        subtitle={`+${ov?.total_open_requests ?? 0} otwartych`}
        icon={Briefcase}
        color="slate"
      />
      <PastelKpi
        title="Placements"
        value={ov?.total_placements ?? 0}
        subtitle={`${ov?.total_vacancies ?? 0} wakatów łącznie`}
        icon={Target}
        color="amber"
      />
      <PastelKpi
        title="Średni Hit Ratio"
        value={`${(ov?.avg_hit_ratio ?? 0).toFixed(1)}%`}
        subtitle={`cel: ${targetPct}%`}
        icon={TrendingUp}
        color="purple"
      />
      <PastelKpi
        title={`Osiąga target (${targetPct}%)`}
        value={
          <>
            {ov?.target_count ?? 0}
            <span className="text-muted-foreground text-2xl">
              /{ov?.dl_count ?? 0}
            </span>
          </>
        }
        subtitle={`Fill Rate śr.: ${(ov?.avg_fill_rate ?? 0).toFixed(1)}%`}
        icon={Users}
        color="emerald"
      />
    </div>
  )
}
