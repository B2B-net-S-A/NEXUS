"use client"

import { useQuery } from "@tanstack/react-query"
import {
  AlertTriangle,
  BriefcaseBusiness,
  ClipboardList,
  History,
  ShieldCheck,
} from "lucide-react"

import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { WidgetErrorBlock } from "@/components/v2/dashboard/WidgetState"
import {
  priorityWorkApi,
  priorityWorkQueryKeys,
} from "@/lib/priority-work-api"
import { hasRole, useAuthStore } from "@/store/auth"

import {
  ChannelBadge,
  ModeNotice,
  PlanReviewNotice,
  PriorityWorkLoading,
  RankBadge,
} from "./PriorityWorkPrimitives"

export function JobPriorityContext({ jobId }: { jobId: number }) {
  const user = useAuthStore((state) => state.user)
  const hydrated = useAuthStore((state) => state.hydrated)
  const canView = hasRole(
    user,
    "admin",
    "head_of_recruitment",
    "delivery_lead",
    "tac",
    "recruiter",
    "sourcer",
  )

  const query = useQuery({
    queryKey: priorityWorkQueryKeys.job(jobId),
    queryFn: () => priorityWorkApi.getJobContext(jobId),
    enabled: hydrated && canView && Number.isFinite(jobId),
    staleTime: 60_000,
  })

  if (!hydrated || !canView) return null
  if (query.isPending) return <PriorityWorkLoading rows={1} />
  if (query.isError) {
    return (
      <Card>
        <WidgetErrorBlock
          title="Nie udało się pobrać kontekstu Priority Work."
          error={query.error}
          onRetry={() => query.refetch()}
        />
      </Card>
    )
  }

  const data = query.data
  const mode = data.mode ?? data.plan?.mode ?? "off"
  const isEmpty =
    !data.plan &&
    data.assignments.length === 0 &&
    data.carry_over_count === 0 &&
    data.blockers.length === 0

  return (
    <Card data-testid="job-priority-context">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-primary" />
              <CardTitle className="text-base">Priority Work</CardTitle>
            </div>
            <CardDescription>
              Przydział do nowego sourcingu i rozpoczęte procesy są liczone
              osobno.
            </CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">
              <History className="h-3 w-3" />
              Carry-over: {data.carry_over_count}
            </Badge>
            {data.plan ? (
              <Badge variant="soft">Plan v{data.plan.version}</Badge>
            ) : null}
          </div>
        </div>
        <div className="mt-3 space-y-2">
          <ModeNotice mode={mode} />
          <PlanReviewNotice plan={data.plan} />
        </div>
      </CardHeader>
      <CardContent>
        {isEmpty ? (
          <div className="flex items-center gap-3 rounded-lg border border-dashed border-border p-4">
            <BriefcaseBusiness className="h-5 w-5 text-muted-foreground" />
            <div>
              <p className="text-sm font-medium text-foreground">
                Brak kontekstu priorytetowego
              </p>
              <p className="text-xs text-muted-foreground">
                Request nie jest w aktywnym planie i nie ma procesów carry-over.
              </p>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            {data.assignments.length > 0 ? (
              <div className="grid gap-2 lg:grid-cols-2">
                {data.assignments
                  .slice()
                  .sort((left, right) => left.rank.localeCompare(right.rank))
                  .map((assignment) => (
                    <div
                      key={assignment.id}
                      className="flex items-center gap-3 rounded-lg border border-border px-3 py-2"
                    >
                      <RankBadge rank={assignment.rank} />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-foreground">
                          {assignment.user_name ??
                            `Osoba #${assignment.user_id ?? "—"}`}
                        </p>
                        <div className="mt-1 flex flex-wrap items-center gap-2">
                          <ChannelBadge channel={assignment.channel} />
                          <span className="text-xs text-muted-foreground">
                            {assignment.progress.verifications}/
                            {assignment.verification_target} weryfikacji
                          </span>
                        </div>
                      </div>
                    </div>
                  ))}
              </div>
            ) : (
              <Alert
                variant="info"
                title="Brak aktywnego assignmentu"
                description={
                  data.carry_over_count > 0
                    ? "Można obsługiwać istniejących kandydatów, ale nie dodawać nowych."
                    : "Nowy sourcing nie został przydzielony w bieżącym planie."
                }
                icon={ClipboardList}
              />
            )}

            {data.blockers.length > 0 ? (
              <div className="space-y-2">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Blockery
                </p>
                {data.blockers.map((blocker) => (
                  <Alert
                    key={blocker.id}
                    variant={
                      blocker.status === "accepted" ? "warning" : "info"
                    }
                    title={
                      blocker.status === "accepted"
                        ? "Zaakceptowany blocker"
                        : "Blocker oczekuje na decyzję"
                    }
                    description={blocker.note}
                    icon={AlertTriangle}
                  />
                ))}
              </div>
            ) : null}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
