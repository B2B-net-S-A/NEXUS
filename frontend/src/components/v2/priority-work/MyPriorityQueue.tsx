"use client"

import { useMemo, useState } from "react"
import Link from "next/link"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  AlertTriangle,
  BriefcaseBusiness,
  CheckCircle2,
  Clock3,
  Inbox,
  ListChecks,
  MessageSquareWarning,
  UsersRound,
} from "lucide-react"

import { EmptyState } from "@/components/ds"
import { useToast } from "@/components/Toast"
import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { WidgetErrorBlock } from "@/components/v2/dashboard/WidgetState"
import {
  priorityWorkApi,
  priorityWorkQueryKeys,
  type PriorityAssignment,
  type PriorityCarryOver,
} from "@/lib/priority-work-api"
import { hasRole, useAuthStore } from "@/store/auth"

import {
  AssignmentProgress,
  ChannelBadge,
  GateBadge,
  ModeNotice,
  PlanReviewNotice,
  PriorityJobLink,
  PriorityWorkLoading,
  RankBadge,
} from "./PriorityWorkPrimitives"

const BLOCKER_CATEGORIES = [
  ["brief", "Brak lub niepełny brief"],
  ["client_feedback", "Brak feedbacku klienta"],
  ["rate", "Nieadekwatna stawka"],
  ["market", "Brak kandydatów na rynku"],
  ["competence", "Brak wymaganych kompetencji"],
  ["capacity", "Brak pojemności"],
  ["access", "Brak dostępu lub narzędzi"],
  ["other", "Inny"],
] as const

const STAGE_LABELS: Record<string, string> = {
  // Legacy CandidateStage values — keep these labels for processes that have
  // not yet been reconciled to the canonical semantic lifecycle.
  new: "Nowy",
  prep_call: "Prep call",
  screening: "Screening",
  verified: "Zweryfikowany",
  interview: "Interview wewnętrzne",
  cv_sent: "CV wysłane do klienta",
  client_interview: "Interview u klienta",
  acceptance: "Akceptacja",
  negotiation: "Negocjacje",
  onboarding: "Onboarding",
  // Canonical RecruitmentProcess semantic states.
  identified: "Zidentyfikowany",
  screening_pending: "Screening — oczekuje",
  screening_completed: "Screening — zakończony",
  internal_review: "Przegląd wewnętrzny",
  internally_approved: "Zatwierdzony wewnętrznie",
  submission_preparation: "Przygotowanie prezentacji",
  submission_approved: "Prezentacja zatwierdzona",
  submission_dispatch_pending: "Wysyłka w toku",
  submitted_to_client: "Wysłany do klienta",
  client_review: "Przegląd klienta",
  client_interview_scheduled: "Rozmowa u klienta — umówiona",
  client_interview_completed: "Rozmowa u klienta — odbyta",
  feedback_pending: "Oczekiwanie na feedback",
  client_approved: "Zaakceptowany przez klienta",
  offer_preparation: "Przygotowanie oferty",
  offer_approved: "Oferta zatwierdzona",
  offer_dispatch_pending: "Oferta — wysyłka w toku",
  offer_sent: "Oferta wysłana",
  offer_accepted: "Oferta zaakceptowana",
  contract_preparation: "Przygotowanie kontraktu",
  contract_signed: "Kontrakt podpisany",
  start_confirmed: "Start potwierdzony",
  placement_active: "Placement aktywny",
  placement_ended: "Placement zakończony",
  on_hold: "Wstrzymany (on hold)",
  hired: "Zatrudniony (decyzja)",
  rejected_internal: "Odrzucony wewnętrznie",
  rejected_client: "Odrzucony przez klienta",
  rejected: "Odrzucony",
  candidate_withdrawn: "Kandydat się wycofał",
  offer_declined: "Oferta odrzucona",
  offer_expired: "Oferta wygasła",
  job_cancelled: "Oferta pracy anulowana",
  placement_failed: "Placement nieudany",
  unmapped: "Niezmapowany (kwarantanna)",
}

const URGENCY_WEIGHT: Record<string, number> = {
  critical: 3,
  urgent: 2,
  normal: 1,
}

function BlockerForm({
  assignment,
  onClose,
}: {
  assignment: PriorityAssignment
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const { showError, showSuccess } = useToast()
  const [category, setCategory] = useState("brief")
  const [note, setNote] = useState("")

  const mutation = useMutation({
    mutationFn: () =>
      priorityWorkApi.createBlocker(assignment.id, {
        category,
        note: note.trim(),
      }),
    onSuccess: () => {
      showSuccess("Blocker został przekazany do Head of Recruitment.")
      queryClient.invalidateQueries({ queryKey: priorityWorkQueryKeys.mine() })
      queryClient.invalidateQueries({ queryKey: priorityWorkQueryKeys.team() })
      onClose()
    },
    onError: () => {
      showError("Nie udało się zgłosić blockera. Spróbuj ponownie.")
    },
  })

  return (
    <div className="mt-4 space-y-3 rounded-lg border border-border bg-muted/40 p-3">
      <div>
        <p className="text-sm font-medium text-foreground">Zgłoś blocker</p>
        <p className="text-xs text-muted-foreground">
          Opisz konkretnie, dlaczego nie możesz realizować targetu.
        </p>
      </div>
      <Select value={category} onValueChange={setCategory}>
        <SelectTrigger aria-label="Kategoria blockera">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {BLOCKER_CATEGORIES.map(([value, label]) => (
            <SelectItem key={value} value={value}>
              {label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Textarea
        value={note}
        onChange={(event) => setNote(event.target.value)}
        placeholder="Co zostało sprawdzone i czego potrzebujesz?"
        rows={3}
      />
      <div className="flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onClose}>
          Anuluj
        </Button>
        <Button
          size="sm"
          loading={mutation.isPending}
          disabled={note.trim().length < 10}
          onClick={() => mutation.mutate()}
        >
          Wyślij blocker
        </Button>
      </div>
    </div>
  )
}

function AssignmentCard({
  assignment,
}: {
  assignment: PriorityAssignment
}) {
  const [showBlocker, setShowBlocker] = useState(false)
  const activeBlocker =
    assignment.blocker &&
    ["pending", "accepted"].includes(assignment.blocker.status)
      ? assignment.blocker
      : null

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <RankBadge rank={assignment.rank} />
          <div className="min-w-0">
            <PriorityJobLink job={assignment.job} className="block truncate" />
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <ChannelBadge channel={assignment.channel} />
              <GateBadge state={assignment.gate_state} />
              {assignment.job.client_name ? (
                <span className="text-xs text-muted-foreground">
                  {assignment.job.client_name}
                </span>
              ) : null}
            </div>
          </div>
        </div>
        {!activeBlocker ? (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowBlocker((current) => !current)}
          >
            <MessageSquareWarning className="h-3.5 w-3.5" />
            Zgłoś blocker
          </Button>
        ) : null}
      </div>

      <div className="mt-4">
        <AssignmentProgress assignment={assignment} />
      </div>

      {activeBlocker ? (
        <Alert
          className="mt-4"
          variant={activeBlocker.status === "accepted" ? "warning" : "info"}
          title={
            activeBlocker.status === "accepted"
              ? "Blocker zaakceptowany"
              : "Blocker czeka na decyzję"
          }
          description={activeBlocker.note}
        />
      ) : null}

      {showBlocker ? (
        <BlockerForm
          assignment={assignment}
          onClose={() => setShowBlocker(false)}
        />
      ) : null}
    </div>
  )
}

function CarryOverCard({ item }: { item: PriorityCarryOver }) {
  const isUrgent = ["critical", "urgent"].includes(item.urgency)
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 items-start gap-3">
        <div
          className={
            isUrgent
              ? "flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-warning-muted text-warning-muted-foreground"
              : "flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground"
          }
        >
          {isUrgent ? (
            <AlertTriangle className="h-4 w-4" aria-hidden="true" />
          ) : (
            <Clock3 className="h-4 w-4" aria-hidden="true" />
          )}
        </div>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href={`/candidates/${item.candidate.id}`}
              className="font-medium text-foreground hover:text-primary"
            >
              {item.candidate.name}
            </Link>
            {isUrgent ? (
              <Badge variant="warning" size="sm">
                Pilne
              </Badge>
            ) : null}
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {STAGE_LABELS[item.current_stage] ?? item.current_stage} ·{" "}
            {item.days_in_stage} dni na etapie
          </p>
          <Link
            href={`/jobs/${item.job.id}`}
            className="mt-1 block truncate text-xs text-primary hover:underline"
          >
            {item.job.title}
          </Link>
        </div>
      </div>
      <Link
        href={`/jobs/${item.job.id}`}
        className={buttonVariants({ variant: "outline", size: "sm" })}
      >
        Obsłuż proces
      </Link>
    </div>
  )
}

export function MyPriorityQueue() {
  const user = useAuthStore((state) => state.user)
  const hydrated = useAuthStore((state) => state.hydrated)
  const isOperational = hasRole(user, "recruiter", "sourcer", "tac")

  const query = useQuery({
    queryKey: priorityWorkQueryKeys.mine(),
    queryFn: priorityWorkApi.getMine,
    enabled: hydrated && isOperational,
    staleTime: 60_000,
  })

  const assignments = useMemo(
    () =>
      [...(query.data?.assignments ?? [])].sort((left, right) =>
        left.rank.localeCompare(right.rank),
      ),
    [query.data?.assignments],
  )
  const carryOver = useMemo(
    () =>
      [...(query.data?.carry_over ?? [])].sort((left, right) => {
        const urgencyDelta =
          (URGENCY_WEIGHT[right.urgency] ?? 0) -
          (URGENCY_WEIGHT[left.urgency] ?? 0)
        return urgencyDelta || right.days_in_stage - left.days_in_stage
      }),
    [query.data?.carry_over],
  )

  if (!hydrated || !isOperational) return null
  if (query.isPending) return <PriorityWorkLoading rows={3} />
  if (query.isError) {
    return (
      <Card>
        <WidgetErrorBlock
          title="Nie udało się załadować Twojego planu pracy."
          error={query.error}
          onRetry={() => query.refetch()}
        />
      </Card>
    )
  }

  const data = query.data
  return (
    <section className="space-y-4" aria-labelledby="my-priority-work-title">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <ListChecks className="h-5 w-5 text-primary" />
                <CardTitle id="my-priority-work-title">Mój plan pracy</CardTitle>
              </div>
              <CardDescription>
                Nowy sourcing realizuj według A–E. Rozpoczęte procesy zawsze
                dokończ w osobnej kolejce.
              </CardDescription>
            </div>
            <Badge variant="outline" size="md">
              {assignments.length} aktywne requesty
            </Badge>
          </div>
          <div className="mt-3 space-y-2">
            <ModeNotice mode={data.mode} />
            <PlanReviewNotice plan={data.plan} />
          </div>
        </CardHeader>
        <CardContent>
          {assignments.length === 0 ? (
            <EmptyState
              icon={BriefcaseBusiness}
              title="Brak requestów do nowego sourcingu"
              description={
                data.plan
                  ? "Head of Recruitment nie przypisał Ci requestów w tym planie."
                  : "Nie ma jeszcze opublikowanego planu pracy."
              }
              className="py-8"
            />
          ) : (
            <div className="space-y-3">
              {assignments.map((assignment) => (
                <AssignmentCard
                  key={assignment.id}
                  assignment={assignment}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <UsersRound className="h-5 w-5 text-primary" />
                <CardTitle>Do dokończenia</CardTitle>
              </div>
              <CardDescription>
                Kandydaci rozpoczęci wcześniej. Ta kolejka nie jest kolejnym
                priorytetem A–E.
              </CardDescription>
            </div>
            <Badge variant={carryOver.length ? "warning" : "success"}>
              {carryOver.length}
            </Badge>
          </div>
        </CardHeader>
        <CardContent>
          {carryOver.length === 0 ? (
            <EmptyState
              icon={CheckCircle2}
              title="Nie masz zaległych procesów"
              description="Wszystkie rozpoczęte procesy są zakończone."
              className="py-8"
            />
          ) : (
            <div className="space-y-3">
              {carryOver.map((item) => (
                <CarryOverCard key={item.process_id} item={item} />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {!data.plan && data.mode !== "off" ? (
        <Alert
          variant="warning"
          title="Brak aktywnego planu"
          description="Nie rozpoczynaj nowych procesów. Nadal obsługuj kolejkę „Do dokończenia”."
          icon={Inbox}
        />
      ) : null}
    </section>
  )
}
