"use client";

import { useId, type ReactNode } from "react";

import { ClientSinglePicker } from "@/components/clients/ClientSinglePicker";
import type { RecruitmentOption } from "@/lib/cv-generator";

import { OTHER_CLIENT_CHOICE, processLabel, type CvClientRef } from "./cv-generator-form";
import { StatusChip, StepCard } from "./GeneratorParts";

/** Klucz cache listy klientów generatora (zasiewa go harness). */
export const CV_GENERATOR_CLIENTS_QUERY_KEY = "clients-lookup-cv-generator";

export interface ProcessStepProps {
  recruitments: readonly RecruitmentOption[];
  loading: boolean;
  error: boolean;
  value: string;
  onChange: (value: string) => void;
  otherClient: CvClientRef | null;
  onOtherClientChange: (client: CvClientRef | null) => void;
  /** Źródła (Champion, notatki, plik CV) — pod wyborem procesu. */
  children?: ReactNode;
}

/**
 * Krok 2 — proces kandydata albo „Inny klient (bez procesu)”. Klient jest
 * zawsze wymagany: od niego zależą język, nazwa pliku i zgoda RODO.
 */
export function ProcessStep({
  recruitments,
  loading,
  error,
  value,
  onChange,
  otherClient,
  onOtherClientChange,
  children,
}: ProcessStepProps) {
  const selectId = useId();
  const count = recruitments.length;
  const badge = loading ? null : count === 0 ? (
    <StatusChip tone="neutral">kandydat nie ma procesów</StatusChip>
  ) : count > 1 ? (
    <StatusChip tone="neutral">{`kandydat jest w ${count} procesach`}</StatusChip>
  ) : null;

  return (
    <StepCard step={2} title="Proces" badge={badge}>
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
          <option value={OTHER_CLIENT_CHOICE}>Inny klient (bez procesu)</option>
        </select>
        {error ? (
          <p role="alert" className="text-xs text-destructive">
            Nie udało się wczytać procesów kandydata — odśwież stronę albo wybierz klienta ręcznie.
          </p>
        ) : !loading && count === 1 && value === String(recruitments[0].stage_id) ? (
          <p className="text-xs text-muted-foreground">Jedyny proces tej osoby, więc wybraliśmy go sami.</p>
        ) : !loading && count === 0 ? (
          <p className="text-xs text-muted-foreground">Kandydat nie jest w żadnym procesie — wybierz klienta, dla którego robisz CV.</p>
        ) : null}
      </div>

      {value === OTHER_CLIENT_CHOICE ? (
        <div className="mt-4 space-y-2">
          <p className="text-sm font-semibold text-foreground">
            Klient <span className="text-destructive" aria-hidden>*</span>
          </p>
          <ClientSinglePicker
            value={otherClient}
            onChange={onOtherClientChange}
            queryKey={CV_GENERATOR_CLIENTS_QUERY_KEY}
            placeholder="Wybierz klienta…"
          />
          <p className="text-xs text-muted-foreground">
            Od klienta zależą język, nazwa pliku i zgoda RODO. Bez procesu nie ma Championa
            ani notatek z rekrutacji — CV nie trafi też do żadnego etapu.
          </p>
        </div>
      ) : null}

      {children ? <div className="mt-4 divide-y divide-border rounded-lg border border-border">{children}</div> : null}
    </StepCard>
  );
}
