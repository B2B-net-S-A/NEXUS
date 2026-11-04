"use client";

/**
 * ScreeningWorkbench — sekcja „Screening” panelu osoby.
 *
 * Krok 05 programu „flow w języku C2” zebrał screening w jedno stanowisko
 * (kolejka, arkusz Championa, dok „Weryfikacja” ze stawką, kartą i notatkami).
 * Od 0424 (decyzje Artura D1–D10, 07.10.2026) to jeden formularz pary —
 * pytania z Profilu Championa, warunki kandydata (stawka i pola karty)
 * i ocena rekrutera — z podglądem obok (D3: „od razu z boku”). Od 09.10.2026
 * podgląd stoi w dużej LEWEJ strefie panelu osoby (`PersonPanelSide`), a ta
 * sekcja zajmuje prawą kolumnę; w wąskim oknie podgląd zostaje w miejscu,
 * pod przyciskiem „Pokaż CV i wymagania”:
 * - „Nowi” i „Screening”: od razu formularz, nad nim blok „Co już wiemy”
 *   (`BeforeCallProfile`, P2 14.10.2026 — zwinięty do dwóch linii faktów, żeby
 *   stawka formularza była widoczna bez przewijania przy 1280 × 720); do tej
 *   daty „Nowi” dostawali najpierw sam profil
 *   z „Zacznij screening” i „Biorę — 12 h” (pierwszy zapis bierze teraz osobę
 *   na 12 h sam). Podgląd w „Nowych” zaczyna od CV, w „Screeningu” od wymagań,
 * - dalsze etapy: formularz i wymagania obok; od „CV wysłane” formularz dalej
 *   da się poprawić (D8) z banerem, co ta zmiana znaczy,
 * - proces zakończony: widok „Screening” tylko do odczytu i historia.
 *
 * Gospodarz zostaje tu (plakietki, Prep-kit, „Baza pytań”, formularz,
 * podgląd). Zakładki doku „Stawka i decyzja” / „Karta” / „Notatki” i układ
 * „full” z kolejką zniknęły — kolejką jest kolumna „Nowi” na Tablicy, stawka
 * i karta są polami formularza, a notatki zostają w panelu osoby.
 *
 * Pamięć rozmowy (16.10.2026, decyzje Artura D1 A, D2 A, D3 B): odpowiedzi
 * wpisane w rozmowie żyją w pamięci osoby (`store/screening-memory.ts`), nie
 * w samym formularzu — odznaczenie rekrutacji w „Screening dla” ją chowa,
 * a nie kasuje („N odpowiedzi w pamięci”, „Cofnij”), zapis czyści pamięć,
 * a powrót do osoby po zamknięciu panelu przywraca niezapisany screening.
 *
 * Podgląd (`CandidatePreviewPane`, pdf.js i `docx-preview`) ładuje się za
 * `next/dynamic` — pilnuje tego `heavy-bundle-boundaries.test.ts`.
 */

import { useEffect, useMemo, useRef, useState, type ComponentProps } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, ExternalLink, HelpCircle, PanelRight, Sparkles, UserX } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { JobDetailTab } from "@/components/v2/jobs/JobDetailCompactHeader";
import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";
import type { NoteFillChannel } from "@/lib/note-fill-channel";
import { PersonPanelSide, usePersonPanelSideActive } from "@/components/v2/person/PersonPanelSide";
import type { WorkbenchPanelProps } from "@/components/v2/recruitment/types";
import { BeforeCallProfile } from "@/components/v2/screening-form/BeforeCallProfile";
import { ScreeningFormHistory } from "@/components/v2/screening-form/ScreeningFormHistory";
import { ScreeningFullForm } from "@/components/v2/screening-form/ScreeningFullForm";
import { JointScreeningForm } from "@/components/v2/screening-form/JointScreeningForm";
import { JointScreeningPicker, type JointPickerNotice } from "@/components/v2/screening-form/JointScreeningPicker";
import { MemoryRestoredNotice } from "@/components/v2/screening-form/ScreeningMemoryNotes";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { alsoFitsApi, alsoFitsKeys } from "@/lib/also-fits-api";
import { apiErrorMessage } from "@/lib/api-error";
import { proposalsBulkApi } from "@/lib/candidate-search-api";
import { useAuthStore } from "@/store/auth";
import { useJointScreeningIntent } from "@/store/joint-screening";
import { readScreeningMemory, useScreeningMemorySummary, writeScreeningMemory } from "@/store/screening-memory";
import { ScreeningLegacyText, ScreeningSummaryView } from "@/components/v2/screening-form/ScreeningSummaryView";
import { interviewQuestionsApi } from "@/lib/api";
import {
  jointContextQueryKey,
  useJointContext,
  useScreeningFormState,
  type JointContextAnchor,
  type JointContextPair,
} from "@/lib/api/screeningForm";
import { JOINT_MAX_OTHERS } from "@/lib/joint-screening";
import {
  memoryHasEntries,
  memoryWithSelection,
  type PendingMemoryItem,
  type ScreeningMemoryLink,
} from "@/lib/screening-memory";
import { placeStage } from "@/lib/board-stages";
import { needsAutofillReason } from "@/lib/autofill-feedback";
import { terminalOf } from "@/lib/kanban-terminal";
import { VERIFIED_STAGE, findStageColumn, isNewColumn, itemFullName } from "@/lib/pipeline-flow";
import { isOverHourlyBudget } from "@/lib/rate-to-hourly";
import { AFTER_CV_SENT_COLUMNS } from "@/lib/screening-form";
import type { RejectFollowUp } from "@/lib/reject-follow-up";
import { encodeJobBackRef } from "@/lib/url-filters";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";
import { useCapability } from "@/hooks/useCapability";

function PreviewLoading() {
  return <Skeleton className="h-64 w-full rounded-xl" />;
}

const CandidatePreviewPane = dynamic(
  () =>
    import("@/components/v2/screening-form/CandidatePreviewPane").then(
      (m) => m.CandidatePreviewPane,
    ),
  { ssr: false, loading: PreviewLoading },
);

type PreviewProps = ComponentProps<typeof CandidatePreviewPane>;
type PreviewTab = NonNullable<PreviewProps["tab"]>;

/** Proces zakończony albo rekrutacja zamknięta — formularz jest już historią. */
const ENDED_REASONS: ReadonlySet<string> = new Set(["process_closed", "process_voided", "job_closed"]);

export interface ScreeningWorkbenchProps extends Omit<WorkbenchPanelProps, "layout"> {
  jobId: number;
  /** Budżet PLN/h rekrutacji (`effective_budget_hourly`) — porównanie stawki. */
  jobBudgetHourly: number | null;
  columns: KanbanColumn[];
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  isSuccess: boolean;
  onRetry: () => void;
  /** Odśwież kanban po udanym ruchu (strona trzyma klucz zapytania). */
  onMoved: () => void;
  readOnly: boolean;
  onTabChange: (tab: JobDetailTab) => void;
  /**
   * Od 14.10.2026 nieużywane — „Biorę — 12 h” zniknęło sprzed formularza
   * (pierwszy zapis bierze osobę sam); prop zostaje dla kontekstu panelu.
   */
  onTake?: (item: KanbanItem) => void;
  /** Panel osoby: dokąd przejść po „Odrzuć” w formularzu (13.10.2026). */
  rejectFollowUp?: (candidateId: number) => RejectFollowUp | undefined;
  /** „Zapisz i przekaż dalej” przeszło — panel przechodzi na „CV” (14.10.2026). */
  onForwarded?: (candidateId: number) => void;
  /** D3: formularz przyjmuje notatkę zapisaną w doku (14.10.2026). */
  noteFill?: NoteFillChannel;
  /** Harness `/preview/screening-form`: bajty CV z plików statycznych, bez API. */
  previewLoaders?: Pick<PreviewProps, "loadDocumentBlob" | "loadOriginalBlob" | "loadStageCvFile">;
}

interface JointSelection {
  candidateId: number;
  anchor: JointContextAnchor;
  others: JointContextPair[];
  verifiedStageDefId: number | null;
}

export function ScreeningWorkbench({
  jobId,
  jobBudgetHourly,
  columns,
  isLoading,
  isError,
  error,
  isSuccess,
  onRetry,
  onMoved,
  readOnly,
  onTabChange,
  rejectFollowUp,
  onForwarded,
  noteFill,
  previewLoaders,
  focusCandidateId = null,
  panelFallback,
}: ScreeningWorkbenchProps) {
  const found = useMemo(() => {
    if (focusCandidateId == null) return null;
    for (const col of columns) {
      const item = col.items.find((i) => i.candidate_id === focusCandidateId);
      if (item) return { item, col };
    }
    return null;
  }, [columns, focusCandidateId]);
  const verifiedCol = useMemo(() => findStageColumn(columns, VERIFIED_STAGE), [columns]);
  const rejectedCol = useMemo(() => columns.find((c) => terminalOf(c) === "rejected") ?? null, [columns]);

  const candidateId = found?.item.candidate_id ?? -1;
  const formQuery = useScreeningFormState(candidateId, jobId, found != null);
  const state = formQuery.data;

  // „Screening dla” (14.10.2026, D3): jedna rozmowa pod kilka rekrutacji —
  // tylko w „Nowych”/„Screeningu”, z prawem zapisu i bez prośby DL o poprawki.
  const jointEnabled =
    found != null && isNewColumn(found.col) && !readOnly && state != null && state.editable && !state.fix_request;
  const jointContext = useJointContext(candidateId, jobId, jointEnabled);
  const alsoFitsQuery = useQuery({
    queryKey: alsoFitsKeys.one(jobId, candidateId),
    queryFn: () => alsoFitsApi.get(candidateId, jobId),
    enabled: jointEnabled,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
  const [jointIds, setJointIds] = useState<ReadonlySet<number>>(() => new Set());
  const [addingJobId, setAddingJobId] = useState<number | null>(null);
  // Bliźniaki (0614), w których osoba nie bierze udziału — powód idzie z ruchem.
  const [twinSkips, setTwinSkips] = useState<ReadonlyMap<number, string>>(() => new Map());
  const consumeIntent = useJointScreeningIntent((s) => s.consume);
  const intent = useJointScreeningIntent((s) => s.intent);
  const queryClient = useQueryClient();
  const [jointError, setJointError] = useState<string | null>(null);
  const [manualAddedNote, setManualAddedNote] = useState<string | null>(null);
  // Trwający zapis wspólny: ten sam wybór do zamknięcia karty wyniku, choć
  // kotwica przeszła dalej, a lista rekrutacji się odświeżyła.
  const [jointSession, setJointSession] = useState<JointSelection | null>(null);
  // Pamięć rozmowy osoby (16.10.2026): wpisy z rozmowy niezależne od tego,
  // które rekrutacje są zaznaczone, w karcie przeglądarki do zapisu (max 12 h).
  const userId = useAuthStore((s) => s.user?.id);
  const memorySummary = useScreeningMemorySummary(userId, candidateId);
  const anchorClientId = jointContext.data?.anchor?.client_id;
  const memoryLink = useMemo<ScreeningMemoryLink | undefined>(
    () =>
      candidateId > 0
        ? {
            read: () => readScreeningMemory(userId, candidateId),
            write: (update) => {
              writeScreeningMemory(userId, candidateId, update);
            },
            clientId: anchorClientId,
          }
        : undefined,
    [userId, candidateId, anchorClientId],
  );
  const rememberSelection = (ids: ReadonlySet<number>) =>
    writeScreeningMemory(userId, candidateId, (prev) => memoryWithSelection(prev, jobId, [...ids], Date.now()));
  // Niezapisany screening z wcześniejszego otwarcia panelu (D3 B) — kiedy.
  const [restoredAt, setRestoredAt] = useState<number | null>(null);
  const [pickerNotice, setPickerNotice] = useState<JointPickerNotice | null>(null);
  // „Odrzuć szkic” zaczyna formularze od nowa, od ostatniego zapisu.
  const [memoryEpoch, setMemoryEpoch] = useState(0);
  const { askConfirm, confirmDialog } = useConfirmV2();
  // Inna osoba = nowa rozmowa, chyba że ta osoba ma niezapisany screening —
  // wtedy wraca jego zaznaczenie. „Screening razem” z karty zaznacza od razu —
  // także dla osoby, której panel jest już otwarty. Pusty odbiór (podwójny
  // efekt StrictMode) niczego nie czyści.
  const jointFor = useRef<number | null>(null);
  useEffect(() => {
    if (jointFor.current !== candidateId) {
      jointFor.current = candidateId;
      const saved = candidateId > 0 ? readScreeningMemory(userId, candidateId) : null;
      setJointIds(new Set(saved && saved.anchorJobId === jobId ? saved.selected.slice(0, JOINT_MAX_OTHERS) : []));
      setRestoredAt(memoryHasEntries(saved) ? saved.updatedAt : null);
      setPickerNotice(null);
      setJointSession(null);
      setTwinSkips(new Map());
    }
    if (candidateId <= 0 || intent?.candidateId !== candidateId) return;
    const ids = consumeIntent(candidateId);
    if (ids.length > 0) {
      const next = new Set(ids.slice(0, JOINT_MAX_OTHERS));
      setJointIds(next);
      writeScreeningMemory(userId, candidateId, (prev) => memoryWithSelection(prev, jobId, [...next], Date.now()));
    }
  }, [candidateId, intent, consumeIntent, userId, jobId]);
  // „Wgraj CV” w podglądzie — ta sama bramka co kafelek w doku osoby.
  const canManageDocuments = useCapability("candidate.document.manage");

  // Pytania przypięte do rekrutacji (zakładka „Baza pytań”).
  const pinnedQuery = useQuery({
    queryKey: ["job-questions", jobId],
    queryFn: () => interviewQuestionsApi.listForJob(jobId).then((r) => r.data),
    staleTime: 60_000,
  });

  const [previewTab, setPreviewTab] = useState<PreviewTab | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  // „Historia osoby” w podglądzie — otwiera ją też „Pokaż” w bloku „Co już wiemy”.
  const [historyOpen, setHistoryOpen] = useState(false);
  const previewColumnRef = useRef<HTMLDivElement | null>(null);
  // Od 1024 px szerokości okna podgląd stoi w lewej strefie panelu osoby.
  const previewInSide = usePersonPanelSideActive();

  const viewState = resolveViewState({ isLoading, isError, error, isSuccess });
  if (viewState === "loading") return <Skeleton className="h-64 w-full rounded-xl" />;
  if (viewState === "forbidden" || viewState === "not_found" || viewState === "error") {
    return (
      <QueryStateNotice
        state={viewState}
        className="rounded-xl"
        description={
          viewState === "forbidden"
            ? "Twoja rola nie ma dostępu do pipeline'u tej rekrutacji — to nie znaczy, że nikt nie czeka na screening."
            : undefined
        }
        onRetry={onRetry}
      />
    );
  }

  if (!found) {
    if (panelFallback != null) return <>{panelFallback}</>;
    return (
      <p className="rounded-lg border border-dashed border-border bg-muted/20 px-3 py-4 text-center text-xs text-muted-foreground">
        Tej osoby nie ma dziś na Tablicy tej rekrutacji.
      </p>
    );
  }

  const { item, col } = found;
  const name = itemFullName(item);
  const entry = isNewColumn(col);
  const inNew = entry && placeStage(col).column === "new";
  const ended =
    state != null && !state.editable && state.read_only_reason != null && ENDED_REASONS.has(state.read_only_reason);
  // Przed telefonem („Nowi”) rekruter czyta CV, w trakcie rozmowy — wymagania.
  const tab: PreviewTab = previewTab ?? (inNew ? "cv" : "requirements");

  const forward =
    entry && verifiedCol && !readOnly
      ? { stage: VERIFIED_STAGE, stageDefId: verifiedCol.stage_def_id ?? null, label: "Zweryfikowany" }
      : null;
  const reject =
    entry && rejectedCol && !readOnly
      ? {
          stage: rejectedCol.stage,
          stageDefId: rejectedCol.stage_def_id ?? null,
          previousStage: col.stage,
          previousCategory: col.category === "external" ? ("external" as const) : ("internal" as const),
          // Osoba od systemu (23.10.2026): okno odrzucenia pyta o powód dla systemu.
          autofill: needsAutofillReason(item, placeStage(col).column)
            ? { rateKnown: Boolean(item.entry_autofill?.rate_known), several: false }
            : null,
        }
      : null;
  const afterCvSent = state?.board_column != null && AFTER_CV_SENT_COLUMNS.has(state.board_column);

  // Historia stoi w zakładce CV podglądu; w wąskim oknie podgląd trzeba też odsłonić.
  const openHistory = () => {
    setHistoryOpen(true);
    setPreviewTab("cv");
    setPreviewOpen(true);
    // Poniżej 1024 px podgląd stoi nad profilem — bez przewinięcia klik wyglądałby na pusty.
    if (!previewInSide) {
      requestAnimationFrame(() => previewColumnRef.current?.scrollIntoView?.({ block: "nearest" }));
    }
  };

  // Starszy serwer (albo atrapa w testach) może nie oddać pól — wtedy bez trybu wspólnego.
  const jointAnchor = jointContext.data?.anchor ?? null;
  const jointPairs = Array.isArray(jointContext.data?.pairs) ? jointContext.data.pairs : [];
  const inContext = new Set(jointPairs.map((p) => p.job_id));
  const jointSuggestions = (Array.isArray(alsoFitsQuery.data?.jobs) ? alsoFitsQuery.data.jobs : []).filter(
    (job) => !inContext.has(job.job_id),
  );
  // Bliźniaki (0614) są w rozmowie zawsze — przed wyborem rekrutera, bez odznaczania.
  const twinIds = jointPairs
    .filter((p) => p.twin === true && p.selectable && !twinSkips.has(p.job_id))
    .map((p) => p.job_id);
  const skipTwin = (id: number, reason: string | null) => {
    setTwinSkips((prev) => {
      const next = new Map(prev);
      if (reason) next.set(id, reason);
      else next.delete(id);
      return next;
    });
    if (reason) {
      const next = new Set([...jointIds].filter((j) => j !== id));
      setJointIds(next);
      rememberSelection(next);
    }
  };
  const twinSkipsPayload =
    twinSkips.size > 0 ? Object.fromEntries([...twinSkips].map(([id, reason]) => [String(id), reason])) : undefined;
  const jointMissingTwins = Array.isArray(jointContext.data?.missing_twins) ? jointContext.data.missing_twins : [];
  const selectedJoint = new Set(
    [
      ...twinIds,
      ...[...jointIds].filter(
        (id) => !twinSkips.has(id) && jointPairs.some((p) => p.job_id === id && p.selectable),
      ),
    ].slice(
      0,
      JOINT_MAX_OTHERS,
    ),
  );
  const selectedPairs = jointPairs.filter((p) => selectedJoint.has(p.job_id));
  // Odznaczenie chowa rekrutację, wpisy zostają w pamięci (D1 A) — z „Cofnij”.
  const toggleJoint = (id: number) => {
    if (twinIds.includes(id)) return;
    const title = jointPairs.find((p) => p.job_id === id)?.title ?? "";
    const memory = memorySummary.byJob.get(id);
    // Od tego, co widać — zaznaczenie przywrócone z pamięci może mieć rekrutację,
    // która przestała być do wyboru (np. jest już po screeningu).
    const next = new Set(selectedJoint);
    if (next.has(id)) {
      next.delete(id);
      setPickerNotice({ kind: "unchecked", jobId: id, title, answers: memory?.answers ?? 0 });
    } else if (next.size < JOINT_MAX_OTHERS) {
      next.add(id);
      setPickerNotice(memory?.any ? { kind: "restored", jobId: id, title, answers: memory.answers } : null);
    } else {
      return;
    }
    setJointIds(next);
    rememberSelection(next);
  };
  // Zapis zamyka rozmowę (D2 A) — komunikaty o pamięci przestają dotyczyć.
  const onFormSaved = () => {
    setPickerNotice(null);
    setRestoredAt(null);
  };
  const discardMemory = async () => {
    const ok = await askConfirm({
      title: "Odrzucić niezapisany screening?",
      description:
        "Wpisy z tej rozmowy znikną we wszystkich rekrutacjach, a formularz wróci do ostatniego zapisu.",
      confirmLabel: "Odrzuć szkic",
      variant: "destructive",
    });
    if (!ok) return;
    writeScreeningMemory(userId, item.candidate_id, () => null);
    setJointIds(new Set());
    setPickerNotice(null);
    setRestoredAt(null);
    setMemoryEpoch((epoch) => epoch + 1);
  };
  // Odznaczone rekrutacje z wpisami — zapis ich nie obejmie i po nim znikną (D2 A).
  const pendingMemory: PendingMemoryItem[] = jointPairs.flatMap((pair) => {
    const memory = memorySummary.byJob.get(pair.job_id);
    if (selectedJoint.has(pair.job_id) || !memory?.any) return [];
    return [
      {
        jobId: pair.job_id,
        title: pair.title,
        answers: memory.answers,
        canReselect: pair.selectable && selectedJoint.size < JOINT_MAX_OTHERS,
      },
    ];
  });
  // „+ Dodaj i dołącz”: dodanie jak w oknie „Kandydaci do dodania” (źródło
  // `also_fits`), potem rekrutacja wchodzi do rozmowy. „+ Dodaj inną
  // rekrutację” (29.10.2026) idzie tą samą drogą ze źródłem `also_manual`;
  // rekrutacja spoza zespołu trafia tylko do „Nowych” (`join: false`).
  const addAndJoin = (
    otherJobId: number,
    {
      source = "also_fits",
      join = true,
      addedNote,
    }: { source?: "also_fits" | "also_manual"; join?: boolean; addedNote?: string } = {},
  ) => {
    setAddingJobId(otherJobId);
    setJointError(null);
    setManualAddedNote(null);
    proposalsBulkApi
      .add(otherJobId, {
        candidate_ids: [item.candidate_id],
        initial_stage_legacy: "new",
        source,
        origin_job_id: jobId,
      })
      .then(async (result) => {
        if (!result.added.includes(item.candidate_id)) {
          setJointError(result.skipped[0]?.reason_label ?? "Nie dodano do tej rekrutacji.");
          return;
        }
        await queryClient.invalidateQueries({ queryKey: jointContextQueryKey(jobId, item.candidate_id) });
        void queryClient.invalidateQueries({ queryKey: alsoFitsKeys.one(jobId, item.candidate_id) });
        void queryClient.invalidateQueries({ queryKey: ["kanban", String(otherJobId)] });
        void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
        if (!join) {
          setManualAddedNote(addedNote ?? null);
          return;
        }
        if (jointIds.size < JOINT_MAX_OTHERS) {
          const next = new Set([...jointIds, otherJobId]);
          setJointIds(next);
          rememberSelection(next);
        }
      })
      .catch((error: unknown) => setJointError(apiErrorMessage(error, "Nie udało się dodać do tej rekrutacji.")))
      .finally(() => setAddingJobId(null));
  };

  // Wybór z „Screening dla” albo zamrożony na czas zapisu (`jointSession`).
  const liveJoint: JointSelection | null =
    jointEnabled && jointAnchor && selectedPairs.length > 0
      ? { candidateId: item.candidate_id, anchor: jointAnchor, others: selectedPairs, verifiedStageDefId: forward?.stageDefId ?? null }
      : null;
  const jointSaving = jointSession != null && jointSession.candidateId === item.candidate_id;
  const activeJoint = jointSaving ? jointSession : liveJoint;

  const badges = (
    <>
      {isOverHourlyBudget(item, jobBudgetHourly) ? (
        <Badge
          variant="warning"
          size="sm"
          title="Stawka kandydata przekracza budżet PLN/h rekrutacji — informacja, nic nie blokuje."
        >
          <HelpCircle className="h-2.5 w-2.5" /> Ponad budżet
        </Badge>
      ) : null}
      {item.hm_veto ? (
        <Badge variant="danger" size="sm" title={`Powód: ${item.hm_veto.rejection_reason_name}`}>
          <UserX className="h-2.5 w-2.5" /> Weto HM
        </Badge>
      ) : null}
    </>
  );

  let left;
  if (formQuery.isLoading) {
    left = <Skeleton className="h-64 w-full rounded-xl" />;
  } else if (ended && state) {
    left = (
      <div className="space-y-4" data-testid="screening-ended">
        {/* 09.10.2026: jeden widok „Screening” (warunki, odpowiedzi, ocena) —
            wcześniej zapisany arkusz i osobno „Karta rekomendacji”. */}
        <ScreeningSummaryView
          state={state}
          showLockNote
          legacy={<ScreeningLegacyText candidateId={item.candidate_id} jobId={jobId} />}
        />
        {state.versions_count > 0 ? (
          <ScreeningFormHistory
            candidateId={item.candidate_id}
            jobId={jobId}
            currentVersion={state.version}
            stateToken={state.state_token}
            canRestore={false}
          />
        ) : null}
      </div>
    );
  } else {
    left = (
      <div className="space-y-3">
        {/* P2 (14.10.2026): to, co już wiemy, nad formularzem — bez kroku „Zacznij screening”. */}
        {entry ? (
          <BeforeCallProfile
            key={item.candidate_id}
            item={item}
            jobId={jobId}
            readOnly={readOnly}
            onOpenHistory={openHistory}
          />
        ) : null}
        {jointEnabled && !jointSaving && restoredAt != null && memorySummary.hasEntries ? (
          <MemoryRestoredNotice savedAt={restoredAt} onDiscard={() => void discardMemory()} />
        ) : null}
        {jointEnabled && !jointSaving ? (
          <JointScreeningPicker
            anchorTitle={jointAnchor?.title ?? "Ta rekrutacja"}
            anchorReference={jointAnchor?.client_reference}
            pairs={jointPairs}
            suggestions={jointSuggestions}
            selected={selectedJoint}
            onToggle={toggleJoint}
            onAddAndJoin={(otherJobId) => addAndJoin(otherJobId)}
            manualAdd={{
              candidateId: item.candidate_id,
              fromJobId: jobId,
              onAdd: (job) =>
                addAndJoin(job.job_id, {
                  source: "also_manual",
                  join: job.joinable && selectedJoint.size < JOINT_MAX_OTHERS,
                  addedNote: job.joinable
                    ? `Dodano do „Nowych”: ${job.title}. W tej rozmowie jest już komplet rekrutacji.`
                    : `Dodano do „Nowych”: ${job.title}. Rozmowę o niej prowadzi jej zespół.`,
                }),
              addedNote: manualAddedNote,
            }}
            missingTwins={jointMissingTwins}
            twinSkips={twinSkips}
            onTwinSkip={skipTwin}
            addingJobId={addingJobId}
            error={jointError}
            memory={memorySummary.byJob}
            notice={pickerNotice}
            onUndo={() => {
              if (pickerNotice?.kind === "unchecked") toggleJoint(pickerNotice.jobId);
            }}
          />
        ) : null}
        {activeJoint ? (
          <JointScreeningForm
            key={`${memoryEpoch}:${item.candidate_id}:${activeJoint.others.map((p) => p.job_id).join(",")}`}
            candidateId={item.candidate_id}
            candidateName={name}
            anchor={{
              jobId,
              title: activeJoint.anchor.title,
              clientId: activeJoint.anchor.client_id,
              clientName: activeJoint.anchor.client_name,
              budgetHourly: jobBudgetHourly ?? activeJoint.anchor.budget_hourly,
              verifiedStageDefId: activeJoint.verifiedStageDefId,
              workMode: activeJoint.anchor,
            }}
            others={activeJoint.others}
            onMoved={onMoved}
            onForwarded={onForwarded ? () => onForwarded(item.candidate_id) : undefined}
            onSessionChange={(active) => {
              setJointSession(active ? activeJoint : null);
              if (active) onFormSaved();
            }}
            memory={memoryLink}
            pendingMemory={pendingMemory}
            onReselect={toggleJoint}
            twinSkips={twinSkipsPayload}
          />
        ) : (
        <ScreeningFullForm
          key={memoryEpoch}
          candidateId={item.candidate_id}
          jobId={jobId}
          candidateName={name}
          jobBudgetHourly={jobBudgetHourly}
          forward={forward}
          reject={reject}
          rejectFollowUp={rejectFollowUp ? () => rejectFollowUp(item.candidate_id) : undefined}
          readOnly={readOnly}
          onMoved={onMoved}
          onForwarded={onForwarded ? () => onForwarded(item.candidate_id) : undefined}
          noteFill={noteFill}
          onOpenChampion={() => onTabChange("champion")}
          memory={jointEnabled ? memoryLink : undefined}
          twinSkips={twinSkipsPayload}
          pendingMemory={jointEnabled ? pendingMemory : undefined}
          onReselect={toggleJoint}
          onSaved={onFormSaved}
          banner={
            afterCvSent ? (
              <p
                role="note"
                data-testid="screening-after-cv-sent"
                className="rounded-md border border-info/30 bg-info-muted px-3 py-2 text-xs text-info-muted-foreground"
              >
                CV tej osoby poszło już do klienta. Zmiana w formularzu poprawia to, co widzi Delivery Lead,
                i trafi do następnego CV firmowego — klient nie dostaje jej automatycznie.
              </p>
            ) : null
          }
        />
        )}
      </div>
    );
  }

  return (
    <div className="@container min-w-0 space-y-3" data-testid="screening-workbench">
      <div className="flex flex-wrap items-center gap-1.5">
        {badges}
        <Link
          href={`/jobs/${jobId}/prep/${item.candidate_id}`}
          title="Prep-kit: pytania AI z podobnych rekrutacji"
          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border px-3 text-xs text-foreground hover:bg-muted"
        >
          <Sparkles className="h-3.5 w-3.5 text-primary" /> Prep-kit
        </Link>
        <Button size="sm" variant="outline" onClick={() => onTabChange("questions")}>
          <BookOpen className="h-3.5 w-3.5" /> Baza pytań
          {pinnedQuery.isSuccess ? ` · przypięte: ${pinnedQuery.data?.length ?? 0}` : ""}
        </Button>
        <Link
          href={`/candidates/${item.candidate_id}?${encodeJobBackRef(jobId).toString()}`}
          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border px-3 text-xs text-foreground hover:bg-muted"
        >
          <ExternalLink className="h-3.5 w-3.5" /> Pełny profil
        </Link>
        {!previewInSide ? (
          <Button
            size="sm"
            variant="outline"
            aria-expanded={previewOpen}
            onClick={() => setPreviewOpen((open) => !open)}
          >
            <PanelRight className="h-3.5 w-3.5" aria-hidden /> {previewOpen ? "Schowaj podgląd" : "Pokaż CV i wymagania"}
          </Button>
        ) : null}
      </div>

      {/* Podgląd: w szerokim oknie w lewej strefie panelu (portal), w wąskim
          w miejscu, nad formularzem, po kliknięciu „Pokaż CV i wymagania”. */}
      <PersonPanelSide
        inline={(content) => (
          <div
            ref={previewColumnRef}
            className={cn("min-w-0", previewOpen ? "flex h-[70dvh] flex-col" : "hidden")}
            data-testid="screening-preview-column"
          >
            {content}
          </div>
        )}
      >
        <CandidatePreviewPane
          candidateId={item.candidate_id}
          jobId={jobId}
          stageId={state?.stage_id ?? item.id}
          tab={tab}
          onTabChange={setPreviewTab}
          historyOpen={historyOpen}
          onHistoryOpenChange={setHistoryOpen}
          budgetHourly={jobBudgetHourly}
          cvActions={readOnly || ended ? undefined : { candidateName: name }}
          cvUpload={readOnly || !canManageDocuments ? undefined : { candidateName: name }}
          collapsible
          className="flex-1"
          {...previewLoaders}
        />
      </PersonPanelSide>

      <div className="min-w-0">{left}</div>
      {confirmDialog}
    </div>
  );
}
