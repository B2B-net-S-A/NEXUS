"use client"

import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { Briefcase, Inbox } from "lucide-react"

import api from "@/lib/api"
import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"

interface JobListItem {
  id: number
  title: string
  client_id: number | null
  status: string
  candidate_count: number
  stage_breakdown?: Record<string, number>
  primary_owner?: { id: number; name: string; email: string } | null
}

interface JobListResponse {
  items: JobListItem[]
  total: number
  page: number
  page_size: number
}

interface ActiveJobsTabProps {
  deliveryLeadId: number
}

const STAGE_LABEL: Record<string, string> = {
  new: "Nowy",
  prep_call: "Prep Call",
  screening: "Screening",
  verified: "Zweryfikowany",
  interview: "Interview",
  cv_sent: "CV wysłane",
  client_interview: "Interview klient",
  acceptance: "Akceptacja",
  negotiation: "Negocjacje",
  onboarding: "Onboarding",
  hired: "Hired",
  rejected: "Odrzucony",
  withdrawn: "Wycofany",
}

const TERMINAL = new Set(["hired", "rejected", "withdrawn"])

function stageChipClass(stage: string): string {
  if (stage === "hired") return "bg-emerald-100 text-emerald-900"
  if (stage === "rejected" || stage === "withdrawn") return "bg-rose-100 text-rose-900"
  return "bg-sky-100 text-sky-900"
}

export function ActiveJobsTab({ deliveryLeadId }: ActiveJobsTabProps) {
  const { data, isLoading, isError } = useQuery<JobListResponse>({
    queryKey: ["my-active-jobs", deliveryLeadId],
    queryFn: () =>
      api
        .get<JobListResponse>("/api/jobs", {
          params: {
            delivery_lead_id: deliveryLeadId,
            status: "published",
            include_stage_counts: true,
            page_size: 100,
          },
        })
        .then((r) => r.data),
    staleTime: 5 * 60 * 1000,
  })

  if (isLoading) {
    return (
      <Card className="p-4! text-sm text-muted-foreground">
        Ładowanie aktywnych jobów…
      </Card>
    )
  }
  if (isError) {
    return (
      <Card className="p-4! text-sm text-rose-700 bg-rose-50 border border-rose-200">
        Nie udało się pobrać jobów.
      </Card>
    )
  }
  const items = data?.items ?? []
  if (items.length === 0) {
    return (
      <Card className="p-8! text-center text-sm text-muted-foreground">
        <Inbox className="h-10 w-10 mx-auto mb-3 opacity-40" />
        Brak aktywnych jobów przypisanych do Ciebie jako DL.
      </Card>
    )
  }

  return (
    <div className="space-y-2">
      {items.map((job) => {
        const breakdown = job.stage_breakdown ?? {}
        // Active stages first (non-terminal), terminals na końcu
        const stages = Object.entries(breakdown).sort(([a], [b]) => {
          const aT = TERMINAL.has(a)
          const bT = TERMINAL.has(b)
          if (aT === bT) return a.localeCompare(b)
          return aT ? 1 : -1
        })
        return (
          <Card key={job.id} className="p-3!">
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <div className="min-w-0 flex-1">
                <Link
                  href={`/jobs/${job.id}`}
                  className="inline-flex items-center gap-1.5 font-medium text-primary hover:underline"
                >
                  <Briefcase className="h-3.5 w-3.5 opacity-60" />
                  {job.title}
                </Link>
                <div className="text-xs text-muted-foreground mt-0.5">
                  {job.candidate_count} kandydatów łącznie
                  {job.primary_owner && (
                    <span className="opacity-80"> · rekruter: {job.primary_owner.name}</span>
                  )}
                </div>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {stages.length === 0 ? (
                  <span className="text-xs text-muted-foreground">brak kandydatów</span>
                ) : (
                  stages.map(([stage, n]) => (
                    <span
                      key={stage}
                      className={cn(
                        "inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium",
                        stageChipClass(stage),
                      )}
                    >
                      {STAGE_LABEL[stage] ?? stage}: {n}
                    </span>
                  ))
                )}
              </div>
            </div>
          </Card>
        )
      })}
    </div>
  )
}
