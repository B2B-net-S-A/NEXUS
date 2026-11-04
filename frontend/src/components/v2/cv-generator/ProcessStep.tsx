"use client";

import { useId, type ReactNode } from "react";

import type { RecruitmentOption } from "@/lib/cv-generator";

import { processLabel } from "./cv-generator-form";
import { StatusChip, StepCard } from "./GeneratorParts";

export interface ProcessStepProps {
  recruitments: readonly RecruitmentOption[];
  loading: boolean;
  error: boolean;
  value: string;
  onChange: (value: string) => void;
  /** Źródła (Champion, notatki, plik CV) — pod wyborem procesu. */
  children?: ReactNode;
}

/**
 * Krok 2 — proces kandydata. Od 13.10.2026 CV powstaje wyłącznie
 * w rekrutacji (decyzja Artura): bez „Inny klient (bez procesu)”, a osoba
 * bez rekrutacji dostaje wyjaśnienie zamiast pustego wyboru. Klient wynika
 * z procesu — od niego zależą język, nazwa pliku i zgoda RODO.
 */
export function ProcessStep({
  recruitments,
  loading,
  error,
  value,
  onChange,
  children,
}: ProcessStepProps) {
  const selectId = useId();
  const count = recruitments.length;
  const noRecruitment = !loading && !error && count === 0;
  // Awaria listy procesów nie może wyglądać jak osoba bez rekrutacji.
  const badge = loading || error ? null : count === 0 ? (
    <StatusChip tone="neutral">kandydat nie ma procesów</StatusChip>
  ) : count > 1 ? (
    <StatusChip tone="neutral">{`kandydat jest w ${count} procesach`}</StatusChip>
  ) : null;

  return (
    <StepCard step={2} title="Proces" badge={badge}>
      {noRecruitment ? (
        <p role="status" className="text-sm text-muted-foreground">
          Ta osoba nie jest w żadnej rekrutacji. CV generujemy w rekrutacji — dodaj ją do rekrutacji
          i wygeneruj CV z panelu osoby.
        </p>
      ) : (
        <div className="space-y-2">
          <label htmlFor={selectId} className="block text-sm font-semibold text-foreground">
            Proces rekrutacyjny
          </label>
          <select
            id={selectId}
            value={value}
            disabled={loading}
            onChange={(event) => onChange(event.target.value)}
            className="h-10 w-full rounded-lg border border-border bg-card px-3 text-sm text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
          >
            {value === "" ? <option value="">{loading ? "Wczytuję procesy…" : "Wybierz proces…"}</option> : null}
            {recruitments.map((r) => (
              <option key={r.stage_id} value={String(r.stage_id)}>
                {processLabel(r)}
              </option>
            ))}
          </select>
          {error ? (
            <p role="alert" className="text-xs text-destructive">
              Nie udało się wczytać procesów kandydata — odśwież stronę.
            </p>
          ) : !loading && count === 1 && value === String(recruitments[0].stage_id) ? (
            <p className="text-xs text-muted-foreground">Jedyny proces tej osoby, więc wybraliśmy go sami.</p>
          ) : null}
        </div>
      )}

      {children ? <div className="mt-4 divide-y divide-border rounded-lg border border-border">{children}</div> : null}
    </StepCard>
  );
}
