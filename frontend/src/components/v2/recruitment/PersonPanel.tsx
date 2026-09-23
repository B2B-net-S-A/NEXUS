"use client";

/**
 * Panel osoby — prawa kolumna widoku „rekrutacja = jedna tabela".
 *
 * Dawne osobne zakładki rekrutacji (Screening, CV do klienta, Rozmowy, Umowa)
 * stają się SEKCJAMI panelu: te same warsztaty, ale w układzie `layout="panel"`
 * i zawężone do jednej osoby (`focusCandidateId`). Panel nie powiela ich
 * logiki — przekazuje im dokładnie te propsy, które dziś podaje strona
 * rekrutacji (`workbenchContext`).
 *
 * Dwie rzeczy są tu celowo nietypowe:
 *
 * 1. Odwiedzone sekcje zostają ZAMONTOWANE (ukryte atrybutem `hidden`), dopóki
 *    panel pokazuje tę samą osobę. Przełączenie na „Notatki" w połowie
 *    wypełniania arkusza screeningu nie może skasować wpisanego tekstu.
 * 2. Treść panelu renderuje się przez portal do JEDNEGO, trwałego węzła DOM,
 *    który przenosimy między wąską kolumną a szeroką nakładką. Radix montuje
 *    nakładkę w portalu, więc zwykłe „wyrenderuj to samo w innym miejscu"
 *    odmontowałoby sekcje — i znów zgubiło wpisany tekst.
 */

import { foldBoardColumns } from "@/lib/board-stages";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Info, Loader2, Maximize2, Minimize2, Send, X } from "lucide-react";

import api, { candidatesApi, extractErrorMsg } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { TabbedNav } from "@/components/ds";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from "@/components/ui/sheet";
import { JobContractTab } from "@/components/v2/jobs/JobContractTab";
import type { JobDetailTab } from "@/components/v2/jobs/JobDetailCompactHeader";
import { JobInterviewsTab } from "@/components/v2/jobs/JobInterviewsTab";
import { DopasowanieTab } from "@/components/v2/pages/DopasowanieTab";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { colId, columnLabel, type KanbanColumn } from "@/components/v2/pages/kanban-shared";
import type { PipelineMoveControls } from "@/hooks/usePipelineMove";
import { terminalOf } from "@/lib/kanban-terminal";
import {
  VERIFIED_STAGE,
  findStageColumn,
  isNewColumn,
  moveBlockedReason,
  countHired,
  primaryForwardMove,
} from "@/lib/pipeline-flow";
import {
  BACKGROUND_EVENTS_STEP,
  autoCvSkipReason,
  jobBackgroundEventsApi,
  jobBackgroundEventsQueryKey,
  latestAutoCvSkip,
} from "@/lib/job-background-events";
import { isOverHourlyBudget } from "@/lib/rate-to-hourly";
import { encodeJobBackRef } from "@/lib/url-filters";
import { cn, formatDate } from "@/lib/utils";

import { CvHandoffWorkbench, ScreeningWorkbench } from "./panel-workbenches";
import { SavedCvView, SavedScreeningView } from "./PanelSavedViews";
import { defaultPanelSectionFor, isOffTemplateRow } from "./person-rows";
import type { PersonPanelSection, ProcessPersonRow } from "./types";

// ── Kontrakt z warsztatami ────────────────────────────────────────────

/** Stan zapytania tablicy — warsztaty renderują z niego własne ładowanie/błąd. */
export interface KanbanQueryState {
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  isSuccess: boolean;
  refetch: () => void;
}

/**
 * Wszystko, co strona rekrutacji podaje dziś warsztatom kroków 05–08 —
 * w jednym obiekcie, żeby panel nie rósł o prop przy każdej zmianie warsztatu.
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
  /** `job.update` — domknięcie rekrutacji z sekcji „Umowa". */
  canCloseJob: boolean;
  /** Ile osób klient zamówił (`job.headcount`); `null` = nie wiadomo. */
  headcount?: number | null;
  /** Rekrutacja już zamknięta — podpowiedź domknięcia nie ma sensu. */
  jobClosed?: boolean;
  /**
   * Otwiera okno „Zlecenie" na akcji zamknięcia (tam żyje „Zamknij
   * rekrutację" z domyślnym powodem „Obsadzone przez nas").
   */
  onRequestCloseJob?: () => void;
}

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

export interface PersonPanelProps {
  row: ProcessPersonRow;
  jobId: number;
  columns: KanbanColumn[];
  move: PipelineMoveControls;
  readOnly: boolean;
  canWriteClientRate: boolean;
  workbenchContext: WorkbenchContext;

  /** Sekcja sterowana z zewnątrz (adres strony). Bez niej — z etapu osoby. */
  section?: PersonPanelSection | null;
  onSectionChange?: (section: PersonPanelSection) => void;

  /** Tryb szeroki — opcjonalnie sterowany. */
  wide?: boolean;
  onWideChange?: (wide: boolean) => void;

  /** Rosnący licznik: skrót „N" w tabeli → fokus w polu notatki. */
  noteFocusSignal?: number;
  /** Rosnący licznik: skrót „E" w tabeli → fokus na wyborze etapu. */
  stageFocusSignal?: number;

  onClose?: () => void;
  className?: string;
}

// ── Notatki i historia ────────────────────────────────────────────────

interface NoteListItem {
  id: number;
  content: string;
  author_name?: string | null;
  created_at: string;
}

function daysPhrase(days: number): string {
  if (days <= 0) return "od dziś";
  return `od ${days} ${days === 1 ? "dnia" : "dni"}`;
}

/**
 * Notatki przypięte do TEJ rekrutacji + oś czasu z faktów, które niesie wiersz.
 *
 * Dok kanbana (`PipelineCandidateDock`) trzyma tę samą listę wewnątrz siebie
 * i jej nie eksportuje. Używamy DOKŁADNIE tych samych tras i kluczy zapytań,
 * więc notatka dodana tutaj jest od razu widoczna w doku i na profilu.
 */
/**
 * Dlaczego automat NIE przygotował CV tej osoby (np. reguła klienta wymaga
 * zrzutu zgody RODO). Źródłem jest „Praca w tle" rekrutacji — ten sam klucz
 * zapytania co okno „Historia i czat", bez osobnego endpointu. Informacja, nie
 * bramka: ładowanie, błąd i brak zdarzenia nie rysują nic.
 */
function AutoCvSkipNotice({ jobId, candidateId }: { jobId: number; candidateId: number }) {
  const query = useQuery({
    queryKey: jobBackgroundEventsQueryKey(jobId, BACKGROUND_EVENTS_STEP),
    queryFn: () => jobBackgroundEventsApi.list(jobId, BACKGROUND_EVENTS_STEP),
    retry: false,
    staleTime: 30_000,
  });
  const skipped = latestAutoCvSkip(query.data?.items ?? [], candidateId);
  if (!skipped) return null;
  return (
    <p
      role="note"
      data-testid="auto-cv-skip-notice"
      className="mb-2 flex items-start gap-2 rounded-lg border border-info/25 bg-info-muted px-3 py-2 text-xs text-info-muted-foreground"
    >
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <span>
        CV nie zostało wygenerowane automatycznie: {autoCvSkipReason(skipped)}. Możesz je
        wygenerować ręcznie poniżej.
      </span>
    </p>
  );
}

function NotesSection({
  row,
  jobId,
  readOnly,
  focusSignal,
}: {
  row: ProcessPersonRow;
  jobId: number;
  readOnly: boolean;
  focusSignal: number;
}) {
  const { showSuccess, showError } = useToast();
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const candidateId = row.candidateId;

  useEffect(() => {
    if (focusSignal > 0) textareaRef.current?.focus();
  }, [focusSignal]);

  const notesQuery = useQuery<{ items?: NoteListItem[] }>({
    queryKey: [...candidateQueryKeys.notes(candidateId), jobId],
    queryFn: () =>
      api.get(`/api/notes?candidate_id=${candidateId}&job_id=${jobId}`).then((r) => r.data),
  });

  const addNote = useMutation({
    mutationFn: (content: string) =>
      api.post("/api/notes", {
        candidate_id: candidateId,
        job_id: jobId,
        content,
        note_type: "general",
      }),
    onSuccess: () => {
      setText("");
      queryClient.invalidateQueries({ queryKey: candidateQueryKeys.notes(candidateId) });
      queryClient.invalidateQueries({ queryKey: candidateQueryKeys.timelineRoot(candidateId) });
      showSuccess("Notatka dodana.");
    },
    // Tekst ZOSTAJE w polu — nieudany zapis nie może kosztować przepisywania.
    onError: (error) => showError(extractErrorMsg(error) || "Nie udało się dodać notatki."),
  });

  const submit = () => {
    const content = text.trim();
    if (!content || addNote.isPending) return;
    addNote.mutate(content);
  };

  const { item } = row;
  const notes = notesQuery.data?.items ?? [];

  return (
    <div className="space-y-4 text-[13px]">
      {!readOnly ? (
        <div className="space-y-1.5">
          <label htmlFor={`person-note-${candidateId}`} className="sr-only">
            Nowa notatka
          </label>
          <textarea
            id={`person-note-${candidateId}`}
            ref={textareaRef}
            value={text}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                event.preventDefault();
                submit();
              }
            }}
            rows={3}
            placeholder="Napisz notatkę… (Ctrl+Enter zapisuje)"
            className="w-full resize-none rounded-md border border-border bg-card px-3 py-2 text-[13px] text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          <div className="flex justify-end">
            <Button
              size="sm"
              onClick={submit}
              disabled={!text.trim() || addNote.isPending}
              loading={addNote.isPending}
            >
              <Send className="size-3.5" aria-hidden />
              Dodaj notatkę
            </Button>
          </div>
        </div>
      ) : null}

      <section aria-label="Notatki" className="space-y-2">
        <h3 className="text-xs font-semibold text-muted-foreground">Notatki w tej rekrutacji</h3>
        {notesQuery.isLoading ? (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="size-3 animate-spin" aria-hidden /> Wczytywanie…
          </p>
        ) : notesQuery.isError ? (
          // Awaria NIE może wyglądać jak „brak notatek".
          <p role="alert" className="text-xs text-destructive-muted-foreground">
            Nie udało się wczytać notatek.{" "}
            <button
              type="button"
              className="font-medium underline underline-offset-2"
              onClick={() => void notesQuery.refetch()}
            >
              Ponów
            </button>
          </p>
        ) : notesQuery.isSuccess && notes.length === 0 ? (
          <p className="text-xs text-muted-foreground">Brak notatek w tej rekrutacji.</p>
        ) : (
          <ul className="space-y-2">
            {notes.map((note) => (
              <li key={note.id} className="grid grid-cols-[76px_minmax(0,1fr)] gap-x-2.5">
                <span className="text-xs text-muted-foreground">{formatDate(note.created_at)}</span>
                <span className="min-w-0">
                  <span className="block whitespace-pre-line text-foreground">{note.content}</span>
                  <span className="block text-xs text-muted-foreground">
                    {note.author_name ?? "Nieznany autor"}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        )}
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

// ── Panel ─────────────────────────────────────────────────────────────

interface CandidateHeaderDetail {
  city?: string | null;
  location?: string | null;
  linkedin_current_title?: string | null;
}

/**
 * Podpowiedź zamknięcia rekrutacji po zatrudnieniu. Dawny krok 08 podpowiadał
 * „Obsadzone przez nas" po KAŻDYM zatrudnieniu; w v3 akcja mieszka w oknie
 * „Zlecenie", więc podpowiedź tylko je otwiera — domyślny powód liczy tam ta
 * sama reguła (`hiredCount > 0` → „Obsadzone przez nas").
 *
 * - obsada znana: pokazuje się, gdy zatrudnionych jest co najmniej tylu, ilu
 *   zamówiono („Obsada kompletna · N z M");
 * - obsada NIEZNANA: każde zatrudnienie liczy się jak komplet, ale tekst tego
 *   nie twierdzi — nie wiemy, ilu osób szuka klient.
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

function initialsOf(fullName: string): string {
  return fullName
    .split(/\s+/)
    .map((word) => word[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

/** Trwały węzeł DOM na treść panelu — `null` na serwerze (brak `document`). */
function useStableHost(): HTMLDivElement | null {
  const [host] = useState<HTMLDivElement | null>(() => {
    if (typeof document === "undefined") return null;
    const node = document.createElement("div");
    node.className = "flex min-h-0 flex-1 flex-col";
    node.dataset.personPanelHost = "";
    return node;
  });
  return host;
}

export function PersonPanel({
  row,
  jobId,
  columns,
  move,
  readOnly,
  canWriteClientRate,
  workbenchContext,
  section: controlledSection,
  onSectionChange,
  wide: controlledWide,
  onWideChange,
  noteFocusSignal = 0,
  stageFocusSignal = 0,
  onClose,
  className,
}: PersonPanelProps) {
  const candidateId = row.candidateId;
  const { item, column } = row;
  const offTemplate = isOffTemplateRow(row);

  // Sekcja: prop wygrywa; inaczej własny wybór użytkownika; inaczej z etapu.
  const [localSection, setLocalSection] = useState<PersonPanelSection | null>(null);
  const [localWide, setLocalWide] = useState(false);
  const wide = controlledWide ?? localWide;
  const setWide = useCallback(
    (next: boolean) => {
      setLocalWide(next);
      onWideChange?.(next);
    },
    [onWideChange],
  );

  const section: PersonPanelSection =
    controlledSection ?? localSection ?? defaultPanelSectionFor(row.group, column);
  const changeSection = useCallback(
    (next: PersonPanelSection) => {
      setLocalSection(next);
      onSectionChange?.(next);
    },
    [onSectionChange],
  );

  // Odwiedzone sekcje tej osoby zostają zamontowane. Zmiana osoby czyści zbiór
  // (i lokalny wybór sekcji) — nowa osoba startuje od sekcji SWOJEGO etapu.
  const [visited, setVisited] = useState<{ candidateId: number; sections: PersonPanelSection[] }>(
    { candidateId, sections: [section] },
  );
  if (visited.candidateId !== candidateId) {
    // Pusty zbiór: `section` w TYM renderze może jeszcze nieść wybór zrobiony
    // przy poprzedniej osobie. Właściwą sekcję dopisze render po wyzerowaniu.
    setVisited({ candidateId, sections: [] });
    setLocalSection(null);
  } else if (!visited.sections.includes(section)) {
    setVisited({ candidateId, sections: [...visited.sections, section] });
  }
  const mounted = visited.candidateId === candidateId ? visited.sections : [section];

  // „N" w tabeli: notatki + fokus w polu. „E": fokus na wyborze etapu.
  const stageSelectRef = useRef<HTMLSelectElement>(null);
  const lastNoteSignal = useRef(noteFocusSignal);
  // Prośba o fokus jest przypięta do OSOBY: bez tego każda kolejna osoba
  // otwierana strzałkami na sekcji „Notatki" kradłaby fokus tabeli starym
  // sygnałem i nawigacja klawiaturą urywałaby się po jednym wierszu.
  const [noteFocusRequest, setNoteFocusRequest] = useState({ signal: 0, candidateId });
  useEffect(() => {
    if (noteFocusSignal === lastNoteSignal.current) return;
    lastNoteSignal.current = noteFocusSignal;
    setNoteFocusRequest({ signal: noteFocusSignal, candidateId });
    changeSection("notes");
  }, [noteFocusSignal, candidateId, changeSection]);
  const lastStageSignal = useRef(stageFocusSignal);
  useEffect(() => {
    if (stageFocusSignal === lastStageSignal.current) return;
    lastStageSignal.current = stageFocusSignal;
    stageSelectRef.current?.focus();
  }, [stageFocusSignal]);

  // Podtytuł nagłówka — ten sam klucz zapytania co profil kandydata i dok
  // kanbana, więc przejście na profil trafia w cache. Jedno zapytanie na
  // OTWARTY panel, nigdy na wiersz tabeli.
  const detailQuery = useQuery<CandidateHeaderDetail>({
    queryKey: candidateQueryKeys.detail(candidateId),
    queryFn: () => candidatesApi.get(candidateId).then((r) => r.data as CandidateHeaderDetail),
    staleTime: 60_000,
  });
  const detail = detailQuery.data;
  const meta = [
    detail?.linkedin_current_title?.trim() || null,
    detail?.city?.trim() || detail?.location?.trim() || null,
    row.rateLabel,
    row.availabilityLabel,
  ]
    .filter(Boolean)
    .join(" · ");

  // ── Ruch etapu ──────────────────────────────────────────────────────
  const currentColId = colId(column);
  // Cały szablon jest celem selecta — także „Odrzucony"/„Wycofany": hook
  // otwiera wtedy okno powodu (z odpowiedzią kandydata na ofertę), dokładnie
  // jak upuszczenie karty na taką kolumnę tablicy. „Zatrudniony" pyta
  // o potwierdzenie. Przycisk „Odrzuć" obok zostaje skrótem.
  const stageTargets = columns;
  const writeBlocked = moveBlockedReason({ item, readOnly, targetStage: null });
  // Naprzód po KOLUMNACH Tablicy (Pipeline v4), nie po etapach szablonu —
  // z „CV wysłane" dalej jest „Rozmowa u klienta", a nie etap-odznaka
  // „Preparation Meeting" (test na produkcji 23.09.2026).
  const forward = useMemo(() => {
    const fold = foldBoardColumns(columns);
    const hostCols = fold.columns.map((f) => ({ ...f.host, name: f.label }));
    const host = fold.columns.find((f) =>
      f.members.some((m) => colId(m) === currentColId),
    )?.host;
    const result = primaryForwardMove({
      item,
      columns: hostCols,
      currentColId: host ? colId(host) : currentColId,
      readOnly,
    });
    // Ruch i etykieta idą z PRAWDZIWEGO etapu szablonu (gospodarza kolumny).
    const original = result.target
      ? columns.find((c) => colId(c) === colId(result.target as KanbanColumn))
      : null;
    return { ...result, target: original ?? result.target };
  }, [item, columns, currentColId, readOnly]);
  // Poza szablonem nie ma „następnego" etapu — jest pierwszy etap szablonu.
  const forwardTarget = offTemplate
    ? readOnly
      ? null
      : (columns.find((col) => terminalOf(col) == null) ?? null)
    : forward.target;
  const forwardBlockedReason = forward.blocked?.reason ?? writeBlocked;
  const isClosed = row.group === "closed";

  // Warsztat „Screening" i „CV" prowadzi osobę ze SWOJEJ kolejki i ma własny
  // przycisk ruchu („Zweryfikowany — zapisz stawkę…", „Oznacz CV Wysłane").
  // Lustro wyboru z warsztatów: kolejka etapu, a w screeningu także karty
  // „ponad budżet" i z wetem HM z innych etapów nie-terminalnych. Od
  // Pipeline v4 (23.09.2026) screening robi się w kolumnie „Nowi"
  // (`isNewColumn` — ta sama reguła co kolejka warsztatu).
  const inScreeningWorkbench =
    (!offTemplate && isNewColumn(column)) ||
    (column.category !== "terminal" &&
      !offTemplate &&
      (Boolean(item.hm_veto) || isOverHourlyBudget(item, workbenchContext.budgetHourly)));
  const inCvWorkbench = column === findStageColumn(columns, VERIFIED_STAGE);
  // JEDNO wejście do ruchu: gdy widoczna sekcja ma własny przycisk, ogólny
  // „Przenieś na etap…" znika (select etapu i „Odrzuć" zostają).
  const sectionOwnsMove =
    !readOnly &&
    ((section === "screening" && inScreeningWorkbench) || (section === "cv" && inCvWorkbench));

  const handleStageSelect = (value: string) => {
    if (value === currentColId) return;
    const target = columns.find((col) => colId(col) === value);
    // Select jest kontrolowany etapem z WIERSZA: jeśli okno ruchu zostanie
    // anulowane, wraca sam na bieżący etap — bez ręcznego cofania.
    if (target) move.requestMove(item, column, target);
  };

  const ctx = workbenchContext;
  const kanban = ctx.kanbanQueryState;
  const jobLabel = ctx.jobTitle?.trim() || `Rekrutacja #${jobId}`;
  const profileHref = `/candidates/${candidateId}?${encodeJobBackRef(jobId).toString()}`;

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
          <>
          {/* Tylko w kolejce „CV do klienta": po wysyłce powód jest historią. */}
          {inCvWorkbench ? <AutoCvSkipNotice jobId={jobId} candidateId={candidateId} /> : null}
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
          </>
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
        return (
          <NotesSection
            row={row}
            jobId={jobId}
            readOnly={readOnly}
            focusSignal={
              noteFocusRequest.candidateId === candidateId ? noteFocusRequest.signal : 0
            }
          />
        );
    }
  };

  // ── Trwały węzeł treści: wąska kolumna ↔ szeroka nakładka ───────────
  const host = useStableHost();
  const inlineSlotRef = useRef<HTMLDivElement>(null);
  const wideSlotRef = useCallback(
    (slot: HTMLDivElement | null) => {
      if (slot && host && host.parentElement !== slot) slot.appendChild(host);
    },
    [host],
  );
  useLayoutEffect(() => {
    // Powrót do wąskiej kolumny (i pierwszy render). Wejście w tryb szeroki
    // obsługuje `wideSlotRef` — slot nakładki powstaje dopiero z jej otwarciem.
    if (!wide && host && inlineSlotRef.current && host.parentElement !== inlineSlotRef.current) {
      inlineSlotRef.current.appendChild(host);
    }
  }, [wide, host]);

  const body = (
    <>
      <div className="flex items-center gap-3">
        <div
          className="flex size-10 shrink-0 items-center justify-center rounded-full bg-primary/15 text-[13px] font-semibold text-primary"
          aria-hidden
        >
          {initialsOf(row.fullName)}
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="truncate text-[15px] font-semibold text-foreground">{row.fullName}</span>
          <span className="truncate text-xs text-muted-foreground">
            {meta || (detailQuery.isLoading ? "Wczytywanie profilu…" : row.stageLabel)}
          </span>
        </div>
        <Link href={profileHref} className="shrink-0 text-xs font-medium text-primary hover:underline">
          Pełny profil
        </Link>
      </div>

      <div className="flex items-center gap-2">
        <label htmlFor={`person-stage-${candidateId}`} className="text-xs font-semibold text-muted-foreground">
          Etap
        </label>
        <select
          id={`person-stage-${candidateId}`}
          ref={stageSelectRef}
          value={currentColId}
          disabled={writeBlocked != null || move.isMoving}
          title={writeBlocked ?? undefined}
          onChange={(event) => handleStageSelect(event.target.value)}
          className="h-[34px] min-w-0 flex-1 rounded-md border border-border bg-card px-2 text-[13px] font-medium text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
        >
          {/* Bieżący etap spoza listy celów (odrzucony, poza szablonem) musi
              być opcją — inaczej select pokazałby pierwszy etap szablonu. */}
          {stageTargets.some((col) => colId(col) === currentColId) ? null : (
            <option value={currentColId}>{columnLabel(column)}</option>
          )}
          {stageTargets.map((col) => (
            <option key={colId(col)} value={colId(col)}>
              {columnLabel(col)}
            </option>
          ))}
        </select>
        {!isClosed ? (
          <Button
            variant="outline"
            size="sm"
            className="h-[34px] text-destructive-muted-foreground"
            disabled={writeBlocked != null || move.isMoving}
            title={writeBlocked ?? undefined}
            onClick={() => move.requestReject(item)}
          >
            Odrzuć…
          </Button>
        ) : null}
        {/* Pipeline v4: rezygnację kandydata zapisuje się osobno — to inny
            wniosek w statystykach niż odrzucenie. */}
        {!isClosed ? (
          <Button
            variant="outline"
            size="sm"
            className="h-[34px]"
            disabled={writeBlocked != null || move.isMoving}
            title={writeBlocked ?? undefined}
            onClick={() => move.requestWithdraw(item)}
          >
            Zrezygnował…
          </Button>
        ) : null}
      </div>

      {sectionOwnsMove ? null : forwardTarget ? (
        <Button
          className="h-10 w-full shrink-0 text-sm"
          disabled={move.isMoving}
          onClick={() => move.requestMove(item, column, forwardTarget)}
        >
          Przenieś na etap: {columnLabel(forwardTarget)}
        </Button>
      ) : forwardBlockedReason && !isClosed ? (
        <Button className="h-10 w-full shrink-0 text-sm" disabled title={forwardBlockedReason}>
          {forward.blocked
            ? `Przenieś na etap: ${columnLabel(forward.blocked.col)}`
            : "Przenieś na kolejny etap"}
        </Button>
      ) : null}
      {!sectionOwnsMove && forwardBlockedReason && !forwardTarget && !isClosed ? (
        <p className="-mt-1.5 text-xs text-muted-foreground">{forwardBlockedReason}</p>
      ) : null}

      <TabbedNav
        ariaLabel="Sekcje osoby"
        tabs={PERSON_PANEL_SECTIONS.map(({ value, label }) => ({ value, label }))}
        value={section}
        onValueChange={(value) => changeSection(value as PersonPanelSection)}
        overflow="wrap"
        dense
      />

      <div className="min-h-0 flex-1 overflow-y-auto">
        {PERSON_PANEL_SECTIONS.filter(({ value }) => mounted.includes(value)).map(({ value, label }) => (
          <div
            // Klucz = osoba + sekcja: przerysowanie tabeli (nowa tablica wierszy
            // co kilka sekund) NIE odmontowuje sekcji, zmiana osoby — tak.
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

      <p className="shrink-0 text-xs text-muted-foreground">
        ↑ ↓ następna osoba · E zmiana etapu · N notatka
      </p>
    </>
  );

  const toolbar = (
    <div className="flex shrink-0 items-center justify-end gap-1">
      <button
        type="button"
        onClick={() => setWide(!wide)}
        aria-pressed={wide}
        className="inline-flex h-7 items-center gap-1 rounded-md px-2 text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {wide ? (
          <Minimize2 className="size-3.5" aria-hidden />
        ) : (
          <Maximize2 className="size-3.5" aria-hidden />
        )}
        {wide ? "Zwiń" : "Rozwiń"}
      </button>
      {onClose && !wide ? (
        <button
          type="button"
          onClick={onClose}
          aria-label="Zamknij panel osoby"
          className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <X className="size-4" aria-hidden />
        </button>
      ) : null}
    </div>
  );

  return (
    <aside
      aria-label="Wybrana osoba"
      data-wide={wide ? "" : undefined}
      className={cn(
        "flex min-h-0 w-full shrink-0 flex-col gap-3 rounded-lg border border-border bg-card p-4 lg:w-[372px]",
        className,
      )}
    >
      {!wide ? toolbar : null}
      <div ref={inlineSlotRef} className={cn("flex min-h-0 flex-1 flex-col", wide && "hidden")} />
      {wide ? (
        <p className="text-sm text-muted-foreground">
          Panel jest otwarty w szerokim widoku.{" "}
          <button
            type="button"
            className="font-medium text-primary underline-offset-2 hover:underline"
            onClick={() => setWide(false)}
          >
            Zwiń
          </button>
        </p>
      ) : null}

      {/* Nakładka, NIE szersza kolumna siatki: tabela pod spodem nie zmienia
          szerokości, więc po „Zwiń" wiersz jest tam, gdzie był. Radix daje
          pułapkę fokusu i Esc. */}
      <Sheet open={wide} onOpenChange={(open) => setWide(open)}>
        <SheetContent
          side="right"
          hideClose
          className="w-full gap-3 p-4 sm:max-w-[760px]"
        >
          <SheetTitle className="sr-only">{row.fullName} — panel osoby</SheetTitle>
          <SheetDescription className="sr-only">
            Szeroki widok panelu osoby. Esc zamyka.
          </SheetDescription>
          {toolbar}
          <div ref={wideSlotRef} className="flex min-h-0 flex-1 flex-col" />
        </SheetContent>
      </Sheet>

      {host ? createPortal(<div className="flex min-h-0 flex-1 flex-col gap-3">{body}</div>, host) : null}
    </aside>
  );
}
