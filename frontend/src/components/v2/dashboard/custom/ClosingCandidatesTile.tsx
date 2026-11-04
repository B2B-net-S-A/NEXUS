"use client"

// Kafelek „Kandydaci do zamknięcia” (prośba Olafa, decyzje Artura 20.10.2026):
// osoby w kolumnie Tablicy „Akceptacja i umowa” ze wszystkich rekrutacji
// z zakresu patrzącego — klient, koszt, przychód, marża, Delivery Lead
// i rekruter pary. Najdłużej czekający na górze. Bez prawa do stawki do
// klienta kafelek nie ma kolumn przychodu i marży (serwer i tak je wycina).
//
// Wariant A z makiet (20.10.2026): nad tabelą podsumowanie z sumą marży
// i filtr kroków z licznikami z serwera, w wierszu „Następny krok” — link do
// istniejącego ekranu (Generator albo panel osoby).

import Link from "next/link"
import { useState } from "react"
import { useQuery } from "@tanstack/react-query"

import { Skeleton } from "@/components/ui/skeleton"
import { WidgetErrorBlock } from "@/components/v2/dashboard/WidgetState"
import { api } from "@/lib/api"
import { waitingFor } from "@/lib/api/boardTasks"
import {
  CLOSING_CANDIDATES_QUERY_KEY,
  CLOSING_FILTER_LABEL,
  CLOSING_STEPS,
  CLOSING_STEP_LABEL,
  closingMargin,
  closingMarginSum,
  closingNextStep,
  rateText,
  type ClosingCandidateRow,
  type ClosingCandidatesResponse,
  type ClosingFilter,
  type ClosingStep,
} from "@/lib/closing-candidates"
import { formatHourly, formatPln } from "@/lib/dl-review-margin"
import { countPl } from "@/lib/plural-pl"

const STEP_TONE: Record<ClosingStep, string> = {
  accepted: "border-success/40 bg-success-muted text-success-muted-foreground",
  sent: "border-info/30 bg-info-muted text-info-muted-foreground",
  signed: "border-border bg-card text-muted-foreground",
}

const FILTER_ACTIVE = "border-primary bg-primary/10 text-primary"
const FILTER_IDLE = "border-border bg-card text-foreground hover:bg-muted"

function jobLabel(row: ClosingCandidateRow): string {
  return row.job_working_title?.trim() || row.job_title || "Rekrutacja"
}

function MarginCell({ row }: { row: ClosingCandidateRow }) {
  const margin = closingMargin(row)
  if (margin.kind === "empty") return <span className="text-muted-foreground">—</span>
  if (margin.kind === "not_comparable") {
    return (
      <span className="text-xs text-muted-foreground">
        {margin.reason === "currency" ? "inna waluta" : "brak stawki kandydata"}
      </span>
    )
  }
  return (
    <span
      className={`whitespace-nowrap tabular-nums ${margin.negative ? "text-destructive" : "text-foreground"}`}
    >
      {formatHourly(margin.hourly)}
      <span className="text-xs text-muted-foreground"> · {margin.percent.toLocaleString("pl-PL")}%</span>
    </span>
  )
}

function Rate({ value }: { value: string | null }) {
  return value ? (
    <span className="whitespace-nowrap tabular-nums">{value}</span>
  ) : (
    <span className="text-muted-foreground">—</span>
  )
}

function Summary({ data, rows }: { data: ClosingCandidatesResponse; rows: ClosingCandidateRow[] }) {
  const people = countPl(data.total, "osoba", "osoby", "osób")
  if (!data.show_client_rate) {
    return <p className="text-xs text-muted-foreground">{people} · najdłużej czekający na górze</p>
  }
  const sum = closingMarginSum(rows)
  return (
    <p className="text-xs text-muted-foreground">
      {people}
      {sum.counted > 0 ? (
        <>
          {" · marża ok. "}
          <strong className="font-semibold text-foreground">{formatPln(sum.monthly)}/mc</strong>
          {` (${countPl(sum.counted, "osoba", "osoby", "osób")} z porównywalnymi stawkami${
            data.total > rows.length ? ` spośród ${rows.length} pokazanych` : ""
          })`}
        </>
      ) : null}
      {" · najdłużej czekający na górze"}
    </p>
  )
}

function StepFilter({
  counts,
  total,
  value,
  onChange,
}: {
  counts: Record<ClosingStep, number>
  total: number
  value: ClosingFilter
  onChange: (next: ClosingFilter) => void
}) {
  const options: Array<{ key: ClosingFilter; n: number }> = [
    { key: "all", n: total },
    ...CLOSING_STEPS.map((step) => ({ key: step, n: counts[step] ?? 0 })),
  ]
  return (
    <div role="group" aria-label="Filtr kroku" className="flex flex-wrap gap-2">
      {options.map((option) => (
        <button
          key={option.key}
          type="button"
          aria-pressed={value === option.key}
          onClick={() => onChange(option.key)}
          className={`h-8 rounded-full border px-3 text-xs font-medium ${
            value === option.key ? FILTER_ACTIVE : FILTER_IDLE
          }`}
        >
          {CLOSING_FILTER_LABEL[option.key]} <span className="font-semibold">{option.n}</span>
        </button>
      ))}
    </div>
  )
}

export function ClosingCandidatesTile() {
  const [filter, setFilter] = useState<ClosingFilter>("all")
  const query = useQuery({
    queryKey: CLOSING_CANDIDATES_QUERY_KEY,
    queryFn: () =>
      api.get<ClosingCandidatesResponse>("/api/board-tasks/closing").then((r) => r.data),
    staleTime: 60_000,
  })

  if (query.isPending) return <Skeleton className="h-full min-h-[48px] w-full" />
  if (query.isError) {
    return <WidgetErrorBlock error={query.error} onRetry={() => query.refetch()} />
  }

  const data = query.data
  const { rows, total, show_client_rate: money } = data
  if (rows.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Nikt nie czeka w „Akceptacja i umowa” w Twoich rekrutacjach.
      </p>
    )
  }

  const shown = filter === "all" ? rows : rows.filter((row) => row.step === filter)
  return (
    <div className="flex h-full flex-col gap-3 text-sm">
      <Summary data={data} rows={rows} />
      <StepFilter counts={data.step_counts} total={total} value={filter} onChange={setFilter} />
      <div className="relative overflow-x-auto">
        <table className="w-full min-w-[820px] text-left">
          <thead>
            <tr className="border-b border-border text-xs text-muted-foreground">
              <th className="py-1.5 pr-3 font-medium">Kandydat</th>
              <th className="px-2 py-1.5 font-medium">Etap</th>
              <th className="px-2 py-1.5 text-right font-medium">Koszt</th>
              {money ? <th className="px-2 py-1.5 text-right font-medium">Przychód</th> : null}
              {money ? <th className="px-2 py-1.5 text-right font-medium">Marża</th> : null}
              <th className="px-2 py-1.5 font-medium">Delivery Lead</th>
              <th className="px-2 py-1.5 font-medium">Rekruter</th>
              <th className="py-1.5 pl-2 text-right font-medium">Następny krok</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((row) => {
              const next = closingNextStep(row)
              return (
                <tr
                  key={`${row.job_id}-${row.candidate_id}`}
                  className="border-b border-border/60 last:border-0"
                >
                  <td className="max-w-[280px] py-1.5 pr-3">
                    <Link
                      href={`/jobs/${row.job_id}?candidate=${row.candidate_id}`}
                      className="block truncate font-medium text-foreground hover:text-primary hover:underline"
                    >
                      {row.candidate_name}
                    </Link>
                    <span className="block truncate text-xs text-muted-foreground" title={jobLabel(row)}>
                      {row.client_name ? `${row.client_name} · ` : ""}
                      {jobLabel(row)}
                    </span>
                  </td>
                  <td className="px-2 py-1.5">
                    <span
                      className={`inline-flex whitespace-nowrap rounded-full border px-2 py-0.5 text-xs ${STEP_TONE[row.step]}`}
                    >
                      {CLOSING_STEP_LABEL[row.step]}
                    </span>
                    <span className="block whitespace-nowrap text-xs text-muted-foreground">
                      {waitingFor(row.since)}
                    </span>
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    <Rate
                      value={rateText(
                        row.candidate_rate_value,
                        row.candidate_rate_unit,
                        row.candidate_rate_currency,
                      )}
                    />
                  </td>
                  {money ? (
                    <td className="px-2 py-1.5 text-right">
                      <Rate
                        value={rateText(row.client_rate_value, row.client_rate_unit, row.client_rate_currency)}
                      />
                    </td>
                  ) : null}
                  {money ? (
                    <td className="px-2 py-1.5 text-right">
                      <MarginCell row={row} />
                    </td>
                  ) : null}
                  <td className="whitespace-nowrap px-2 py-1.5 text-xs text-foreground">
                    {row.delivery_lead_name ?? <span className="text-muted-foreground">—</span>}
                  </td>
                  <td className="whitespace-nowrap px-2 py-1.5 text-xs text-foreground">
                    {row.recruiter_name ?? <span className="text-muted-foreground">—</span>}
                  </td>
                  <td className="py-1.5 pl-2 text-right">
                    <Link
                      href={next.href}
                      className="inline-flex h-8 items-center whitespace-nowrap rounded-md border border-border px-3 text-xs font-medium text-foreground hover:bg-muted"
                    >
                      {next.label}
                    </Link>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {shown.length === 0 ? (
          <p className="py-3 text-xs text-muted-foreground">
            Na tym kroku nikt nie czeka wśród {rows.length} najdłużej czekających.
          </p>
        ) : null}
      </div>
      {total > rows.length ? (
        <p className="mt-auto text-xs text-muted-foreground">
          Pokazano {rows.length} z {total} — najdłużej czekający.
        </p>
      ) : null}
    </div>
  )
}
