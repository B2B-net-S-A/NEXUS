"use client";

/**
 * Pełne narzędzia osoby w rozwiniętym panelu osoby (jeden panel osoby,
 * 04.10.2026 — decyzja „Sekcje + Rozwiń”). Do tej pory żyły w osobnym oknie
 * (`BoardWorkbenchDrawer` → `PersonPanel` z dawnej „Tabeli”) z własnym
 * nagłówkiem, wyborem etapu i „Odrzuć”. Teraz głowa jest jedna — dok —
 * a „Rozwiń” poszerza panel i pod nią pokazuje te zakładki.
 *
 * Warsztaty dostają dokładnie te propsy, które dawał im `PersonPanel`
 * (`layout="panel"`, `focusCandidateId`, kontekst strony rekrutacji).
 * Odwiedzone zakładki tej osoby zostają ZAMONTOWANE (ukryte atrybutem
 * `hidden`): przełączenie na „Notatki” w połowie arkusza screeningu nie może
 * skasować wpisanego tekstu.
 */

import { useCallback, useMemo, useState, type ReactNode } from "react";

import { TabbedNav } from "@/components/ds";
import { JobContractTab } from "@/components/v2/jobs/JobContractTab";
import type { JobDetailTab } from "@/components/v2/jobs/JobDetailCompactHeader";
import { JobInterviewsTab } from "@/components/v2/jobs/JobInterviewsTab";
import { JobNotesBlock, useJobNotes } from "@/components/v2/jobs/workbench-chrome";
import { DopasowanieTab } from "@/components/v2/pages/DopasowanieTab";
import type { KanbanColumn } from "@/components/v2/pages/kanban-shared";
import { CvHandoffWorkbench, ScreeningWorkbench } from "@/components/v2/recruitment/panel-workbenches";
import { SavedCvView, SavedScreeningView } from "@/components/v2/recruitment/PanelSavedViews";
import {
  buildProcessRows,
  defaultPanelSectionFor,
  isOffTemplateRow,
  type OffTemplateBucket,
} from "@/components/v2/recruitment/person-rows";
import type { PersonPanelSection, ProcessPersonRow } from "@/components/v2/recruitment/types";
import { countHired, findStageColumn, isNewColumn, VERIFIED_STAGE } from "@/lib/pipeline-flow";
import { isOverHourlyBudget } from "@/lib/rate-to-hourly";
import { formatDate } from "@/lib/utils";

/** Stan zapytania tablicy — warsztaty renderują z niego własne ładowanie/błąd. */
export interface KanbanQueryState {
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  isSuccess: boolean;
  refetch: () => void;
}

/**
 * Wszystko, co strona rekrutacji podaje warsztatom — w jednym obiekcie, żeby
 * panel nie rósł o prop przy każdej zmianie warsztatu.
 */
export interface WorkbenchContext {
  jobTitle?: string;
  /** Nordea: „CV wysłane" = „Wysłane do Cpro" — wysyła osoba od Cpro (jedna na firmę), nie DL. */
  cproEnabled?: boolean;
  clientId: number | null;
  clientName?: string | null;
  /** `effective_budget_hourly` rekrutacji. */
  budgetHourly: number | null;
  kanbanQueryState: KanbanQueryState;
  /** Po ruchu wykonanym WEWNĄTRZ warsztatu — strona unieważnia tablicę. */
  onMoved: () => void;
  /** Warsztat screeningu umie odesłać do innej zakładki rekrutacji. */
  onTabChange?: (tab: JobDetailTab) => void;
  /** `job.update` — domknięcie rekrutacji z zakładki „Umowa". */
  canCloseJob: boolean;
  /** Ile osób klient zamówił (`job.headcount`); `null` = nie wiadomo. */
  headcount?: number | null;
  /** Rekrutacja już zamknięta — podpowiedź domknięcia nie ma sensu. */
  jobClosed?: boolean;
  /** Otwiera okno „Zlecenie" na akcji zamknięcia rekrutacji. */
  onRequestCloseJob?: () => void;
}

/** Kontekst, który podaje strona rekrutacji (bez stanu tablicy i budżetu). */
export type BoardWorkbenchContext = Omit<WorkbenchContext, "kanbanQueryState" | "budgetHourly" | "jobTitle">;

export const PERSON_PANEL_SECTIONS: ReadonlyArray<{
  value: PersonPanelSection;
  label: string;
}> = [
  { value: "cv", label: "CV" },
  { value: "screening", label: "Screening" },
  { value: "interviews", label: "Rozmowy" },
  { value: "contract", label: "Umowa" },
  { value: "match", label: "Dopasowanie" },
  { value: "notes", label: "Notatki i historia" },
];

const NO_SCORES = new Map<number, number>();

/** Wiersz osoby z kolumn Tablicy — ten sam, który budowała dawna Tabela. */
export function usePersonRow(
  columns: KanbanColumn[],
  candidateId: number | null,
  budgetHourly: number | null,
  offTemplate: OffTemplateBucket | null = null,
): ProcessPersonRow | null {
  return useMemo(
    () =>
      candidateId == null
        ? null
        : (buildProcessRows(columns, { scores: NO_SCORES, slaDays: null, budgetHourly, offTemplate }).find(
            (r) => r.candidateId === candidateId,
          ) ?? null),
    [columns, candidateId, budgetHourly, offTemplate],
  );
}

/** Zakładka otwierana bez wyboru użytkownika — z etapu osoby. */
export function workbenchDefaultSection(row: ProcessPersonRow): PersonPanelSection {
  return defaultPanelSectionFor(row.group, row.column);
}

/**
 * Czy otwarta zakładka ma WŁASNY przycisk ruchu (screening w „Nowych”, CV na
 * „Zweryfikowanym”). Wtedy panel chowa ogólną ramkę „Następny etap” — jedno
 * wejście do ruchu, jak dawniej w warsztacie.
 */
export function workbenchSectionOwnsMove({
  row,
  section,
  columns,
  readOnly,
  budgetHourly,
}: {
  row: ProcessPersonRow;
  section: PersonPanelSection;
  columns: KanbanColumn[];
  readOnly: boolean;
  budgetHourly: number | null;
}): boolean {
  if (readOnly) return false;
  const { item, column } = row;
  const offTemplate = isOffTemplateRow(row);
  const inScreeningWorkbench =
    (!offTemplate && isNewColumn(column)) ||
    (column.category !== "terminal" &&
      !offTemplate &&
      (Boolean(item.hm_veto) || isOverHourlyBudget(item, budgetHourly)));
  const inCvWorkbench = column === findStageColumn(columns, VERIFIED_STAGE);
  return (section === "screening" && inScreeningWorkbench) || (section === "cv" && inCvWorkbench);
}

/**
 * Podpowiedź zamknięcia rekrutacji po zatrudnieniu. Otwiera okno „Zlecenie”
 * na zamknięciu (tam liczy się domyślny powód „Obsadzone przez nas”).
 * - obsada znana: gdy zatrudnionych jest co najmniej tylu, ilu zamówiono;
 * - obsada nieznana: każde zatrudnienie, bez twierdzenia o komplecie.
 */
export function HeadcountFilledHint({
  columns,
  headcount,
  enabled,
  onRequestCloseJob,
}: {
  columns: KanbanColumn[];
  headcount: number | null;
  enabled: boolean;
  onRequestCloseJob?: () => void;
}) {
  if (!enabled || !onRequestCloseJob) return null;
  const hired = countHired(columns);
  const target = headcount != null && headcount > 0 ? headcount : null;
  if (hired < (target ?? 1)) return null;
  return (
    <button
      type="button"
      onClick={onRequestCloseJob}
      title={`Zatrudnionych: ${hired}${target != null ? ` z ${target}` : ""}. Otwiera okno „Zlecenie" na zamknięciu rekrutacji.`}
      className="mb-3 flex w-full items-center justify-between gap-2 rounded-md border border-success/20 bg-success-muted px-3 py-2 text-left text-xs font-medium text-success-muted-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <span>
        {target != null
          ? "Obsada kompletna — zamknij rekrutację"
          : "Jest zatrudnienie — zamknij rekrutację, jeśli obsada jest kompletna"}
      </span>
      {target != null ? (
        <span className="tabular-nums opacity-80">{hired} z {target}</span>
      ) : null}
    </button>
  );
}

function daysPhrase(days: number): string {
  if (days <= 0) return "od dziś";
  return `od ${days} ${days === 1 ? "dnia" : "dni"}`;
}

/**
 * Notatki w tej rekrutacji + oś czasu z faktów, które niesie wiersz. Pole
 * nowej notatki stoi zawsze na dole panelu — tu go nie dublujemy.
 */
function NotesTab({ row, jobId, readOnly }: { row: ProcessPersonRow; jobId: number; readOnly: boolean }) {
  const notesQuery = useJobNotes(row.candidateId, jobId);
  const { item } = row;
  return (
    <div className="space-y-4 text-[13px]">
      <section aria-label="Notatki" className="space-y-2">
        <h3 className="text-xs font-semibold text-muted-foreground">Notatki w tej rekrutacji</h3>
        <JobNotesBlock
          candidateId={row.candidateId}
          query={notesQuery}
          readOnly={readOnly}
          emptyText="Brak notatek w tej rekrutacji."
        />
      </section>
      {/* Oś czasu WYŁĄCZNIE z faktów, które niesie wiersz — zmyślony wpis
          w historii jest gorszy niż jej brak. */}
      <section aria-label="Historia w rekrutacji" className="space-y-2">
        <h3 className="text-xs font-semibold text-muted-foreground">Historia w rekrutacji</h3>
        <ul className="space-y-2">
          {row.nextAction.label ? (
            <li className="grid grid-cols-[76px_minmax(0,1fr)] gap-x-2.5">
              <span className="text-xs font-medium text-primary">teraz</span>
              <span className="text-foreground">Następny krok: {row.nextAction.label}</span>
            </li>
          ) : null}
          {row.daysInStage != null ? (
            <li className="grid grid-cols-[76px_minmax(0,1fr)] gap-x-2.5">
              <span className="text-xs text-muted-foreground">etap</span>
              <span className="text-foreground">
                {row.stageLabel} — {daysPhrase(row.daysInStage)}
              </span>
            </li>
          ) : null}
          <li className="grid grid-cols-[76px_minmax(0,1fr)] gap-x-2.5">
            <span className="text-xs text-muted-foreground">
              {item.added_to_job_at ? formatDate(item.added_to_job_at) : "—"}
            </span>
            <span className="min-w-0">
              <span className="block text-foreground">Dodany do rekrutacji</span>
              <span className="block text-xs text-muted-foreground">
                {item.added_to_job_by_name?.trim() || "Brak danych o osobie dodającej"}
              </span>
            </span>
          </li>
        </ul>
      </section>
    </div>
  );
}

export interface PersonWorkbenchTabsProps {
  row: ProcessPersonRow;
  jobId: number;
  columns: KanbanColumn[];
  readOnly: boolean;
  canWriteClientRate: boolean;
  workbenchContext: WorkbenchContext;
  section: PersonPanelSection;
  onSectionChange: (section: PersonPanelSection) => void;
}

export function PersonWorkbenchTabs({
  row,
  jobId,
  columns,
  readOnly,
  canWriteClientRate,
  workbenchContext: ctx,
  section,
  onSectionChange,
}: PersonWorkbenchTabsProps) {
  const candidateId = row.candidateId;
  const { item } = row;

  // Odwiedzone zakładki tej osoby zostają zamontowane. Zmiana osoby czyści zbiór.
  const [visited, setVisited] = useState<{ candidateId: number; sections: PersonPanelSection[] }>({
    candidateId,
    sections: [section],
  });
  if (visited.candidateId !== candidateId) {
    setVisited({ candidateId, sections: [section] });
  } else if (!visited.sections.includes(section)) {
    setVisited({ candidateId, sections: [...visited.sections, section] });
  }
  const mounted = visited.candidateId === candidateId ? visited.sections : [section];

  const change = useCallback((next: string) => onSectionChange(next as PersonPanelSection), [onSectionChange]);

  const kanban = ctx.kanbanQueryState;
  const jobLabel = ctx.jobTitle?.trim() || `Rekrutacja #${jobId}`;

  const renderSection = (value: PersonPanelSection): ReactNode => {
    switch (value) {
      case "screening":
        return (
          <ScreeningWorkbench
            layout="panel"
            focusCandidateId={candidateId}
            jobId={jobId}
            jobBudgetHourly={ctx.budgetHourly}
            columns={columns}
            isLoading={kanban.isLoading}
            isError={kanban.isError}
            error={kanban.error}
            isSuccess={kanban.isSuccess}
            onRetry={kanban.refetch}
            onMoved={ctx.onMoved}
            readOnly={readOnly}
            onTabChange={ctx.onTabChange ?? (() => undefined)}
            clientId={ctx.clientId}
            clientName={ctx.clientName ?? null}
            panelFallback={<SavedScreeningView item={item} stageLabel={row.stageLabel} />}
          />
        );
      case "cv":
        return (
          // Karta „CV do klienta” (gotowe / generuje się / brak / powód
          // pominięcia auto-CV) jest w warsztacie; po wysyłce — podgląd.
          <CvHandoffWorkbench
            layout="panel"
            focusCandidateId={candidateId}
            jobId={jobId}
            jobTitle={ctx.jobTitle}
            clientId={ctx.clientId}
            columns={columns}
            isLoading={kanban.isLoading}
            isError={kanban.isError}
            error={kanban.error}
            isSuccess={kanban.isSuccess}
            onRetry={kanban.refetch}
            onMoved={ctx.onMoved}
            readOnly={readOnly}
            canWriteClientRate={canWriteClientRate}
            cproEnabled={ctx.cproEnabled ?? false}
            budgetHourly={ctx.budgetHourly}
            panelFallback={
              <SavedCvView
                item={item}
                stageLabel={row.stageLabel}
                candidateName={row.fullName}
                jobTitle={jobLabel}
                jobId={jobId}
              />
            }
          />
        );
      case "interviews":
        return (
          <JobInterviewsTab
            layout="panel"
            focusCandidateId={candidateId}
            jobId={jobId}
            jobTitle={ctx.jobTitle}
            columns={columns}
            columnsLoading={kanban.isLoading}
            columnsError={kanban.isError ? (kanban.error ?? true) : undefined}
            columnsSuccess={kanban.isSuccess}
            onColumnsRetry={kanban.refetch}
            readOnly={readOnly}
            budgetHourly={ctx.budgetHourly}
          />
        );
      case "contract":
        return (
          <>
            <HeadcountFilledHint
              columns={columns}
              headcount={ctx.headcount ?? null}
              enabled={ctx.canCloseJob && !readOnly && ctx.jobClosed !== true}
              onRequestCloseJob={ctx.onRequestCloseJob}
            />
            <JobContractTab
              layout="panel"
              focusCandidateId={candidateId}
              jobId={jobId}
              jobTitle={jobLabel}
              clientId={ctx.clientId}
              columns={columns}
              columnsLoading={kanban.isLoading}
              columnsError={kanban.isError ? (kanban.error ?? true) : undefined}
              columnsSuccess={kanban.isSuccess}
              onColumnsRetry={kanban.refetch}
              readOnly={readOnly}
              canCloseJob={ctx.canCloseJob}
              // „Zamknij rekrutację" mieszka w oknie „Zlecenie" — panel JEDNEJ
              // osoby nie jest miejscem na akcję dotyczącą całej rekrutacji.
              hideCloseJob
            />
          </>
        );
      case "match":
        return (
          <DopasowanieTab
            candidateId={candidateId}
            recruitments={[{ job_id: jobId, job_title: jobLabel }]}
            defaultJobId={jobId}
            readOnly={readOnly}
          />
        );
      case "notes":
      default:
        return <NotesTab row={row} jobId={jobId} readOnly={readOnly} />;
    }
  };

  return (
    <div className="space-y-3" data-testid="person-workbench">
      <TabbedNav
        ariaLabel="Narzędzia osoby"
        tabs={PERSON_PANEL_SECTIONS.map(({ value, label }) => ({ value, label }))}
        value={section}
        onValueChange={change}
        overflow="wrap"
        dense
      />
      {PERSON_PANEL_SECTIONS.filter(({ value }) => mounted.includes(value)).map(({ value, label }) => (
        <div
          // Klucz = osoba + zakładka: odświeżenie tablicy NIE odmontowuje
          // zakładki, zmiana osoby — tak.
          key={`${candidateId}:${value}`}
          role="tabpanel"
          aria-label={label}
          hidden={value !== section}
          data-section={value}
        >
          {renderSection(value)}
        </div>
      ))}
    </div>
  );
}
