"use client";

import { StatusDot } from "@/components/ds/StatusDot";
import { TruncatedText } from "@/components/ds/TruncatedText";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { DecisionMapEntry, OpportunityDetail, OpportunityStep } from "@/lib/api/sales";
import { formatIsoDatePl } from "@/lib/date-pl";

import { daysLabel, daysSince } from "./format";
import { callAdvice } from "./step";

interface OpportunityStepBarProps {
  opportunity: OpportunityDetail;
  queue: readonly DecisionMapEntry[];
  canEdit: boolean;
  canChangeOwner: boolean;
  onPlan: () => void;
  onLog: () => void;
  onOwner: () => void;
}

function stepText(step: OpportunityStep): string {
  return `${step.subject ?? "Zaplanowany kontakt"} · ${formatIsoDatePl(step.at)}`;
}

function why(opportunity: OpportunityDetail): string {
  const contact = opportunity.last_contact;
  if (opportunity.waiting_for_reply && contact) {
    return `Klient napisał ${formatIsoDatePl(contact.at)} i czeka na odpowiedź`;
  }
  if (!contact) return "Bez kontaktu w historii";
  const days = daysSince(contact.at) ?? 0;
  return days === 0
    ? "Ostatni kontakt dziś"
    : `Ostatni kontakt ${formatIsoDatePl(contact.at)}, ${daysLabel(days)} temu`;
}

/** Pasek przyklejony nad treścią: co zrobić i dlaczego, a obok przyciski, które to załatwiają. */
export function OpportunityStepBar({
  opportunity,
  queue,
  canEdit,
  canChangeOwner,
  onPlan,
  onLog,
  onOwner,
}: OpportunityStepBarProps) {
  const { next_step: step, overdue_step: overdue, step_alarm: alarm } = opportunity;
  const headline = step
    ? stepText(step)
    : overdue
      ? stepText(overdue)
      : (callAdvice(queue) ?? "Przy tej szansie nic nie jest zaplanowane");
  return (
    <div className="flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-2 shadow-xs">
      <div className="shrink-0">
        {step ? (
          <StatusDot tone="success">Krok ustalony</StatusDot>
        ) : overdue ? (
          <Badge variant="warning">Po terminie</Badge>
        ) : (
          <Badge variant={alarm ? "danger" : "neutral"}>Brak kroku</Badge>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <TruncatedText className="max-w-none text-sm font-medium text-foreground">{headline}</TruncatedText>
        <TruncatedText className="max-w-none text-xs text-muted-foreground">
          {`${why(opportunity)} · Opiekun ${opportunity.owner?.name ?? "nieprzypisany"}`}
        </TruncatedText>
      </div>
      {canEdit && (
        <div className="flex shrink-0 items-center gap-2">
          <Button size="sm" variant="outline" onClick={onPlan}>
            Zaplanuj
          </Button>
          <Button size="sm" onClick={onLog}>
            Zaloguj rozmowę
          </Button>
          {canChangeOwner && (
            <Button size="sm" variant="outline" onClick={onOwner}>
              Zmień opiekuna
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
