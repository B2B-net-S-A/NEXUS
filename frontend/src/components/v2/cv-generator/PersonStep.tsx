"use client";

import { useId } from "react";
import { Loader2, Search, Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { StepCard, initials } from "./GeneratorParts";
import type { CvCandidateOption } from "./useCvGenerator";

export interface PersonStepProps {
  candidate: CvCandidateOption | null;
  query: string;
  onQueryChange: (value: string) => void;
  results: readonly CvCandidateOption[];
  searching: boolean;
  searchError: string | null;
  onChoose: (candidate: CvCandidateOption | null) => void;
  /** „Osoby nie ma w bazie? Wgraj jej plik CV” — przełącza na plik z dysku. */
  onStartUpload?: () => void;
  /** Osoba ustalona z góry (okno z profilu / panelu osoby) — bez „Zmień”. */
  locked?: boolean;
}

/** Krok 1 — wybór osoby po imieniu, nazwisku, e-mailu albo telefonie. */
export function PersonStep({
  candidate,
  query,
  onQueryChange,
  results,
  searching,
  searchError,
  onChoose,
  onStartUpload,
  locked = false,
}: PersonStepProps) {
  const inputId = useId();
  const listId = useId();
  const showResults = !candidate && query.trim().length > 0;

  return (
    <StepCard step={1} title="Kandydat">
      {candidate ? (
        <div className="flex items-center gap-3 rounded-lg border border-border bg-muted/40 p-3">
          <span
            aria-hidden
            className="inline-flex h-10 w-10 flex-none items-center justify-center rounded-full bg-primary/10 text-sm font-semibold text-primary"
          >
            {initials(candidate.full_name)}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate font-semibold text-foreground">{candidate.full_name}</p>
            {candidate.position || candidate.email ? (
              <p className="truncate text-xs text-muted-foreground">
                {[candidate.position, candidate.email].filter(Boolean).join(" · ")}
              </p>
            ) : null}
          </div>
          {!locked ? (
            <Button type="button" variant="tertiary" size="sm" onClick={() => onChoose(null)}>
              Zmień
            </Button>
          ) : null}
        </div>
      ) : (
        <div className="space-y-2">
          <label htmlFor={inputId} className="block text-sm font-semibold text-foreground">
            Znajdź osobę
          </label>
          <div className="relative">
            <Search aria-hidden className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              id={inputId}
              aria-controls={listId}
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder="Imię i nazwisko, e-mail albo telefon"
              className="pl-9"
              autoComplete="off"
            />
          </div>
          {showResults ? (
            <div id={listId} className="rounded-lg border border-border bg-card">
              {searchError ? (
                <p role="alert" className="p-3 text-sm text-destructive">{searchError}</p>
              ) : searching ? (
                <p className="flex items-center gap-2 p-3 text-sm text-muted-foreground">
                  <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> Szukam…
                </p>
              ) : results.length === 0 ? (
                <p className="p-3 text-sm text-muted-foreground">
                  Nie znaleźliśmy takiej osoby w bazie.
                </p>
              ) : (
                <ul aria-label="Znalezione osoby" className="max-h-72 divide-y divide-border overflow-y-auto">
                  {results.map((option) => (
                    <li key={option.id}>
                      <button
                        type="button"
                        onClick={() => onChoose(option)}
                        className="flex w-full flex-col items-start px-3 py-2 text-left hover:bg-muted focus-visible:bg-muted focus-visible:outline-none"
                      >
                        <span className="text-sm font-medium text-foreground">{option.full_name}</span>
                        <span className="text-xs text-muted-foreground">
                          {[option.position, option.email].filter(Boolean).join(" · ") || "—"}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : null}
        </div>
      )}
      {onStartUpload && !locked ? (
        <Button
          type="button"
          variant="tertiary"
          size="sm"
          className="mt-3 px-0"
          onClick={onStartUpload}
        >
          <Upload aria-hidden className="mr-1.5 h-4 w-4" />
          Osoby nie ma w bazie? Wgraj jej plik CV
        </Button>
      ) : null}
    </StepCard>
  );
}
