"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { DragDropContext, Draggable, Droppable, type DropResult } from "@hello-pangea/dnd";
import { Plus, Search } from "lucide-react";

import { CaseFormDialog } from "@/components/admin-cases/CaseFormDialog";
import { casePatchError } from "@/components/admin-cases/CaseConsultant";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { apiErrorMessage } from "@/lib/api-error";
import {
  CASE_AREAS,
  CASE_AREA_LABELS,
  usePatchCase,
  useCases,
  useTakeCase,
  type CaseCard,
  type CaseListFilters,
} from "@/lib/api/admin-cases";
import { useUpdateRedeploy, type CardCase } from "@/lib/api/care";
import {
  useCareBoard,
  useSetCareBoardState,
  type CareBoardCard,
  type CareBoardColumn,
} from "@/lib/api/care-board";
import type { HrConfig } from "@/lib/api/hr";
import { cn } from "@/lib/utils";
import { isForbiddenError, isNotFoundError, resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";

import { BoardStateDialog, type BoardStateValue } from "./BoardStateDialog";
import { canSeeCareBoard } from "./care-access";
import { CaseTile } from "./CaseTile";
import { CareTile } from "./CareTile";
import { Chip } from "./Chip";
import { DecisionDoneDialog, type DecisionOutcome } from "./DecisionDoneDialog";
import { DoneColumn } from "./DoneColumn";
import { WorkItemPanel } from "./WorkItemPanel";
import { WorkList } from "./WorkList";
import {
  LIST_FILTER_LABELS,
  OPEN_WORK_COLUMNS,
  WORK_COLUMN_LABELS,
  buildColumns,
  careActionHref,
  careItem,
  caseDueThisWeek,
  caseItem,
  caseItemKey,
  caseStubFromCardCase,
  decisionIdOf,
  demandNeedsManager,
  filterCareCards,
  isOrderEndDecision,
  itemColumn,
  matchesListFilter,
  moveAction,
  planItemIdOf,
  readViewPreference,
  showsCare,
  showsCases,
  visibleColumnItems,
  writeViewPreference,
  type ListFilter,
  type WorkArea,
  type WorkColumn,
  type WorkFilters,
  type WorkItem,
  type WorkScope,
  type WorkView,
} from "./work-board-model";

const MODULE_OFF_NOTICE =
  "Moduł „Sprawy administracja@” nie jest jeszcze włączony. Włącza go administrator w Ustawieniach → Kadry.";

type Scope = "mine" | "all";

export interface WorkBoardProps {
  /** `cases` — Ludzie → Sprawy; `care` — Opieka → Do zrobienia. */
  scope: WorkScope;
  config: HrConfig;
  /** Okno „Rozmowa” (F2); `planItemId` = punkt planu, który rozmowa zamyka. */
  onOpenConversation?: (contractId: number, planItemId?: number | null) => void;
  /** Okno opinii menedżera (F3). */
  onOpenFeedback?: (card: CareBoardCard) => void;
  /** „Przekaż do front office” (F2). */
  onOpenFrontOffice?: (contractId: number) => void;
  /** „Rozmowa z menedżerem” o popycie (F3). */
  onOpenDemand?: (card: CareBoardCard) => void;
  /**
   * Otwarty panel karty (np. `/care?card=<key>` z dzwonka). Zmiana wartości
   * (miękka nawigacja na tej samej zakładce) otwiera panel nowej karty.
   */
  initialSelectedKey?: string | null;
  /** Zamknięcie panelu — ekran zdejmuje `card` z adresu (F5 nie otwiera go ponownie). */
  onCloseSelected?: () => void;
  /** Widok na start (harness); bez niego — zapamiętany wybór osoby. */
  initialView?: WorkView;
  initialArea?: WorkArea | null;
  /**
   * Filtr kolejki z adresu (`/care?filter=po-terminie|do-piatku|rozmowy|opinie|
   * decyzje|dane|popyt` — linki z dzwonków): chip listy i filtr tablicy.
   */
  initialFilter?: ListFilter;
  /** Karta konsultanta w panelu ekranu (/care) — klik w osobę i „Otwórz pełną kartę”. */
  onOpenContract?: (contractId: number) => void;
}

function showCaseControlsFor(casesAllowed: boolean, casesQuiet: boolean): boolean {
  return casesAllowed && !casesQuiet;
}

interface PendingState {
  card: CareBoardCard;
  column: CareBoardColumn;
  ask: "schedule" | "retry";
}

function OpenColumn({
  column,
  items,
  expanded,
  onToggleExpanded,
  renderItem,
  canDrag,
}: {
  column: WorkColumn;
  items: WorkItem[];
  expanded: boolean;
  onToggleExpanded: () => void;
  renderItem: (item: WorkItem, drag: Parameters<typeof CaseTile>[0]["drag"]) => React.ReactNode;
  canDrag: (item: WorkItem) => boolean;
}) {
  const { visible, hiddenCare } = visibleColumnItems(items, expanded);
  return (
    <Droppable droppableId={column}>
      {(provided, snapshot) => (
        <section
          aria-labelledby={`cases-col-${column}`}
          className={cn(
            "flex min-w-0 flex-col gap-2 rounded-xl bg-muted/70 p-2.5 transition-colors",
            snapshot.isDraggingOver && "bg-primary/10",
          )}
        >
          <div className="flex items-center justify-between px-1">
            <h3 id={`cases-col-${column}`} className="text-[13.5px] font-semibold">
              {WORK_COLUMN_LABELS[column]}
            </h3>
            <Badge size="sm" variant="neutral" className="tabular-nums">
              {items.length}
            </Badge>
          </div>
          <ul ref={provided.innerRef} {...provided.droppableProps} className="flex min-h-8 flex-col gap-2">
            {visible.map((item, index) => (
              <Draggable
                key={item.key}
                draggableId={item.key}
                index={index}
                isDragDisabled={!canDrag(item)}
              >
                {(dragProvided, dragSnapshot) => (
                  <>{renderItem(item, { provided: dragProvided, isDragging: dragSnapshot.isDragging })}</>
                )}
              </Draggable>
            ))}
            {provided.placeholder}
          </ul>
          {hiddenCare > 0 || (expanded && items.some((item) => item.type === "care")) ? (
            <Button size="sm" variant="ghost" className="w-full" onClick={onToggleExpanded}>
              {expanded ? "Zwiń" : `Pokaż wszystkie (${items.length})`}
            </Button>
          ) : null}
        </section>
      )}
    </Droppable>
  );
}

/**
 * Wspólna tablica pracy (decyzja Artura 22.10.2026): Ludzie → Sprawy
 * (`scope="cases"`) i Opieka → Do zrobienia (`scope="care"`). Wszystko
 * z dzisiejszej tablicy spraw zostaje (Moje/Wszystkie, chipy obszarów
 * z licznikami, Na ten tydzień, Bez osoby, szukanie, Nowa sprawa, karta
 * sprawy, Weź, wąskie „Zrobione”); dochodzą karty opieki (obszar „Opieka”,
 * tylko z dostępem do opieki), „Moi podopieczni”, kropka zdrowia przy
 * kartach z konsultantem, Tablica / Lista, przeciąganie z „Przenieś do…”
 * i panel boczny karty.
 */
export function WorkBoard({
  scope: boardScope,
  config,
  onOpenConversation,
  onOpenFeedback,
  onOpenFrontOffice,
  onOpenDemand,
  initialSelectedKey = null,
  onCloseSelected,
  initialView,
  initialArea = null,
  initialFilter = "all",
  onOpenContract,
}: WorkBoardProps) {
  const router = useRouter();
  const { showToast } = useToast();
  const user = useAuthStore((s) => s.user);
  const me = user?.id ?? null;
  const careAccess = canSeeCareBoard(user, config);
  const canManageFromConfig = config.me.cases || config.me.is_admin;
  const casesAllowed =
    boardScope === "cases" ||
    (config.open_modules.cases &&
      (config.me.cases || config.me.is_admin || config.me.has_assigned_cases === true));

  // Obsługa skrzynki zaczyna od „Wszystkie” — także w Opiece, do której sprawy
  // przeszły z „Ludzi” (22.10.2026), gdy nie ma roli opieki.
  const [scope, setScope] = useState<Scope>(
    (boardScope === "cases" || !careAccess) && canManageFromConfig ? "all" : "mine",
  );
  const [area, setArea] = useState<WorkArea | null>(initialArea);
  const [week, setWeek] = useState(false);
  const [unassigned, setUnassigned] = useState(false);
  const [mineCare, setMineCare] = useState(false);
  const [query, setQuery] = useState("");
  const [showClosed, setShowClosed] = useState(false);
  const [creating, setCreating] = useState(false);
  const [view, setView] = useState<WorkView>(initialView ?? "board");
  const [selectedKey, setSelectedKey] = useState<string | null>(initialSelectedKey);
  const [snapshot, setSnapshot] = useState<WorkItem | null>(null);
  const [overrides, setOverrides] = useState<ReadonlyMap<string, WorkColumn>>(new Map());
  const [expanded, setExpanded] = useState<ReadonlySet<WorkColumn>>(new Set());
  const [pending, setPending] = useState<PendingState | null>(null);
  const [pendingError, setPendingError] = useState<string | null>(null);
  const [listFilter, setListFilter] = useState<ListFilter>(initialFilter);
  const [closing, setClosing] = useState<CareBoardCard | null>(null);
  const [closingError, setClosingError] = useState<string | null>(null);

  // Link z dzwonka z innym `?filter=` przy otwartej tablicy (miękka nawigacja).
  useEffect(() => setListFilter(initialFilter), [initialFilter]);

  // Link z dzwonka przy otwartej już tablicy (miękka nawigacja) — inicjalizator
  // `useState` działa tylko raz, więc nowy klucz z adresu dosyłamy efektem.
  useEffect(() => {
    setSelectedKey(initialSelectedKey);
    setSnapshot(null);
  }, [initialSelectedKey]);

  useEffect(() => {
    if (!initialView) setView(readViewPreference(boardScope, me, "board"));
  }, [boardScope, me, initialView]);

  const take = useTakeCase();
  const patchCase = usePatchCase();
  const setCareState = useSetCareBoardState();
  const updateRedeploy = useUpdateRedeploy();

  // TEN SAM kształt filtrów co przed 22.10.2026 (`mine_care` tylko, gdy włączony) —
  // inaczej klucz listy rozjeżdża się z zasianym cache harnessu. „Moi podopieczni”
  // = sprawy moich konsultantów niezależnie od tego, kto je prowadzi (K1) — bez `mine`.
  const casesFilters: CaseListFilters = {
    mine: !mineCare && (scope === "mine" || !canManageFromConfig),
    area: area === "care" ? null : area,
    q: query,
    include_closed: showClosed,
    week,
    unassigned,
    ...(mineCare ? { mine_care: true } : {}),
  };
  // „Moi podopieczni” u opiekuna bez „Spraw” i bez własnej sprawy: serwer daje
  // sprawy podopiecznych (bez treści cudzych spraw) — audyt 22.10, F11.
  const cases = useCases(
    casesFilters,
    casesAllowed || (careAccess && mineCare && Boolean(config.open_modules.cases)),
  );
  const careBoard = useCareBoard(scope === "mine" || mineCare ? "mine" : "all", careAccess);
  // Wyłączone zapytanie i tak oddaje dane z cache (np. po zmianie konta) — bez
  // dostępu do opieki kart opieki nie pokazujemy wcale.
  const careData = careAccess ? careBoard.data : undefined;

  const canManage = cases.data?.can_manage ?? canManageFromConfig;
  const counts = cases.data?.counts;
  const today = cases.data?.today ?? careData?.today;
  const weekEnd = cases.data?.week_end ?? careData?.week_end;
  const filters: WorkFilters = { area, week, unassigned, query };

  // W „Opiece” brak dostępu do spraw (403) albo wyłączony moduł (404) to nie
  // awaria — tablica pokazuje same karty opieki.
  const casesQuiet =
    boardScope === "care" && (isForbiddenError(cases.error) || isNotFoundError(cases.error));
  const caseCards = useMemo(
    () =>
      showsCases(filters) && !casesQuiet
        ? (cases.data?.items ?? []).filter(
            // Opiekun bez „Spraw” widzi w „Do zrobienia” sprawę tylko z terminem do
            // piątku albo po terminie (S3). Obsługa skrzynki pracuje na pełnym
            // kanbanie spraw — od #2567 jest on tylko tutaj (K1: „zostaje wszystko”),
            // tak samo osoba przypisana do sprawy bez roli opieki (audyt 22.10, F12).
            (card) => boardScope !== "care" || canManage || !careAccess || caseDueThisWeek(card, weekEnd),
          )
        : [],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [cases.data, area, casesQuiet, boardScope, weekEnd, canManage, careAccess],
  );
  const allCareCards = useMemo(() => careData?.cards ?? [], [careData]);
  const careCards = useMemo(
    () =>
      filterCareCards(allCareCards, filters, weekEnd).filter(
        (card) => !mineCare || card.owner_user_id === me,
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [allCareCards, area, week, unassigned, query, weekEnd, mineCare, me],
  );
  const allItems = useMemo<WorkItem[]>(
    () => [...caseCards.map(caseItem), ...careCards.map(careItem)],
    [caseCards, careCards],
  );
  // Filtr kolejki (chip listy albo `?filter=`) — na tablicy chowa otwarte karty spoza filtra.
  const items = useMemo<WorkItem[]>(
    () =>
      view === "board" && listFilter !== "all"
        ? allItems.filter((item) => {
            const column = itemColumn(item);
            // Zrobione i zamknięte zostają w wąskiej kolumnie — filtr dotyczy kolejki.
            return column === "done" || column === "closed" || matchesListFilter(item, listFilter, weekEnd);
          })
        : allItems,
    [allItems, view, listFilter, weekEnd],
  );
  const columns = useMemo(
    () => buildColumns(items, { careFirst: boardScope === "care", overrides }),
    [items, boardScope, overrides],
  );

  const resolved = selectedKey ? (allItems.find((item) => item.key === selectedKey) ?? null) : null;
  useEffect(() => {
    if (resolved) setSnapshot(resolved);
  }, [resolved]);
  const selected = selectedKey ? (resolved ?? (snapshot?.key === selectedKey ? snapshot : null)) : null;

  const casesState = resolveViewState({
    isLoading: cases.isLoading,
    isError: cases.isError,
    error: cases.error,
    isSuccess: cases.isSuccess,
  });

  if (boardScope === "cases" && casesState === "not_found") {
    return <QueryStateNotice state="not_found" description={MODULE_OFF_NOTICE} />;
  }
  if (boardScope === "cases" && casesState === "forbidden") {
    return (
      <QueryStateNotice
        state="forbidden"
        description="Sprawy widzą osoby z uprawnieniem „Sprawy” i osoby przypisane do sprawy."
      />
    );
  }
  if (boardScope === "care" && careBoard.isError && isForbiddenError(careBoard.error)) {
    return (
      <QueryStateNotice
        state="forbidden"
        description="Tablicę opieki widzą opiekunowie konsultantów, Delivery Leadzi, Head of Recruitment i administrator."
      />
    );
  }

  const loading = (casesAllowed && cases.isLoading) || (careAccess && careBoard.isLoading);
  const casesFailed = casesAllowed && cases.isError && !casesQuiet;
  const careFailed = careAccess && careBoard.isError;
  const blockingError = boardScope === "cases" ? casesFailed : careFailed && (casesFailed || !casesAllowed);

  const selectItem = (item: WorkItem) => {
    setSnapshot(item);
    setSelectedKey(item.key);
  };

  const setOverride = (key: string, column: WorkColumn | null) =>
    setOverrides((current) => {
      const next = new Map(current);
      if (column) next.set(key, column);
      else next.delete(key);
      return next;
    });

  const careAction = (card: CareBoardCard): (() => void) | null => {
    // Dane i popyt bez menedżera prowadzą do „Ludzie i technologie” klienta (link).
    if (card.kind === "data" || demandNeedsManager(card)) return null;
    if (card.kind === "contact" && onOpenConversation && card.contract_id) {
      const contractId = card.contract_id;
      return () => onOpenConversation(contractId, planItemIdOf(card.key));
    }
    if (card.kind === "feedback" && onOpenFeedback) return () => onOpenFeedback(card);
    if (card.kind === "decision" && onOpenFrontOffice && card.contract_id) {
      const contractId = card.contract_id;
      return () => onOpenFrontOffice(contractId);
    }
    if (card.kind === "demand" && onOpenDemand) return () => onOpenDemand(card);
    return null;
  };

  const runCareAction = (card: CareBoardCard) => {
    const action = careAction(card);
    if (action) action();
    else router.push(careActionHref(card));
  };

  const saveCareState = (card: CareBoardCard, column: CareBoardColumn, value: BoardStateValue = {}) => {
    setOverride(card.key, column);
    setPendingError(null);
    setCareState.mutate(
      { key: card.key, column, ...value },
      {
        onSuccess: () => {
          setPending(null);
          if (card.kind === "demand" && column === "waiting") showToast("Nie teraz — popyt wróci za 30 dni", "success");
        },
        onError: (err) => {
          const message = apiErrorMessage(err, "Nie udało się przesunąć karty.");
          if (pending) setPendingError(message);
          else showToast(message, "error");
        },
        onSettled: () => setOverride(card.key, null),
      },
    );
  };

  const closeDecision = (card: CareBoardCard) => {
    setClosingError(null);
    setClosing(card);
  };

  /**
   * „Przekazana” = wpis zrobiony, „Nie dotyczy” = odrzucony. Karta z samego
   * końca zamówienia (`decision:end:<kontrakt>`) nie ma jeszcze wpisu —
   * najpierw zakłada go ruch na „W toku” (serwer oddaje klucz `decision:<id>`).
   */
  const finishDecision = async (card: CareBoardCard, outcome: DecisionOutcome) => {
    setClosingError(null);
    setOverride(card.key, "done");
    try {
      let itemId = decisionIdOf(card.key);
      if (itemId == null && isOrderEndDecision(card.key)) {
        const created = (await setCareState.mutateAsync({ key: card.key, column: "in_progress" })) as {
          key?: string;
        };
        itemId = decisionIdOf(created?.key ?? "");
      }
      if (itemId == null) throw new Error("decision without entry");
      await updateRedeploy.mutateAsync({ itemId, status: outcome });
      setClosing(null);
      showToast(outcome === "done" ? "Decyzja przekazana" : "Decyzja: nie dotyczy", "success");
    } catch (err) {
      setClosingError(apiErrorMessage(err, "Nie udało się zamknąć decyzji."));
    } finally {
      setOverride(card.key, null);
    }
  };

  /** „Sprawy tej osoby” w panelu karty opieki — ten sam panel, teraz ze sprawą. */
  const openCaseFromCard = (item: CardCase) => {
    const known = allItems.find((candidate) => candidate.key === caseItemKey(item.id));
    selectItem(known ?? caseItem(caseStubFromCardCase(item, today)));
  };

  const requestMove = (item: WorkItem, target: WorkColumn) => {
    const action = moveAction(item, target, { canManageCases: canManage });
    switch (action.type) {
      case "none":
        return;
      case "forbidden":
        showToast(action.message, "error");
        return;
      case "case-status": {
        if (item.type !== "case") return;
        setOverride(item.key, target);
        patchCase.mutate(
          {
            id: item.card.id,
            patch: { status: action.status, expected_updated_at: item.card.updated_at },
          },
          {
            onSuccess: () => showToast(`Sprawa: ${WORK_COLUMN_LABELS[target]}`, "success"),
            onError: (err) =>
              showToast(casePatchError(err, "Nie udało się zmienić statusu sprawy."), "error"),
            onSettled: () => setOverride(item.key, null),
          },
        );
        return;
      }
      case "care-state": {
        if (item.type !== "care") return;
        if (action.ask) {
          setPendingError(null);
          setPending({ card: item.card, column: action.column, ask: action.ask });
        } else {
          saveCareState(item.card, action.column);
        }
        return;
      }
      case "close-decision":
        if (item.type === "care") closeDecision(item.card);
        return;
      case "open-conversation":
      case "open-feedback":
      case "open-demand":
        if (item.type === "care") runCareAction(item.card);
        return;
    }
  };

  const onDragEnd = (result: DropResult) => {
    const target = result.destination?.droppableId as WorkColumn | undefined;
    if (!target) return;
    const item = items.find((candidate) => candidate.key === result.draggableId);
    if (item) requestMove(item, target);
  };

  const takeCase = (card: CaseCard) => {
    if (me == null) return;
    take.mutate(
      { id: card.id, userId: me, expectedUpdatedAt: card.updated_at },
      {
        onSuccess: () => showToast("Sprawa jest Twoja", "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się wziąć sprawy."), "error"),
      },
    );
  };

  const changeView = (next: WorkView) => {
    setView(next);
    writeViewPreference(boardScope, me, next);
  };

  const careCount = careAccess
    ? filterCareCards(allCareCards, { ...filters, area: "care", week: false, unassigned: false }, weekEnd).length
    : 0;
  const careWeek = careAccess
    ? filterCareCards(allCareCards, { ...filters, area: "care", week: true, unassigned: false }, weekEnd).length
    : 0;
  const careUnassigned = careAccess
    ? filterCareCards(allCareCards, { ...filters, area: "care", week: false, unassigned: true }, weekEnd).length
    : 0;
  // „Moi podopieczni” liczy sprawy moich konsultantów (serwer) i moje karty opieki.
  const careMine = careAccess
    ? filterCareCards(allCareCards, { ...filters, area: "care", week: false, unassigned: false }, weekEnd).filter(
        (card) => card.owner_user_id === me,
      ).length
    : 0;
  const unassignedCases = canManage && showCaseControlsFor(casesAllowed, casesQuiet);
  const haveCounts = Boolean(counts) || (careAccess && careBoard.isSuccess);
  const areaChips = CASE_AREAS.filter((key) => (counts?.areas[key] ?? 0) > 0 || key === area);
  const filtered = Boolean(query.trim() || area || week || unassigned || mineCare || listFilter !== "all");
  const showScope = canManage || careAccess;
  const showCaseControls = showCaseControlsFor(casesAllowed, casesQuiet);
  const everythingReady =
    (!casesAllowed || cases.isSuccess || casesQuiet) && (!careAccess || careBoard.isSuccess);

  const renderItem = (item: WorkItem, drag: Parameters<typeof CaseTile>[0]["drag"]) => {
    const column = overrides.get(item.key) ?? itemColumn(item);
    if (item.type === "case") {
      return (
        <CaseTile
          card={item.card}
          today={today}
          weekEnd={weekEnd}
          onOpen={() => selectItem(item)}
          onTake={canManage && me != null ? () => takeCase(item.card) : null}
          taking={take.isPending}
          onMove={canManage ? (target) => requestMove(item, target) : null}
          column={column}
          drag={drag}
          selected={selectedKey === item.key}
          careLinks={careAccess}
        />
      );
    }
    return (
      <CareTile
        card={column === "done" ? item.card : { ...item.card, column: column as CareBoardColumn }}
        today={today}
        weekEnd={weekEnd}
        onOpen={() => selectItem(item)}
        onAction={careAction(item.card)}
        onMove={(target) => requestMove(item, target)}
        drag={drag}
        selected={selectedKey === item.key}
      />
    );
  };

  const doneCases = columns.done.filter((item) => item.type === "case").map((item) => item.card as CaseCard);
  const closedCases = columns.closed.filter((item) => item.type === "case").map((item) => item.card as CaseCard);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {showScope ? (
          <SegmentedRadio
            label={boardScope === "cases" ? "Zakres spraw" : "Zakres"}
            size="sm"
            value={scope}
            onChange={setScope}
            options={[
              { value: "mine", label: "Moje" },
              { value: "all", label: "Wszystkie" },
            ]}
          />
        ) : null}
        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Obszar">
          <Chip active={area === null} onClick={() => setArea(null)}>
            Wszystkie obszary
          </Chip>
          {careAccess ? (
            <Chip active={area === "care"} onClick={() => setArea(area === "care" ? null : "care")}>
              Opieka <span className="tabular-nums opacity-70">{careCount}</span>
            </Chip>
          ) : null}
          {showCaseControls
            ? areaChips.map((key) => (
                <Chip key={key} active={area === key} onClick={() => setArea(area === key ? null : key)}>
                  {CASE_AREA_LABELS[key]}{" "}
                  <span className="tabular-nums opacity-70">{counts?.areas[key] ?? 0}</span>
                </Chip>
              ))
            : null}
        </div>
        <span aria-hidden className="h-6 w-px bg-border" />
        <Chip active={week} onClick={() => setWeek((v) => !v)} tone="danger">
          Na ten tydzień{" "}
          {haveCounts ? (
            <span className="tabular-nums opacity-70">{(counts?.week ?? 0) + careWeek}</span>
          ) : null}
        </Chip>
        {unassignedCases || careAccess ? (
          <Chip active={unassigned} onClick={() => setUnassigned((v) => !v)}>
            Bez osoby{" "}
            {haveCounts ? (
              <span className="tabular-nums opacity-70">
                {(unassignedCases ? (counts?.unassigned ?? 0) : 0) + careUnassigned}
              </span>
            ) : null}
          </Chip>
        ) : null}
        {careAccess ? (
          <Chip active={mineCare} onClick={() => setMineCare((v) => !v)}>
            Moi podopieczni{" "}
            {counts?.mine_care != null || careBoard.isSuccess ? (
              <span className="tabular-nums opacity-70">{(counts?.mine_care ?? 0) + careMine}</span>
            ) : null}
          </Chip>
        ) : null}
        {view === "board" && listFilter !== "all" ? (
          <Chip active onClick={() => setListFilter("all")}>
            {LIST_FILTER_LABELS[listFilter]} <span aria-hidden>×</span>
            <span className="sr-only">— pokaż wszystko</span>
          </Chip>
        ) : null}
        <div className="ml-auto flex w-full flex-wrap items-center gap-2 sm:w-auto">
          <div className="relative w-full sm:w-56">
            <Search
              aria-hidden
              className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              aria-label={boardScope === "cases" ? "Szukaj sprawy" : "Szukaj na tablicy"}
              placeholder="Szukaj w tytule i opisie…"
              className="h-8 pl-8"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
          <SegmentedRadio
            label="Widok"
            size="sm"
            value={view}
            onChange={changeView}
            options={[
              { value: "board", label: "Tablica" },
              { value: "list", label: "Lista" },
            ]}
          />
          {canManage && showCaseControls ? (
            <Button size="sm" onClick={() => setCreating(true)}>
              <Plus className="h-4 w-4" aria-hidden />
              Nowa sprawa
            </Button>
          ) : null}
        </div>
      </div>

      {loading ? (
        <p className="py-6 text-sm text-muted-foreground">
          {boardScope === "cases" ? "Wczytywanie spraw…" : "Wczytywanie tablicy…"}
        </p>
      ) : blockingError ? (
        <QueryStateNotice
          state="error"
          description={boardScope === "cases" ? "Nie udało się wczytać spraw." : "Nie udało się wczytać tablicy opieki."}
          onRetry={() => {
            if (casesAllowed) void cases.refetch();
            if (careAccess) void careBoard.refetch();
          }}
        />
      ) : (
        <>
          {careFailed ? (
            <QueryStateNotice
              state="error"
              description="Nie udało się wczytać kart opieki — sprawy są aktualne."
              onRetry={() => careBoard.refetch()}
            />
          ) : null}
          {casesFailed ? (
            <QueryStateNotice
              state="error"
              description="Nie udało się wczytać spraw — karty opieki są aktualne."
              onRetry={() => cases.refetch()}
            />
          ) : null}
          {everythingReady && items.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {filtered
                ? "Żadna karta nie pasuje do filtrów."
                : boardScope === "care"
                  ? "Nic nie czeka — brak rozmów, opinii i spraw na ten tydzień."
                  : scope === "mine"
                    ? "Nie masz przypisanych spraw."
                    : "Nie ma otwartych spraw."}
            </p>
          ) : null}
          {view === "list" ? (
            <WorkList
              items={items}
              today={today}
              weekEnd={weekEnd}
              selectedKey={selectedKey}
              onOpen={selectItem}
              careAction={careAction}
              filter={listFilter}
              onFilterChange={setListFilter}
              progress={careAccess ? (careData?.week_progress ?? null) : null}
              onOpenContract={onOpenContract}
            />
          ) : (
            <DragDropContext onDragEnd={onDragEnd}>
              <div
                className="grid items-start gap-3 sm:grid-cols-2 lg:grid-cols-[repeat(3,minmax(0,1fr))_200px]"
                aria-label={boardScope === "cases" ? "Sprawy według statusu" : "Do zrobienia według stanu"}
                role="group"
              >
                {OPEN_WORK_COLUMNS.map((column) => (
                  <OpenColumn
                    key={column}
                    column={column}
                    items={columns[column]}
                    expanded={expanded.has(column)}
                    onToggleExpanded={() =>
                      setExpanded((current) => {
                        const next = new Set(current);
                        if (next.has(column)) next.delete(column);
                        else next.add(column);
                        return next;
                      })
                    }
                    renderItem={renderItem}
                    canDrag={(item) => (item.type === "care" ? item.card.kind !== "data" : canManage)}
                  />
                ))}
                <DoneColumn
                  done={doneCases}
                  closed={closedCases}
                  doneThisMonth={cases.data?.done_this_month ?? 0}
                  showCases={showsCases(filters) && showCaseControls}
                  careDone={showsCare(filters) ? (careData?.done ?? null) : null}
                  showClosed={showClosed}
                  onToggleClosed={() => setShowClosed((value) => !value)}
                  onOpen={(card) => selectItem(caseItem(card))}
                  dropDisabled={false}
                />
              </div>
            </DragDropContext>
          )}
          {cases.data?.truncated ? (
            <p className="text-xs text-muted-foreground">
              Pokazujemy 500 spraw — zawęź obszar albo wyszukiwanie.
            </p>
          ) : null}
        </>
      )}

      <WorkItemPanel
        item={selected}
        onClose={() => {
          setSelectedKey(null);
          onCloseSelected?.();
        }}
        today={today}
        weekEnd={weekEnd}
        careAccess={careAccess}
        canManageCases={canManage}
        onMove={requestMove}
        careAction={careAction}
        onOpenCase={openCaseFromCard}
        onOpenContract={onOpenContract}
        canCreateCase={Boolean(config.open_modules.cases && canManageFromConfig)}
      />

      {closing ? (
        <DecisionDoneDialog
          card={closing}
          pending={setCareState.isPending || updateRedeploy.isPending}
          error={closingError}
          onCancel={() => {
            setClosing(null);
            setClosingError(null);
          }}
          onPick={(outcome) => void finishDecision(closing, outcome)}
        />
      ) : null}

      {pending && today ? (
        <BoardStateDialog
          card={pending.card}
          ask={pending.ask}
          today={today}
          pending={setCareState.isPending}
          error={pendingError}
          onCancel={() => {
            setPending(null);
            setPendingError(null);
          }}
          onSubmit={(value) => saveCareState(pending.card, pending.column, value)}
        />
      ) : null}

      {canManage && creating ? (
        <CaseFormDialog
          open={creating}
          onOpenChange={setCreating}
          onCreated={(id) => router.push(`/people/cases/${id}`)}
        />
      ) : null}
    </div>
  );
}
