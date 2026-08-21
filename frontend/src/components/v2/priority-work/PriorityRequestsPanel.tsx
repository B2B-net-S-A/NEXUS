"use client"

import { useMemo, useState } from "react"
import Link from "next/link"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  BriefcaseBusiness,
  CalendarDays,
  CheckCircle2,
  CirclePause,
  ClipboardCheck,
  Inbox,
  Plus,
  Send,
  Target,
} from "lucide-react"

import { EmptyState } from "@/components/ds"
import { useToast } from "@/components/Toast"
import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { WidgetErrorBlock } from "@/components/v2/dashboard/WidgetState"
import api from "@/lib/api"
import {
  priorityWorkApi,
  priorityWorkQueryKeys,
  type PriorityChannel,
  type PriorityDemand,
  type PriorityDemandInput,
} from "@/lib/priority-work-api"
import { hasRole, useAuthStore } from "@/store/auth"

import {
  AssignmentProgress,
  ChannelBadge,
  formatPriorityDate,
  ModeNotice,
  PlanReviewNotice,
  PriorityWorkLoading,
  RankBadge,
} from "./PriorityWorkPrimitives"

interface DeliveryLeadJob {
  id: number
  title: string
  client_name?: string | null
}

interface DeliveryLeadJobsResponse {
  items: DeliveryLeadJob[]
}

const STATUS_LABELS: Record<
  string,
  {
    label: string
    variant: "success" | "warning" | "neutral" | "info"
  }
> = {
  open: { label: "Otwarte", variant: "info" },
  covered: { label: "Pokryte planem", variant: "success" },
  fulfilled: { label: "Zrealizowane", variant: "success" },
  paused: { label: "Wstrzymane", variant: "warning" },
  cancelled: { label: "Anulowane", variant: "neutral" },
}

function DemandForm({
  jobs,
  onCancel,
}: {
  jobs: DeliveryLeadJob[]
  onCancel: () => void
}) {
  const queryClient = useQueryClient()
  const { showError, showSuccess } = useToast()
  const [jobId, setJobId] = useState("")
  const [recommendations, setRecommendations] = useState(3)
  const [deadline, setDeadline] = useState("")
  const [channel, setChannel] = useState<PriorityChannel>("linkedin")
  const [urgency, setUrgency] = useState("normal")
  const [briefReady, setBriefReady] = useState(false)
  const [note, setNote] = useState("")

  const mutation = useMutation({
    mutationFn: () => {
      const payload: PriorityDemandInput = {
        job_id: Number(jobId),
        urgency,
        expected_recommendations: recommendations,
        deadline: deadline || null,
        channel,
        brief_ready: briefReady,
        note: note.trim(),
      }
      return priorityWorkApi.createDemand(payload)
    },
    onSuccess: () => {
      showSuccess("Zapotrzebowanie zostało przekazane do Head of Recruitment.")
      queryClient.invalidateQueries({
        queryKey: priorityWorkQueryKeys.demands(),
      })
      queryClient.invalidateQueries({ queryKey: priorityWorkQueryKeys.team() })
      onCancel()
    },
    onError: () => {
      showError("Nie udało się zapisać zapotrzebowania.")
    },
  })

  return (
    <Card className="border-primary/30">
      <CardHeader>
        <CardTitle>Nowe zapotrzebowanie</CardTitle>
        <CardDescription>
          Wskaż request i oczekiwany rezultat. HoR podejmie ostateczną decyzję o
          przydziale.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 md:grid-cols-2">
          <label className="space-y-1.5 text-sm">
            <span className="font-medium text-foreground">Request</span>
            <Select value={jobId} onValueChange={setJobId}>
              <SelectTrigger aria-label="Request">
                <SelectValue placeholder="Wybierz aktywny request" />
              </SelectTrigger>
              <SelectContent>
                {jobs.map((job) => (
                  <SelectItem key={job.id} value={String(job.id)}>
                    {job.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="font-medium text-foreground">
              Oczekiwane rekomendacje
            </span>
            <Input
              type="number"
              min={3}
              max={99}
              value={recommendations}
              onChange={(event) =>
                setRecommendations(
                  Math.max(3, Number(event.target.value) || 3),
                )
              }
            />
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="font-medium text-foreground">Termin</span>
            <Input
              type="date"
              value={deadline}
              onChange={(event) => setDeadline(event.target.value)}
            />
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="font-medium text-foreground">Kanał</span>
            <Select
              value={channel}
              onValueChange={(value) =>
                setChannel(value as PriorityChannel)
              }
            >
              <SelectTrigger aria-label="Kanał">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="linkedin">LinkedIn</SelectItem>
                <SelectItem value="database">Baza NEXUS</SelectItem>
                <SelectItem value="mixed">
                  TAC / mieszany (Baza + LinkedIn)
                </SelectItem>
              </SelectContent>
            </Select>
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="font-medium text-foreground">Pilność</span>
            <Select value={urgency} onValueChange={setUrgency}>
              <SelectTrigger aria-label="Pilność">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="normal">Standardowa</SelectItem>
                <SelectItem value="urgent">Pilna</SelectItem>
                <SelectItem value="critical">Krytyczna</SelectItem>
              </SelectContent>
            </Select>
          </label>
          <label className="flex items-center gap-3 rounded-lg border border-border px-3 py-2 text-sm">
            <input
              type="checkbox"
              checked={briefReady}
              onChange={(event) => setBriefReady(event.target.checked)}
              className="h-4 w-4 accent-primary"
            />
            <span>
              <span className="block font-medium text-foreground">
                Brief gotowy
              </span>
              <span className="text-xs text-muted-foreground">
                Wymagania, stawka i proces są kompletne
              </span>
            </span>
          </label>
        </div>
        <label className="block space-y-1.5 text-sm">
          <span className="font-medium text-foreground">Uzasadnienie</span>
          <Textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Dlaczego ten request wymaga priorytetu?"
            rows={3}
          />
        </label>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onCancel}>
            Anuluj
          </Button>
          <Button
            loading={mutation.isPending}
            disabled={!jobId || note.trim().length < 10}
            onClick={() => mutation.mutate()}
          >
            <Send className="h-4 w-4" />
            Wyślij do HoR
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function DemandCard({
  demand,
  canFulfill,
}: {
  demand: PriorityDemand
  canFulfill: boolean
}) {
  const queryClient = useQueryClient()
  const { showError, showSuccess } = useToast()
  const status = STATUS_LABELS[demand.status] ?? {
    label: demand.status,
    variant: "neutral" as const,
  }
  const covered = demand.covered_recommendations ?? 0
  const coveragePct = Math.min(
    100,
    Math.round((covered / Math.max(1, demand.expected_recommendations)) * 100),
  )
  const assignments = demand.assignments ?? []

  const updateMutation = useMutation({
    mutationFn: (nextStatus: string) =>
      priorityWorkApi.updateDemand(demand.id, {
        expected_version: demand.row_version,
        status: nextStatus,
      }),
    onSuccess: () => {
      showSuccess("Status zapotrzebowania został zaktualizowany.")
      queryClient.invalidateQueries({
        queryKey: priorityWorkQueryKeys.demands(),
      })
      queryClient.invalidateQueries({ queryKey: priorityWorkQueryKeys.team() })
    },
    onError: () => showError("Nie udało się zmienić statusu."),
  })

  return (
    <Card>
      <CardContent>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Link
                href={`/jobs/${demand.job.id}`}
                className="font-semibold text-foreground hover:text-primary"
              >
                {demand.job.title}
              </Link>
              <Badge variant={status.variant}>{status.label}</Badge>
              {demand.urgency !== "normal" ? (
                <Badge variant="warning">
                  {demand.urgency === "critical" ? "Krytyczne" : "Pilne"}
                </Badge>
              ) : null}
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
              <ChannelBadge channel={demand.channel} />
              <span className="inline-flex items-center gap-1">
                <Target className="h-3.5 w-3.5" />
                {demand.expected_recommendations} rekomendacji
              </span>
              <span className="inline-flex items-center gap-1">
                <CalendarDays className="h-3.5 w-3.5" />
                {demand.deadline
                  ? formatPriorityDate(demand.deadline)
                  : "bez terminu"}
              </span>
              <span className="inline-flex items-center gap-1">
                <ClipboardCheck className="h-3.5 w-3.5" />
                {demand.brief_ready ? "brief gotowy" : "brief niegotowy"}
              </span>
            </div>
            {demand.note ? (
              <p className="mt-3 text-sm text-muted-foreground">{demand.note}</p>
            ) : null}
          </div>
          <div className="min-w-40 rounded-lg bg-muted/50 px-3 py-2 text-right">
            <p className="text-xs text-muted-foreground">Pokrycie planem</p>
            <p className="font-semibold tabular-nums text-foreground">
              {covered}/{demand.expected_recommendations}
            </p>
            <p className="text-xs text-muted-foreground">{coveragePct}%</p>
          </div>
        </div>

        {["open", "covered"].includes(demand.status) ? (
          <div className="mt-4 flex flex-wrap justify-end gap-2 border-t border-border pt-3">
            <Button
              variant="ghost"
              size="sm"
              loading={updateMutation.isPending}
              onClick={() => updateMutation.mutate("paused")}
            >
              <CirclePause className="h-3.5 w-3.5" />
              Wstrzymaj
            </Button>
            {/* `fulfilled` to werdykt Head of Recruitment —
                `_DEMAND_STATUS_TRANSITIONS_DL` w priority_work_service.py nie ma
                tego celu w ŻADNYM wpisie, więc czysty Delivery Lead dostawał tu
                422 przy każdym kliknięciu, obok legalnego „Wstrzymaj". Panel
                renderuje się dla DL, więc przycisk pokazujemy tylko osobie,
                która trzyma też rolę HoR — czyli dokładnie tej, której backend
                to przejście przyznaje. */}
            {canFulfill ? (
              <Button
                variant="outline"
                size="sm"
                loading={updateMutation.isPending}
                onClick={() => updateMutation.mutate("fulfilled")}
              >
                <CheckCircle2 className="h-3.5 w-3.5" />
                Oznacz jako zrealizowane
              </Button>
            ) : null}
          </div>
        ) : null}

        <div className="mt-4 border-t border-border pt-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Assignmenty i postęp
          </p>
          {assignments.length === 0 ? (
            <p className="mt-2 text-sm text-muted-foreground">
              Demand nie ma jeszcze assignmentu w opublikowanym planie.
            </p>
          ) : (
            <div className="mt-2 space-y-2">
              {assignments
                .slice()
                .sort((left, right) => left.rank.localeCompare(right.rank))
                .map((assignment) => {
                  const blockers =
                    assignment.blockers ??
                    (assignment.blocker ? [assignment.blocker] : [])
                  return (
                    <div
                      key={assignment.id}
                      className="rounded-lg border border-border bg-muted/30 p-3"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <RankBadge rank={assignment.rank} />
                        <span className="font-medium text-foreground">
                          {assignment.user_name ??
                            `Osoba #${assignment.user_id ?? "—"}`}
                        </span>
                        <ChannelBadge channel={assignment.channel} />
                      </div>
                      <div className="mt-3">
                        <AssignmentProgress assignment={assignment} />
                      </div>
                      {blockers.map((blocker) => (
                        <Alert
                          key={blocker.id}
                          className="mt-3"
                          variant={
                            blocker.status === "accepted" ? "warning" : "info"
                          }
                          title={
                            blocker.status === "accepted"
                              ? "Zaakceptowany blocker"
                              : "Blocker czeka na decyzję"
                          }
                          description={blocker.note}
                        />
                      ))}
                    </div>
                  )
                })}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

export function PriorityRequestsPanel({
  deliveryLeadId,
}: {
  deliveryLeadId: number
}) {
  const user = useAuthStore((state) => state.user)
  const hydrated = useAuthStore((state) => state.hydrated)
  const isDeliveryLead = hasRole(user, "delivery_lead")
  const isHeadOfRecruitment = hasRole(user, "head_of_recruitment")
  const [showForm, setShowForm] = useState(false)

  const currentQuery = useQuery({
    queryKey: priorityWorkQueryKeys.current(),
    queryFn: priorityWorkApi.getCurrent,
    enabled: hydrated && isDeliveryLead,
    staleTime: 60_000,
  })
  const demandsQuery = useQuery({
    queryKey: priorityWorkQueryKeys.demands(),
    queryFn: priorityWorkApi.listDemands,
    enabled: hydrated && isDeliveryLead,
    staleTime: 60_000,
  })
  const jobsQuery = useQuery({
    queryKey: ["priority-work", "delivery-lead-jobs", deliveryLeadId],
    queryFn: () =>
      api
        .get<DeliveryLeadJobsResponse>("/api/jobs", {
          params: {
            delivery_lead_id: deliveryLeadId,
            status: "published",
            page_size: 100,
          },
        })
        .then((response) => response.data),
    enabled: hydrated && isDeliveryLead && showForm,
    staleTime: 5 * 60_000,
  })

  const demands = useMemo(
    () =>
      [...(demandsQuery.data ?? [])].sort((left, right) => {
        const active = new Set(["open", "covered"])
        if (active.has(left.status) === active.has(right.status)) {
          return left.job.title.localeCompare(right.job.title)
        }
        return active.has(left.status) ? -1 : 1
      }),
    [demandsQuery.data],
  )

  if (!hydrated || !isDeliveryLead) return null
  if (currentQuery.isPending || demandsQuery.isPending) {
    return <PriorityWorkLoading rows={2} />
  }
  if (currentQuery.isError || demandsQuery.isError) {
    return (
      <Card>
        <WidgetErrorBlock
          title="Nie udało się załadować priorytetów rekrutacji."
          error={currentQuery.error ?? demandsQuery.error}
          onRetry={() => {
            currentQuery.refetch()
            demandsQuery.refetch()
          }}
        />
      </Card>
    )
  }

  const plan = currentQuery.data?.plan ?? null
  const mode = currentQuery.data?.mode ?? plan?.mode ?? "off"
  return (
    <section className="space-y-4" aria-labelledby="priority-demands-title">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <BriefcaseBusiness className="h-5 w-5 text-primary" />
                <CardTitle id="priority-demands-title">
                  Priorytety rekrutacji
                </CardTitle>
              </div>
              <CardDescription>
                Zgłoś oczekiwany rezultat. Head of Recruitment zatwierdza
                ostateczny przydział osób.
              </CardDescription>
            </div>
            <Button
              size="sm"
              onClick={() => setShowForm((current) => !current)}
            >
              <Plus className="h-4 w-4" />
              Nowe zapotrzebowanie
            </Button>
          </div>
          <div className="mt-3 space-y-2">
            <ModeNotice mode={mode} />
            <PlanReviewNotice plan={plan} />
          </div>
        </CardHeader>
      </Card>

      {showForm ? (
        jobsQuery.isPending ? (
          <PriorityWorkLoading rows={1} />
        ) : jobsQuery.isError ? (
          <Alert
            variant="error"
            title="Nie udało się pobrać aktywnych requestów."
            description="Odśwież widok i spróbuj ponownie."
          />
        ) : (
          <DemandForm
            jobs={jobsQuery.data?.items ?? []}
            onCancel={() => setShowForm(false)}
          />
        )
      ) : null}

      {demands.length === 0 ? (
        <Card>
          <EmptyState
            icon={Inbox}
            title="Brak zgłoszonych priorytetów"
            description="Dodaj zapotrzebowanie dla requestu, który wymaga pokrycia przez zespół rekrutacji."
          />
        </Card>
      ) : (
        <div className="space-y-3">
          {demands.map((demand) => (
            <DemandCard
              key={demand.id}
              demand={demand}
              canFulfill={isHeadOfRecruitment}
            />
          ))}
        </div>
      )}
    </section>
  )
}
