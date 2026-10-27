"use client";

/**
 * Lista osób do zaznaczenia w oknie „Kandydaci do dodania” — wspólna dla
 * zakładek „Nowi z ogłoszeń”, „Propozycje z bazy” i „Szukaj w bazie”.
 * Klik w nazwisko otwiera podgląd osoby obok okna (jak w „Podobnych
 * rekrutacjach”); zaznaczenie zmienia wyłącznie pole wyboru.
 *
 * 14.10.2026 (decyzja Artura, D1 + P1): wiersz sam zgłasza, że jest na
 * ekranie (`onRowVisible` — dopasowanie liczy się bez przycisku), ma „+ Dodaj”
 * jednym kliknięciem, a po dodaniu zostaje z „Dodano do „Nowych” · rezerwacja
 * 12 h · Cofnij”. Pod faktami do trzech chipów powodu (`reason-chips.ts`).
 *
 * 19.10.2026 (decyzja D3): na początku rzędu chipów stała plakietka stawki
 * względem budżetu (`lib/rate-budget-badge.ts`) — także przy osobie dodanej.
 */

import { useEffect, useRef, type ReactNode, type RefObject } from "react";
import { Check, ChevronLeft, ChevronRight, Plus, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { MATCH_SCORES_MAX_CANDIDATES } from "@/hooks/useVisibleMatchScores";
import { eligibilityBadgeClass } from "@/lib/conflicts";
import type { CvYearBadge } from "@/lib/proposal-facts";
import { EmploymentPill } from "@/components/ds/EmploymentMarker";
import type { EmploymentMarker } from "@/lib/employment-marker";
import type { RateBudgetBadge, RateBudgetTone } from "@/lib/rate-budget-badge";
import { cn } from "@/lib/utils";

import { shortChipLabel, type ReasonChipList, type ReasonChipTone } from "./reason-chips";

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
  /** Znacznik „Pracuje u nas” — pigułka w rzędzie plakietek. */
  employment?: EmploymentMarker | null;
  warnings: Array<{ key: string; label: string; blocking: boolean }>;
  /** Dodatkowa treść pod wierszem (np. trafienia słów kluczowych w CV). */
  extra?: ReactNode;
  /** Do trzech chipów „✓ / ✕ / ?” i „+N” (powód bez otwierania osoby). */
  chips?: ReasonChipList | null;
  /**
   * „w budżecie · 140 zł/h” / „+12% ponad budżet · 160 zł/h” — pierwsza
   * w rzędzie chipów, nie liczy się do trzech chipów wymagań (D3, 19.10.2026).
   */
  rateBadge?: RateBudgetBadge | null;
  /**
   * Osoba z innej roli niż rekrutacja (tester przy programiście, 27.10.2026):
   * plakietka „Inna rola”, przekreślony procent, miejsce na końcu listy.
   */
  roleMismatch?: { label: string; detail: string } | null;
  /**
   * „musi mieć 4/10” pod procentem — procent to głównie podobieństwo tekstu
   * CV, a ta liczba odróżnia 9/10 od 4/10 (27.10.2026).
   */
  mustCoverage?: { met: number; total: number } | null;
  /**
   * „+ Dodaj” w toku, osoba dodana w tym oknie (wiersz zostaje z „Cofnij”)
   * albo cofanie w toku.
   */
  addState?: "adding" | "added" | "undoing" | null;
  /** „Cofnij” jeszcze działa (okno 15 min, `useUndoWindow`); `false` = minęło. */
  undoable?: boolean;
  /**
   * Blok „Pasuje też do” (`AlsoFitsBlock`) — tylko pod osobą dodaną w tym
   * oknie. Dane liczy właściciel zakładki (`useAlsoFitsJobs`), nie lista.
   */
  alsoFits?: ReactNode;
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
  /** „+ Dodaj” jednej osoby do „Nowych” (ta sama droga co „Dodaj N do Nowych”). */
  onAdd?: (row: PickRow) => void;
  /** „Cofnij” przy osobie dodanej w tym oknie. */
  onUndo?: (row: PickRow) => void;
  /**
   * Wiersz pierwszy raz na ekranie (`IntersectionObserver`) — dopasowanie
   * liczy się samo. Bez obserwatora (jsdom) zgłasza się pierwszych 20.
   */
  onRowVisible?: (candidateId: number) => void;
}

/** Calls `onVisible(id)` the first time the element enters the viewport. */
function useReportWhenVisible(
  ref: RefObject<HTMLElement | null>,
  id: number,
  onVisible: ((candidateId: number) => void) | undefined,
  fallback: boolean,
) {
  useEffect(() => {
    if (!onVisible) return;
    const element = ref.current;
    if (!element) return;
    if (typeof IntersectionObserver === "undefined") {
      if (fallback) onVisible(id);
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        observer.disconnect();
        onVisible(id);
      }
    });
    observer.observe(element);
    return () => observer.disconnect();
    // `onVisible` changes identity per result set, re-arming the observer.
  }, [ref, id, onVisible, fallback]);
}

const CHIP_CLASS: Record<ReasonChipTone, string> = {
  met: "bg-success-muted text-success-muted-foreground",
  gap: "bg-destructive-muted text-destructive-muted-foreground",
  ask: "bg-warning-muted text-warning-muted-foreground",
};
const CHIP_GLYPH: Record<ReasonChipTone, string> = { met: "✓", gap: "✕", ask: "?" };
const CHIP_TITLE: Record<ReasonChipTone, string> = {
  met: "Spełnia",
  gap: "Brakuje",
  ask: "Nie wiemy — zapytaj w rozmowie",
};
const CHIP_BASE =
  "inline-flex min-w-0 max-w-full items-center gap-1 rounded px-1.5 py-0.5 text-[10.5px] font-semibold leading-4";

const RATE_CLASS: Record<RateBudgetTone, string> = {
  in: "bg-success-muted text-success-muted-foreground",
  over: "bg-warning-muted text-warning-muted-foreground",
  far: "bg-destructive-muted text-destructive-muted-foreground",
  plain: "bg-muted text-muted-foreground",
};

/**
 * Chipy powodu pod całym wierszem (także pod przyciskami po prawej) —
 * najwyżej dwie linie, etykieta do ~18 znaków, cała w podpowiedzi. Plakietka
 * stawki stoi pierwsza i się nie skraca — chipy wymagań mają swoje trzy miejsca.
 */
function ReasonChips({ chips, rateBadge }: { chips: ReasonChipList | null; rateBadge: RateBudgetBadge | null }) {
  const shown = chips?.shown ?? [];
  const hidden = chips?.hidden ?? [];
  return (
    <div
      role="group"
      aria-label="Dlaczego ta osoba"
      className="mt-1 flex max-h-11 flex-wrap gap-1 overflow-hidden pl-7"
      data-testid="pick-row-reasons"
    >
      {rateBadge ? (
        <span
          title={rateBadge.title}
          data-tone={`rate-${rateBadge.tone}`}
          data-testid="pick-row-rate"
          className={cn(CHIP_BASE, "shrink-0 whitespace-nowrap", RATE_CLASS[rateBadge.tone])}
        >
          <span className="sr-only">Stawka: </span>
          {rateBadge.label}
        </span>
      ) : null}
      {shown.map((chip) => (
        <span
          key={`${chip.tone}-${chip.label}`}
          title={`${CHIP_TITLE[chip.tone]}: ${chip.label}`}
          data-tone={chip.tone}
          className={cn(CHIP_BASE, CHIP_CLASS[chip.tone])}
        >
          <span aria-hidden="true">{CHIP_GLYPH[chip.tone]}</span>
          <span className="sr-only">{CHIP_TITLE[chip.tone]}: </span>
          <span className="truncate">{shortChipLabel(chip.label)}</span>
        </span>
      ))}
      {hidden.length > 0 ? (
        <span
          title={hidden.map((chip) => `${CHIP_GLYPH[chip.tone]} ${chip.label}`).join(", ")}
          data-tone="more"
          className={cn(CHIP_BASE, "bg-muted text-muted-foreground")}
        >
          <span aria-hidden="true">+{hidden.length}</span>
          <span className="sr-only">
            I jeszcze: {hidden.map((chip) => `${CHIP_TITLE[chip.tone]}: ${chip.label}`).join(", ")}
          </span>
        </span>
      ) : null}
    </div>
  );
}

interface PickListItemProps extends Omit<PickListProps, "rows" | "selected" | "emptyText" | "label"> {
  row: PickRow;
  checked: boolean;
  scoreWithoutObserver: boolean;
}

function PickListItem({
  row,
  checked: selectedNow,
  readOnly,
  onToggle,
  renderScore,
  onPreview,
  onClosePreview,
  activeId = null,
  onDismiss,
  onAdd,
  onUndo,
  onRowVisible,
  scoreWithoutObserver,
}: PickListItemProps) {
  const rowRef = useRef<HTMLLIElement | null>(null);
  useReportWhenVisible(rowRef, row.candidateId, onRowVisible, scoreWithoutObserver);
  const blocking = row.warnings.find((w) => w.blocking);
  const added = row.addState === "added" || row.addState === "undoing";
  const reasonChips = !added && row.chips && row.chips.shown.length > 0 ? row.chips : null;
  const checked = selectedNow && !added;
  const active = activeId === row.candidateId;
  const inputId = `add-candidate-${row.candidateId}`;
  return (
    <li
      ref={rowRef}
      data-candidate-id={row.candidateId}
      data-added={added || undefined}
      className={cn(
        "px-3 py-2",
        checked && "bg-primary/5",
        added && "bg-success-muted/40",
        active && "bg-primary/10",
      )}
    >
      <div className="flex items-start gap-3">
        <Checkbox
          id={inputId}
          checked={checked}
          disabled={readOnly || Boolean(blocking) || added}
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
            <span className="flex shrink-0 flex-col items-end leading-tight">
              {row.roleMismatch ? (
                <span
                  className="text-xs font-bold tabular-nums text-muted-foreground line-through"
                  title="Inna rola niż rekrutacja — procent mierzy podobieństwo CV, nie zawód"
                  data-testid="pick-row-score-off-role"
                >
                  {row.fitScore != null ? `${Math.round(row.fitScore)}%` : "—"}
                  <span className="sr-only"> (inna rola)</span>
                </span>
              ) : renderScore ? (
                renderScore(row)
              ) : (
                <ScoreBadge score={row.fitScore} />
              )}
              {row.mustCoverage ? (
                <span
                  className={cn(
                    "text-[10.5px] font-semibold tabular-nums",
                    row.mustCoverage.met * 2 <= row.mustCoverage.total
                      ? "text-warning-muted-foreground"
                      : "text-muted-foreground",
                  )}
                  title="Ile wymagań „musi mieć” widać w CV"
                  data-testid="pick-row-must-coverage"
                >
                  musi mieć {row.mustCoverage.met}/{row.mustCoverage.total}
                </span>
              ) : null}
            </span>
          </div>
          {row.roleMismatch ? (
            <p className="mt-0.5 text-xs" data-testid="pick-row-role-mismatch">
              <span className="rounded bg-warning-muted px-1.5 py-px text-[10.5px] font-semibold text-warning-muted-foreground">
                Inna rola: {row.roleMismatch.label}
              </span>{" "}
              <span className="text-muted-foreground">{row.roleMismatch.detail}</span>
            </p>
          ) : null}
          {/* Fakty zamiast pustych pól — nieznane po prostu nie wchodzą. */}
          {row.facts ? (
            <p className="text-xs text-muted-foreground">{row.facts}</p>
          ) : row.rateLabel || row.availabilityLabel ? (
            <p className="text-xs text-muted-foreground">
              {[row.rateLabel, row.availabilityLabel].filter(Boolean).join(" · ")}
            </p>
          ) : null}
          {/* Jedna linia powodu — całość w podpowiedzi i w podglądzie osoby. */}
          {row.note && (
            <p className="line-clamp-1 text-xs text-muted-foreground" title={row.note}>
              {row.note}
            </p>
          )}
          {added ? (
            <p
              role="status"
              className="mt-0.5 flex flex-wrap items-center gap-x-1 text-xs font-medium text-success-muted-foreground"
              data-testid="pick-row-added"
            >
              <Check className="h-3.5 w-3.5" aria-hidden="true" />
              Dodano do „Nowych” · rezerwacja 12 h
              {onUndo && !readOnly && row.undoable !== false ? (
                <>
                  <span aria-hidden="true">·</span>
                  <button
                    type="button"
                    onClick={() => onUndo(row)}
                    disabled={row.addState === "undoing"}
                    aria-label={`Cofnij dodanie: ${row.fullName}`}
                    className="font-semibold text-primary hover:underline disabled:opacity-60"
                  >
                    {row.addState === "undoing" ? "Cofam…" : "Cofnij"}
                  </button>
                </>
              ) : null}
            </p>
          ) : null}
          {added ? row.alsoFits : null}
          {row.extra}
          {(row.sourceLabel || row.cvBadge || row.employment || row.warnings.length > 0) && (
            <div className="mt-1 flex flex-wrap items-center gap-1">
              {/* Poza przyciskiem nazwiska i linią faktów — ich treść
                  jest nazwą dostępną wiersza i tekstem do skanowania. */}
              {row.employment ? <EmploymentPill marker={row.employment} /> : null}
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
        {onAdd && !readOnly && !added ? (
          <Button
            size="sm"
            variant="outline"
            className="h-7 shrink-0 gap-1 px-2"
            onClick={() => onAdd(row)}
            disabled={Boolean(blocking)}
            loading={row.addState === "adding"}
            aria-label={`Dodaj do „Nowych”: ${row.fullName}`}
            title={blocking ? blocking.label : "Dodaj do „Nowych” — rezerwacja 12 h dla Ciebie"}
            data-testid="pick-row-add"
          >
            <Plus className="h-3.5 w-3.5" aria-hidden="true" />
            Dodaj
          </Button>
        ) : null}
        {onDismiss && !readOnly && !added ? (
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
            onClick={(event) => (active ? onClosePreview?.() : onPreview(row, event.currentTarget))}
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
      </div>
      {/* Pod całym wierszem, nie obok przycisków — inaczej chip mieścił 1–3 litery.
          Osoba dodana: bez chipów wymagań (ma status z „Cofnij”), stawka zostaje. */}
      {reasonChips || row.rateBadge ? (
        <ReasonChips chips={reasonChips} rateBadge={row.rateBadge ?? null} />
      ) : null}
    </li>
  );
}

export function PickList({ rows, selected, emptyText, label, ...rest }: PickListProps) {
  if (rows.length === 0) {
    return <p className="py-4 text-sm text-muted-foreground">{emptyText}</p>;
  }
  return (
    <ul aria-label={label} className="divide-y divide-border rounded-md border border-border">
      {rows.map((row, index) => (
        <PickListItem
          key={row.candidateId}
          row={row}
          checked={selected.has(row.candidateId)}
          scoreWithoutObserver={index < MATCH_SCORES_MAX_CANDIDATES}
          {...rest}
        />
      ))}
    </ul>
  );
}
