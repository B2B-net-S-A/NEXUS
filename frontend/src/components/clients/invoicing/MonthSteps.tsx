"use client";

import { StatusDot } from "@/components/ds/StatusDot";
import { useDeliverySettlements } from "@/lib/api/client-settlements";
import { cn } from "@/lib/utils";
import { isForbiddenError, isNotFoundError } from "@/lib/view-state";

import type { MonthStep, RcpInput } from "./month-steps";

/**
 * RCP miesiąca z modułu rozliczeń — ten sam klucz zapytania co sekcja
 * „Rozliczenie miesiąca i marża” w „Fakturach”, więc przejście do zakładki
 * niczego nie pobiera drugi raz. 404 (moduł zamknięty) i 403 to brak dostępu,
 * nie awaria.
 */
export function useMonthRcp(clientId: number, month: string, enabled = true): RcpInput {
  const query = useDeliverySettlements(clientId, month, enabled);
  if (!enabled) return { state: "unavailable" };
  if (query.isPending) return { state: "loading" };
  if (query.isError) {
    return isNotFoundError(query.error) || isForbiddenError(query.error)
      ? { state: "unavailable" }
      : { state: "error" };
  }
  return { state: "ready", rows: query.data.rows };
}

function stepTitle(step: MonthStep): string {
  return `${step.label}: ${step.value}${step.note ? ` · ${step.note}` : ""}`;
}

/**
 * Karta „Rozliczenie” w Przeglądzie (wariant A, decyzja Artura z 20.11.2026):
 * cztery wiersze „krok — stan”. Drobny druk tylko w dymku — z nim karta przy
 * 1280 px rosła do 450 px wysokości (zrzut ze stagingu 20.11.2026).
 */
export function MonthStepsList({ steps }: { steps: readonly MonthStep[] }) {
  return (
    <ol className="mt-0.5 space-y-1" aria-label="Kroki rozliczenia miesiąca">
      {steps.map((step) => (
        <li key={step.key} className="flex min-w-0 items-baseline justify-between gap-2" title={stepTitle(step)}>
          <StatusDot tone={step.tone} className="shrink-0">
            {step.label}
          </StatusDot>
          {/* Zawija się zamiast ucinać: kwota w dwóch walutach nie może zgubić drugiej. */}
          <span className="min-w-0 break-words text-right text-xs font-semibold tabular-nums text-foreground">
            {step.short ?? step.value}
            {/* Dymek (`title`) nie dociera do czytnika ekranu ani na dotyk — drobny druk dla czytnika. */}
            {step.note ? <span className="sr-only">{` · ${step.note}`}</span> : null}
          </span>
        </li>
      ))}
    </ol>
  );
}

/** Zakładka „Faktury i rozliczenie”: cztery kroki nad tabelą (makieta 6A). */
export function MonthStepsStrip({
  steps,
  frontier,
}: {
  steps: readonly MonthStep[];
  frontier: MonthStep | null;
}) {
  return (
    <ol className="grid grid-cols-[minmax(0,1fr)] gap-2 sm:grid-cols-2 lg:grid-cols-4" aria-label="Kroki rozliczenia miesiąca">
      {steps.map((step, index) => (
        <li
          key={step.key}
          className={cn(
            "flex min-w-0 flex-col gap-0.5 rounded-lg border bg-card px-3 py-2",
            step.done ? "border-success/60" : "border-border",
            frontier?.key === step.key && !step.done && "border-primary ring-2 ring-primary/15",
          )}
        >
          <span className="text-[11px] text-muted-foreground">
            {index + 1} · {step.label}
          </span>
          <StatusDot tone={step.tone} className="min-w-0">
            <span className="truncate text-[13px] font-semibold">{step.value}</span>
          </StatusDot>
          {step.note ? <span className="text-[11px] leading-4 text-muted-foreground">{step.note}</span> : null}
        </li>
      ))}
    </ol>
  );
}
