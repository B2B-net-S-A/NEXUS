"use client";

// Lista w panelu „Czeka na Ciebie” — nagłówek z liczbą, podpowiedź,
// zwijanie po `BOARD_TASKS_ROWS` wierszach. Wspólna dla sekcji panelu
// i sekcji przepływu (`BoardFlowSections`).

import type { ReactNode } from "react";

/** Tyle wierszy na listę, zanim trzeba kliknąć „Pokaż wszystkie" — na produkcji
 *  „Wysłane do Cpro" liczyło 98 osób, a panel stoi NAD pulpitem. */
export const BOARD_TASKS_ROWS = 6;

interface SectionProps {
  title: string;
  hint: string;
  count: number;
  /** Liczba wierszy listy, gdy inna niż `count` (Cpro: wiersz = rekrutacja). */
  rows?: number;
  expanded: boolean;
  onToggle: () => void;
  /** Dodatek pod nagłówkiem (Cpro: kto wrzuca · Zmień). */
  aside?: ReactNode;
  children: ReactNode;
}

export function Section({ title, hint, count, rows = count, expanded, onToggle, aside, children }: SectionProps) {
  return (
    <section aria-label={title} className="min-w-0">
      <header className="mb-2 flex items-baseline gap-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        <span className="rounded-full bg-primary/10 px-1.5 text-xs font-semibold tabular-nums text-primary">
          {count}
        </span>
      </header>
      {aside ? <div className="mb-1">{aside}</div> : null}
      <p className="mb-2 text-xs text-muted-foreground">{hint}</p>
      <ul className="divide-y divide-border rounded-lg border border-border">{children}</ul>
      {rows > BOARD_TASKS_ROWS && (
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={expanded}
          className="mt-1.5 text-xs font-medium text-primary hover:underline"
        >
          {expanded ? "Zwiń" : `Pokaż wszystkie (${rows})`}
        </button>
      )}
    </section>
  );
}

