"use client"

import { AllocationWorkloadBoard } from "./AllocationWorkloadBoard"

import { priorityPosition } from "@/lib/priority-work-api"

import { useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Activity,
  AlertTriangle,
  Check,
  Clock3,
  ClipboardList,
  History,
  Inbox,
  KeyRound,
  PauseCircle,
  Plus,
  RefreshCw,
  Save,
  Send,
  ShieldAlert,
  Trash2,
  UserCog,
  UsersRound,
} from "lucide-react"

import { EmptyState, TabbedNav } from "@/components/ds"
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
import { extractErrorMsg } from "@/lib/api"
import {
  DEFAULT_PRIORITY_VERIFICATION_CAPACITY,
  priorityCapacityFields,
  priorityWorkApi,
  priorityWorkQueryKeys,
  type PriorityAssignment,
  type PriorityAssignmentInput,
  type PriorityBlocker,
  type PriorityCarryOver,
  type PriorityChannel,
  type PriorityDemand,
  type PriorityException,
  type PriorityMemberStatus,
  type PriorityPlan,
  type PriorityPlanAssignmentSnapshot,
  type PriorityPlanMemberSnapshot,
  type PriorityPlanMemberInput,
  type PriorityRank,
  type PriorityTeamMember,
  type PriorityWorkStatus,
} from "@/lib/priority-work-api"
import { hasRole, useAuthStore } from "@/store/auth"

import {
  ChannelBadge,
  formatPriorityDate,
  ModeNotice,
  PlanReviewNotice,
  PriorityWorkLoading,
  RankBadge,
} from "./PriorityWorkPrimitives"

type BoardTab =
  | "plan"
  | "blockers"
  | "carry-over"
  | "unowned"
  | "exceptions"

interface EditableAssignment extends PriorityAssignmentInput {
  local_key: string
  cc_exception_required: boolean
}

interface EditableMember extends Omit<PriorityPlanMemberInput, "assignments"> {
  user_name: string
  role: string
  roles: string[]
  allowed_channels: PriorityChannel[]
  competence_category_ids: number[]
  assignments: EditableAssignment[]
}

const RANKS: PriorityRank[] = ["A", "B", "C", "D", "E"]
const DEFAULT_VERIFICATION_TARGETS: Record<number, number[]> = {
  3: [6, 4, 2],
  4: [5, 4, 2, 1],
  5: [4, 3, 2, 2, 1],
}

const ROLE_LABELS: Record<string, string> = {
  recruiter: "Rekruter",
  sourcer: "Sourcer",
  tac: "TAC",
}

const CHANNEL_OPTIONS: Record<
  "database" | "linkedin" | "mixed",
  string
> = {
  database: "Baza NEXUS",
  linkedin: "LinkedIn",
  mixed: "TAC / mieszany (Baza + LinkedIn)",
}

function inferredAllowedChannels(
  role: string,
  roles: string[] = [],
): PriorityChannel[] {
  const roleValues = new Set([role, ...roles])
  if (roleValues.has("tac")) return ["database", "linkedin", "mixed"]
  const channels: PriorityChannel[] = []
  if (roleValues.has("sourcer")) channels.push("database")
  if (roleValues.has("recruiter")) channels.push("linkedin")
  return channels
}

function channelForMember(
  member: EditableMember,
  requested: PriorityChannel,
): PriorityChannel {
  const allowed = member.allowed_channels
  return allowed.includes(requested) ? requested : allowed[0] ?? requested
}

function memberRoleLabel(member: {
  role: string
  roles?: string[]
}): string {
  const labels = [...new Set([member.role, ...(member.roles ?? [])])]
    .filter((role) => role in ROLE_LABELS)
    .map((role) => ROLE_LABELS[role])
  return labels.length > 0 ? labels.join(" + ") : member.role
}

function competenceMatch(
  member: Pick<EditableMember, "competence_category_ids">,
  demand: PriorityDemand,
): boolean {
  const categoryIds =
    demand.job.competence_category_ids ??
    (demand.job.competence_category_id == null
      ? []
      : [demand.job.competence_category_id])
  return categoryIds.some((categoryId) =>
    member.competence_category_ids.includes(categoryId),
  )
}

function assignmentToEditable(
  assignment: PriorityAssignment | PriorityPlanAssignmentSnapshot,
  index: number,
): EditableAssignment {
  const isSnapshot = "job_id" in assignment
  const ccMatch = isSnapshot
    ? assignment.competence_matches
    : assignment.cc_match ?? false
  return {
    local_key: `${assignment.id || "new"}-${index}`,
    job_id: isSnapshot ? assignment.job_id : assignment.job.id,
    demand_id: assignment.demand_id ?? null,
    rank: assignment.rank,
    position: priorityPosition(assignment),
    channel: assignment.channel,
    verification_target: assignment.verification_target,
    recommendation_target: assignment.recommendation_target,
    cc_match: ccMatch,
    cc_exception_required:
      assignment.cc_exception_required ?? !ccMatch,
    cc_exception_reason: assignment.cc_exception_reason ?? null,
  }
}

function membersToEditable(
  members: Array<PriorityTeamMember | PriorityPlanMemberSnapshot>,
  fallbackMembers: PriorityTeamMember[] = [],
): EditableMember[] {
  return members.map((member) => {
    const fallback = fallbackMembers.find(
      (item) => item.user_id === member.user_id,
    )
    const role =
      ("role" in member ? member.role : undefined) ??
      fallback?.role ??
      "recruiter"
    const roles =
      ("roles" in member ? member.roles : undefined) ??
      fallback?.roles ??
      [role]
    return {
      user_id: member.user_id,
      user_name:
        ("user_name" in member ? member.user_name : undefined) ??
        fallback?.user_name ??
        `User #${member.user_id}`,
      role,
      roles,
      allowed_channels:
        ("allowed_channels" in member
          ? member.allowed_channels
          : undefined) ??
        fallback?.allowed_channels ??
        inferredAllowedChannels(role, roles),
      competence_category_ids:
        ("competence_category_ids" in member
          ? member.competence_category_ids
          : undefined) ??
        fallback?.competence_category_ids ??
        [],
      status: member.status,
      verification_capacity: member.verification_capacity ?? 12,
      capacity_reason: member.capacity_reason ?? null,
      paused_reason: member.paused_reason ?? null,
      extra_slots_reason:
        member.extra_slots_reason ??
        member.capacity_reason ??
        member.assignments.find((assignment) =>
          priorityPosition(assignment) > 3,
        )?.extra_slot_reason ??
        null,
      assignments: member.assignments
        .slice()
        .sort((left, right) => priorityPosition(left) - priorityPosition(right))
        .map(assignmentToEditable),
    }
  })
}

function serializeMembers(
  members: EditableMember[],
): PriorityPlanMemberInput[] {
  return members.map((member) => {
    if (member.status === "paused") {
      return {
        user_id: member.user_id,
        status: member.status,
        verification_capacity: 0,
        capacity_reason: null,
        paused_reason: member.paused_reason?.trim() || null,
        extra_slots_reason: null,
        assignments: [],
      }
    }
    const capacity = priorityCapacityFields(
      member.assignments.map((assignment) => assignment.verification_target),
      member.capacity_reason,
    )
    return {
      user_id: member.user_id,
      status: member.status,
      ...capacity,
      paused_reason: null,
      extra_slots_reason:
        member.assignments.length > 3
          ? member.extra_slots_reason?.trim() || null
          : null,
      assignments: member.assignments.map(
        ({
          local_key: _localKey,
          cc_exception_required: ccExceptionRequired,
          ...assignment
        }) => ({
          ...assignment,
          cc_exception_reason: !ccExceptionRequired
            ? null
            : assignment.cc_exception_reason?.trim() || null,
        }),
      ),
    }
  })
}

function applyDefaultVerificationTargets(
  assignments: EditableAssignment[],
): EditableAssignment[] {
  const defaults = DEFAULT_VERIFICATION_TARGETS[assignments.length]
  return assignments.map((assignment, index) => ({
    ...assignment,
    rank: RANKS[index] ?? null,
    position: index + 1,
    verification_target:
      defaults?.[index] ?? assignment.verification_target,
  }))
}

function validateMembers(members: EditableMember[]): string[] {
  const errors: string[] = []
  for (const member of members) {
    if (member.status === "paused") {
      if ((member.paused_reason?.trim().length ?? 0) < 10) {
        errors.push(`${member.user_name}: podaj powód wstrzymania.`)
      }
      continue
    }
    if (member.assignments.length === 0) {
      errors.push(`${member.user_name}: dodaj co najmniej jeden request albo wstrzymaj osobę.`)
    }
    const verificationCapacity = member.assignments.reduce(
      (total, assignment) => total + assignment.verification_target,
      0,
    )
    if (
      verificationCapacity !== DEFAULT_PRIORITY_VERIFICATION_CAPACITY &&
      (member.capacity_reason?.trim().length ?? 0) < 10
    ) {
      errors.push(
        `${member.user_name}: suma targetów ${verificationCapacity} zamiast ${DEFAULT_PRIORITY_VERIFICATION_CAPACITY} wymaga uzasadnienia pojemności.`,
      )
    }
    const jobIds = member.assignments.map((assignment) => assignment.job_id)
    if (new Set(jobIds).size !== jobIds.length) {
      errors.push(`${member.user_name}: ten sam request jest wybrany dwa razy.`)
    }
    for (const assignment of member.assignments) {
      if (!member.allowed_channels.includes(assignment.channel)) {
        errors.push(
          `${member.user_name}, priorytet ${assignment.position ?? assignment.rank}: kanał ${CHANNEL_OPTIONS[assignment.channel]} nie pasuje do roli ${memberRoleLabel(member)}.`,
        )
      }
      if (
        assignment.verification_target < 1 ||
        assignment.recommendation_target < 1
      ) {
        errors.push(
          `${member.user_name}, priorytet ${assignment.position ?? assignment.rank}: targety muszą być większe od zera.`,
        )
      }
      if (
        assignment.cc_exception_required &&
        (assignment.cc_exception_reason?.trim().length ?? 0) < 10
      ) {
        errors.push(
          `${member.user_name}, priorytet ${assignment.position ?? assignment.rank}: wyjątek CC wymaga uzasadnienia.`,
        )
      }
    }
  }
  return errors
}

function ReconciliationStatusPanel({
  status,
  loading,
  error,
  onRetry,
}: {
  status?: PriorityWorkStatus
  loading: boolean
  error: unknown
  onRetry: () => void
}) {
  if (loading) {
    return (
      <Card aria-busy="true">
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Ładowanie statusu reconciliation…
          </p>
        </CardContent>
      </Card>
    )
  }
  if (error || !status) {
    return (
      <Card>
        <WidgetErrorBlock
          title="Nie udało się pobrać statusu Priority Work."
          error={error}
          onRetry={onRetry}
        />
      </Card>
    )
  }

  return (
    <Card data-testid="priority-work-reconciliation-status">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <Activity className="h-5 w-5 text-primary" aria-hidden="true" />
              <CardTitle className="text-base">
                Gotowość i reconciliation
              </CardTitle>
            </div>
            <CardDescription>
              Dane operacyjne wymagane przed przejściem z shadow do enforce.
            </CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">Tryb: {status.mode}</Badge>
            {status.plan_overdue ? (
              <Badge variant="warning">Plan po terminie przeglądu</Badge>
            ) : (
              <Badge variant="success">Plan aktualny</Badge>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
          <StatusMetric
            label="Aktywny plan"
            value={
              status.current_plan_id == null
                ? "Brak"
                : `#${status.current_plan_id}`
            }
            warning={status.current_plan_id == null}
          />
          <StatusMetric
            label="Bez pokrycia"
            value={String(status.users_without_coverage)}
            warning={status.users_without_coverage > 0}
          />
          <StatusMetric
            label="Carry-over bez ownera"
            value={String(status.unowned_carry_over)}
            warning={status.unowned_carry_over > 0}
          />
          <StatusMetric
            label="Eligibility"
            value={`${status.eligibility_coverage_percent.toFixed(1)}%`}
            warning={status.eligibility_coverage_percent < 100}
          />
          <StatusMetric
            label="Shadow delta"
            value={String(status.shadow_violation_count)}
            warning={status.shadow_violation_count > 0}
          />
        </div>
        <div className="grid gap-2 text-xs text-muted-foreground sm:grid-cols-2">
          <div className="flex items-center gap-2">
            <Clock3 className="h-3.5 w-3.5" aria-hidden="true" />
            <span>
              Heartbeat workera:{" "}
              <strong className="font-medium text-foreground">
                {formatPriorityDate(status.worker_heartbeat_at)}
              </strong>
            </span>
          </div>
          <div className="flex items-center gap-2">
            <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
            <span>
              Ostatnia reconciliation:{" "}
              <strong className="font-medium text-foreground">
                {formatPriorityDate(status.last_reconciled_at)}
              </strong>
            </span>
          </div>
        </div>
        {status.last_error ? (
          <Alert
            variant="error"
            title="Ostatni błąd workera"
            description={status.last_error}
          />
        ) : null}
      </CardContent>
    </Card>
  )
}

function StatusMetric({
  label,
  value,
  warning,
}: {
  label: string
  value: string
  warning: boolean
}) {
  return (
    <div className="rounded-lg border border-border bg-muted/40 px-3 py-2">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p
        className={
          warning
            ? "mt-1 text-lg font-semibold tabular-nums text-warning-muted-foreground"
            : "mt-1 text-lg font-semibold tabular-nums text-foreground"
        }
      >
        {value}
      </p>
    </div>
  )
}

function DemandSummary({ demand }: { demand: PriorityDemand }) {
  const covered = demand.covered_recommendations ?? 0
  return (
    <div className="rounded-lg border border-border px-3 py-2">
      <div className="flex items-start justify-between gap-2">
        <Link
          href={`/jobs/${demand.job.id}`}
          className="text-sm font-medium text-foreground hover:text-primary"
        >
          {demand.job.title}
        </Link>
        <Badge
          variant={
            demand.status === "fulfilled"
              ? "success"
              : demand.urgency === "normal"
                ? "info"
                : "warning"
          }
          size="sm"
        >
          {demand.status}
        </Badge>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <ChannelBadge channel={demand.channel} />
        <span>
          Pokrycie: {covered}/{demand.expected_recommendations}
        </span>
        {!demand.brief_ready ? (
          <Badge variant="warning" size="sm">
            Brief niegotowy
          </Badge>
        ) : null}
      </div>
    </div>
  )
}

function EditableAssignmentRow({
  assignment,
  demands,
  member,
  onChange,
  onRemove,
}: {
  assignment: EditableAssignment
  demands: PriorityDemand[]
  member: EditableMember
  onChange: (next: EditableAssignment) => void
  onRemove: () => void
}) {
  const selectedDemand = demands.find(
    (demand) => demand.job.id === assignment.job_id,
  )

  const changeJob = (rawJobId: string) => {
    const jobId = Number(rawJobId)
    const demand = demands.find((item) => item.job.id === jobId)
    if (!demand) return
    const matches = competenceMatch(member, demand)
    onChange({
      ...assignment,
      job_id: jobId,
      demand_id: demand.id,
      channel: channelForMember(member, demand.channel),
      recommendation_target: Math.max(1, demand.expected_recommendations),
      cc_match: matches,
      cc_exception_required: !matches,
      cc_exception_reason: null,
    })
  }

  return (
    <div className="space-y-3 rounded-lg border border-border bg-card p-3">
      <div className="flex items-start gap-3">
        <RankBadge rank={assignment.rank} position={assignment.position} />
        <div className="grid min-w-0 flex-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
          <label className="space-y-1 text-xs text-muted-foreground md:col-span-2">
            <span>Request</span>
            <Select
              value={String(assignment.job_id)}
              onValueChange={changeJob}
            >
              <SelectTrigger aria-label={`Request ${assignment.position ?? assignment.rank}`}>
                <SelectValue placeholder="Wybierz request" />
              </SelectTrigger>
              <SelectContent>
                {demands.map((demand) => (
                  <SelectItem key={demand.id} value={String(demand.job.id)}>
                    {demand.job.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
          <label className="space-y-1 text-xs text-muted-foreground">
            <span>Kanał</span>
            <Select
              value={assignment.channel}
              onValueChange={(value) =>
                onChange({
                  ...assignment,
                  channel: value as EditableAssignment["channel"],
                })
              }
            >
              <SelectTrigger aria-label={`Kanał ${assignment.position ?? assignment.rank}`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {member.allowed_channels.map((channel) => (
                  <SelectItem key={channel} value={channel}>
                    {CHANNEL_OPTIONS[channel]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
          <div className="grid grid-cols-2 gap-2">
            <label className="space-y-1 text-xs text-muted-foreground">
              <span>Weryfikacje</span>
              <Input
                type="number"
                min={1}
                value={assignment.verification_target}
                onChange={(event) =>
                  onChange({
                    ...assignment,
                    verification_target: Math.max(
                      1,
                      Number(event.target.value) || 1,
                    ),
                  })
                }
                aria-label={`Target weryfikacji ${assignment.position ?? assignment.rank}`}
              />
            </label>
            <label className="space-y-1 text-xs text-muted-foreground">
              <span>Rekomendacje</span>
              <Input
                type="number"
                min={1}
                value={assignment.recommendation_target}
                onChange={(event) =>
                  onChange({
                    ...assignment,
                    recommendation_target: Math.max(
                      1,
                      Number(event.target.value) || 1,
                    ),
                  })
                }
                aria-label={`Target rekomendacji ${assignment.position ?? assignment.rank}`}
              />
            </label>
          </div>
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={onRemove}
          aria-label={`Usuń priorytet ${assignment.position ?? assignment.rank}`}
        >
          <Trash2 className="h-4 w-4 text-destructive" />
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <Badge
          variant={assignment.cc_exception_required ? "warning" : "success"}
          size="sm"
        >
          {assignment.cc_exception_required
            ? "Wymagany wyjątek CC"
            : "CC dopasowane"}
        </Badge>
        <span>
          {(selectedDemand?.job.competence_category_ids?.length ?? 0) === 0 &&
          selectedDemand?.job.competence_category_id == null
            ? "Request nie ma przypisanej Competence Category."
            : assignment.cc_exception_required
              ? "Kategoria requestu nie należy do CC tej osoby."
              : "Dopasowanie potwierdzone na podstawie danych zespołu."}
        </span>
      </div>
      {assignment.cc_exception_required ? (
        <Input
          value={assignment.cc_exception_reason ?? ""}
          onChange={(event) =>
            onChange({
              ...assignment,
              cc_exception_reason: event.target.value,
            })
          }
          placeholder="Dlaczego przydział poza CC jest uzasadniony przez HoR?"
          aria-label={`Uzasadnienie wyjątku CC ${assignment.position ?? assignment.rank}`}
        />
      ) : null}
    </div>
  )
}

function EditableMemberCard({
  member,
  demands,
  onChange,
}: {
  member: EditableMember
  demands: PriorityDemand[]
  onChange: (next: EditableMember) => void
}) {
  const updateAssignment = (
    localKey: string,
    nextAssignment: EditableAssignment,
  ) => {
    onChange({
      ...member,
      assignments: member.assignments.map((assignment) =>
        assignment.local_key === localKey ? nextAssignment : assignment,
      ),
    })
  }

  const removeAssignment = (localKey: string) => {
    const remaining = member.assignments.filter(
      (assignment) => assignment.local_key !== localKey,
    )
    onChange({
      ...member,
      assignments: applyDefaultVerificationTargets(remaining),
    })
  }

  const addAssignment = () => {
    const usedJobIds = new Set(
      member.assignments.map((assignment) => assignment.job_id),
    )
    const demand =
      demands.find((item) => !usedJobIds.has(item.job.id)) ?? demands[0]
    if (!demand) return
    const rank = RANKS[member.assignments.length] ?? null
    const matches = competenceMatch(member, demand)
    const assignments = applyDefaultVerificationTargets([
      ...member.assignments,
      {
        local_key: `new-${member.user_id}-${Date.now()}`,
        job_id: demand.job.id,
        demand_id: demand.id,
        rank,
        position: member.assignments.length + 1,
        channel: channelForMember(member, demand.channel),
        verification_target: 1,
        recommendation_target: Math.max(1, demand.expected_recommendations),
        cc_match: matches,
        cc_exception_required: !matches,
        cc_exception_reason: null,
      },
    ])
    onChange({
      ...member,
      assignments,
    })
  }

  const verificationCapacity = member.assignments.reduce(
    (total, assignment) => total + assignment.verification_target,
    0,
  )

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="text-base">{member.user_name}</CardTitle>
            <CardDescription>
              {memberRoleLabel(member)} ·{" "}
              {member.assignments.length} requesty · domyślnie 3
            </CardDescription>
          </div>
          <Select
            value={member.status}
            onValueChange={(value) =>
              onChange({
                ...member,
                status: value as PriorityMemberStatus,
              })
            }
          >
            <SelectTrigger
              className="w-40"
              aria-label={`Status ${member.user_name}`}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="active">Aktywna osoba</SelectItem>
              <SelectItem value="paused">Wstrzymana</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {member.status === "paused" ? (
          <label className="block space-y-1.5 text-sm">
            <span className="font-medium text-foreground">
              Powód wstrzymania
            </span>
            <Textarea
              value={member.paused_reason ?? ""}
              onChange={(event) =>
                onChange({ ...member, paused_reason: event.target.value })
              }
              placeholder="Np. urlop, choroba albo praca wyłącznie na carry-over"
              rows={2}
            />
            <span className="text-xs text-muted-foreground">
              Wstrzymanie blokuje nowy sourcing, ale nie usuwa carry-over.
            </span>
          </label>
        ) : (
          <>
            {member.assignments.map((assignment) => (
              <EditableAssignmentRow
                key={assignment.local_key}
                assignment={assignment}
                demands={demands}
                member={member}
                onChange={(next) =>
                  updateAssignment(assignment.local_key, next)
                }
                onRemove={() => removeAssignment(assignment.local_key)}
              />
            ))}
            <div className="rounded-lg border border-border bg-muted/40 px-3 py-2">
              <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <span className="font-medium text-foreground">
                  Łączny target weryfikacji
                </span>
                <Badge
                  variant={
                    verificationCapacity ===
                    DEFAULT_PRIORITY_VERIFICATION_CAPACITY
                      ? "success"
                      : "warning"
                  }
                >
                  {verificationCapacity}/
                  {DEFAULT_PRIORITY_VERIFICATION_CAPACITY}
                </Badge>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                Standardowa pojemność na trzy dni robocze to 12 weryfikacji.
              </p>
              {verificationCapacity !==
              DEFAULT_PRIORITY_VERIFICATION_CAPACITY ? (
                <label className="mt-3 block space-y-1.5 text-sm">
                  <span className="font-medium text-foreground">
                    Uzasadnienie zmiany pojemności
                  </span>
                  <Textarea
                    value={member.capacity_reason ?? ""}
                    onChange={(event) =>
                      onChange({
                        ...member,
                        verification_capacity: verificationCapacity,
                        capacity_reason: event.target.value,
                      })
                    }
                    placeholder={`Dlaczego target wynosi ${verificationCapacity}, a nie 12?`}
                    rows={2}
                    aria-label={`Uzasadnienie pojemności ${member.user_name}`}
                  />
                </label>
              ) : null}
            </div>
            {(
              <Button
                variant="outline"
                size="sm"
                onClick={addAssignment}
                disabled={demands.length === 0}
              >
                <Plus className="h-4 w-4" />
                Dodaj pozycję {member.assignments.length + 1}
              </Button>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}

function ReadOnlyMemberCard({ member }: { member: PriorityTeamMember }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="text-base">{member.user_name}</CardTitle>
            <CardDescription>
              {memberRoleLabel(member)}
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            {member.status === "paused" ? (
              <Badge variant="warning">
                <PauseCircle className="h-3 w-3" />
                Wstrzymana
              </Badge>
            ) : (
              <Badge variant="success">
                <Check className="h-3 w-3" />
                Aktywna
              </Badge>
            )}
            <Badge variant="outline">
              <History className="h-3 w-3" />
              {member.carry_over_count ?? member.carry_over?.length ?? 0}
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {member.status === "paused" ? (
          <Alert
            variant="warning"
            title="Nowy sourcing wstrzymany"
            description={
              member.paused_reason ??
              "Osoba nadal ma obowiązek obsługiwać rozpoczęte procesy."
            }
          />
        ) : member.assignments.length === 0 ? (
          <p className="text-sm text-muted-foreground">Brak assignmentów.</p>
        ) : (
          <div className="space-y-2">
            {member.assignments
              .slice()
              .sort((left, right) => priorityPosition(left) - priorityPosition(right))
              .map((assignment) => (
                <div
                  key={assignment.id}
                  className="flex flex-wrap items-center gap-3 rounded-lg border border-border px-3 py-2"
                >
                  <RankBadge rank={assignment.rank} position={assignment.position} />
                  <Link
                    href={`/jobs/${assignment.job.id}`}
                    className="min-w-0 flex-1 truncate text-sm font-medium text-foreground hover:text-primary"
                  >
                    {assignment.job.title}
                  </Link>
                  <ChannelBadge channel={assignment.channel} />
                  {assignment.cc_exception_required ||
                  assignment.cc_match === false ? (
                    <Badge variant="warning" size="sm">
                      Wyjątek CC
                    </Badge>
                  ) : (
                    <Badge variant="success" size="sm">
                      CC zgodne
                    </Badge>
                  )}
                  <span className="text-xs tabular-nums text-muted-foreground">
                    W {assignment.progress.verifications}/
                    {assignment.verification_target} · R{" "}
                    {assignment.progress.recommendations}/
                    {assignment.recommendation_target}
                  </span>
                </div>
              ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function BlockerDecisionRow({
  blocker,
}: {
  blocker: PriorityBlocker & { userName: string; jobTitle: string }
}) {
  const queryClient = useQueryClient()
  const { showError, showSuccess } = useToast()
  const [note, setNote] = useState("")
  const mutation = useMutation({
    mutationFn: (status: "accepted" | "rejected" | "resolved") =>
      priorityWorkApi.updateBlocker(blocker.id, {
        status,
        decision_note: note.trim() || null,
      }),
    onSuccess: () => {
      showSuccess("Decyzja dotycząca blockera została zapisana.")
      queryClient.invalidateQueries({ queryKey: priorityWorkQueryKeys.team() })
      queryClient.invalidateQueries({ queryKey: priorityWorkQueryKeys.mine() })
    },
    onError: () => showError("Nie udało się zapisać decyzji."),
  })

  return (
    <Card>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <p className="font-medium text-foreground">{blocker.userName}</p>
              <Badge
                variant={
                  blocker.status === "accepted"
                    ? "warning"
                    : blocker.status === "pending"
                      ? "info"
                      : "neutral"
                }
              >
                {blocker.status}
              </Badge>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              {blocker.jobTitle} · {blocker.category}
            </p>
          </div>
        </div>
        <Alert
          variant={blocker.status === "accepted" ? "warning" : "info"}
          title="Opis blockera"
          description={blocker.note}
        />
        {["pending", "accepted"].includes(blocker.status) ? (
          <>
            <Input
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="Notatka do decyzji (opcjonalnie)"
              aria-label={`Notatka do blockera ${blocker.id}`}
            />
            <div className="flex flex-wrap justify-end gap-2">
              {blocker.status === "pending" ? (
                <>
                  <Button
                    variant="outline"
                    size="sm"
                    loading={mutation.isPending}
                    onClick={() => mutation.mutate("rejected")}
                  >
                    Odrzuć
                  </Button>
                  <Button
                    size="sm"
                    loading={mutation.isPending}
                    onClick={() => mutation.mutate("accepted")}
                  >
                    Zaakceptuj
                  </Button>
                </>
              ) : (
                <Button
                  size="sm"
                  loading={mutation.isPending}
                  onClick={() => mutation.mutate("resolved")}
                >
                  Oznacz jako rozwiązany
                </Button>
              )}
            </div>
          </>
        ) : null}
      </CardContent>
    </Card>
  )
}

function HandoffRow({
  item,
  members,
}: {
  item: PriorityCarryOver
  members: PriorityTeamMember[]
}) {
  const queryClient = useQueryClient()
  const { showError, showSuccess } = useToast()
  const [expanded, setExpanded] = useState(false)
  const [ownerId, setOwnerId] = useState("")
  const [reason, setReason] = useState("")
  const mutation = useMutation({
    mutationFn: () =>
      priorityWorkApi.handoffProcess(item.process_id, {
        process_id: item.process_id,
        new_owner_user_id: Number(ownerId),
        reason: reason.trim(),
        expected_process_version: item.state_version,
      }),
    onSuccess: () => {
      showSuccess("Carry-over został przekazany. Autor KPI nie zmienił się.")
      queryClient.invalidateQueries({ queryKey: priorityWorkQueryKeys.team() })
      queryClient.invalidateQueries({ queryKey: priorityWorkQueryKeys.mine() })
      setExpanded(false)
    },
    onError: () => showError("Nie udało się przekazać procesu."),
  })

  return (
    <Card>
      <CardContent>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <Link
              href={`/candidates/${item.candidate.id}`}
              className="font-medium text-foreground hover:text-primary"
            >
              {item.candidate.name}
            </Link>
            <p className="mt-1 text-xs text-muted-foreground">
              {item.job.title} · {item.current_stage} · {item.days_in_stage} dni
            </p>
          </div>
          <div className="flex items-center gap-2">
            {["critical", "urgent"].includes(item.urgency) ? (
              <Badge variant="warning">Pilne</Badge>
            ) : null}
            <Button
              variant="outline"
              size="sm"
              onClick={() => setExpanded((current) => !current)}
            >
              <UserCog className="h-3.5 w-3.5" />
              Handoff
            </Button>
          </div>
        </div>
        {expanded ? (
          <div className="mt-4 grid gap-3 border-t border-border pt-4 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_auto]">
            <Select value={ownerId} onValueChange={setOwnerId}>
              <SelectTrigger aria-label="Nowy właściciel carry-over">
                <SelectValue placeholder="Nowy właściciel" />
              </SelectTrigger>
              <SelectContent>
                {members
                  .filter(
                    (member) =>
                      member.status === "active" &&
                      member.user_id !== item.owner_user_id,
                  )
                  .map((member) => (
                    <SelectItem
                      key={member.user_id}
                      value={String(member.user_id)}
                    >
                      {member.user_name}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
            <Input
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Powód handoffu — credit zostaje u verifiera"
            />
            <Button
              loading={mutation.isPending}
              disabled={!ownerId || reason.trim().length < 10}
              onClick={() => mutation.mutate()}
            >
              Przekaż
            </Button>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

function defaultExceptionExpiry(): string {
  const expires = new Date(Date.now() + 3 * 24 * 60 * 60 * 1000)
  const offsetMs = expires.getTimezoneOffset() * 60 * 1000
  return new Date(expires.getTime() - offsetMs).toISOString().slice(0, 16)
}

function ExceptionsPanel({
  exceptions,
  members,
  demands,
  loading,
  error,
  onRetry,
}: {
  exceptions: PriorityException[]
  members: PriorityTeamMember[]
  demands: PriorityDemand[]
  loading: boolean
  error: unknown
  onRetry: () => void
}) {
  const queryClient = useQueryClient()
  const { showError, showSuccess } = useToast()
  const [userId, setUserId] = useState("")
  const [jobId, setJobId] = useState("")
  const [reason, setReason] = useState("")
  const [expiresAt, setExpiresAt] = useState(defaultExceptionExpiry)
  const [revokeReasons, setRevokeReasons] = useState<Record<number, string>>({})

  const expiry = expiresAt ? new Date(expiresAt) : null
  const maxExpiry = Date.now() + 7 * 24 * 60 * 60 * 1000
  const expiryInvalid =
    !expiry ||
    Number.isNaN(expiry.getTime()) ||
    expiry.getTime() <= Date.now() ||
    expiry.getTime() > maxExpiry

  const createMutation = useMutation({
    mutationFn: () =>
      priorityWorkApi.createException({
        user_id: Number(userId),
        job_id: Number(jobId),
        reason: reason.trim(),
        valid_from: new Date().toISOString(),
        expires_at: new Date(expiresAt).toISOString(),
      }),
    onSuccess: () => {
      showSuccess("Jednorazowy wyjątek został nadany.")
      setReason("")
      setExpiresAt(defaultExceptionExpiry())
      queryClient.invalidateQueries({
        queryKey: priorityWorkQueryKeys.exceptions(),
      })
    },
    onError: (mutationError) =>
      showError(extractErrorMsg(mutationError)),
  })

  const revokeMutation = useMutation({
    mutationFn: ({
      exceptionId,
      revokeReason,
    }: {
      exceptionId: number
      revokeReason: string
    }) => priorityWorkApi.revokeException(exceptionId, revokeReason),
    onSuccess: (_result, variables) => {
      showSuccess("Wyjątek został odwołany.")
      setRevokeReasons((current) => {
        const next = { ...current }
        delete next[variables.exceptionId]
        return next
      })
      queryClient.invalidateQueries({
        queryKey: priorityWorkQueryKeys.exceptions(),
      })
    },
    onError: (mutationError) =>
      showError(extractErrorMsg(mutationError)),
  })

  if (loading) return <PriorityWorkLoading rows={2} />
  if (error) {
    return (
      <Card>
        <WidgetErrorBlock
          title="Nie udało się pobrać wyjątków Priority Work."
          error={error}
          onRetry={onRetry}
        />
      </Card>
    )
  }

  const memberName = (id: number) =>
    members.find((member) => member.user_id === id)?.user_name ?? `User #${id}`
  const jobTitle = (id: number) =>
    demands.find((demand) => demand.job.id === id)?.job.title ?? `Request #${id}`

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Nadaj jednorazowy wyjątek</CardTitle>
          <CardDescription>
            Wyjątek pozwala wskazanej osobie otworzyć jeden nowy proces poza
            assignmentem. Ważność nie może przekroczyć 7 dni.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 lg:grid-cols-2">
          <label className="space-y-1.5 text-sm">
            <span className="font-medium text-foreground">Osoba</span>
            <Select value={userId} onValueChange={setUserId}>
              <SelectTrigger aria-label="Osoba dla wyjątku">
                <SelectValue placeholder="Wybierz osobę" />
              </SelectTrigger>
              <SelectContent>
                {members.map((member) => (
                  <SelectItem
                    key={member.user_id}
                    value={String(member.user_id)}
                  >
                    {member.user_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="font-medium text-foreground">Request</span>
            <Select value={jobId} onValueChange={setJobId}>
              <SelectTrigger aria-label="Request dla wyjątku">
                <SelectValue placeholder="Wybierz request" />
              </SelectTrigger>
              <SelectContent>
                {demands
                  .filter((demand) =>
                    ["open", "covered", "paused"].includes(demand.status),
                  )
                  .map((demand) => (
                    <SelectItem
                      key={demand.job.id}
                      value={String(demand.job.id)}
                    >
                      {demand.job.title}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="font-medium text-foreground">Ważny do</span>
            <Input
              type="datetime-local"
              value={expiresAt}
              onChange={(event) => setExpiresAt(event.target.value)}
              aria-label="Ważność wyjątku"
            />
            {expiryInvalid ? (
              <span className="text-xs text-destructive">
                Termin musi przypadać w ciągu najbliższych 7 dni.
              </span>
            ) : null}
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="font-medium text-foreground">Uzasadnienie HoR</span>
            <Textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Dlaczego jednorazowe odstępstwo jest potrzebne?"
              rows={2}
              aria-label="Uzasadnienie wyjątku"
            />
          </label>
          <div className="flex justify-end lg:col-span-2">
            <Button
              loading={createMutation.isPending}
              disabled={
                !userId || !jobId || reason.trim().length < 10 || expiryInvalid
              }
              onClick={() => createMutation.mutate()}
            >
              <KeyRound className="h-4 w-4" />
              Nadaj wyjątek
            </Button>
          </div>
        </CardContent>
      </Card>

      {exceptions.length === 0 ? (
        <Card>
          <EmptyState
            icon={KeyRound}
            title="Brak wyjątków"
            description="Nie nadano jeszcze jednorazowych odstępstw od Priority Lock."
          />
        </Card>
      ) : (
        <div className="space-y-3">
          {exceptions.map((item) => {
            const revokeReason = revokeReasons[item.id] ?? ""
            return (
              <Card key={item.id}>
                <CardContent className="space-y-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="font-medium text-foreground">
                        {memberName(item.user_id)} · {jobTitle(item.job_id)}
                      </p>
                      <p className="mt-1 text-sm text-muted-foreground">
                        {item.reason}
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        Ważny do {formatPriorityDate(item.expires_at)}
                      </p>
                    </div>
                    <Badge
                      variant={item.status === "approved" ? "warning" : "neutral"}
                    >
                      {item.status}
                    </Badge>
                  </div>
                  {item.status === "approved" ? (
                    <div className="flex flex-col gap-2 border-t border-border pt-3 sm:flex-row">
                      <Input
                        value={revokeReason}
                        onChange={(event) =>
                          setRevokeReasons((current) => ({
                            ...current,
                            [item.id]: event.target.value,
                          }))
                        }
                        placeholder="Powód odwołania wyjątku"
                        aria-label={`Powód odwołania wyjątku ${item.id}`}
                      />
                      <Button
                        variant="outline"
                        loading={
                          revokeMutation.isPending &&
                          revokeMutation.variables?.exceptionId === item.id
                        }
                        disabled={revokeReason.trim().length < 10}
                        onClick={() =>
                          revokeMutation.mutate({
                            exceptionId: item.id,
                            revokeReason: revokeReason.trim(),
                          })
                        }
                      >
                        Odwołaj
                      </Button>
                    </div>
                  ) : null}
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}

export function TeamAllocationBoard() {
  const user = useAuthStore((state) => state.user)
  const hydrated = useAuthStore((state) => state.hydrated)
  const canManage = hasRole(user, "head_of_recruitment")
  const queryClient = useQueryClient()
  const { showError, showSuccess } = useToast()
  const [activeTab, setActiveTab] = useState<BoardTab>("plan")
  const [draft, setDraft] = useState<PriorityPlan | null>(null)
  const [editorMembers, setEditorMembers] = useState<EditableMember[]>([])
  const [note, setNote] = useState("")
  const [validationErrors, setValidationErrors] = useState<string[]>([])
  const [operationError, setOperationError] = useState<string | null>(null)

  const teamQuery = useQuery({
    queryKey: priorityWorkQueryKeys.team(),
    queryFn: priorityWorkApi.getTeam,
    enabled: hydrated && canManage,
    staleTime: 60_000,
  })
  const statusQuery = useQuery({
    queryKey: priorityWorkQueryKeys.status(),
    queryFn: priorityWorkApi.getStatus,
    enabled: hydrated && canManage,
    staleTime: 30_000,
  })
  const exceptionsQuery = useQuery({
    queryKey: priorityWorkQueryKeys.exceptions(),
    queryFn: () => priorityWorkApi.listExceptions(),
    enabled: hydrated && canManage,
    staleTime: 30_000,
  })

  useEffect(() => {
    if (!teamQuery.data || draft) return
    setEditorMembers(membersToEditable(teamQuery.data.members))
  }, [draft, teamQuery.data])

  const createDraftMutation = useMutation({
    mutationFn: () =>
      priorityWorkApi.createDraft({
        source_plan_id: teamQuery.data?.plan?.id,
        note: "Przegląd priorytetów zespołu",
      }),
    onSuccess: (created) => {
      setDraft(created)
      setNote(created.note ?? "")
      const teamMembers = teamQuery.data?.members ?? []
      const snapshotMembers = created.members ?? []
      const teamUserIds = new Set(teamMembers.map((member) => member.user_id))
      const sourceMembers =
        snapshotMembers.length > 0
          ? [
              ...teamMembers.map(
                (member) =>
                  snapshotMembers.find(
                    (snapshot) => snapshot.user_id === member.user_id,
                  ) ?? member,
              ),
              ...snapshotMembers.filter(
                (snapshot) => !teamUserIds.has(snapshot.user_id),
              ),
            ]
          : teamMembers
      setEditorMembers(
        membersToEditable(sourceMembers, teamMembers),
      )
      setValidationErrors([])
      setOperationError(null)
      showSuccess("Szkic planu jest gotowy do edycji.")
    },
    onError: (error) => {
      const message = extractErrorMsg(error)
      setOperationError(message)
      showError(message)
    },
  })

  const saveMutation = useMutation({
    mutationFn: () => {
      if (!draft) throw new Error("Brak szkicu planu")
      return priorityWorkApi.updatePlan(draft.id, {
        expected_version: draft.row_version,
        note: note.trim() || null,
        members: serializeMembers(editorMembers),
      })
    },
    onSuccess: (saved) => {
      setDraft(saved)
      setValidationErrors([])
      setOperationError(null)
      showSuccess("Szkic planu został zapisany.")
    },
    onError: (error) => {
      const message = extractErrorMsg(error)
      setOperationError(message)
      showError(message)
    },
  })

  const publishMutation = useMutation({
    mutationFn: async () => {
      if (!draft) throw new Error("Brak szkicu planu")
      const saved = await priorityWorkApi.updatePlan(draft.id, {
        expected_version: draft.row_version,
        note: note.trim() || null,
        members: serializeMembers(editorMembers),
      })
      return priorityWorkApi.publishPlan(saved.id, saved.row_version)
    },
    onSuccess: () => {
      setDraft(null)
      setValidationErrors([])
      setOperationError(null)
      showSuccess("Nowy plan został opublikowany.")
      queryClient.invalidateQueries({ queryKey: priorityWorkQueryKeys.all })
    },
    onError: (error) => {
      const message = extractErrorMsg(error)
      setOperationError(message)
      showError(message)
    },
  })

  const validate = () => {
    const errors = validateMembers(editorMembers)
    setValidationErrors(errors)
    return errors.length === 0
  }

  const updateMember = (nextMember: EditableMember) => {
    setEditorMembers((members) =>
      members.map((member) =>
        member.user_id === nextMember.user_id ? nextMember : member,
      ),
    )
  }

  const blockers = useMemo(
    () =>
      (teamQuery.data?.members ?? []).flatMap((member) =>
        member.assignments.flatMap((assignment) =>
          assignment.blocker
            ? [
                {
                  ...assignment.blocker,
                  userName: member.user_name,
                  jobTitle: assignment.job.title,
                },
              ]
            : [],
        ),
      ),
    [teamQuery.data?.members],
  )

  const carryOver = useMemo(
    () =>
      (teamQuery.data?.members ?? []).flatMap(
        (member) => member.carry_over ?? [],
      ),
    [teamQuery.data?.members],
  )

  if (!hydrated || !canManage) return null
  if (teamQuery.isPending) return <PriorityWorkLoading rows={4} />
  if (teamQuery.isError) {
    return (
      <Card>
        <WidgetErrorBlock
          title="Nie udało się załadować planu zespołu."
          error={teamQuery.error}
          onRetry={() => teamQuery.refetch()}
        />
      </Card>
    )
  }

  const team = teamQuery.data
  const tabs = [
    { value: "plan", label: "Plan zespołu", icon: ClipboardList },
    {
      value: "blockers",
      label: "Blockery",
      icon: ShieldAlert,
      count: blockers.filter((blocker) =>
        ["pending", "accepted"].includes(blocker.status),
      ).length,
    },
    {
      value: "carry-over",
      label: "Carry-over",
      icon: History,
      count:
        carryOver.length ||
        team.members.reduce(
          (total, member) => total + (member.carry_over_count ?? 0),
          0,
        ),
    },
    {
      value: "unowned",
      label: "Bez właściciela",
      icon: Inbox,
      count: team.unowned_carry_over_count,
    },
    {
      value: "exceptions",
      label: "Wyjątki",
      icon: KeyRound,
      count: (exceptionsQuery.data ?? []).filter(
        (item) => item.status === "approved",
      ).length,
    },
  ]

  return (
    <section
      className="space-y-4"
      aria-labelledby="team-allocation-board-title"
    >
      <AllocationWorkloadBoard />
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <UsersRound className="h-5 w-5 text-primary" />
                <CardTitle id="team-allocation-board-title">
                  Team Allocation Board
                </CardTitle>
              </div>
              <CardDescription>
                Ostateczny plan nowego sourcingu. Carry-over pozostaje osobnym,
                obowiązkowym strumieniem pracy.
              </CardDescription>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  void teamQuery.refetch()
                  void statusQuery.refetch()
                  void exceptionsQuery.refetch()
                }}
                disabled={
                  teamQuery.isFetching ||
                  statusQuery.isFetching ||
                  exceptionsQuery.isFetching
                }
              >
                <RefreshCw
                  className={
                    teamQuery.isFetching ||
                    statusQuery.isFetching ||
                    exceptionsQuery.isFetching
                      ? "h-4 w-4 animate-spin"
                      : "h-4 w-4"
                  }
                />
                Odśwież
              </Button>
              {!draft ? (
                <Button
                  size="sm"
                  loading={createDraftMutation.isPending}
                  onClick={() => createDraftMutation.mutate()}
                >
                  <Plus className="h-4 w-4" />
                  {team.plan ? "Nowa wersja planu" : "Utwórz pierwszy plan"}
                </Button>
              ) : (
                <>
                  <Button
                    variant="outline"
                    size="sm"
                    loading={saveMutation.isPending}
                    onClick={() => {
                      if (validate()) saveMutation.mutate()
                    }}
                  >
                    <Save className="h-4 w-4" />
                    Zapisz szkic
                  </Button>
                  <Button
                    size="sm"
                    loading={publishMutation.isPending}
                    onClick={() => {
                      if (validate()) publishMutation.mutate()
                    }}
                  >
                    <Send className="h-4 w-4" />
                    Opublikuj
                  </Button>
                </>
              )}
            </div>
          </div>
          <div className="mt-3 space-y-2">
            <ModeNotice mode={team.mode} />
            <PlanReviewNotice plan={team.plan} overdue={team.overdue} />
            {draft ? (
              <Alert
                variant="info"
                title={`Edytujesz szkic v${draft.version}`}
                description="Opublikowany plan nadal obowiązuje. Zmiany wejdą w życie dopiero po publikacji."
              />
            ) : null}
            {operationError ? (
              <Alert
                variant="error"
                title="Nie udało się wykonać operacji"
                description={operationError}
              />
            ) : null}
          </div>
        </CardHeader>
        <CardContent>
          <TabbedNav
            tabs={tabs}
            value={activeTab}
            onValueChange={(value) => setActiveTab(value as BoardTab)}
            overflow="scroll"
          />
        </CardContent>
      </Card>

      <ReconciliationStatusPanel
        status={statusQuery.data}
        loading={statusQuery.isPending}
        error={statusQuery.error}
        onRetry={() => void statusQuery.refetch()}
      />

      {activeTab === "plan" ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]">
          <div className="space-y-4">
            {validationErrors.length > 0 ? (
              <Alert variant="error" title="Plan wymaga poprawy">
                <ul className="mt-2 list-disc space-y-1 pl-4 text-xs">
                  {validationErrors.map((error) => (
                    <li key={error}>{error}</li>
                  ))}
                </ul>
              </Alert>
            ) : null}
            {draft ? (
              <>
                <Card>
                  <CardContent>
                    <label className="block space-y-1.5 text-sm">
                      <span className="font-medium text-foreground">
                        Notatka do wersji
                      </span>
                      <Textarea
                        value={note}
                        onChange={(event) => setNote(event.target.value)}
                        placeholder="Co zmienia ta wersja planu?"
                        rows={2}
                      />
                    </label>
                  </CardContent>
                </Card>
                {editorMembers.map((member) => (
                  <EditableMemberCard
                    key={member.user_id}
                    member={member}
                    demands={team.demands.filter((demand) =>
                      ["open", "covered"].includes(demand.status),
                    )}
                    onChange={updateMember}
                  />
                ))}
              </>
            ) : team.members.length === 0 ? (
              <Card>
                <EmptyState
                  icon={UsersRound}
                  title="Brak osób do zaplanowania"
                  description="Najpierw skonfiguruj role i Competence Categories zespołu."
                />
              </Card>
            ) : (
              team.members.map((member) => (
                <ReadOnlyMemberCard key={member.user_id} member={member} />
              ))
            )}
          </div>

          <div className="space-y-3 xl:sticky xl:top-4 xl:self-start">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">
                  Otwarte zapotrzebowania
                </CardTitle>
                <CardDescription>
                  Demand określa rezultat DL; assignment wskazuje osobę i
                  kolejność pracy.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {team.demands.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    Delivery Leadzi nie zgłosili aktywnych potrzeb.
                  </p>
                ) : (
                  <div className="space-y-2">
                    {team.demands.map((demand) => (
                      <DemandSummary key={demand.id} demand={demand} />
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      ) : null}

      {activeTab === "blockers" ? (
        blockers.length === 0 ? (
          <Card>
            <EmptyState
              icon={Check}
              title="Brak blockerów"
              description="Zespół nie zgłosił przeszkód wymagających decyzji."
            />
          </Card>
        ) : (
          <div className="space-y-3">
            {blockers.map((blocker) => (
              <BlockerDecisionRow key={blocker.id} blocker={blocker} />
            ))}
          </div>
        )
      ) : null}

      {activeTab === "carry-over" ? (
        carryOver.length > 0 ? (
          <div className="space-y-3">
            {carryOver.map((item) => (
              <HandoffRow
                key={item.process_id}
                item={item}
                members={team.members}
              />
            ))}
          </div>
        ) : (
          <Card>
            <CardContent>
              {team.members.some((member) => member.carry_over_count) ? (
                <div className="space-y-3">
                  {team.members
                    .filter((member) => (member.carry_over_count ?? 0) > 0)
                    .map((member) => (
                      <div
                        key={member.user_id}
                        className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2"
                      >
                        <span className="text-sm font-medium text-foreground">
                          {member.user_name}
                        </span>
                        <div className="flex gap-2">
                          <Badge variant="outline">
                            {member.carry_over_count} procesów
                          </Badge>
                          {(member.urgent_carry_over_count ?? 0) > 0 ? (
                            <Badge variant="warning">
                              {member.urgent_carry_over_count} pilne
                            </Badge>
                          ) : null}
                        </div>
                      </div>
                    ))}
                </div>
              ) : (
                <EmptyState
                  icon={History}
                  title="Brak procesów carry-over"
                  description="Zespół nie ma rozpoczętych procesów poza bieżącym planem."
                />
              )}
            </CardContent>
          </Card>
        )
      ) : null}

      {activeTab === "unowned" ? (
        team.unowned_carry_over.length > 0 ? (
          <div className="space-y-3">
            <Card>
              <CardContent>
              <Alert
                variant="warning"
                title={`${team.unowned_carry_over_count} procesów bez właściciela`}
                description="Przypisz właścicieli przed włączeniem trybu enforce. Procesy nie mogą zniknąć po zmianie planu lub dezaktywacji użytkownika."
                icon={AlertTriangle}
              />
              </CardContent>
            </Card>
            {team.unowned_carry_over.map((item) => (
              <HandoffRow
                key={item.process_id}
                item={item}
                members={team.members}
              />
            ))}
          </div>
        ) : (
          <Card>
            <EmptyState
              icon={Inbox}
              title="Wszystkie procesy mają właściciela"
              description="Nie ma nieprzypisanego carry-over ani inboundu."
            />
          </Card>
        )
      ) : null}

      {activeTab === "exceptions" ? (
        <ExceptionsPanel
          exceptions={exceptionsQuery.data ?? []}
          members={team.members}
          demands={team.demands}
          loading={exceptionsQuery.isPending}
          error={exceptionsQuery.error}
          onRetry={() => void exceptionsQuery.refetch()}
        />
      ) : null}
    </section>
  )
}
