"use client"

import { Medal } from "lucide-react"

import { Podium } from "@/components/ds"
import { HeroLigaMistrzow } from "@/components/v2/gamification/HeroLigaMistrzow"
import type { HeroPodiumEntry } from "@/components/v2/gamification/HeroLigaMistrzow"
import { RaceCard } from "@/components/v2/gamification/RaceCard"
import type {
  CompetitionRankingEntry,
  RecruitmentHallOfFame,
  RecruitmentMonthlyRaces,
  RecruitmentQuarterlyLeague,
} from "@/lib/dashboard-v2-api"

// Blok rywalizacji sekcji „Statystyki rekrutacji" — czysta kompozycja
// gotowych rendererów (HeroLigaMistrzow / RaceCard / ds Podium) z danych
// composite'u. Rywalizacje NIE podążają za okresem sekcji (liga = bieżący
// kwartał, wyścigi = bieżący miesiąc, HoF = all-time) — reguły konkursów.

function toHeroEntry(entry: CompetitionRankingEntry): HeroPodiumEntry {
  return {
    rank: entry.rank,
    user_id: entry.user_id,
    name: entry.name,
    metric_value: entry.metric_value,
    hit_ratio: entry.hit_ratio,
    prize_pln: entry.prize_pln ?? undefined,
    role: entry.role ?? undefined,
    placements: entry.placements ?? undefined,
    interviews: entry.interviews ?? undefined,
    recommendations: entry.recommendations ?? undefined,
    excluded: entry.excluded,
  }
}

function toRaceEntry(entry: CompetitionRankingEntry) {
  return {
    rank: entry.rank,
    user_id: entry.user_id,
    name: entry.name,
    metric_value: entry.metric_value,
    role: entry.role ?? undefined,
    excluded: entry.excluded,
    extras: {
      verifications: entry.verifications,
      precision_pct: entry.precision_pct,
      required_verifications: entry.required_verifications,
      qualified: entry.qualified,
      disqualification_reasons: entry.disqualification_reasons,
    },
  }
}

export function RecruitmentCompetitions({
  league,
  races,
  hallOfFame,
  highlightUserId,
}: {
  league: RecruitmentQuarterlyLeague | null
  races: RecruitmentMonthlyRaces | null
  hallOfFame: RecruitmentHallOfFame | null
  highlightUserId: number | null
}) {
  const prizes: Record<number, number> = {}
  for (const [rank, amount] of Object.entries(league?.prizes_pln ?? {})) {
    prizes[Number(rank)] = amount
  }
  const formula = league?.points_formula

  return (
    <div className="space-y-4">
      {league ? (
        <HeroLigaMistrzow
          title="Liga Mistrzów"
          period={league.period}
          daysRemaining={league.days_remaining}
          top3={league.top3.map(toHeroEntry)}
          fullRanking={league.full_ranking.map(toHeroEntry)}
          quarterlyPrizes={prizes}
          metricLabel="pkt"
          metricUnit="pkt"
          pointsFormula={
            formula
              ? {
                  placement: formula.placement ?? 0,
                  interview: formula.interview ?? 0,
                  recommendation: formula.recommendation ?? 0,
                }
              : null
          }
          requirement={league.requirement}
          highlightUserId={highlightUserId}
        />
      ) : (
        <UnavailableCard label="Liga Mistrzów" />
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {races ? (
          <>
            <RaceCard
              title="Wyścig Rekomendacji"
              period={races.period}
              daysRemaining={races.days_remaining}
              variant="blue"
              prize={{
                amount_pln: races.prize_amount_pln,
                name: races.prize_name,
              }}
              requirements={races.recommendations.requirements}
              ranking={races.recommendations.ranking.map(toRaceEntry)}
              metricSuffix="rek."
              highlightUserId={highlightUserId}
            />
            <RaceCard
              title="Wyścig Placementów"
              period={races.period}
              daysRemaining={races.days_remaining}
              variant="green"
              prize={{
                amount_pln: races.prize_amount_pln,
                name: races.prize_name,
              }}
              requirements={races.placements.requirements}
              ranking={races.placements.ranking.map(toRaceEntry)}
              metricSuffix="plac."
              highlightUserId={highlightUserId}
            />
          </>
        ) : (
          <UnavailableCard label="Wyścigi miesięczne" className="lg:col-span-2" />
        )}
      </div>

      {hallOfFame ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <Podium
            title="Hall of Fame — placementy all-time"
            entries={hallOfFame.all_time.slice(0, 3).map((entry) => ({
              rank: entry.rank,
              name: entry.name,
              points: entry.metric_value,
              me: entry.user_id === highlightUserId,
            }))}
          />
          <div className="rounded-xl border border-border bg-card p-4">
            <div className="mb-3 flex items-center gap-2">
              <Medal className="h-4 w-4 text-primary" />
              <h3 className="text-sm font-semibold text-foreground">
                Zamrożone podia ligi
              </h3>
            </div>
            {hallOfFame.history.length === 0 ? (
              <p className="py-4 text-center text-xs text-muted-foreground">
                Jeszcze żaden kwartał nie został zamknięty.
              </p>
            ) : (
              <ul className="space-y-3">
                {hallOfFame.history.map((period) => (
                  <li key={period.period}>
                    <p className="text-xs font-semibold text-muted-foreground">
                      {period.period}
                    </p>
                    <ul className="mt-1 space-y-0.5">
                      {period.top3.map((winner) => (
                        <li
                          key={`${period.period}-${winner.rank}`}
                          className="flex items-center justify-between text-sm"
                        >
                          <span className="text-foreground">
                            {winner.rank}. {winner.name}
                          </span>
                          <span className="tabular-nums text-muted-foreground">
                            {winner.points ?? winner.metric_value ?? "—"} pkt
                            {winner.prize_pln
                              ? ` · ${winner.prize_pln} PLN`
                              : ""}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      ) : (
        <UnavailableCard label="Hall of Fame" />
      )}
    </div>
  )
}

function UnavailableCard({
  label,
  className,
}: {
  label: string
  className?: string
}) {
  return (
    <div
      className={`rounded-xl border border-dashed border-border bg-card px-4 py-6 text-center text-xs text-muted-foreground ${className ?? ""}`}
    >
      {label}: dane chwilowo niedostępne (to NIE jest zero).
    </div>
  )
}

export default RecruitmentCompetitions
