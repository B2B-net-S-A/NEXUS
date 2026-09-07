"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  BriefcaseBusiness,
  CheckCircle2,
  Clock3,
  Phone,
  PhoneCall,
  RefreshCw,
  UserRoundX,
} from "lucide-react";

import { ContactOutcomeSheet } from "@/components/candidate-contact/ContactOutcomeSheet";
import { ContactStatusBadge } from "@/components/candidate-contact/ContactStatusBadge";
import { PageHeader } from "@/components/ds";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  candidateContactApi,
  candidateContactFullName,
  candidateContactQueryKeys,
  type CandidateContactAttemptInput,
  type CandidateContactCase,
  type CandidateContactQueueResponse,
} from "@/lib/candidate-contact";
import { extractErrorMsg } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useCandidateContactFeature } from "@/hooks/useCandidateContactFeature";

type QueueFilter = "all" | "due" | "callbacks" | "exceptions";

const ACTIONABLE_STATUSES = new Set(["queued", "callback_due"]);
const EXCEPTION_STATUSES = new Set([
  "unassigned",
  "awaiting_capacity",
  "blocked_no_phone",
]);

function initials(candidate: CandidateContactCase["candidate"]): string {
  const value = candidateContactFullName(candidate)
    .split(/\s+/)
    .map((part) => part[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
  return value || "?";
}

function contactDate(value: string | null | undefined): string {
  if (!value) return "Brak terminu";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Brak terminu";
  return new Intl.DateTimeFormat("pl-PL", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/Warsaw",
  }).format(date);
}

function isOverdue(item: CandidateContactCase, nowMs: number): boolean {
  const due = item.callback_at ?? item.due_at;
  return Boolean(due && new Date(due).getTime() < nowMs);
}

function deduplicateCases(items: CandidateContactCase[]): CandidateContactCase[] {
  const byCandidate = new Map<number, CandidateContactCase>();
  for (const item of items) {
    const existing = byCandidate.get(item.candidate.id);
    if (!existing) {
      byCandidate.set(item.candidate.id, item);
      continue;
    }
    const newest = item.version > existing.version ? item : existing;
    const older = newest === item ? existing : item;
    const opportunities = new Map(
      older.opportunities.map((opportunity) => [
        opportunity.job_id,
        opportunity,
      ]),
    );
    for (const opportunity of newest.opportunities) {
      opportunities.set(opportunity.job_id, opportunity);
    }
    byCandidate.set(item.candidate.id, {
      ...newest,
      opportunities: Array.from(opportunities.values()),
    });
  }
  return Array.from(byCandidate.values());
}

export interface ContactQueueWorkspaceProps {
  initialData?: CandidateContactQueueResponse;
  now?: string | Date;
  featureEnabledOverride?: boolean;
  submitAttempt?: (
    caseId: number,
    input: CandidateContactAttemptInput,
    idempotencyKey: string,
  ) => Promise<CandidateContactCase>;
}

export function ContactQueueWorkspace({
  initialData,
  now,
  featureEnabledOverride,
  submitAttempt,
}: ContactQueueWorkspaceProps) {
  const [filter, setFilter] = React.useState<QueueFilter>("all");
  const [selectedCase, setSelectedCase] =
    React.useState<CandidateContactCase | null>(null);
  const contactFeature = useCandidateContactFeature({
    enabledOverride: featureEnabledOverride,
  });
  const queueQuery = useQuery({
    queryKey: candidateContactQueryKeys.queue(),
    queryFn: async () => {
      const first = await candidateContactApi.queue({ limit: 100 });
      const items = [...first.items];
      let cursor = first.next_cursor;
      const seen = new Set<string>();
      while (cursor && !seen.has(cursor)) {
        seen.add(cursor);
        const page = await candidateContactApi.queue({ limit: 100, cursor });
        items.push(...page.items);
        cursor = page.next_cursor;
      }
      return { ...first, items, next_cursor: null };
    },
    enabled: initialData === undefined && contactFeature.enabled,
    initialData,
    staleTime: 30_000,
  });

  const items = React.useMemo(
    () => deduplicateCases(queueQuery.data?.items ?? []),
    [queueQuery.data?.items],
  );
  React.useEffect(() => {
    if (!selectedCase) return;
    const refreshedCase = items.find((item) => item.id === selectedCase.id);
    if (
      refreshedCase &&
      refreshedCase.version !== selectedCase.version
    ) {
      setSelectedCase(refreshedCase);
    }
  }, [items, selectedCase]);
  const nowMs = React.useMemo(
    () => (now ? new Date(now).getTime() : Date.now()),
    [now],
  );
  const visibleItems = React.useMemo(() => {
    switch (filter) {
      case "due":
        return items.filter(
          (item) =>
            ACTIONABLE_STATUSES.has(item.status) && isOverdue(item, nowMs),
        );
      case "callbacks":
        return items.filter((item) => item.status === "callback_due");
      case "exceptions":
        return items.filter((item) => EXCEPTION_STATUSES.has(item.status));
      default:
        return items;
    }
  }, [filter, items, nowMs]);

  const utilization = queueQuery.data?.utilization ?? {
    used: 0,
    capacity: 20,
  };
  const utilizationPct = Math.min(
    100,
    Math.round((utilization.used / Math.max(utilization.capacity, 1)) * 100),
  );
  const overdueCount = items.filter(
    (item) =>
      ACTIONABLE_STATUSES.has(item.status) && isOverdue(item, nowMs),
  ).length;
  const callbackCount = items.filter(
    (item) => item.status === "callback_due",
  ).length;
  const exceptionsCount = items.filter((item) =>
    EXCEPTION_STATUSES.has(item.status),
  ).length;

  if (contactFeature.isPending) {
    return (
      <div className="mx-auto max-w-[1400px] p-4 md:p-6">
        <Card className="p-8 text-center text-sm text-muted-foreground">
          Sprawdzanie dostępności kolejki…
        </Card>
      </div>
    );
  }

  if (!contactFeature.enabled) {
    return (
      <div className="mx-auto max-w-[1400px] space-y-5 p-4 md:p-6">
        <PageHeader
          density="compact"
          eyebrow="Kandydaci · Kontakt"
          title="Do przedzwonienia"
          description="Globalna koordynacja pierwszego kontaktu z kandydatem."
        />
        <Card className="border-dashed p-8 text-center">
          <PhoneCall
            aria-hidden
            className="mx-auto h-8 w-8 text-muted-foreground"
          />
          <p className="mt-3 font-medium text-foreground">
            Kolejka kontaktu jest obecnie wyłączona
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            {contactFeature.isError
              ? "Nie udało się potwierdzić statusu funkcji. Spróbuj ponownie później."
              : "Zostanie udostępniona po kontrolowanej aktywacji przez administratora."}
          </p>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1400px] space-y-5 p-4 md:p-6">
      <PageHeader
        density="compact"
        eyebrow="Kandydaci · Kontakt"
        title="Do przedzwonienia"
        description="Każdy kandydat występuje raz, niezależnie od liczby otwartych rekrutacji."
        actions={
          initialData === undefined ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => void queueQuery.refetch()}
              loading={queueQuery.isFetching}
            >
              <RefreshCw aria-hidden className="h-4 w-4" />
              Odśwież
            </Button>
          ) : null
        }
      />

      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
        <Card className="p-4">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-xs font-medium text-muted-foreground">
                Wykorzystanie kolejki
              </p>
              <p className="mt-1 text-2xl font-semibold tabular-nums text-foreground">
                {utilization.used}/{utilization.capacity}
              </p>
            </div>
            <PhoneCall aria-hidden className="h-7 w-7 text-primary" />
          </div>
          <div
            className="mt-3 h-2 overflow-hidden rounded-full bg-muted"
            role="progressbar"
            aria-label="Wykorzystanie kolejki kontaktu"
            aria-valuemin={0}
            aria-valuemax={utilization.capacity}
            aria-valuenow={utilization.used}
          >
            <div
              className={cn(
                "h-full rounded-full transition-[width]",
                utilizationPct >= 100 ? "bg-warning" : "bg-primary",
              )}
              style={{ width: `${utilizationPct}%` }}
            />
          </div>
        </Card>

        <div className="grid grid-cols-3 gap-2">
          <Card className="min-w-24 p-3 text-center">
            <p className="text-xl font-semibold tabular-nums text-foreground">
              {overdueCount}
            </p>
            <p className="text-[11px] text-muted-foreground">Zaległe</p>
          </Card>
          <Card className="min-w-24 p-3 text-center">
            <p className="text-xl font-semibold tabular-nums text-foreground">
              {callbackCount}
            </p>
            <p className="text-[11px] text-muted-foreground">Callbacki</p>
          </Card>
          <Card className="min-w-24 p-3 text-center">
            <p className="text-xl font-semibold tabular-nums text-foreground">
              {exceptionsCount}
            </p>
            <p className="text-[11px] text-muted-foreground">Wyjątki</p>
          </Card>
        </div>
      </div>

      <div
        className="flex gap-2 overflow-x-auto pb-1"
        role="tablist"
        aria-label="Filtry kolejki kontaktu"
      >
        {[
          { value: "all", label: `Wszystkie (${items.length})` },
          { value: "due", label: `Zaległe (${overdueCount})` },
          { value: "callbacks", label: `Callbacki (${callbackCount})` },
          { value: "exceptions", label: `Wyjątki (${exceptionsCount})` },
        ].map((item) => (
          <Button
            key={item.value}
            type="button"
            size="sm"
            variant={filter === item.value ? "primary" : "outline"}
            role="tab"
            aria-selected={filter === item.value}
            onClick={() => setFilter(item.value as QueueFilter)}
          >
            {item.label}
          </Button>
        ))}
      </div>

      {queueQuery.isPending ? (
        <Card className="p-8 text-center text-sm text-muted-foreground">
          Ładowanie kolejki…
        </Card>
      ) : queueQuery.isError ? (
        <Card className="border-destructive/30 p-5">
          <div className="flex items-start gap-3">
            <AlertTriangle
              aria-hidden
              className="mt-0.5 h-5 w-5 shrink-0 text-destructive"
            />
            <div>
              <p className="font-medium text-foreground">
                Nie udało się pobrać kolejki.
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                {extractErrorMsg(queueQuery.error)}
              </p>
              <Button
                className="mt-3"
                size="sm"
                variant="outline"
                onClick={() => void queueQuery.refetch()}
              >
                Spróbuj ponownie
              </Button>
            </div>
          </div>
        </Card>
      ) : visibleItems.length === 0 ? (
        <Card className="border-dashed p-10 text-center">
          <CheckCircle2 className="mx-auto h-8 w-8 text-success" />
          <p className="mt-3 font-medium text-foreground">
            Brak kandydatów w tym widoku
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            Kolejka zostanie uzupełniona automatycznie po przypisaniu kontaktu.
          </p>
        </Card>
      ) : (
        <div className="grid gap-3">
          {visibleItems.map((item) => {
            const fullName = candidateContactFullName(item.candidate);
            const due = item.callback_at ?? item.due_at;
            const overdue =
              ACTIONABLE_STATUSES.has(item.status) && isOverdue(item, nowMs);
            const canLog =
              ACTIONABLE_STATUSES.has(item.status) &&
              Boolean(item.candidate.phone);
            return (
              <Card
                key={item.candidate.id}
                className={cn(
                  "p-4 transition-colors hover:border-primary/40",
                  overdue && "border-warning/50",
                )}
              >
                <div className="flex flex-col gap-4 lg:flex-row lg:items-center">
                  <div className="flex min-w-0 flex-1 items-start gap-3">
                    <Avatar>
                      <AvatarFallback>{initials(item.candidate)}</AvatarFallback>
                    </Avatar>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <Link
                          href={`/candidates/${item.candidate.id}`}
                          className="truncate font-semibold text-foreground hover:text-primary"
                        >
                          {fullName}
                        </Link>
                        <ContactStatusBadge contactCase={item} size="sm" />
                        {overdue ? (
                          <Badge variant="warning" size="sm">
                            Po terminie
                          </Badge>
                        ) : null}
                      </div>
                      <p className="mt-0.5 truncate text-xs text-muted-foreground">
                        {item.candidate.current_role ??
                          item.candidate.position ??
                          "Brak stanowiska"}
                      </p>
                      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                        <span className="inline-flex items-center gap-1">
                          <Clock3 aria-hidden className="h-3.5 w-3.5" />
                          {contactDate(due)}
                        </span>
                        <span>
                          Próba {Math.min((item.attempts_in_cycle ?? 0) + 1, 2)}
                          /2
                        </span>
                        {item.owner ? <span>Opiekun: {item.owner.name}{item.substitution ? ` · Zastępuje: ${item.effective_owner?.name ?? "—"}` : ""}</span> : null}
                      </div>
                    </div>
                  </div>

                  <div className="min-w-0 flex-1">
                    <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                      Otwarte rekrutacje ({item.opportunities.length})
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {item.opportunities.map((opportunity) => (
                        <span
                          key={opportunity.job_id}
                          className="inline-flex flex-col items-start gap-0.5"
                        >
                          <Badge
                            variant="outline"
                            title={opportunity.client_name ?? undefined}
                          >
                            <BriefcaseBusiness
                              aria-hidden
                              className="h-3 w-3"
                            />
                            {opportunity.job_title}
                          </Badge>
                          {opportunity.owner ? (
                            <span className="pl-2 text-[11px] text-muted-foreground">
                              właściciel: {opportunity.owner.name}
                            </span>
                          ) : null}
                        </span>
                      ))}
                    </div>
                  </div>

                  <div className="flex shrink-0 flex-wrap items-center gap-2">
                    {item.candidate.phone ? (
                      <a
                        href={`tel:${item.candidate.phone}`}
                        className={buttonVariants({
                          variant: "outline",
                          size: "sm",
                        })}
                      >
                        <Phone aria-hidden className="h-4 w-4" />
                        {item.candidate.phone}
                      </a>
                    ) : (
                      <Badge variant="danger">
                        <UserRoundX aria-hidden className="h-3.5 w-3.5" />
                        Brak numeru
                      </Badge>
                    )}
                    <Button
                      size="sm"
                      disabled={!canLog}
                      onClick={() => setSelectedCase(item)}
                    >
                      Zaloguj wynik
                      <ArrowRight aria-hidden className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      <ContactOutcomeSheet
        contactCase={selectedCase}
        open={selectedCase !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedCase(null);
        }}
        onSaved={(updated) => {
          setSelectedCase(null);
          void updated;
        }}
        onConflict={() => void queueQuery.refetch()}
        submitAttempt={submitAttempt}
      />
    </div>
  );
}
