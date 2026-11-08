"use client"

// Kafelek „Odpowiedź klienta” dla Head of Recruitment i Delivery Leada (audyt 2,
// 08.11.2026): od CV do zatrudnienia mija 22,7 dnia, a pulpit nie pokazywał, który
// klient nie odpowiada. Delivery Lead widzi klientów ze swojego portfela (serwer).

import Link from "next/link"
import { useQuery } from "@tanstack/react-query"

import { Skeleton } from "@/components/ui/skeleton"
import { WidgetErrorBlock } from "@/components/v2/dashboard/WidgetState"
import {
  CLIENT_RESPONSE_QUERY_KEY,
  dateRangeLabel,
  fetchClientResponseBoard,
  pctLabel,
  workdaysLabel,
  type ClientResponseSummary,
  type FirstCvSummary,
} from "@/lib/client-response"
import { cn } from "@/lib/utils"

function ResponseStat({ response }: { response: ClientResponseSummary }) {
  const below =
    response.response_7d_pct !== null && response.response_7d_pct < response.target_pct
  return (
    <div className="min-w-0 rounded-lg border border-border bg-card p-3">
      <p className="text-xs text-muted-foreground">
        Odpowiedź klienta w {response.workdays} dni rob.
      </p>
      <p
        className={cn(
          "mt-1 text-2xl font-semibold tabular-nums",
          below ? "text-warning" : "text-foreground",
        )}
      >
        {pctLabel(response.response_7d_pct)}
      </p>
      <p className="mt-0.5 text-xs text-muted-foreground">
        {response.responded_7d} z {response.cohort_cv} CV wysłanych{" "}
        {dateRangeLabel(response.window_from, response.window_to)} · cel{" "}
        {response.target_pct}%
      </p>
    </div>
  )
}

function FirstCvStat({ firstCv }: { firstCv: FirstCvSummary }) {
  return (
    <div className="min-w-0 rounded-lg border border-border bg-card p-3">
      <p className="text-xs text-muted-foreground">Pierwsze CV po otwarciu</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-foreground">
        {workdaysLabel(firstCv.median_first_cv_workdays)}
      </p>
      <p className="mt-0.5 text-xs text-muted-foreground">
        mediana · {firstCv.sla_within_jobs} z {firstCv.sla_eligible_jobs} rekrutacji w{" "}
        {firstCv.sla_workdays} dni rob.
      </p>
    </div>
  )
}

export function ClientResponseTile() {
  const query = useQuery({
    queryKey: CLIENT_RESPONSE_QUERY_KEY,
    queryFn: fetchClientResponseBoard,
    staleTime: 5 * 60_000,
  })

  if (query.isPending) return <Skeleton className="h-full min-h-[48px] w-full" />
  if (query.isError) {
    return <WidgetErrorBlock error={query.error} onRetry={() => query.refetch()} />
  }

  const { response, first_cv: firstCv } = query.data
  return (
    <div className="flex h-full min-h-0 flex-col gap-3 text-sm">
      <div className="grid shrink-0 grid-cols-1 gap-3 sm:grid-cols-2">
        <ResponseStat response={response} />
        <FirstCvStat firstCv={firstCv} />
      </div>
      {response.clients.length === 0 ? (
        <p className="text-muted-foreground">Brak CV u klientów w tym okresie.</p>
      ) : (
        <div className="min-h-0 flex-1 overflow-auto">
          <table
            aria-label="Klienci: czekamy na odpowiedź"
            className="w-full border-collapse text-left"
          >
            <thead className="sticky top-0 bg-card">
              <tr className="border-b border-border text-xs text-muted-foreground">
                <th className="py-1.5 pr-3 font-medium">Klient</th>
                <th className="whitespace-nowrap py-1.5 pr-3 text-right font-medium">
                  CV w toku
                </th>
                <th className="whitespace-nowrap py-1.5 pr-3 text-right font-medium">
                  Odpowiedź w {response.workdays} dni rob.
                </th>
                <th className="whitespace-nowrap py-1.5 text-right font-medium">
                  Najstarsze bez odpowiedzi
                </th>
              </tr>
            </thead>
            <tbody>
              {response.clients.map((row) => (
                <tr key={row.client_id} className="border-b border-border/60">
                  <td className="max-w-[240px] truncate py-1.5 pr-3">
                    <Link
                      href={`/clients/${row.client_id}`}
                      className="text-foreground hover:underline"
                    >
                      {row.client_name}
                    </Link>
                  </td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">
                    {row.cv_in_progress}
                  </td>
                  <td className="whitespace-nowrap py-1.5 pr-3 text-right tabular-nums">
                    {pctLabel(row.response_7d_pct)}
                    {row.cohort_cv > 0 ? (
                      <span className="ml-1 text-xs text-muted-foreground">
                        {row.responded_7d} z {row.cohort_cv}
                      </span>
                    ) : null}
                  </td>
                  <td className="whitespace-nowrap py-1.5 text-right tabular-nums">
                    {workdaysLabel(row.oldest_waiting_workdays)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="shrink-0 text-xs text-muted-foreground">
        Liczy się odpowiedź zapisana w NEXUSIE.
        {response.excluded_mass_cv > 0
          ? ` W procencie pominięto ${response.excluded_mass_cv} CV z rekrutacji masowych.`
          : ""}
      </p>
    </div>
  )
}
