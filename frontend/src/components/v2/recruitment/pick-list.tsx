"use client";

/**
 * Lista osób do zaznaczenia w oknie „Kandydaci do dodania” — wspólna dla
 * zakładek „Nowi z ogłoszeń”, „Propozycje z bazy” i „Szukaj w bazie”.
 * Klik w nazwisko otwiera podgląd osoby obok okna (jak w „Podobnych
 * rekrutacjach”); zaznaczenie zmienia wyłącznie pole wyboru.
 */

import type { ReactNode } from "react";
import { ChevronLeft, ChevronRight, X } from "lucide-react";

import { Checkbox } from "@/components/ui/checkbox";
import { eligibilityBadgeClass } from "@/lib/conflicts";
import type { CvYearBadge } from "@/lib/proposal-facts";
import { cn } from "@/lib/utils";

/** Wiersz listy do zaznaczenia — wspólny dla wszystkich źródeł. */
export interface PickRow {
  candidateId: number;
  fullName: string;
  fitScore: number | null;
  rateLabel: string | null;
  availabilityLabel: string | null;
  note: string | null;
  /** Linia faktów (stanowisko, staż, miasto, tryb, dostępność, stawka). */
  facts?: string | null;
  /** „CV z 2023” — tylko przy znanej dacie wgrania głównego CV. */
  cvBadge?: CvYearBadge | null;
  sourceLabel: string | null;
  warnings: Array<{ key: string; label: string; blocking: boolean }>;
  /** Dodatkowa treść pod wierszem (np. trafienia słów kluczowych w CV). */
  extra?: ReactNode;
}

/** „CV z RRRR” — neutralnie; starsze niż 2 lata w tonie ostrzeżenia. */
export function CvBadge({ badge }: { badge: CvYearBadge }) {
  return (
    <span
      className={cn(
        "inline-flex rounded px-1.5 text-[10.5px] font-semibold",
        badge.stale
          ? "bg-warning-muted text-warning-muted-foreground"
          : "bg-muted text-muted-foreground",
      )}
      title={badge.stale ? "CV może być nieaktualne" : undefined}
      data-testid="cv-year-badge"
      data-stale={badge.stale || undefined}
    >
      {badge.label}
      {badge.stale ? <span className="sr-only"> — CV może być nieaktualne</span> : null}
    </span>
  );
}

export function ScoreBadge({ score }: { score: number | null }) {
  return (
    <span
      className={cn(
        "shrink-0 text-xs font-bold tabular-nums",
        score != null ? "text-primary" : "font-normal text-muted-foreground",
      )}
      title={score != null ? "Dopasowanie do rekrutacji" : "Dopasowania nie policzono"}
    >
      {score != null ? `${Math.round(score)}%` : "nie policzono"}
    </span>
  );
}

export interface PickListProps {
  rows: PickRow[];
  selected: ReadonlySet<number>;
  onToggle: (row: PickRow) => void;
  readOnly: boolean;
  emptyText: string;
  label: string;
  /** Własna komórka wyniku (dopasowanie liczone na żądanie). */
  renderScore?: (row: PickRow) => ReactNode;
  /** Podgląd osoby obok okna; `activeId` = osoba, której karta jest otwarta. */
  onPreview?: (row: PickRow, trigger: HTMLElement) => void;
  onClosePreview?: () => void;
  activeId?: number | null;
  /** „Pomiń” przy wierszu (pyta o powód) — tylko tam, gdzie propozycję da się pominąć. */
  onDismiss?: (row: PickRow) => void;
}

export function PickList({
  rows,
  selected,
  onToggle,
  readOnly,
  emptyText,
  label,
  renderScore,
  onPreview,
  onClosePreview,
  activeId = null,
  onDismiss,
}: PickListProps) {
  if (rows.length === 0) {
    return <p className="py-4 text-sm text-muted-foreground">{emptyText}</p>;
  }
  return (
    <ul aria-label={label} className="divide-y divide-border rounded-md border border-border">
      {rows.map((row) => {
        const blocked = row.warnings.some((w) => w.blocking);
        const checked = selected.has(row.candidateId);
        const active = activeId === row.candidateId;
        const inputId = `add-candidate-${row.candidateId}`;
        return (
          <li
            key={row.candidateId}
            data-candidate-id={row.candidateId}
            className={cn(
              "flex items-start gap-3 px-3 py-2",
              checked && "bg-primary/5",
              active && "bg-primary/10",
            )}
          >
            <Checkbox
              id={inputId}
              checked={checked}
              disabled={readOnly || blocked}
              onCheckedChange={() => onToggle(row)}
              aria-label={`Zaznacz ${row.fullName}`}
              className="mt-0.5"
            />
            <div className="min-w-0 flex-1">
              <div className="flex items-start justify-between gap-2">
                {onPreview ? (
                  <button
                    type="button"
                    onClick={(event) => onPreview(row, event.currentTarget)}
                    className={cn(
                      "min-w-0 truncate text-left text-sm font-medium hover:text-primary hover:underline",
                      active ? "text-primary" : "text-foreground",
                    )}
                  >
                    {row.fullName}
                  </button>
                ) : (
                  <label htmlFor={inputId} className="min-w-0 truncate text-sm font-medium text-foreground">
                    {row.fullName}
                  </label>
                )}
                {renderScore ? renderScore(row) : <ScoreBadge score={row.fitScore} />}
              </div>
              {/* Fakty zamiast pustych pól — nieznane po prostu nie wchodzą. */}
              {row.facts ? (
                <p className="text-xs text-muted-foreground">{row.facts}</p>
              ) : row.rateLabel || row.availabilityLabel ? (
                <p className="text-xs text-muted-foreground">
                  {[row.rateLabel, row.availabilityLabel].filter(Boolean).join(" · ")}
                </p>
              ) : null}
              {row.note && <p className="line-clamp-2 text-xs text-muted-foreground">{row.note}</p>}
              {row.extra}
              {(row.sourceLabel || row.cvBadge || row.warnings.length > 0) && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {row.cvBadge ? <CvBadge badge={row.cvBadge} /> : null}
                  {row.sourceLabel && (
                    <span className="rounded bg-muted px-1.5 text-[10.5px] font-semibold text-muted-foreground">
                      {row.sourceLabel}
                    </span>
                  )}
                  {row.warnings.map((w) => (
                    <span
                      key={w.key}
                      className={cn(
                        "rounded px-1.5 text-[10.5px] font-semibold",
                        eligibilityBadgeClass({ assignment_allowed: !w.blocking }),
                      )}
                    >
                      {w.label}
                    </span>
                  ))}
                </div>
              )}
            </div>
            {onDismiss && !readOnly ? (
              <button
                type="button"
                aria-label={`Pomiń: ${row.fullName}`}
                title="Pomiń — wróci tylko z nową wersją CV"
                onClick={() => onDismiss(row)}
                className="hit-area rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <X className="h-4 w-4" aria-hidden />
              </button>
            ) : null}
            {onPreview ? (
              <button
                type="button"
                aria-label={`Podgląd: ${row.fullName}`}
                aria-pressed={active}
                onClick={(event) =>
                  active ? onClosePreview?.() : onPreview(row, event.currentTarget)
                }
                className={cn(
                  "hit-area rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground",
                  active && "text-primary",
                )}
              >
                {active ? (
                  <ChevronLeft className="h-4 w-4" aria-hidden />
                ) : (
                  <ChevronRight className="h-4 w-4" aria-hidden />
                )}
              </button>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
