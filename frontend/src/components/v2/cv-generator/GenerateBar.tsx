"use client";

import type { ReactNode } from "react";
import { Loader2, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";

import { StatusChip } from "./GeneratorParts";

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 border-t border-border py-2.5 text-sm">
      <span className="shrink-0 whitespace-nowrap text-muted-foreground">{label}</span>
      <span className="min-w-0 break-words text-right font-medium text-foreground">{children}</span>
    </div>
  );
}

export interface ClientRulesCardProps {
  clientName: string | null;
  /** Skąd klient: z procesu albo wybrany ręcznie. */
  clientSource: "process" | "manual" | null;
  loading: boolean;
  error: boolean;
  languageLabel: string;
  filename: string | null;
  projectRef: string | null;
  projectRefFromJob: boolean;
  consentRequired: boolean;
  consentAttached: boolean;
  /** Pole wgrania zrzutu (przed generacją) albo zdanie, że dojdzie po niej. */
  consentSlot?: ReactNode;
}

/** Karta „Reguły klienta” w prawej kolumnie generatora. */
export function ClientRulesCard(props: ClientRulesCardProps) {
  return (
    <section aria-label="Reguły klienta" className="rounded-xl border border-border bg-card p-5">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h2 className="text-base font-semibold text-foreground">Reguły klienta</h2>
        {props.clientName ? (
          <StatusChip tone="info">
            {props.clientName}
            {props.clientSource === "process" ? " · z procesu" : ""}
          </StatusChip>
        ) : null}
      </div>
      {!props.clientName ? (
        <p className="text-sm text-muted-foreground">
          Wybierz klienta, żeby zobaczyć jego reguły: język, nazwę pliku, numer projektu i zgodę RODO.
        </p>
      ) : props.loading ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
          <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> Wczytuję zasady CV klienta…
        </p>
      ) : props.error ? (
        <p role="alert" className="text-sm text-destructive">
          Nie udało się odczytać zasad CV klienta. Odśwież stronę przed generacją.
        </p>
      ) : (
        <>
          <Row label="Język">{props.languageLabel}</Row>
          {props.filename ? (
            <Row label="Nazwa pliku"><span className="font-mono text-xs">{props.filename}</span></Row>
          ) : null}
          {props.projectRef ? (
            <Row label="Numer projektu">
              <span className="inline-flex flex-wrap items-center justify-end gap-2">
                <span className="font-mono text-xs">{props.projectRef}</span>
                {props.projectRefFromJob ? <StatusChip tone="ok">z rekrutacji</StatusChip> : null}
              </span>
            </Row>
          ) : null}
          <div className="border-t border-border pt-2.5">
            <div className="flex items-center justify-between gap-3 text-sm">
              <span className="text-muted-foreground">Zgoda RODO</span>
              {!props.consentRequired ? (
                <StatusChip tone="neutral">nie wymaga</StatusChip>
              ) : props.consentAttached ? (
                <StatusChip tone="ok">zrzut dołączony</StatusChip>
              ) : (
                <StatusChip tone="warn">brak zrzutu</StatusChip>
              )}
            </div>
            {props.consentRequired ? (
              <div className="mt-2 space-y-2">
                <p className="text-xs leading-relaxed text-muted-foreground">
                  {props.clientName} wymaga zrzutu maila ze zgodą kandydata. Bez niego CV się wygeneruje,
                  ale nie da się go pobrać. Możesz dodać zrzut teraz albo po generacji.
                </p>
                {props.consentSlot}
              </div>
            ) : null}
          </div>
        </>
      )}
    </section>
  );
}

export interface GenerateBarProps {
  missing: readonly string[];
  pending: boolean;
  onGenerate: () => void;
  /** Co się stanie z wynikiem (proces / lista Moje CV). */
  hint: string;
  readOnly?: boolean;
}

/** Przycisk „Generuj CV” z listą braków — aktywny dokładnie przy pustej liście. */
export function GenerateBar({ missing, pending, onGenerate, hint, readOnly = false }: GenerateBarProps) {
  const ready = missing.length === 0 && !readOnly;
  return (
    <section aria-label="Generowanie" className="rounded-xl border border-border bg-card p-5">
      <Button
        type="button"
        size="lg"
        className="h-11 w-full text-base font-semibold"
        disabled={!ready || pending}
        onClick={onGenerate}
        aria-describedby="cvgen-generate-hint"
      >
        {pending ? (
          <><Loader2 aria-hidden className="mr-2 h-4 w-4 animate-spin" />Uruchamiam…</>
        ) : (
          <><Sparkles aria-hidden className="mr-2 h-4 w-4" />Generuj CV</>
        )}
      </Button>
      <div id="cvgen-generate-hint" className="mt-2.5 space-y-1 text-xs leading-relaxed">
        {missing.length > 0 ? (
          <p className="font-medium text-warning-muted-foreground" data-testid="cvgen-missing">
            Brakuje: {missing.join("; ")}
          </p>
        ) : null}
        <p className="text-muted-foreground">{hint}</p>
      </div>
    </section>
  );
}
