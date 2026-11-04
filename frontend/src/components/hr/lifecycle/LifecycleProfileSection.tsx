"use client";

import Link from "next/link";

import { StatusDot } from "@/components/ds/StatusDot";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { HrConfig } from "@/lib/api/hr";
import {
  CASE_STATUS_LABELS,
  usePersonLifecycleSummary,
  type PersonLifecycleSummary,
} from "@/lib/api/hr-lifecycle";
import { isForbiddenError, isNotFoundError } from "@/lib/view-state";
import { formatWeekdayDayPl } from "@/lib/date-pl";

import { CASE_STATUS_TONE, ACCOUNT_RESULT_LABELS, progressLabel } from "./lifecycle-format";

/** Zdanie o sprawie do kartoteki (czysta funkcja — test bez zapytań). */
export function lifecycleSummaryLine(summary: PersonLifecycleSummary): string | null {
  const item = summary.case;
  if (!item) return null;
  if (item.kind === "onboarding") {
    return `Wejście · start ${formatWeekdayDayPl(item.start_date)} · ${progressLabel(item.progress)}`;
  }
  if (item.account_close_result) {
    return `Odejście · ostatni dzień ${formatWeekdayDayPl(item.last_working_day)} · ${ACCOUNT_RESULT_LABELS[item.account_close_result]}`;
  }
  const handed = item.handover_executed_at ? " · praca przekazana" : "";
  return `Odejście · ostatni dzień ${formatWeekdayDayPl(item.last_working_day)}${handed} · ${progressLabel(item.progress)}`;
}

interface LifecycleProfileSectionProps {
  userId: number;
  config: HrConfig;
}

/**
 * Sekcja „Wejście i odejście” w kartotece osoby (wpina ją `PersonProfile`).
 * Bez dostępu albo przy wyłączonym module — nic nie pokazuje (kartoteka
 * ma własne stany błędu; ta sekcja jest dodatkiem).
 */
export function LifecycleProfileSection({ userId, config }: LifecycleProfileSectionProps) {
  const open = config.open_modules.lifecycle;
  const summary = usePersonLifecycleSummary(userId, open);
  if (!open) return null;
  if (summary.isError && (isForbiddenError(summary.error) || isNotFoundError(summary.error))) {
    return null;
  }
  if (summary.isLoading) {
    return (
      <Card className="p-4">
        <p className="text-sm text-muted-foreground">Wczytywanie wejścia i odejścia…</p>
      </Card>
    );
  }
  if (summary.isError || !summary.data) {
    return (
      <Card className="p-4">
        <p role="alert" className="text-sm text-destructive">
          Nie udało się wczytać wejścia i odejścia.{" "}
          <button type="button" className="underline" onClick={() => summary.refetch()}>
            Spróbuj ponownie
          </button>
        </p>
      </Card>
    );
  }
  const data = summary.data;
  const item = data.case;
  const line = lifecycleSummaryLine(data);
  const canStartExit =
    data.can_manage &&
    (!item || item.status === "cancelled" || (item.kind === "onboarding" && item.status === "done"));

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
            Wejście i odejście
          </h3>
          {item ? (
            <p className="flex flex-wrap items-center gap-2 text-sm text-foreground">
              {line}
              <StatusDot tone={CASE_STATUS_TONE[item.status]}>{CASE_STATUS_LABELS[item.status]}</StatusDot>
            </p>
          ) : (
            <p className="text-sm text-muted-foreground">Bez sprawy wejścia ani odejścia.</p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {item && item.status !== "cancelled" ? (
            <Button asChild size="sm" variant="outline">
              <Link href={item.link}>Otwórz sprawę</Link>
            </Button>
          ) : null}
          {canStartExit ? (
            <Button asChild size="sm" variant="ghost">
              <Link href={`/people/${userId}/offboarding`}>Rozpocznij odejście</Link>
            </Button>
          ) : null}
        </div>
      </div>
    </Card>
  );
}
