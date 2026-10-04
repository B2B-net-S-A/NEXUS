"use client"

// Kafelek „Moje rekrutacje": niezamknięte rekrutacje z zakresu „Moje” listy
// `/jobs` (jestem Rekruterem albo Delivery Leadem), z liczbami w ośmiu
// kolumnach Tablicy i terminem. Te same parametry i te same komórki co lista
// rekrutacji, więc liczby na pulpicie i na liście są identyczne.

import Link from "next/link"
import { useQuery } from "@tanstack/react-query"

import { Skeleton } from "@/components/ui/skeleton"
import {
  JobDeadlineCell,
  JobStageCounts,
  JobStageCountsHeader,
} from "@/components/v2/jobs/JobListCells"
import { WidgetErrorBlock } from "@/components/v2/dashboard/WidgetState"
import { api } from "@/lib/api"
import { jobDisplayTitle } from "@/lib/job-names"
import { stageSummaryOf, type PipelineStageSummary } from "@/lib/job-pipeline-funnel"
import {
  recruitersOf,
  recruitersSummary,
  workingRecruiters,
  type JobRecruiter,
} from "@/lib/job-team"
import { hasRole, useAuthStore } from "@/store/auth"

export interface MyRecruitmentRow extends PipelineStageSummary {
  id: number
  title?: string | null
  working_title?: string | null
  client_name?: string | null
  deadline?: string | null
  deadline_time?: string | null
  delivery_lead_id?: number | null
  recruiters?: JobRecruiter[] | null
}

export const MY_RECRUITMENTS_PARAMS = {
  mine: true,
  open_only: true,
  include_stage_counts: true,
  sort: "deadline",
  page: 1,
  page_size: 20,
} as const

export const MY_RECRUITMENTS_QUERY_KEY = ["dashboard", "my-recruitments", MY_RECRUITMENTS_PARAMS] as const

/** „DL”, „Rekruter”, „DL + Rekruter” albo `null`, gdy żadne. */
export function myRoleInJob(row: MyRecruitmentRow, userId: number): string | null {
  const isDl = row.delivery_lead_id === userId
  const isRecruiter = workingRecruiters(recruitersOf(row)).some((p) => p.user_id === userId)
  if (isDl && isRecruiter) return "DL + Rekruter"
  if (isDl) return "DL"
  if (isRecruiter) return "Rekruter"
  return null
}

function RecruiterCell({ row }: { row: MyRecruitmentRow }) {
  const summary = recruitersSummary(recruitersOf(row))
  if (!summary.lead) {
    return <span className="text-xs text-muted-foreground">Bez rekrutera</span>
  }
  return (
    <span className="whitespace-nowrap text-xs text-foreground" title={summary.tooltip}>
      {summary.lead}
      {summary.more > 0 ? <span className="text-muted-foreground"> +{summary.more}</span> : null}
    </span>
  )
}

export function MyRecruitmentsTile() {
  const user = useAuthStore((s) => s.user)
  const isDl = hasRole(user, "delivery_lead")
  const showRole = isDl && hasRole(user, "recruiter")
  const query = useQuery({
    queryKey: MY_RECRUITMENTS_QUERY_KEY,
    queryFn: () =>
      api
        .get<{ items: MyRecruitmentRow[]; total: number }>("/api/jobs", {
          params: MY_RECRUITMENTS_PARAMS,
        })
        .then((r) => r.data),
    staleTime: 60_000,
  })

  if (query.isPending) return <Skeleton className="h-full min-h-[48px] w-full" />
  if (query.isError) {
    return <WidgetErrorBlock error={query.error} onRetry={() => query.refetch()} />
  }

  const rows = query.data.items ?? []
  if (rows.length === 0) {
    return (
      <div className="flex flex-col gap-2 text-sm">
        <p className="text-muted-foreground">Nie masz otwartych rekrutacji.</p>
        <Link href="/jobs" className="self-start font-medium text-primary hover:underline">
          Wszystkie →
        </Link>
      </div>
    )
  }

  const total = query.data.total ?? rows.length
  return (
    <div className="flex h-full flex-col gap-2 text-sm">
      <div className="relative overflow-x-auto">
        <table className="w-full min-w-[640px] text-left">
          <thead>
            <tr className="border-b border-border text-xs text-muted-foreground">
              <th className="py-1.5 pr-3 font-medium">Rekrutacja</th>
              <th className="px-2 py-1.5 font-medium">
                <span className="sr-only">Etapy</span>
                <JobStageCountsHeader />
              </th>
              <th className="px-2 py-1.5 font-medium">Termin</th>
              {isDl ? <th className="px-2 py-1.5 font-medium">Rekruter</th> : null}
              {showRole ? <th className="px-2 py-1.5 font-medium">Twoja rola</th> : null}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const summary = stageSummaryOf(row)
              const title = jobDisplayTitle(row)
              return (
                <tr key={row.id} className="border-b border-border/60 last:border-0">
                  <td className="max-w-[260px] py-1.5 pr-3">
                    <span className="block min-w-0 truncate" title={title}>
                      <Link
                        href={`/jobs/${row.id}`}
                        className="font-medium text-foreground hover:text-primary hover:underline"
                      >
                        {title}
                      </Link>
                    </span>
                    {row.client_name ? (
                      <span className="block truncate text-xs text-muted-foreground">
                        {row.client_name}
                      </span>
                    ) : null}
                  </td>
                  <td className="px-2 py-1.5">
                    {summary ? (
                      <JobStageCounts summary={summary} />
                    ) : (
                      <span className="text-xs text-muted-foreground">brak danych</span>
                    )}
                  </td>
                  <td className="px-2 py-1.5">
                    <JobDeadlineCell deadline={row.deadline} deadlineTime={row.deadline_time} />
                  </td>
                  {isDl ? (
                    <td className="px-2 py-1.5">
                      <RecruiterCell row={row} />
                    </td>
                  ) : null}
                  {showRole ? (
                    <td className="whitespace-nowrap px-2 py-1.5 text-xs text-foreground">
                      {(user && myRoleInJob(row, user.id)) ?? "—"}
                    </td>
                  ) : null}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <Link href="/jobs" className="mt-auto self-start font-medium text-primary hover:underline">
        {total > rows.length ? `Wszystkie (${total}) →` : "Wszystkie →"}
      </Link>
    </div>
  )
}
