"use client";

import { useId } from "react";
import { Clock, History, Lock, Scale } from "lucide-react";
import { cn } from "@/lib/utils";
import type {
  CompetitionClosure,
  CompetitionPeriodOption,
} from "@/lib/insights-races-api";

/**
 * Okres konkursu na „Rywalizacji” — wybór okresu i to, co karta Ligi albo
 * wyścigu mówi o jego zamknięciu i źródle liczb (przejście z DynaReportera
 * na NEXUS-a 12.10.2026). Jedno miejsce dla obu rodzajów kart, żeby
 * „Zamknięte” i pasek źródła wyglądały i znaczyły to samo.
 */

/**
 * Wybór okresu — natywna lista, nie rząd segmentów: opcji przybywa co miesiąc
 * od stycznia 2026, a dziesięć segmentów nie mieści się obok nagłówka przy
 * 1280 px. Na telefonie otwiera systemowy wybierak.
 */
export function CompetitionPeriodSelect({
  label,
  value,
  options,
  onChange,
}: {
  /** Widoczna etykieta pola: „Kwartał” albo „Miesiąc”. */
  label: string;
  value: string;
  options: readonly CompetitionPeriodOption[];
  onChange: (value: string) => void;
}) {
  const id = useId();
  return (
    <div className="flex min-w-0 items-center gap-2">
      <label
        htmlFor={id}
        className="shrink-0 text-xs font-medium text-muted-foreground"
      >
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-8 min-w-0 rounded-md border border-border bg-card px-2 text-sm font-medium text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

/** Polska odmiana — „1 dzień / 2 dni / 5 dni". */
function daysPl(n: number): string {
  return `${n} ${Math.abs(n) === 1 ? "dzień" : "dni"}`;
}

/**
 * Stan okresu w nagłówku karty: „Zamknięte” (podium zamrożone), „Zakończony”
 * (okres minął, a admin go jeszcze nie zamknął) albo odliczanie.
 *
 * `days_remaining` backend liczy z „dzisiaj”, nie z okresu, więc dla okresu
 * z przeszłości opisywałby okres bieżący — dlatego zamknięty i zakończony
 * nigdy nie odliczają. Zero albo `null` to „—”, nigdy „0 dni”.
 */
export function PeriodCountdown({
  frozen,
  closed,
  daysRemaining,
}: {
  frozen: boolean;
  closed: boolean;
  daysRemaining: number | null | undefined;
}) {
  if (frozen) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-[11px] font-semibold text-muted-foreground">
        <Lock className="h-3 w-3" aria-hidden="true" />
        Zamknięte
      </span>
    );
  }
  if (closed) {
    return (
      <span className="inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-[11px] font-semibold text-muted-foreground">
        Zakończony
      </span>
    );
  }
  return (
    <p className="flex items-center justify-end gap-1 text-xs text-muted-foreground">
      <Clock className="h-3.5 w-3.5" aria-hidden="true" />
      {daysRemaining === null || daysRemaining === undefined || daysRemaining <= 0
        ? "—"
        : `Zostało ${daysPl(daysRemaining)}`}
    </p>
  );
}

/**
 * Pasek źródła liczb. Zdanie przychodzi gotowe z serwera i stoi dosłownie —
 * front nie dopowiada dat przejścia, które zna tylko backend.
 */
export function SourceNote({ closure }: { closure: CompetitionClosure | undefined }) {
  if (!closure?.source_note) return null;
  return (
    <p
      className={cn(
        // Plakietka, nie ramka (22.10.2026): na Rywalizacji stała czterokrotnie,
        // a każda zajmowała pełną szerokość karty nad podium.
        "inline-flex w-fit items-start gap-1.5 rounded-full border px-2.5 py-1 text-[11px]",
        // Okres mieszany wyróżniamy kolorem marki: to trwający okres, w którym
        // część liczb nie pochodzi z NEXUS-a. Rozliczony okres z DynaReportera
        // jest historią — spokojny, wyciszony pasek.
        closure.source === "mixed"
          ? "border-primary/20 bg-primary/10 text-foreground"
          : "border-border bg-muted text-muted-foreground",
      )}
      data-testid="competition-source-note"
    >
      <History className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <span>{closure.source_note}</span>
    </p>
  );
}

/**
 * Jak zamknięto okres, gdy to zmienia odczyt podium: remis czekający na
 * decyzję admina albo okres bez zwycięzcy. Pozostałe stany nie potrzebują
 * zdania — „Zamknięte” w nagłówku mówi już wszystko.
 */
export function ClosureNote({ closure }: { closure: CompetitionClosure | undefined }) {
  if (closure?.closure_status === "tie_pending") {
    return (
      <p
        className="flex items-center gap-2 rounded-lg border border-warning/25 bg-warning-muted px-3 py-2 text-xs font-medium text-warning-muted-foreground"
        data-testid="competition-tie-pending"
      >
        <Scale className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        Remis — o miejscu zdecyduje admin
      </p>
    );
  }
  if (closure?.closure_status === "no_winner") {
    return (
      <p
        className="rounded-lg border border-border bg-muted px-3 py-2 text-xs font-medium text-foreground"
        data-testid="competition-no-winner"
      >
        Brak zwycięzcy w tym okresie
      </p>
    );
  }
  return null;
}
