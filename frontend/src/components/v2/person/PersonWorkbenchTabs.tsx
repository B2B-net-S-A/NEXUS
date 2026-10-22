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

import { useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { ClientQuestions } from "@/components/calendar/cycle/ClientQuestions";
import { TabbedNav } from "@/components/ds";
import { PreContractSection } from "@/components/v2/person/pre-contract/PreContractSection";
import { AgreementPanelTab } from "@/components/v2/b2b-generator/AgreementPanelTab";
import { JobContractTab } from "@/components/v2/jobs/JobContractTab";
import type { JobDetailTab } from "@/components/v2/jobs/JobDetailCompactHeader";
import { JobInterviewsTab } from "@/components/v2/jobs/JobInterviewsTab";
import { DockLoadError } from "@/components/v2/jobs/workbench-chrome";
import { candidateNoteItems, useCandidateNotes } from "@/components/v2/pages/candidate-notes-query";
import { AddedToBaseHistoryRow, PersonInBase } from "@/components/v2/person/PersonInBase";
import { PersonOffLimits } from "@/components/v2/person/PersonOffLimits";
import { PersonNotesHistory } from "@/components/v2/person/PersonNotesHistory";
import { PersonPanelSideSection } from "@/components/v2/person/PersonPanelSide";
import { PersonSidePreview } from "@/components/v2/person/PersonSidePreview";
import { useCapability } from "@/hooks/useCapability";
import { WorkbenchBelowTabsContext } from "@/components/v2/person/WorkbenchBelowTabs";
import { DopasowanieTab } from "@/components/v2/pages/DopasowanieTab";
import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";
import { MoveLogList, pairMovesQueryKey, type JobMoveLogPage } from "@/components/v2/recruitment/JobMoveLog";
import { CvHandoffWorkbench, ScreeningWorkbench } from "@/components/v2/recruitment/panel-workbenches";
import { ScreeningSummarySection } from "@/components/v2/screening-form/ScreeningSummaryView";
import {
  buildProcessRows,
  defaultPanelSectionFor,
  isOffTemplateRow,
  type OffTemplateBucket,
} from "@/components/v2/recruitment/person-rows";
import type { PersonPanelSection, ProcessPersonRow } from "@/components/v2/recruitment/types";
import api from "@/lib/api";
import { humanNoteCount } from "@/lib/candidate-notes-view";
import { countHired, findStageColumn, isNewColumn, VERIFIED_STAGE } from "@/lib/pipeline-flow";
import type { BoardColumnKey } from "@/lib/board-stages";
import type { NoteFillChannel } from "@/lib/note-fill-channel";
import type { RejectFollowUp } from "@/lib/reject-follow-up";
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
  /** „Biorę — 12 h” z profilu przed telefonem (sekcja „Screening”, 0424). */
  onTake?: (item: KanbanItem) => void;
  /** „Odrzuć” w formularzu screeningu: kogo panel pokaże potem (13.10.2026).
   *  Woła się w chwili kliknięcia — migawka kolejności Tablicy. */
  rejectFollowUp?: (candidateId: number) => RejectFollowUp | undefined;
  /** „Zapisz i przekaż dalej” przeszło (14.10.2026) — panel przechodzi na „CV”.
   *  Tylko po sukcesie ruchu, nie po konflikcie wersji ani odrzuceniu. */
  onForwarded?: (candidateId: number) => void;
  /** Osoba, którą przed chwilą przekazano dalej z formularza — karta CV
   *  pokazuje blok postępu (CV → QC) zamiast samego stanu. */
  forwardedCandidateId?: number | null;
  /** Następna osoba w kolumnie w kolejności „›” (np. „Następna w Screeningu”). */
  nextInColumn?: (candidateId: number, column: BoardColumnKey) => NextInColumn | null;
  /** Otwiera wskazaną osobę w panelu tak jak „›”. */
  openPerson?: (candidateId: number) => void;
  /** D3: pole notatki w doku przekazuje zapisaną notatkę do formularza. */
  noteFill?: NoteFillChannel;
  /** D6 (16.10.2026): werdykt „Akceptuje” otwiera okno „Klient zaakceptował”. */
  onClientAccept?: (candidateId: number, note?: string | null) => void;
}

/** Następna osoba w kolumnie Tablicy. */
export interface NextInColumn {
  candidateId: number;
  name: string;
  /** Np. „czeka 2 dni” — może nie być. */
  detail?: string | null;
}

/** Kontekst, który podaje strona rekrutacji (bez stanu tablicy i budżetu). */
export type BoardWorkbenchContext = Omit<
  WorkbenchContext,
  | "kanbanQueryState"
  | "budgetHourly"
  | "jobTitle"
  | "onTake"
  | "rejectFollowUp"
  | "onForwarded"
  | "forwardedCandidateId"
  | "nextInColumn"
  | "openPerson"
  | "noteFill"
>;

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

/**
 * Zakładki ze WSPÓLNYM podglądem po lewej (09.10.2026): CV firmowe albo
 * oryginał, wymagania i opis „po ludzku”. Jeden egzemplarz podglądu dla
 * czterech zakładek — przejście między nimi nie przewija CV od początku
 * i nie renderuje pliku drugi raz. „Screening” ma własny podgląd (szukanie
 * w CV z wymagań), „Rozmowy” własny z zakładką „Pytania klienta”.
 */
const SHARED_PREVIEW_SECTIONS: ReadonlySet<PersonPanelSection> = new Set(["cv", "contract", "match", "notes"]);

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
 * Czy otwarta zakładka ma WŁASNY przycisk ruchu (formularz screeningu
 * w „Nowych” i „Screeningu” — „Zapisz i przekaż dalej”, CV na
 * „Zweryfikowanym”). Wtedy panel chowa ogólną ramkę „Następny etap” — jedno
 * wejście do ruchu, jak dawniej w warsztacie.
 */
export function workbenchSectionOwnsMove({
  row,
  section,
  columns,
  readOnly,
}: {
  row: ProcessPersonRow;
  section: PersonPanelSection;
  columns: KanbanColumn[];
  readOnly: boolean;
  /** Zostaje w sygnaturze dla wołających; od 0424 nie zmienia odpowiedzi. */
  budgetHourly?: number | null;
}): boolean {
  if (readOnly) return false;
  const { column } = row;
  const inScreeningForm = !isOffTemplateRow(row) && isNewColumn(column);
  const inCvWorkbench = column === findStageColumn(columns, VERIFIED_STAGE);
  return (section === "screening" && inScreeningForm) || (section === "cv" && inCvWorkbench);
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

/** Sufit trasy `/moves`; jedna osoba w jednej rekrutacji ma ruchów kilka, nie setki. */
const PAIR_MOVES_LIMIT = 200;

/**
 * Prawdziwe ruchy tej osoby w tej rekrutacji (`/moves?candidate_id=`): kto, kiedy,
 * z jakiego etapu na jaki. `stageId` w kluczu — po ruchu karta dostaje nowy
 * wiersz etapu i lista odświeża się sama.
 */
function PairMoves({
  jobId,
  candidateId,
  stageId,
  fallback,
}: {
  jobId: number;
  candidateId: number;
  stageId: number;
  /** Fakty z karty — gdy dziennik nie ma jeszcze żadnego wiersza tej osoby. */
  fallback: ReactNode;
}) {
  const query = useQuery<JobMoveLogPage>({
    queryKey: [...pairMovesQueryKey(jobId, candidateId), stageId],
    queryFn: ({ signal }) =>
      api
        .get<JobMoveLogPage>(`/api/pipeline/job/${jobId}/moves`, {
          params: { candidate_id: candidateId, limit: PAIR_MOVES_LIMIT },
          signal,
        })
        .then((r) => r.data),
    retry: false,
    staleTime: 30_000,
    // Po ruchu klucz się zmienia — dotychczasowa lista zostaje do nowej odpowiedzi.
    placeholderData: keepPreviousData,
  });
  if (query.isLoading) {
    return (
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground" role="status">
        <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" /> Wczytywanie ruchów…
      </p>
    );
  }
  if (query.isError) {
    return <DockLoadError what="historię ruchów" onRetry={() => void query.refetch()} />;
  }
  // Serwer sprzed filtra ignoruje `candidate_id` i oddaje ruchy wszystkich osób.
  const items = (Array.isArray(query.data?.items) ? query.data.items : []).filter(
    (move) => move.candidate_id === candidateId,
  );
  if (items.length === 0) return <>{fallback}</>;
  return <MoveLogList items={items} hideCandidate />;
}

/**
 * Notatki osoby (ta rekrutacja + „Wcześniej u nas”) i historia ruchów w tej
 * rekrutacji. Pole nowej notatki stoi zawsze na dole panelu — tu go nie dublujemy.
 * Na górze „Osoba w bazie”, na końcu historii „Dodany do bazy” (13.10.2026).
 */
function NotesTab({ row, jobId, readOnly }: { row: ProcessPersonRow; jobId: number; readOnly: boolean }) {
  const { item } = row;
  return (
    <div className="space-y-4 text-[13px]">
      <PersonOffLimits badge={item.entry_off_limits} />
      <PersonInBase candidateId={row.candidateId} item={item} />
      <PersonNotesHistory candidateId={row.candidateId} jobId={jobId} readOnly={readOnly} />
      <section aria-label="Historia w rekrutacji" className="space-y-2">
        <h3 className="text-xs font-semibold text-muted-foreground">Historia w tej rekrutacji</h3>
        {row.nextAction.label ? (
          <p className="flex gap-3">
            <span className="w-[92px] shrink-0 text-xs font-medium text-primary">teraz</span>
            <span className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full border border-primary" aria-hidden="true" />
            <span className="min-w-0 text-foreground">Następny krok: {row.nextAction.label}</span>
          </p>
        ) : null}
        <PairMoves
          jobId={jobId}
          candidateId={row.candidateId}
          stageId={item.id}
          // Oś czasu WYŁĄCZNIE z faktów, które niesie wiersz — zmyślony wpis
          // w historii jest gorszy niż jej brak.
          fallback={
            <ul className="space-y-2">
              {row.daysInStage != null ? (
                <li className="flex gap-3">
                  <span className="w-[92px] shrink-0 text-xs text-muted-foreground">etap</span>
                  <span className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-primary" aria-hidden="true" />
                  <span className="min-w-0 text-foreground">
                    {row.stageLabel} — {daysPhrase(row.daysInStage)}
                  </span>
                </li>
              ) : null}
              <li className="flex gap-3">
                <span className="w-[92px] shrink-0 text-xs text-muted-foreground">
                  {item.added_to_job_at ? formatDate(item.added_to_job_at) : "—"}
                </span>
                <span className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-primary" aria-hidden="true" />
                <span className="min-w-0">
                  <span className="block text-foreground">Dodany do rekrutacji</span>
                  <span className="block text-xs text-muted-foreground">
                    {item.added_to_job_by_name?.trim() || "Brak danych o osobie dodającej"}
                  </span>
                </span>
              </li>
            </ul>
          }
        />
        <AddedToBaseHistoryRow candidateId={row.candidateId} />
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
  const belowTabs = useContext(WorkbenchBelowTabsContext);
  // Licznik na zakładce: notatki ludzi o tej osobie (ta rekrutacja i wcześniejsze).
  // Ten sam klucz co lista w zakładce i dok — jedno pobranie.
  const notesCount = humanNoteCount(candidateNoteItems(useCandidateNotes(candidateId).data));

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
  // „Wgraj CV” w podglądzie po lewej — ta sama bramka co kafelek w doku.
  const canManageDocuments = useCapability("candidate.document.manage");
  const cvUpload = !readOnly && canManageDocuments ? { candidateName: row.fullName, jobTitle: jobLabel } : undefined;

  const renderSection = (value: PersonPanelSection): ReactNode => {
    switch (value) {
      case "screening":
        return (
          // 0424: jeden formularz screeningu z podglądem obok — w „Nowych”
          // najpierw profil przed telefonem; po końcu procesu tylko odczyt.
          <ScreeningWorkbench
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
            onTake={ctx.onTake}
            rejectFollowUp={ctx.rejectFollowUp}
            onForwarded={ctx.onForwarded}
            noteFill={ctx.noteFill}
            panelFallback={<ScreeningSummarySection candidateId={candidateId} jobId={jobId} showLockNote />}
          />
        );
      case "cv":
        return (
          <>
            {/* Karta „CV do klienta” (gotowe / generuje się / brak / powód
                pominięcia auto-CV) jest w warsztacie na każdym etapie; od
                „CV wysłane” bez podmiany CV (D3, 14.10.2026).
                Duży podgląd po lewej jest wspólny (`SHARED_PREVIEW_SECTIONS`). */}
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
              forwarded={ctx.forwardedCandidateId === candidateId}
              nextInColumn={ctx.nextInColumn}
              openPerson={ctx.openPerson}
            />
          </>
        );
      case "interviews":
        return (
          <>
            {/* D6: przy rozmowach po lewej CV i pytania, które ten klient
                zadawał poprzednim kandydatom. */}
            <PersonSidePreview
              candidateId={candidateId}
              jobId={jobId}
              stageId={item.id}
              budgetHourly={ctx.budgetHourly}
              cvUpload={cvUpload}
              extraTab={{
                label: "Pytania klienta",
                content: <ClientQuestions jobId={jobId} clientName={ctx.clientName ?? null} roomy />,
              }}
            />
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
              onClientAccept={ctx.onClientAccept}
            />
          </>
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
            {/* 04.10.2026: rekruter generuje umowę tu — ten sam formularz
                i ten sam wiersz rejestru co w Generatorze. */}
            {/* 0506 (21.10.2026): umowa przedwstępna — prośba DL / HoR /
                rekrutera, kroki podpisu i ważność przy tej osobie. */}
            <PreContractSection
              candidateId={candidateId}
              jobId={jobId}
              personLabel={[[row.item.name, row.item.lastname].filter(Boolean).join(" "), jobLabel].filter(Boolean).join(" · ")}
              readOnly={readOnly}
            />
            <AgreementPanelTab
              candidateId={candidateId}
              jobId={jobId}
              readOnly={readOnly}
              agreement={row.item.agreement ?? null}
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
              agreementInPanel
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
    <div className="@container space-y-3" data-testid="person-workbench">
      <TabbedNav
        ariaLabel="Narzędzia osoby"
        // W kolumnie 460 px sześć pełnych etykiet łamało się w drugi rząd —
        // najdłuższa skraca się tam do „Notatki”.
        tabs={PERSON_PANEL_SECTIONS.map(({ value, label }) => ({
          value,
          label:
            value === "notes" ? (
              <>
                Notatki <span className="@max-md:hidden">i historia</span>
                {/* Liczba zwykłym tekstem, nie plakietką `count`: w kolumnie
                    460 px plakietka zrzucała tę zakładkę do drugiego rzędu.
                    Spacja stoi W liczniku — po schowanym „i historia” zlewa się
                    ze spacją po „Notatki” w jedną. */}
                {notesCount > 0 ? (
                  <span className="text-[11px] tabular-nums text-muted-foreground" data-testid="notes-tab-count">
                    {" "}
                    {notesCount > 99 ? "99+" : notesCount}
                  </span>
                ) : null}
              </>
            ) : (
              label
            ),
        }))}
        value={section}
        onValueChange={change}
        overflow="wrap"
        dense
      />
      {/* Pasek zakładek stoi w miejscu (09.10.2026): „Warunki i następny etap”
          przychodzą z doku i stoją pod paskiem, nie w głowie panelu. */}
      {belowTabs}
      {/* Podgląd po lewej w każdej zakładce: panel ma wtedy stałą szerokość,
          więc pasek zakładek nie przesuwa się też w bok. */}
      {mounted.some((value) => SHARED_PREVIEW_SECTIONS.has(value)) ? (
        <PersonPanelSideSection active={SHARED_PREVIEW_SECTIONS.has(section)}>
          <PersonSidePreview
            key={candidateId}
            candidateId={candidateId}
            jobId={jobId}
            stageId={item.id}
            budgetHourly={ctx.budgetHourly}
            cvUpload={cvUpload}
          />
        </PersonPanelSideSection>
      ) : null}
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
          {/* Podgląd sekcji stoi w lewej strefie panelu, poza tym `div` —
              niewidoczna sekcja musi schować go sama. */}
          <PersonPanelSideSection active={value === section}>{renderSection(value)}</PersonPanelSideSection>
        </div>
      ))}
    </div>
  );
}
