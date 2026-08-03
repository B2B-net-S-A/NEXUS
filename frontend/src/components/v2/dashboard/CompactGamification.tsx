"use client"

import { useQuery } from "@tanstack/react-query"
import { Trophy } from "lucide-react"

import api from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useAuthStore } from "@/store/auth"

type CompetitionType =
  | "quarterly_champions_dl"
  | "quarterly_champions_recruiter"

interface RankingEntry {
  rank: number
  user_id: number
  name: string
  metric_value: number
}

interface CompetitionResponse {
  period: string
  top3: RankingEntry[]
}

const LABELS: Record<CompetitionType, string> = {
  quarterly_champions_dl: "Delivery",
  quarterly_champions_recruiter: "Rekrutacja",
}

function CompactRanking({ type }: { type: CompetitionType }) {
  const user = useAuthStore((state) => state.user)
  const scopeCacheKey = user?.data_scope
    ? JSON.stringify({
        kind: user.data_scope.kind,
        userId: user.data_scope.user_id,
        clientIds: [...user.data_scope.allowed_client_ids].sort((a, b) => a - b),
        tacUserIds: [...user.data_scope.allowed_tac_user_ids].sort(
          (a, b) => a - b,
        ),
        operatorUserIds: [...user.data_scope.allowed_operator_user_ids].sort(
          (a, b) => a - b,
        ),
        clientTacPairs: [
          ...(user.data_scope.allowed_client_tac_pairs ?? []),
        ].sort(
          (a, b) =>
            a.client_id - b.client_id || a.tac_user_id - b.tac_user_id,
        ),
      })
    : null
  const capabilityCacheKey = Array.from(
    new Set([
      ...(user?.capabilities ?? []),
      ...(user?.analytics_capabilities ?? []),
    ]),
  )
    .sort()
    .join(",")
  const query = useQuery<CompetitionResponse>({
    queryKey: [
      "dashboard-compact-competition",
      type,
      user?.id ?? null,
      user?.authorization_version ?? null,
      scopeCacheKey,
      capabilityCacheKey,
    ],
    queryFn: () =>
      api
        .get<CompetitionResponse>(`/api/competitions/current?type=${type}`)
        .then((response) => response.data),
    enabled: Boolean(user),
    staleTime: 5 * 60_000,
  })

  if (query.isError) return null

  return (
    <Card className="min-w-0">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between gap-3 text-sm">
          <span className="flex items-center gap-2">
            <Trophy className="h-4 w-4 text-primary" aria-hidden />
            {LABELS[type]}
          </span>
          {query.data?.period ? (
            <Badge variant="neutral" size="sm">
              {query.data.period}
            </Badge>
          ) : null}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {query.isLoading ? (
          <p className="text-xs text-muted-foreground">Ładowanie rankingu…</p>
        ) : query.data?.top3.length ? (
          <ol className="flex flex-wrap gap-x-5 gap-y-2">
            {query.data.top3.map((entry) => (
              <li
                key={entry.user_id}
                className="flex min-w-0 items-center gap-2 text-sm"
              >
                <span className="font-semibold tabular-nums text-primary">
                  {entry.rank}.
                </span>
                <span className="truncate text-foreground">{entry.name}</span>
                <span className="tabular-nums text-muted-foreground">
                  {entry.metric_value}
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-xs text-muted-foreground">
            Ranking pojawi się po zebraniu wyników.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

export function CompactGamification({
  types,
}: {
  types: CompetitionType[]
}) {
  return (
    <section aria-labelledby="compact-gamification-title" className="space-y-3">
      <div>
        <h2
          id="compact-gamification-title"
          className="text-sm font-semibold text-foreground"
        >
          Wyniki zespołu
        </h2>
        <p className="text-xs text-muted-foreground">
          Skrócony ranking kwartalny; pełna analiza pozostaje w Insights.
        </p>
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        {types.map((type) => (
          <CompactRanking key={type} type={type} />
        ))}
      </div>
    </section>
  )
}
