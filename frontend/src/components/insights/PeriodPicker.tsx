"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import type {
  InsightsPeriodKind,
  InsightsPeriodParams,
} from "@/lib/insights-api";

const GRANULARITIES: Array<{ id: InsightsPeriodKind; label: string }> = [
  { id: "week", label: "Tydzień" },
  { id: "month", label: "Miesiąc" },
  { id: "quarter", label: "Kwartał" },
  { id: "year", label: "Rok" },
];

interface Props {
  value: InsightsPeriodParams;
  onChange: (next: InsightsPeriodParams) => void;
  /** Okno zwrócone przez backend — źródło etykiety. */
  resolved?: { start: string; end: string; timezone: string } | null;
}

/**
 * Wybór okresu: granulacja + kotwica (strzałki).
 *
 * Zastępuje `PeriodSelector`, który oferował „Ostatnie 7 dni" / „Ostatnie
 * 30 dni" — czyli okna KROCZĄCE, podczas gdy backend liczy KALENDARZOWO.
 * Etykieta pod spodem pokazuje realne okno policzone przez serwer, żeby nie
 * trzeba było zgadywać, co właściwie widać.
 */
export function PeriodPicker({ value, onChange, resolved }: Props) {
  const offset = value.offset ?? 0;

  const shift = (by: number) =>
    onChange({ ...value, offset: offset + by, anchor: undefined });

  return (
    <div className="flex flex-col items-end gap-1">
      <div className="flex items-center gap-2">
        <div className="flex rounded-lg border border-border overflow-hidden">
          {GRANULARITIES.map((g) => (
            <button
              key={g.id}
              type="button"
              onClick={() => onChange({ period: g.id, offset: 0 })}
              aria-pressed={value.period === g.id}
              className={cn(
                "px-3 py-1.5 text-xs font-medium transition-colors",
                value.period === g.id
                  ? "bg-primary text-primary-foreground"
                  : "bg-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {g.label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => shift(-1)}
            aria-label="Poprzedni okres"
            className="p-1.5 rounded-md border border-border text-muted-foreground hover:text-foreground"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <button
            type="button"
            onClick={() => shift(1)}
            // Przyszły okres jest legalny (half-open liczy okres w toku),
            // ale ruch naprzód z bieżącego nie ma sensu — blokujemy.
            disabled={offset >= 0}
            aria-label="Następny okres"
            className="p-1.5 rounded-md border border-border text-muted-foreground hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>

      {resolved && (
        <p className="text-xs text-muted-foreground tabular-nums">
          {formatWindow(resolved.start, resolved.end)} · {resolved.timezone}
        </p>
      )}
    </div>
  );
}

/**
 * Okno jest półotwarte [start, end), więc ostatni dzień NALEŻĄCY do okresu to
 * `end - 1 dzień`. Pokazanie surowego `end` sugerowałoby, że lipiec kończy się
 * 1 sierpnia.
 */
function formatWindow(startIso: string, endIso: string): string {
  const start = new Date(startIso);
  const endExclusive = new Date(endIso);
  const lastDay = new Date(endExclusive.getTime() - 24 * 60 * 60 * 1000);
  const fmt = new Intl.DateTimeFormat("pl-PL", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
  return `${fmt.format(start)} – ${fmt.format(lastDay)}`;
}
