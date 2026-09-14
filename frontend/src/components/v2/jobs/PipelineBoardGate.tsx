"use client";

import type { ReactNode } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import type { ViewState } from "@/lib/view-state";

interface PipelineBoardGateProps {
  state: ViewState;
  /** Czy zapytanie ma już wczytane kolumny (np. z poprzedniego odświeżenia). */
  hasData: boolean;
  onRetry: () => void;
  children: ReactNode;
}

/**
 * Stan zakładki „Pipeline" przed narysowaniem tablicy.
 *
 * Tablica dostaje `columns ?? []`, więc bez tej bramki odmowa 403 dla osoby
 * spoza zespołu rekrutacji renderowała się jako „Brak kolumn w tej kategorii."
 * — rekrutacja wyglądała na pustą (UAT A-B01). Awaria i brak uprawnień muszą
 * mówić, czym są.
 *
 * Gdy tablica JEST już wczytana, a nie powiodło się tylko odświeżenie w tle
 * (po ruchu karty, po deployu), zostaje na ekranie z banerem — odmontowanie
 * skasowałoby zaznaczenie, filtry i otwarty dok kandydata.
 */
export function PipelineBoardGate({
  state,
  hasData,
  onRetry,
  children,
}: PipelineBoardGateProps) {
  const failed =
    state === "forbidden" || state === "not_found" || state === "error";
  if (state === "loading" && !hasData) {
    return <div className="text-muted-foreground">Ładowanie pipeline...</div>;
  }
  if (failed && hasData && state === "error") {
    return (
      <>
        <div
          role="status"
          className="mb-3 flex items-center justify-between gap-3 rounded-lg border border-border bg-muted px-3 py-2 text-sm"
        >
          <span>
            Nie udało się odświeżyć tablicy — widzisz ostatnio wczytany stan.
          </span>
          <button
            type="button"
            onClick={onRetry}
            className="font-medium text-primary hover:underline"
          >
            Ponów
          </button>
        </div>
        {children}
      </>
    );
  }
  if (failed) {
    return (
      <QueryStateNotice
        state={state}
        className="rounded-xl"
        description={
          state === "forbidden"
            ? "Nie masz dostępu do tablicy kandydatów tej rekrutacji (np. nie należysz do jej zespołu) — to nie znaczy, że pipeline jest pusty."
            : undefined
        }
        onRetry={onRetry}
      />
    );
  }
  return <>{children}</>;
}
