"use client"

import Link from "next/link"
import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  CircleDashed,
  Database,
  Linkedin,
  LockKeyhole,
} from "lucide-react"

import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import type {
  PriorityAssignment,
  PriorityChannel,
  PriorityPlan,
  PriorityRank,
  PriorityWorkMode,
} from "@/lib/priority-work-api"

const RANK_VARIANT: Record<
  PriorityRank,
  "burgundy" | "soft" | "info" | "warning" | "neutral"
> = {
  A: "burgundy",
  B: "soft",
  C: "info",
  D: "warning",
  E: "neutral",
}

const GATE_COPY: Record<
  string,
  { label: string; variant: "success" | "warning" | "danger" | "neutral" }
> = {
  open: { label: "Możesz dodawać", variant: "success" },
  available: { label: "Możesz dodawać", variant: "success" },
  target_reached: { label: "Target osiągnięty", variant: "neutral" },
  higher_rank_behind: {
    label: "Najpierw wyższy priorytet",
    variant: "warning",
  },
  blocked_by_higher_rank: {
    label: "Najpierw wyższy priorytet",
    variant: "warning",
  },
  blocked: { label: "Nowe osoby zablokowane", variant: "danger" },
}

export function isPlanOverdue(plan: PriorityPlan | null): boolean {
  if (!plan) return false
  if (typeof plan.overdue === "boolean") return plan.overdue
  if (!plan.review_due_at) return false
  const due = Date.parse(plan.review_due_at)
  return Number.isFinite(due) && due < Date.now()
}

export function formatPriorityDate(value?: string | null): string {
  if (!value) return "—"
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return new Intl.DateTimeFormat("pl-PL", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed)
}

export function RankBadge({ rank }: { rank: PriorityRank }) {
  return (
    <Badge
      variant={RANK_VARIANT[rank]}
      size="lg"
      className="min-w-7 justify-center font-semibold"
      aria-label={`Priorytet ${rank}`}
    >
      {rank}
    </Badge>
  )
}

export function ChannelBadge({ channel }: { channel: PriorityChannel }) {
  if (channel === "mixed") {
    return (
      <Badge variant="outline" size="md">
        <Database className="h-3 w-3" aria-hidden="true" />
        <Linkedin className="h-3 w-3" aria-hidden="true" />
        TAC / mieszany · Baza + LinkedIn
      </Badge>
    )
  }
  const Icon = channel === "linkedin" ? Linkedin : Database
  return (
    <Badge variant="outline" size="md">
      <Icon className="h-3 w-3" aria-hidden="true" />
      {channel === "linkedin" ? "LinkedIn" : "Baza NEXUS"}
    </Badge>
  )
}

export function GateBadge({ state }: { state: string }) {
  const config = GATE_COPY[state] ?? {
    label: state.replaceAll("_", " "),
    variant: "neutral" as const,
  }
  const Icon =
    config.variant === "success"
      ? CheckCircle2
      : config.variant === "danger"
        ? LockKeyhole
        : config.variant === "warning"
          ? AlertTriangle
          : CircleDashed
  return (
    <Badge variant={config.variant} size="md">
      <Icon className="h-3 w-3" aria-hidden="true" />
      {config.label}
    </Badge>
  )
}

export function ModeNotice({ mode }: { mode: PriorityWorkMode }) {
  if (mode === "enforce") return null
  if (mode === "shadow") {
    return (
      <Alert
        variant="warning"
        title="Tryb obserwacyjny"
        description="System pokazuje plan i wykrywa pracę poza priorytetem, ale jeszcze jej nie blokuje."
        data-testid="priority-work-shadow-notice"
      />
    )
  }
  return (
    <Alert
      variant="info"
      title="Priority Work jest wyłączony"
      description="Plan jest widoczny informacyjnie. Obowiązują dotychczasowe zasady pracy."
      data-testid="priority-work-off-notice"
    />
  )
}

export function PlanReviewNotice({
  plan,
  overdue,
}: {
  plan: PriorityPlan | null
  overdue?: boolean
}) {
  if (!plan) return null
  const isOverdue = overdue ?? isPlanOverdue(plan)
  if (isOverdue) {
    return (
      <Alert
        variant="warning"
        title="Plan wymaga przeglądu"
        description={`Termin przeglądu minął ${formatPriorityDate(plan.review_due_at)}. Plan nadal obowiązuje do publikacji kolejnej wersji.`}
        data-testid="priority-work-overdue-notice"
      />
    )
  }
  if (!plan.review_due_at) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <CalendarClock className="h-3.5 w-3.5" aria-hidden="true" />
        <span>Plan v{plan.version} · termin przeglądu po publikacji</span>
      </div>
    )
  }
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <CalendarClock className="h-3.5 w-3.5" aria-hidden="true" />
      <span>
        Plan v{plan.version} · przegląd do{" "}
        {formatPriorityDate(plan.review_due_at)}
      </span>
    </div>
  )
}

export function AssignmentProgress({
  assignment,
}: {
  assignment: PriorityAssignment
}) {
  const verificationPct =
    assignment.verification_target > 0
      ? Math.min(
          100,
          (assignment.progress.verifications /
            assignment.verification_target) *
            100,
        )
      : 0
  const recommendationPct =
    assignment.recommendation_target > 0
      ? Math.min(
          100,
          (assignment.progress.recommendations /
            assignment.recommendation_target) *
            100,
        )
      : 0

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <MetricProgress
        label="Weryfikacje"
        value={assignment.progress.verifications}
        target={assignment.verification_target}
        percentage={verificationPct}
      />
      <MetricProgress
        label="Rekomendacje"
        value={assignment.progress.recommendations}
        target={assignment.recommendation_target}
        percentage={recommendationPct}
      />
    </div>
  )
}

function MetricProgress({
  label,
  value,
  target,
  percentage,
}: {
  label: string
  value: number
  target: number
  percentage: number
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-medium tabular-nums text-foreground">
          {value}/{target}
        </span>
      </div>
      <Progress value={percentage} aria-label={`${label}: ${value} z ${target}`} />
    </div>
  )
}

export function PriorityJobLink({
  job,
  className,
}: {
  job: PriorityAssignment["job"]
  className?: string
}) {
  return (
    <Link
      href={`/jobs/${job.id}`}
      className={cn(
        "font-medium text-foreground transition-colors hover:text-primary",
        className,
      )}
    >
      {job.title}
    </Link>
  )
}

export function PriorityWorkLoading({
  rows = 3,
}: {
  rows?: number
}) {
  return (
    <Card className="space-y-4" aria-label="Ładowanie planu pracy">
      <div className="flex items-center justify-between gap-3">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-5 w-24" />
      </div>
      {Array.from({ length: rows }, (_, index) => (
        <Skeleton key={index} className="h-24 w-full" />
      ))}
    </Card>
  )
}
