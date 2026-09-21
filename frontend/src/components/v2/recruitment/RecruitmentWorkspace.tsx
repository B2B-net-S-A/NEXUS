"use client";

/**
 * Widok „osoby" rekrutacji: pasek etapów + szybkie filtry + tabela + panel.
 *
 * Zastępuje dwanaście zakładek jedną tabelą. Komponent SKŁADA gotowe części
 * i trzyma wyłącznie stan widoku (chipy, tekst, sortowanie, zaznaczenie).
 * Wszystko, co ma przeżyć odświeżenie strony albo przyjść z linku —
 * segment, aktywna osoba, sekcja panelu — jest sterowane propsami (adres
 * strony trzyma rodzic).
 *
 * Ruch etapu, odrzucenie i ruch zbiorczy idą WYŁĄCZNIE przez
 * `usePipelineMove` — te same okna i te same reguły co tablica kanbana
 * (CLAUDE.md „Kanban bez bramek").
 */

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";

import { matchingApi } from "@/lib/api";
import { CV_SENT_STAGE, findStageColumn } from "@/lib/pipeline-flow";
import { resolveViewState } from "@/lib/view-state";
import { cn } from "@/lib/utils";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import type { VirtualTableKey } from "@/components/ds/VirtualTable";
import { Button } from "@/components/ui/button";
import type { KanbanColumn } from "@/components/v2/pages/kanban-shared";
import { useCandidateContactFeature } from "@/hooks/useCandidateContactFeature";
import { useFillAvailableHeight } from "@/hooks/useFillAvailableHeight";
import {
  usePipelineMove,
  type PipelineRejectionReasonOption,
} from "@/hooks/usePipelineMove";

import { BulkBar } from "./BulkBar";
import { PeopleTable } from "./PeopleTable";
import { useBulkCvHandoff } from "./useBulkCvHandoff";
import { PersonPanel, type KanbanQueryState, type WorkbenchContext } from "./PersonPanel";
import { QuickChips } from "./QuickChips";
import { StageStrip } from "./StageStrip";
import {
  DEFAULT_PERSON_SORT,
  PERSON_SORT_PRESET,
  buildProcessRows,
  chipCounts,
  filterRows,
  groupRowsByOwner,
  recruiterOptions,
  shouldGroupRows,
  sortRows,
  type OffTemplateBucket,
  type PersonSort,
  type QuickChipKey,
} from "./person-rows";
import type {
  PersonPanelSection,
  PersonRow,
  ProcessPersonRow,
  RecruitmentSegment,
  RecruitmentSlideOver,
} from "./types";

/** Dane rekrutacji, których potrzebuje widok — stronę pobiera je rodzic. */
export interface RecruitmentWorkspaceJob {
  title?: string | null;
  /** `effective_budget_hourly` — odznaka „ponad budżet" i okno „Zweryfikowany". */
  budgetHourly: number | null;
  /** Słownik powodów `RejectionV2` (z szablonu rekrutacji albo domyślnego). */
  rejectionReasons: PipelineRejectionReasonOption[];
  /** SLA klienta w dniach roboczych (karta klienta). */
  slaDays?: number | null;
  /** Definicje etapów ze scorecardem — odznaka „Scorecard". */
  stagesWithScorecard?: ReadonlySet<number> | null;
}

export interface RecruitmentWorkspaceProps {
  jobId: number;
  job: RecruitmentWorkspaceJob;
  kanban: { columns: KanbanColumn[]; off_template?: OffTemplateBucket | null } | null | undefined;
  kanbanQueryState: KanbanQueryState;
  canWritePipeline: boolean;
  canWriteClientRate: boolean;
  /** `null` = jeszcze nie wiadomo. */
  openProposalsCount: number | null;
  shortlistCount: number | null;

  segment: RecruitmentSegment;
  onSegmentChange: (segment: RecruitmentSegment) => void;
  activeCandidateId: number | null;
  onActiveCandidateChange: (candidateId: number | null) => void;
  panelSection: PersonPanelSection | null;
  onPanelSectionChange: (section: PersonPanelSection | null) => void;

  workbenchContext: Omit<WorkbenchContext, "kanbanQueryState" | "budgetHourly" | "jobTitle"> &
    Partial<Pick<WorkbenchContext, "jobTitle">>;

  /** Segment „Propozycje z bazy" — wstrzykiwany (osobny moduł). */
  renderProposals?: () => ReactNode;
  renderShortlist?: () => ReactNode;
  onOpenSlideOver: (kind: RecruitmentSlideOver) => void;
  /**
   * „Wyślij CV do klienta" dla zaznaczonych. Domyślnie: `useBulkCvHandoff` —
   * per osoba ruch na „CV Wysłane" → link dla klienta → stawka, a na końcu
   * jedno okno z linkami.
   */
  onBulkSendCv?: (rows: ProcessPersonRow[]) => void;
  headerSlot?: ReactNode;
  /** `false` w testach (jsdom nie ma layoutu). */
  virtualize?: boolean;
  className?: string;
}

const EMPTY_COLUMNS: KanbanColumn[] = [];

export function RecruitmentWorkspace({
  jobId,
  job,
  kanban,
  kanbanQueryState,
  canWritePipeline,
  canWriteClientRate,
  openProposalsCount,
  shortlistCount,
  segment,
  onSegmentChange,
  activeCandidateId,
  onActiveCandidateChange,
  panelSection,
  onPanelSectionChange,
  workbenchContext,
  renderProposals,
  renderShortlist,
  onOpenSlideOver,
  onBulkSendCv,
  headerSlot,
  virtualize = true,
  className,
}: RecruitmentWorkspaceProps) {
  const readOnly = !canWritePipeline;
  const columns = kanban?.columns ?? EMPTY_COLUMNS;
  const offTemplate = kanban?.off_template ?? null;
  const isPeopleSegment = segment !== "proposals" && segment !== "shortlist";

  // ── Stan widoku ─────────────────────────────────────────────────────
  const [chips, setChips] = useState<Set<QuickChipKey>>(new Set());
  const [text, setText] = useState("");
  const [recruiterId, setRecruiterId] = useState<number | null>(null);
  const [sort, setSort] = useState<PersonSort>(DEFAULT_PERSON_SORT);
  // `null` = decyduje próg (`AUTO_GROUP_THRESHOLD`); wybór użytkownika wygrywa.
  const [groupChoice, setGroupChoice] = useState<boolean | null>(null);
  const [selectedKeys, setSelectedKeys] = useState<Set<VirtualTableKey>>(new Set());
  const [noteFocusSignal, setNoteFocusSignal] = useState(0);
  const [stageFocusSignal, setStageFocusSignal] = useState(0);

  // Zaznaczenie dotyczy tego, co widać. Zmiana segmentu = inna lista, więc
  // akcja zbiorcza nie może po cichu objąć osób z poprzedniego filtra.
  useEffect(() => {
    setSelectedKeys(new Set());
  }, [segment]);

  // ── Dane ────────────────────────────────────────────────────────────
  const contactFeature = useCandidateContactFeature();
  // Podłoga 320 px: przy niskim oknie (ok. 690 px) z banerem zostaje ~440 px —
  // wyższa podłoga dokładałaby drugi pasek przewijania strony.
  const fill = useFillAvailableHeight(320);
  // Ten sam klucz co strona rekrutacji (`id` z adresu jest stringiem) — jedno
  // zapytanie karmi pierścienie tablicy i kolumnę „Dop." tabeli.
  const scoresQuery = useQuery({
    queryKey: ["pipeline-scores", String(jobId)],
    queryFn: () => matchingApi.pipelineScores(jobId).then((r) => r.data),
    enabled: isPeopleSegment && Number.isFinite(jobId),
    staleTime: 5 * 60_000,
  });
  const scores = useMemo(() => {
    const map = new Map<number, number>();
    for (const [candidateId, score] of Object.entries(scoresQuery.data?.scores ?? {})) {
      map.set(Number(candidateId), score);
    }
    return map;
  }, [scoresQuery.data]);

  const allRows = useMemo(
    () =>
      buildProcessRows(columns, {
        scores,
        slaDays: job.slaDays ?? null,
        budgetHourly: job.budgetHourly,
        offTemplate,
      }),
    [columns, scores, job.slaDays, job.budgetHourly, offTemplate],
  );

  const segmentRows = useMemo(
    () => (isPeopleSegment ? filterRows(allRows, { segment }) : []),
    [allRows, segment, isPeopleSegment],
  );
  const counts = useMemo(() => chipCounts(segmentRows), [segmentRows]);
  const recruiters = useMemo(() => recruiterOptions(segmentRows), [segmentRows]);
  const visibleRows = useMemo(
    () => sortRows(filterRows(segmentRows, { segment, chips, recruiterId, text }), sort),
    [segmentRows, segment, chips, recruiterId, text, sort],
  );
  const grouped = shouldGroupRows(visibleRows.length, groupChoice);
  const groups = useMemo(
    () => (grouped ? groupRowsByOwner(visibleRows) : null),
    [grouped, visibleRows],
  );

  // Panel czyta osobę ze WSZYSTKICH wierszy, nie z widocznych: po ruchu pod
  // filtrem etapu osoba znika z listy, ale panel ma zostać otwarty na niej
  // (właśnie coś z nią zrobiłem — chcę zobaczyć skutek).
  const activeRow = useMemo(
    () =>
      activeCandidateId == null
        ? null
        : (allRows.find((row) => row.candidateId === activeCandidateId) ?? null),
    [allRows, activeCandidateId],
  );
  const activeKey = activeRow ? activeRow.key : null;

  const selectedRows = useMemo(
    () => visibleRows.filter((row) => selectedKeys.has(row.key)),
    [visibleRows, selectedKeys],
  );

  // ── Ruch etapu ──────────────────────────────────────────────────────
  const move = usePipelineMove({
    jobId,
    job: { budgetHourly: job.budgetHourly, rejectionReasons: job.rejectionReasons },
    columns,
    readOnly,
    canWriteClientRate,
  });

  const clearSelection = useCallback(() => setSelectedKeys(new Set()), []);

  const bulkCv = useBulkCvHandoff({
    jobId,
    jobTitle: job.title ?? null,
    columns,
    canWriteClientRate,
  });
  const startBulkCv = bulkCv.start;
  const cvSentColumn = useMemo(() => findStageColumn(columns, CV_SENT_STAGE), [columns]);
  const handleBulkSendCv = useMemo(() => {
    if (onBulkSendCv) return onBulkSendCv;
    // Szablon bez „CV Wysłane" nie ma dokąd wysłać — przycisk się nie pokazuje.
    if (!cvSentColumn) return undefined;
    // Sam ruch zbiorczy nie wystarcza: wysyłka CV to także link dla klienta.
    return (rows: ProcessPersonRow[]) => startBulkCv(rows, { onHandled: clearSelection });
  }, [onBulkSendCv, cvSentColumn, startBulkCv, clearSelection]);

  // ── Aktywna osoba ───────────────────────────────────────────────────
  const activate = useCallback(
    (row: PersonRow) => {
      if (row.candidateId === activeCandidateId) return;
      onActiveCandidateChange(row.candidateId);
      // Nowa osoba startuje od sekcji SWOJEGO etapu, nie od sekcji poprzedniej.
      onPanelSectionChange(null);
    },
    [activeCandidateId, onActiveCandidateChange, onPanelSectionChange],
  );

  const requestNote = useCallback(
    (row: ProcessPersonRow) => {
      if (row.candidateId !== activeCandidateId) onActiveCandidateChange(row.candidateId);
      onPanelSectionChange("notes");
      setNoteFocusSignal((n) => n + 1);
    },
    [activeCandidateId, onActiveCandidateChange, onPanelSectionChange],
  );

  const requestStageChange = useCallback(
    (row: ProcessPersonRow) => {
      if (row.candidateId !== activeCandidateId) {
        onActiveCandidateChange(row.candidateId);
        onPanelSectionChange(null);
      }
      setStageFocusSignal((n) => n + 1);
    },
    [activeCandidateId, onActiveCandidateChange, onPanelSectionChange],
  );

  const handleRemoved = useCallback(
    (row: ProcessPersonRow) => {
      if (row.candidateId === activeCandidateId) onActiveCandidateChange(null);
    },
    [activeCandidateId, onActiveCandidateChange],
  );

  const toggleChip = useCallback((chip: QuickChipKey) => {
    setChips((prev) => {
      const next = new Set(prev);
      if (next.has(chip)) next.delete(chip);
      else next.add(chip);
      return next;
    });
  }, []);

  // ── Stan zapytania tablicy ──────────────────────────────────────────
  // `isSuccess` jest obowiązkowy: w przerwie między ponowieniami react-query ma
  // `isLoading=false`, `isError=false` i puste dane — bez niego AWARIA
  // wyglądałaby jak „w tej rekrutacji nie ma nikogo".
  const viewState = resolveViewState({
    isLoading: kanbanQueryState.isLoading,
    isError: kanbanQueryState.isError,
    error: kanbanQueryState.isError ? kanbanQueryState.error : undefined,
    isSuccess: kanbanQueryState.isSuccess,
    isEmpty: false,
  });
  const blocking =
    viewState === "error" || viewState === "forbidden" || viewState === "not_found"
      ? viewState
      : null;

  const hasFilters = chips.size > 0 || text.trim() !== "" || recruiterId != null;
  const emptyState =
    allRows.length === 0 ? (
      <div className="flex flex-col items-center gap-3">
        <p>W tej rekrutacji nie ma jeszcze nikogo.</p>
        {!readOnly ? (
          <Button size="sm" onClick={() => onSegmentChange("proposals")}>
            <Plus className="size-3.5" aria-hidden />
            Zobacz propozycje z bazy
          </Button>
        ) : null}
      </div>
    ) : hasFilters ? (
      <div className="flex flex-col items-center gap-3">
        <p>Nikt nie pasuje do ustawionych filtrów.</p>
        <Button
          size="sm"
          variant="outline"
          onClick={() => {
            setChips(new Set());
            setText("");
            setRecruiterId(null);
          }}
        >
          Wyczyść filtry
        </Button>
      </div>
    ) : segment === "in-process" ? (
      "Nikt nie jest teraz w procesie."
    ) : (
      <div className="flex flex-col items-center gap-3">
        <p>Na tym etapie nie ma teraz nikogo.</p>
        <Button size="sm" variant="outline" onClick={() => onSegmentChange("in-process")}>
          Pokaż wszystkich w procesie
        </Button>
      </div>
    );

  const summary =
    visibleRows.length === segmentRows.length
      ? `${visibleRows.length} ${visibleRows.length === 1 ? "osoba" : "osób"}`
      : `${visibleRows.length} z ${segmentRows.length}`;

  const fullWorkbenchContext: WorkbenchContext = {
    ...workbenchContext,
    jobTitle: workbenchContext.jobTitle ?? job.title ?? undefined,
    budgetHourly: job.budgetHourly,
    kanbanQueryState,
  };

  return (
    <div className={cn("flex min-h-0 flex-col gap-3", className)}>
      {headerSlot}

      <StageStrip
        columns={columns}
        offTemplate={offTemplate}
        openProposalsCount={openProposalsCount}
        shortlistCount={shortlistCount}
        segment={segment}
        onSegmentChange={onSegmentChange}
      />

      {segment === "proposals" ? (
        (renderProposals?.() ?? (
          <p className="rounded-lg border border-dashed border-border px-6 py-10 text-center text-sm text-muted-foreground">
            Propozycje z bazy nie są jeszcze dostępne w tym widoku.
          </p>
        ))
      ) : segment === "shortlist" ? (
        (renderShortlist?.() ?? (
          <p className="rounded-lg border border-dashed border-border px-6 py-10 text-center text-sm text-muted-foreground">
            Shortlista nie jest jeszcze dostępna w tym widoku.
          </p>
        ))
      ) : blocking ? (
        <QueryStateNotice
          state={blocking}
          description={
            blocking === "error"
              ? "Nie udało się pobrać osób w tej rekrutacji. Dane mogą istnieć — spróbuj ponownie."
              : undefined
          }
          onRetry={kanbanQueryState.refetch}
        />
      ) : (
        <>
          <QuickChips
            chips={chips}
            counts={counts}
            onToggleChip={toggleChip}
            text={text}
            onTextChange={setText}
            recruiters={recruiters}
            recruiterId={recruiterId}
            onRecruiterChange={setRecruiterId}
            grouped={grouped}
            onGroupedChange={setGroupChoice}
            sortKey={sort.key}
            onSortKeyChange={(key) => setSort(PERSON_SORT_PRESET[key])}
            actions={
              !readOnly ? (
                <>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => onOpenSlideOver("manual-search")}
                  >
                    <Search className="size-3.5" aria-hidden />
                    Szukaj ręcznie
                  </Button>
                  <Button size="sm" onClick={() => onSegmentChange("proposals")}>
                    <Plus className="size-3.5" aria-hidden />
                    Dodaj kandydatów
                  </Button>
                </>
              ) : null
            }
          />

          <div
            ref={fill.ref}
            // Wysokość z pomiaru (do dolnej krawędzi okna); klasa `h-[…]` to
            // wyłącznie wartość sprzed pierwszego pomiaru.
            style={fill.height != null ? { height: fill.height } : undefined}
            className="flex h-[max(460px,calc(100vh_-_300px))] min-h-0 flex-col gap-3.5 lg:flex-row"
          >
            <section aria-label="Lista osób" className="min-h-0 min-w-0 flex-1">
              <PeopleTable
                variant="process"
                rows={visibleRows}
                jobId={jobId}
                groups={groups}
                selectedKeys={selectedKeys}
                onSelectionChange={setSelectedKeys}
                activeKey={activeKey}
                onActiveChange={activate}
                onRowActivate={activate}
                sort={sort}
                onSortChange={(next) => setSort(next ?? DEFAULT_PERSON_SORT)}
                readOnly={readOnly}
                stagesWithScorecard={job.stagesWithScorecard}
                contactFeatureEnabled={contactFeature.enabled}
                onRequestStageChange={requestStageChange}
                onRequestNote={requestNote}
                onRemoved={handleRemoved}
                loading={viewState === "loading"}
                empty={emptyState}
                virtualize={virtualize}
                footer={
                  // Element, który renderuje `null`, nadal jest „truthy" —
                  // stopka zostawiłaby pustą ramkę. Dlatego warunek TUTAJ.
                  !readOnly && selectedRows.length > 0 ? (
                    <BulkBar
                      rows={selectedRows}
                      columns={columns}
                      move={move}
                      onClear={clearSelection}
                      onBulkSendCv={handleBulkSendCv}
                      summary={summary}
                    />
                  ) : viewState === "ready" && visibleRows.length > 0 ? (
                    <p className="px-3.5 py-2 text-xs text-muted-foreground">{summary}</p>
                  ) : null
                }
              />
            </section>

            {activeRow ? (
              <PersonPanel
                row={activeRow}
                jobId={jobId}
                columns={columns}
                move={move}
                readOnly={readOnly}
                canWriteClientRate={canWriteClientRate}
                workbenchContext={fullWorkbenchContext}
                section={panelSection}
                onSectionChange={onPanelSectionChange}
                noteFocusSignal={noteFocusSignal}
                stageFocusSignal={stageFocusSignal}
                onClose={() => onActiveCandidateChange(null)}
              />
            ) : (
              <aside
                aria-label="Wybrana osoba"
                className="hidden w-[372px] shrink-0 flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground lg:flex"
              >
                <p className="font-medium text-foreground">Wybierz osobę z listy</p>
                <p>Kliknij wiersz albo użyj strzałek ↑ ↓ — tutaj pojawi się CV, screening, rozmowy i notatki.</p>
              </aside>
            )}
          </div>
        </>
      )}

      {move.dialogs}
      {bulkCv.dialogs}
    </div>
  );
}
