"use client";

/**
 * Pasek wymagań nad CV w panelu osoby (13.10.2026, zgłoszenie rekrutera,
 * decyzje D1 i D3).
 *
 * Zwinięta kolumna „Wymagania” nie znika, tylko zostaje tym paskiem; na
 * laptopie (podgląd w zakładkach) pasek stoi nad CV także przy otwartych
 * wymaganiach, bo inaczej czytając CV, wymagań nie widać. Treść:
 * - wymagania krytyczne (★), a gdy rekrutacja ich nie ma — pierwsze cztery
 *   z „Musi mieć”; nadmiar jako „+N”. Klik w wymaganie = „Szukaj w CV”,
 * - warunki rekrutacji w jednej linii (puste pomijamy),
 * - „Wszystkie wymagania” — pełna lista.
 * Dane z `useJobRequirements` — te same zapytania co lista, bez nowego żądania.
 */

import { PanelRightOpen, Search, Star } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import {
  requirementFindWords,
  useJobRequirements,
  type JobRequirementConditions,
} from "./use-job-requirements";

/** Ile wymagań mieści pasek; reszta to „+N”. */
export const STRIP_MAX_REQUIREMENTS = 4;

/** Warunki do jednej linii paska, bez pustych. */
export function stripConditionParts(conditions: JobRequirementConditions): string[] {
  return [
    conditions.budget,
    conditions.location,
    conditions.workMode,
    conditions.officeShort ? `biuro ${conditions.officeShort}` : null,
    conditions.start ? `start ${conditions.start}` : null,
    conditions.length,
    conditions.seniority,
    conditions.language,
  ].filter((part): part is string => Boolean(part));
}

const STATE_TEXT = {
  forbidden: "Nie masz dostępu do wymagań tej rekrutacji.",
  not_found: "Nie znaleziono wymagań tej rekrutacji.",
} as const;

export interface JobRequirementsStripProps {
  jobId: number;
  /** Budżet PLN/h z Tablicy — gdy rekrutacji nie ma w cache strony. */
  budgetHourly?: number | null;
  /** „Szukaj w CV”: nazwa wymagania i słowa lupy z serwera (pusta lista = sama nazwa). */
  onPickRequirement: (name: string, words: readonly string[]) => void;
  /** Pełna lista: rozwija kolumnę albo przełącza na zakładkę „Wymagania”. */
  onShowAll: () => void;
  className?: string;
}

export function JobRequirementsStrip({
  jobId,
  budgetHourly = null,
  onPickRequirement,
  onShowAll,
  className,
}: JobRequirementsStripProps) {
  const { state, refetch, requirements } = useJobRequirements(jobId, budgetHourly);

  let body;
  if (state === "loading") {
    body = <Skeleton className="h-6 min-w-0 flex-1" />;
  } else if (state === "forbidden" || state === "not_found") {
    body = <p className="min-w-0 flex-1 text-muted-foreground">{STATE_TEXT[state]}</p>;
  } else if (state !== "ready" && state !== "empty") {
    body = (
      <>
        <p role="alert" className="min-w-0 flex-1 text-muted-foreground">
          Nie udało się wczytać wymagań.
        </p>
        <Button type="button" size="sm" variant="outline" onClick={refetch}>
          Ponów
        </Button>
      </>
    );
  } else {
    const critical = requirements.mustCritical.length > 0;
    const items = critical ? requirements.mustCritical : requirements.mustOther;
    const label = critical ? "Krytyczne" : "Musi mieć";
    const shown = items.slice(0, STRIP_MAX_REQUIREMENTS);
    const extra = items.length - shown.length;
    const line = stripConditionParts(requirements.conditions).join(" · ");
    body =
      items.length === 0 && !line ? (
        <p className="min-w-0 flex-1 text-muted-foreground">Rekrutacja nie ma jeszcze wymagań.</p>
      ) : (
        <>
          {items.length > 0 ? (
            <div className="flex min-w-0 flex-wrap items-center gap-1.5">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</span>
              {shown.map((name) => {
                const fullLabel = requirements.fullLabels[name] ?? name;
                return (
                <button
                  key={name}
                  type="button"
                  aria-label={`Szukaj „${fullLabel}” w CV`}
                  title={`Szukaj „${fullLabel}” w CV`}
                  onClick={() => onPickRequirement(name, requirementFindWords(requirements.findWords, name))}
                  className="inline-flex max-w-[14rem] items-center gap-1 rounded-full border border-primary/40 bg-primary/10 px-2 py-0.5 font-semibold text-foreground transition-colors hover:bg-primary/20 pointer-coarse:py-1.5"
                >
                  {critical ? <Star className="h-3 w-3 shrink-0 fill-primary text-primary" aria-hidden /> : null}
                  <span className="truncate">{fullLabel}</span>
                  <Search className="h-3 w-3 shrink-0 text-muted-foreground" aria-hidden />
                </button>
                );
              })}
              {extra > 0 ? (
                <button
                  type="button"
                  aria-label={`Jeszcze ${extra} — wszystkie wymagania`}
                  onClick={onShowAll}
                  className="rounded-full border border-border px-2 py-0.5 font-medium text-muted-foreground transition-colors hover:text-foreground pointer-coarse:py-1.5"
                >
                  +{extra}
                </button>
              ) : null}
            </div>
          ) : null}
          {line ? (
            <>
              {items.length > 0 ? <span aria-hidden className="h-4 w-px shrink-0 bg-border" /> : null}
              <p
                data-testid="requirements-strip-conditions"
                title={line}
                className="min-w-0 flex-1 basis-40 truncate text-muted-foreground"
              >
                {line}
              </p>
            </>
          ) : (
            <span className="flex-1" />
          )}
        </>
      );
  }

  return (
    <div
      data-testid="requirements-strip"
      role="region"
      aria-label="Wymagania w skrócie"
      aria-busy={state === "loading" || undefined}
      className={cn(
        "flex flex-none flex-wrap items-center gap-x-2.5 gap-y-1 rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs",
        className,
      )}
    >
      {body}
      <Button type="button" size="sm" variant="ghost" className="ml-auto shrink-0" onClick={onShowAll}>
        <PanelRightOpen className="h-3.5 w-3.5" aria-hidden />
        Wszystkie wymagania
      </Button>
    </div>
  );
}
