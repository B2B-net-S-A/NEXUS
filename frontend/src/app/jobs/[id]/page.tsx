"use client";

import { useUrlSyncedState, writeUrlParams } from "@/lib/url-selection";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import api, { jobChatApi, matchingApi } from "@/lib/api";
import { resolveViewState } from "@/lib/view-state";
import { useCapability } from "@/hooks/useCapability";
import {
  canEditJobContent,
  hasFullJobEditFallback,
  jobEditScope,
  jobPublishAction,
} from "@/lib/job-edit-access";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { KanbanBoardV2 } from "@/components/v2/pages/KanbanBoardV2";
import { PipelineBoardGate } from "@/components/v2/jobs/PipelineBoardGate";
import { EditJobModal } from "@/components/AppShell";
import { AIJobWriterModal } from "@/components/v2/jobs/AIJobWriterModal";
import { RequestStatusBadge } from "@/components/v2/jobs/JobListCells";
import { CHAMPION_ROLES, requestStatusOf } from "@/lib/request-status";
import { similarJobsApi } from "@/lib/similar-jobs-api";
import { toggleChampionFound } from "@/lib/champion-found-toggle";
import { useToast } from "@/components/Toast";
import { countHired } from "@/lib/pipeline-flow";
import { jobBudgetHourly } from "@/lib/job-budget";
import { positiveIntParam } from "@/lib/client-tab";
import { resolveUrlTab } from "@/lib/url-tab";
import { WS_BACKED_SAFETY_POLL_MS } from "@/lib/polling";
import { jobHeaderFacts } from "@/lib/job-header-facts";
import { recruitersOf, recruitersSummary } from "@/lib/job-team";
import { invalidateJobTeam } from "@/lib/job-team-cache";
import {
  JOB_DETAIL_DEFAULT_VIEW,
  readJobDetailUrlState,
  resolveLegacyJobTab,
  rewriteLegacyJobParams,
  type JobDetailView,
  type JobHistoryChatTab,
  type JobOrderSection,
} from "@/lib/job-detail-routing";
import { jobProposalsApi, jobProposalsKeys } from "@/lib/job-proposals-api";
import { proposalsBulkApi, shortlistApi } from "@/lib/candidate-search-api";
import type { KanbanColumn } from "@/components/v2/pages/kanban-shared";
import { ChampionProfileEditor } from "@/components/ChampionProfileEditor";
import { ChampionWorkspace } from "@/components/champion/ChampionWorkspace";
import {
  resolveChampionTab,
  type ChampionBlock,
  type ChampionTab,
} from "@/lib/champion-blocks";
import { JobCloseWithReasonDialog } from "@/components/v2/jobs/JobCloseWithReasonDialog";
import { JobReopenDialog } from "@/components/v2/jobs/JobReopenDialog";
import { scrollToWhenReady } from "@/components/v2/recruitment/OrderMissingBlock";
import {
  ManagedInNexusChip,
  ManagedInTraffitNotice,
} from "@/components/v2/jobs/ManagedInNexusSwitch";
import { CandidateSourcesStrip } from "@/components/v2/jobs/CandidateSourcesStrip";
import { AddCandidatesQuickModal } from "@/components/v2/modals/AddCandidatesQuickModal";
import { AddCandidateFromCVModal } from "@/components/v2/modals/AddCandidateFromCVModal";
import { AddCandidatesPanel } from "@/components/v2/recruitment/AddCandidatesPanel";
import { assignErrorMessage } from "@/lib/assign-error";
import {
  JobShortlist,
  jobShortlistQueryKey,
} from "@/components/v2/jobs/JobShortlist";
import { GenerateInviteLinkV2 } from "@/components/v2/modals/GenerateInviteLinkV2";
import { cn } from "@/lib/utils";
import { useTabsStore } from "@/store/tabs";
import { useUiStore } from "@/store/ui";
import { useMyPeoplePanel } from "@/store/my-people";
import { hasRole, useAuthStore } from "@/store/auth";
import { hasPermission } from "@/lib/permissions";
import { hasSectionAccess } from "@/lib/section-access";
import { ActiveViewers } from "@/components/v2/presence/ActiveViewers";
import {
  JobDetailCompactHeader,
  type JobDetailTab,
} from "@/components/v2/jobs/JobDetailCompactHeader";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ProposalsSegment } from "@/components/v2/recruitment/ProposalsSegment";
import { ProposalMatchDetails } from "@/components/v2/recruitment/ProposalMatchDetails";
import { RequestRequirementsRail } from "@/components/v2/recruitment/RequestRequirementsRail";
import { JobAIActions } from "@/components/v2/recruitment/JobAIActions";
import { EmailTemplateModal } from "@/components/v2/recruitment/EmailTemplateModal";
import { OrderSlideOver } from "@/components/v2/recruitment/slideovers/OrderSlideOver";
import { jobClientTitle, jobDisplayTitle } from "@/lib/job-names";
import { QuestionBankSlideOver } from "@/components/v2/recruitment/slideovers/QuestionBankSlideOver";
import { HistoryChatSlideOver } from "@/components/v2/recruitment/slideovers/HistoryChatSlideOver";
import { ManualSearchSlideOver } from "@/components/v2/recruitment/slideovers/ManualSearchSlideOver";
import type {
  CandidateSourceTab,
  PersonPanelSection,
  RecruitmentSegment,
  RecruitmentSlideOver,
} from "@/components/v2/recruitment/types";

// ── Main Page ─────────────────────────────────────────────────────────────────

/**
 * Widoki rekrutacji (wersja 3) — każdy może stać w `?tab=`: „Tabela"
 * (`people`, domyślny), „Tablica" (`board`, kanban z przeciąganiem) i pełne
 * „Profil Championa" (`champion`).
 */
const JOB_DETAIL_TABS: readonly JobDetailView[] = ["people", "board", "champion"];

/**
 * Dawne identyfikatory zakładek (dwanaście kroków listwy do 09.2026) i obce
 * aliasy z linków zapisanych w bazie powiadomień. Wartość to WIDOK, na którym
 * link ląduje; segment tabeli, sekcję panelu albo okno wysuwane dopowiada
 * `resolveLegacyJobTab` (`lib/job-detail-routing.ts`). Backendowy
 * `test_client_tab_links.py` czyta klucze tego obiektu — każdy `?tab=`, do
 * którego linkuje backend, musi tu być.
 */
const JOB_DETAIL_TAB_ALIASES: Readonly<Record<string, JobDetailView>> = {
  pipeline: "people",
  history: "people",
  "ai-matching": "people",
  "manual-search": "people",
  portals: "people",
  questions: "people",
  chat: "people",
  screening: "people",
  cv: "people",
  interviews: "people",
  contract: "people",
  "champion-profile": "champion",
  similar: "people",
  notes: "people",
};

const DEFAULT_SEGMENT: RecruitmentSegment = "in-process";

/** Widok „Profil Championa”: zakładki albo pełny formularz (`?mode=edit`). */
type ChampionMode = "view" | "edit";

export default function JobDetailPage() {
  const { id } = useParams();
  const jobId = Number(id);
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const openTab = useTabsStore((s) => s.openTab);
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const authUser = useAuthStore((s) => s.user);
  const impersonating = useAuthStore((s) => s.realUser !== null);
  const isAdmin = hasRole(authUser, "admin");
  // Uprawnienie „Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta” —
  // domyślnie administrator i Delivery Lead, ale rozstrzyga panel „Osoby
  // i role”, nie rola. Serwer pyta o nie przy zamknięciu rekrutacji, bramce
  // gotowości, przekazaniu do searchu i powrocie rekrutacji do Traffita.
  const canManageRecruitment = hasPermission(authUser, "recruitment_manage");
  // 0325: powrót rekrutacji do Traffita.
  const canRevertManaged = canManageRecruitment;
  // Lustro bramki doku gotowości: bez uprawnienia `GET /jobs/{id}/readiness`
  // zawsze kończy się 403, więc zapytanie nie jest wysyłane.
  const canSeeReadinessGate = canManageRecruitment;
  const canWritePipeline =
    !impersonating && hasSectionAccess(authUser, "pipeline", "write");
  // Pełna redakcja rekrutacji (PATCH /api/jobs/{id}). Przez rejestr, żeby nie
  // hodować drugiej reguły obok niego (F-19).
  const canUpdateJob = useCapability("job.update");
  // 0341: „Mamy championa" oznacza Delivery Lead (lustro `_CHAMPION_ROLES`).
  const canMarkChampion =
    canWritePipeline && CHAMPION_ROLES.some((role) => hasRole(authUser, role));
  const [championPending, setChampionPending] = useState(false);
  // POST /api/invite-links → RecruiterPlus. Ta sama capability bramkuje akcję
  // na liście ofert — bez niej read-only `user` widział tu przycisk wiodący
  // prosto w 403 (audyt F-19).
  const canCreateInviteLink = useCapability("invite_link.create");
  const canOpenCandidateProfile = useCapability("nav.candidates");
  const canOpenMyPeople = useCapability("nav.my_people");
  const openMyPeople = useMyPeoplePanel((s) => s.openPanel);
  const [showAIWriter, setShowAIWriter] = useState(false);
  const [showEditJob, setShowEditJob] = useState(false);
  const [showInviteLink, setShowInviteLink] = useState(false);
  const [showAddCandidates, setShowAddCandidates] = useState(false);
  // „Przeszukaj całą bazę (AI)” z menu „⋯” — licznik żądań; okno źródeł
  // startuje przegląd raz na każdą nową wartość (nigdy z adresu).
  const [fullReviewRequest, setFullReviewRequest] = useState<number | null>(null);
  // „Ukryj puste kolumny” Tablicy — globalne ustawienie użytkownika (menu „⋯”).
  const hideEmptyColumns = useUiStore((s) => s.hideEmptyKanbanColumns);
  const setHideEmptyColumns = useUiStore((s) => s.setHideEmptyKanbanColumns);
  const [showAddFromCv, setShowAddFromCv] = useState(false);
  const [emailCandidateId, setEmailCandidateId] = useState<number | null>(null);
  // Narzędzia AI administratora z menu „…" — niezależnie od tego, czy
  // jakakolwiek propozycja jest zaznaczona.
  const [showAiTools, setShowAiTools] = useState(false);

  // ── Stan w adresie: widok, segment, sekcja panelu, okno wysuwane ─────────
  const searchKey = searchParams?.toString() ?? "";
  const urlState = useMemo(
    () => readJobDetailUrlState(new URLSearchParams(searchKey)),
    [searchKey],
  );
  // Widok rozstrzygają stałe TEJ strony (te same, które czyta backendowy
  // strażnik linków): nowy identyfikator albo alias dawnej zakładki.
  const viewFromUrl =
    resolveUrlTab(searchParams?.get("tab"), JOB_DETAIL_TABS, JOB_DETAIL_TAB_ALIASES) ??
    // Segment, sekcja panelu albo podświetlenie propozycji istnieją tylko
    // w „Tabeli" — taki adres bez `tab=` nie może otworzyć Tablicy.
    (urlState.view === "people" ? "people" : null);
  const [viewState, setViewState] = useUrlSyncedState<JobDetailView>(
    viewFromUrl,
    JOB_DETAIL_DEFAULT_VIEW,
  );
  const activeView: JobDetailView = viewState ?? JOB_DETAIL_DEFAULT_VIEW;
  const [segmentState, setSegmentState] = useUrlSyncedState<RecruitmentSegment>(
    urlState.segment,
    DEFAULT_SEGMENT,
  );
  const segment: RecruitmentSegment = segmentState ?? DEFAULT_SEGMENT;
  const [panelSection, setPanelSectionState] = useUrlSyncedState<PersonPanelSection>(
    urlState.panelSection,
    null,
  );
  const [slideOver, setSlideOverState] = useUrlSyncedState<RecruitmentSlideOver>(
    urlState.slideOver,
    null,
  );
  const [historyTab, setHistoryTab] = useUrlSyncedState<JobHistoryChatTab>(
    urlState.slideOverTab,
    null,
  );
  const [orderSection, setOrderSection] = useUrlSyncedState<JobOrderSection>(
    urlState.orderSection,
    null,
  );
  // Okno „Kandydaci do dodania”: `?win=add&wintab=similar|postings|base|search`.
  const [sourceTab, setSourceTab] = useUrlSyncedState<CandidateSourceTab>(
    urlState.sourceTab,
    null,
  );
  // „Profil Championa” (04.10.2026): zakładki `?ptab=brief|tech|client|team`
  // (stare `readiness`/`announce` z panelu bocznego czytane jak Brief/Zespół)
  // i pełny formularz `?mode=edit` (stare `?intake=1` otwiera go z panelem AI).
  const modeFromUrl: ChampionMode | null =
    searchParams?.get("mode") === "edit" || searchParams?.get("intake") === "1"
      ? "edit"
      : searchParams?.get("mode") === "view"
        ? "view"
        : null;
  const [championModeState, setChampionModeState] = useUrlSyncedState<ChampionMode>(
    modeFromUrl,
    "view",
  );
  const ptabRaw = searchParams?.get("ptab");
  const [championTab, setChampionTab] = useUrlSyncedState<ChampionTab>(
    resolveChampionTab(ptabRaw),
    "brief",
  );
  // Stary link do zakładki „Ogłoszenie” panelu rozwija od razu portale.
  const [portalsFocus, setPortalsFocus] = useState(ptabRaw === "announce");
  // Szuflada edycji bloku Briefu (`ChampionWorkspace`); tu, bo otwiera ją też
  // okno „Kandydaci do dodania” („Uzupełnij wymagania do wyszukiwania”).
  const [championEditBlock, setChampionEditBlock] = useState<ChampionBlock | null>(null);
  // Edytor zostaje zamontowany po pierwszym wejściu w „Edytuj” — przełączenie
  // na „Podgląd” go tylko chowa, więc niezapisany szkic nie ginie.
  const [championEditorMounted, setChampionEditorMounted] = useState(false);
  const [championDirty, setChampionDirty] = useState(false);
  useEffect(() => {
    if (championModeState === "edit") setChampionEditorMounted(true);
  }, [championModeState]);
  const [showCloseJob, setShowCloseJob] = useState(false);
  // „Otwórz ponownie” / „Dokończ i opublikuj” (04.10.2026): menu „⋯” albo
  // `?reopen=1` (okno edycji, pulpit „Czeka na Ciebie”). Parametr znika po
  // zamknięciu okna, żeby odświeżenie go nie otwierało ponownie.
  const [reopenRequest, setReopenRequest] = useUrlSyncedState<"1">(
    searchParams?.get("reopen") === "1" ? "1" : null,
    null,
  );
  const changeReopenOpen = useCallback(
    (next: boolean) => {
      setReopenRequest(next ? "1" : null);
      if (!next) writeUrlParams({ reopen: null });
    },
    [setReopenRequest],
  );

  // Tryb „Tabela" usunięty (decyzja Artura 22.09.2026): rekrutacja to Tablica.
  // `tab=people` zostaje wyłącznie dla pełnej listy „Do przejrzenia"
  // (propozycje z bazy i shortlista — makieta 4). Każdy inny dawny adres
  // Tabeli (segment etapu, sekcja panelu) otwiera Tablicę.
  const reviewScreen =
    activeView === "people" && (segment === "proposals" || segment === "shortlist");
  const showBoard = activeView === "board" || (activeView === "people" && !reviewScreen);

  const selectView = useCallback(
    (view: JobDetailView) => {
      setViewState(view);
      if (view === "board") setSegmentState(DEFAULT_SEGMENT);
      writeUrlParams({
        tab: view === JOB_DETAIL_DEFAULT_VIEW ? null : view,
        ...(view === "board" ? { seg: null, panel: null } : {}),
        ...(view !== "champion" ? { mode: null, ptab: null, intake: null } : {}),
      });
    },
    [setViewState, setSegmentState],
  );
  const selectChampionMode = useCallback(
    (mode: ChampionMode) => {
      setChampionModeState(mode);
      writeUrlParams({ mode: mode === "edit" ? "edit" : null, intake: null });
    },
    [setChampionModeState],
  );
  const selectChampionTab = useCallback(
    (tab: ChampionTab) => {
      setChampionTab(tab);
      writeUrlParams({ ptab: tab === "brief" ? null : tab });
    },
    [setChampionTab],
  );
  /**
   * Wejście na „Profil Championa”: zakładka (także stare `readiness`/
   * `announce` z okna „Zlecenie”), pełny formularz albo szuflada bloku.
   */
  const openChampion = useCallback(
    (
      opts: {
        panelTab?: ChampionTab | "readiness" | "announce";
        edit?: boolean;
        block?: ChampionBlock;
      } = {},
    ) => {
      selectView("champion");
      const tab = opts.panelTab ? resolveChampionTab(opts.panelTab) : opts.block ? "brief" : null;
      if (opts.panelTab === "announce") setPortalsFocus(true);
      if (tab) selectChampionTab(tab);
      if (opts.edit) selectChampionMode("edit");
      else if (tab) selectChampionMode("view");
      if (opts.block) setChampionEditBlock(opts.block);
    },
    [selectView, selectChampionTab, selectChampionMode],
  );
  const selectSegment = useCallback(
    (next: RecruitmentSegment) => {
      setSegmentState(next);
      writeUrlParams({ seg: next === DEFAULT_SEGMENT ? null : next });
    },
    [setSegmentState],
  );
  const selectPanelSection = useCallback(
    (next: PersonPanelSection | null) => {
      setPanelSectionState(next);
      writeUrlParams({ panel: next });
    },
    [setPanelSectionState],
  );
  const openSlideOver = useCallback(
    (
      kind: RecruitmentSlideOver,
      opts: {
        historyTab?: JobHistoryChatTab;
        orderSection?: JobOrderSection;
        sourceTab?: CandidateSourceTab;
      } = {},
    ) => {
      // Dawne „Podobne rekrutacje” to zakładka okna źródeł.
      const target: RecruitmentSlideOver = kind === "similar" ? "add" : kind;
      const source: CandidateSourceTab | null =
        target === "add" ? (kind === "similar" ? "similar" : (opts.sourceTab ?? "base")) : null;
      setSlideOverState(target);
      setHistoryTab(target === "history-chat" ? (opts.historyTab ?? "all") : null);
      setOrderSection(target === "order" ? (opts.orderSection ?? null) : null);
      setSourceTab(source);
      writeUrlParams({
        win: target,
        wintab: opts.historyTab ?? opts.orderSection ?? source ?? null,
      });
    },
    [setSlideOverState, setHistoryTab, setOrderSection, setSourceTab],
  );
  const closeSlideOver = useCallback(() => {
    setSlideOverState(null);
    setHistoryTab(null);
    setOrderSection(null);
    setSourceTab(null);
    writeUrlParams({ win: null, wintab: null });
  }, [setSlideOverState, setHistoryTab, setOrderSection, setSourceTab]);
  /** Kafle nad Tablicą i zakładki okna „Kandydaci do dodania”. */
  const openSources = useCallback(
    (tab: CandidateSourceTab) => openSlideOver("add", { sourceTab: tab }),
    [openSlideOver],
  );
  const slideOverOpenChange = (kind: RecruitmentSlideOver) => (open: boolean) => {
    if (open) openSlideOver(kind);
    else if (slideOver === kind) closeSlideOver();
  };

  // Stare wejścia do sekcji okna „Zlecenie” (`?win=order&wintab=team|portals|close`
  // — podpowiedź „Obsada kompletna”, powrót z `/jobs/new` po nieudanej
  // publikacji na portalu). Od 29.09.2026 te sekcje żyją w panelu obok
  // Profilu Championa, a zamknięcie w menu „⋯” — link prowadzi tam wprost.
  useEffect(() => {
    if (slideOver !== "order" || !orderSection) return;
    if (orderSection === "close") setShowCloseJob(true);
    else if (orderSection === "team") openChampion({ panelTab: "team" });
    else if (orderSection === "portals") openChampion({ panelTab: "announce" });
    closeSlideOver();
  }, [slideOver, orderSection, openChampion, closeSlideOver]);

  // Stary adres (`?tab=chat`, `?tab=screening`, `?highlight=ai-proposals`…)
  // przepisujemy na nowy kształt — `replace`, nie `push`: stary adres nie ma
  // zostawać w historii. Stan strony jest już poprawny (czyta oba kształty).
  useEffect(() => {
    if (!pathname) return;
    const rewritten = rewriteLegacyJobParams(new URLSearchParams(searchKey));
    if (!rewritten) return;
    const query = rewritten.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }, [searchKey, pathname, router]);

  // `?highlight=ai-proposals` (nowa rekrutacja → „zobacz propozycje"): krótka
  // obwódka wokół segmentu. Parametr znika z adresu przy przepisaniu wyżej.
  const [highlightProposals, setHighlightProposals] = useState(false);
  useEffect(() => {
    if (!urlState.highlightProposals) return;
    setHighlightProposals(true);
    const timer = window.setTimeout(() => setHighlightProposals(false), 2500);
    return () => window.clearTimeout(timer);
  }, [urlState.highlightProposals]);

  // Warsztaty i dok mówią dawnym słownikiem zakładek („otwórz Bazę pytań").
  const handleLegacyTab = useCallback(
    (tab: JobDetailTab) => {
      const target = resolveLegacyJobTab(tab);
      if (!target) return;
      if (target.slideOver) {
        openSlideOver(target.slideOver, {
          historyTab: target.slideOverTab,
          orderSection: target.orderSection,
        });
        return;
      }
      selectView(target.view);
      if (target.segment) selectSegment(target.segment);
      if (target.panelSection) selectPanelSection(target.panelSection);
    },
    [openSlideOver, selectView, selectSegment, selectPanelSection],
  );

  // `?candidate=<id>` (powiadomienia, wzmianka w notatce, „Wróć do rekrutacji")
  // — otwórz tę osobę: panel w „Tabeli", dok na „Tablicy".
  const linkedCandidateId = positiveIntParam(searchParams?.get("candidate") ?? null);
  // `&review=1` (dzwonek „CV do przeglądu”): poza dokiem otwiera przegląd DL.
  const linkedReview = searchParams?.get("review") === "1";


  // Parametr jest jednorazowy: po otwarciu osoby znika z adresu, żeby
  // odświeżenie strony albo zamknięcie panelu nie otwierało jej ponownie.
  const clearCandidateParam = useCallback(() => {
    if (!pathname) return;
    const next = new URLSearchParams(searchParams?.toString() ?? "");
    if (!next.has("candidate")) return;
    next.delete("candidate");
    next.delete("review");
    const query = next.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }, [pathname, router, searchParams]);

  // Odznaka nieprzeczytanych na przycisku „Historia i czat".
  const { data: chatUnread } = useQuery({
    queryKey: ["job-chat-unread", id],
    queryFn: async () => (await jobChatApi.getUnreadCount(Number(id))).data,
    enabled: !!id,
    // Siatka bezpieczeństwa pod WebSocketem (`chat:message:new` unieważnia ten
    // klucz w `useNotifications`) — nie źródło świeżości.
    refetchInterval: WS_BACKED_SAFETY_POLL_MS,
    refetchOnWindowFocus: true,
  });

  const {
    data: job,
    isLoading: jobLoading,
    isError: jobIsError,
    error: jobError,
    refetch: refetchJob,
  } = useQuery({
    queryKey: ["job", id],
    queryFn: () => api.get(`/api/jobs/${id}`).then((r) => r.data),
  });

  const {
    data: kanban,
    isLoading: kanbanLoading,
    // Kroki 05–08 renderują pipeline z TEGO zapytania. Bez przekazania im
    // błędu 403/500 wyglądałby stamtąd jak „nikt nie jest u klienta" — czyli
    // dokładnie ten wzorzec, przez który brak uprawnień czytało się jako
    // utratę danych (F-20).
    isError: kanbanIsError,
    error: kanbanError,
    isSuccess: kanbanIsSuccess,
    isFetching: kanbanIsFetching,
    refetch: refetchKanban,
  } = useQuery({
    queryKey: ["kanban", id],
    queryFn: () => api.get(`/api/pipeline/kanban/${id}`).then((r) => r.data),
  });

  const kanbanViewState = resolveViewState({
    isLoading: kanbanLoading,
    isError: kanbanIsError,
    error: kanbanError,
    isSuccess: kanbanIsSuccess,
  });


  // Tablica niedostępna (403) — osoba się nie otworzy, więc nie zostawiamy
  // martwego `?candidate=` w adresie.
  useEffect(() => {
    if (kanbanViewState === "forbidden" && linkedCandidateId != null) clearCandidateParam();
  }, [kanbanViewState, linkedCandidateId, clearCandidateParam]);

  // Tabela, tablica i panel osoby czytają TE SAME kolumny — jedno zapytanie
  // (`["kanban", id]`).
  const kanbanColumns = useMemo(
    () => (kanban?.columns ?? []) as KanbanColumn[],
    [kanban],
  );
  const invalidateKanban = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["kanban", id] });
    queryClient.invalidateQueries({ queryKey: ["pipeline-scores"] });
  }, [queryClient, id]);

  // Osoby już w rekrutacji (także odrzucone i „poza szablonem") — nie
  // pojawiają się w propozycjach. `undefined` dopóki tablica się nie wczyta:
  // segment propozycji pyta wtedy o nie sam.
  const pipelineCandidateIds = useMemo(() => {
    if (!kanban) return undefined;
    const ids = new Set<number>();
    for (const col of kanbanColumns) for (const item of col.items) ids.add(item.candidate_id);
    for (const item of (kanban.off_template?.items ?? []) as Array<{ candidate_id: number }>) {
      ids.add(item.candidate_id);
    }
    return Array.from(ids);
  }, [kanban, kanbanColumns]);

  // AI match scores (0-100) → pierścienie na kartach tablicy. Ten sam klucz
  // czyta kolumna „Dop." tabeli (`RecruitmentWorkspace`).
  const { data: pipelineScores, isLoading: scoresLoading } = useQuery({
    queryKey: ["pipeline-scores", id],
    queryFn: () => matchingApi.pipelineScores(Number(id)).then((r) => r.data),
    enabled: showBoard && !!id,
    staleTime: 5 * 60_000,
  });
  const scoreMap = useMemo(() => {
    const m = new Map<number, number>();
    const s = pipelineScores?.scores;
    if (s) {
      for (const [cid, score] of Object.entries(s)) m.set(Number(cid), score);
    }
    return m;
  }, [pipelineScores]);

  // Liczniki zakładek ekranu „Do przejrzenia".
  const openProposalsQuery = useQuery({
    queryKey: [...jobProposalsKeys.all(jobId), "open-count"],
    queryFn: ({ signal }) =>
      jobProposalsApi.inbox(jobId, { status: "proposed", limit: 1 }, signal),
    enabled: reviewScreen && Number.isFinite(jobId),
    staleTime: 30_000,
    retry: false,
  });
  // Łączna liczba z segmentu propozycji (wszystkie źródła), gdy był otwarty;
  // inaczej sama skrzynka. Tylko odczyt cache'u — nic nie pobiera.
  const visibleProposalsQuery = useQuery<number | null>({
    queryKey: jobProposalsKeys.visibleCount(jobId),
    queryFn: () => null,
    enabled: false,
  });
  const shortlistCountQuery = useQuery({
    queryKey: jobShortlistQueryKey(jobId),
    queryFn: () => shortlistApi.list(jobId),
    enabled: reviewScreen && Number.isFinite(jobId),
    staleTime: 30_000,
  });

  // „brakuje N" na przycisku „Zlecenie" — werdykt OFICJALNEJ bramki gotowości,
  // ten sam klucz co okno „Zlecenie" i dok (jedna lista braków).
  const readinessQuery = useQuery({
    queryKey: ["job-readiness", jobId],
    queryFn: () => api.get(`/api/jobs/${jobId}/readiness`).then((r) => r.data),
    enabled: canSeeReadinessGate && Number.isFinite(jobId),
    staleTime: 30_000,
    retry: false,
  });
  // „Rekruter: X +N” albo „Bez rekrutera” — do 02.10.2026 w podtytule
  // nagłówka, teraz przy pozycji „Zespół” w menu „⋯”.
  const teamSummary = useMemo(() => {
    if (!job) return null;
    const team = recruitersSummary(recruitersOf(job));
    const recruiterLead = team.lead;
    if (!recruiterLead) return "Bez rekrutera";
    return `Rekruter: ${recruiterLead}${team.more > 0 ? ` +${team.more}` : ""}`;
  }, [job]);

  const orderMissingCount: number | null = useMemo(() => {
    const data = readinessQuery.data;
    if (!readinessQuery.isSuccess || !data) return null;
    if (data.closed || data.ready || data.already_handed_off) return 0;
    return Array.isArray(data.blockers) ? data.blockers.length : null;
  }, [readinessQuery.data, readinessQuery.isSuccess]);

  // Auto-open tab when job data loads
  useEffect(() => {
    if (job) {
      openTab("job", Number(id), jobDisplayTitle(job));
    }
  }, [job, id, openTab]);

  const handleUseDescription = useCallback(async (description: string) => {
    if (!canWritePipeline) return;
    await api.patch(`/api/jobs/${id}`, { description });
    await queryClient.invalidateQueries({ queryKey: ["job", id] });
  }, [canWritePipeline, id, queryClient]);

  // 403 (brak uprawnień) i 5xx (awaria) NIE mogą udawać „nie znaleziono" —
  // to dokładnie ten wzorzec, przez który 403 na GET czytało się jako utratę
  // danych (audyt F-20).
  const jobViewState = resolveViewState({
    isLoading: jobLoading,
    isError: jobIsError,
    error: jobError,
    isEmpty: !job,
  });
  if (jobViewState === "loading")
    return <div className="p-6 text-muted-foreground">Ładowanie...</div>;
  if (jobViewState !== "ready")
    return (
      <div className="p-6">
        <QueryStateNotice
          state={jobViewState === "empty" ? "not_found" : jobViewState}
          description={
            jobViewState === "forbidden"
              ? "Nie masz uprawnień do tej rekrutacji. Rekrutacja istnieje — poproś o dodanie Cię do jej zespołu albo o rozszerzenie roli."
              : undefined
          }
          onRetry={() => void refetchJob()}
        />
      </div>
    );

  // Dwa poziomy edycji (22.09.2026, `lib/job-edit-access.ts`): pełna
  // (`job.update` — klient, budżet, zespół, cykl życia) i treść (`can_edit`
  // z serwera — rekruter prowadzący i współpracownicy: opis, ogłoszenia,
  // Champion). `canEditJob` zostaje bramką PEŁNEJ edycji i cyklu życia.
  const editScope = jobEditScope(job, {
    canWritePipeline,
    canManageJob: canUpdateJob,
  });
  const canEditJob = editScope === "full";
  const canEditJobContentFields = editScope !== "none";
  // Zamknięcie rekrutacji (`POST /api/jobs/{id}/close`) wymaga uprawnienia do
  // jej prowadzenia. Zapis w rekrutacjach i dostęp do tej rekrutacji niesie
  // `editScope`.
  const canCloseJob = canEditJobContentFields && canManageRecruitment;
  // Ponowne otwarcie i dokończenie to publikacja z przekazaniem — ta sama
  // bramka co zamknięcie (`POST /publish` = `POST /handoff` + cykl życia).
  const publishAction = canCloseJob ? jobPublishAction(job) : null;
  const canEditChampion = canEditJobContent(job, {
    canWritePipeline,
    // Odpowiedź bez pola `can_edit` (starszy cache): pełną redakcję rekrutacji
    // daje uprawnienie do jej prowadzenia.
    fallback: hasFullJobEditFallback(authUser),
  });
  // Bez prawa edycji zawsze „Podgląd” — nawet ze starym linkiem `?mode=edit`.
  const championMode: ChampionMode =
    canEditChampion && championModeState === "edit" ? "edit" : "view";
  const renderChampionEditor =
    canEditChampion && (championMode === "edit" || championEditorMounted);
  const onEdit = canEditJobContentFields ? () => setShowEditJob(true) : undefined;
  const onWriteAnnouncement = canEditJobContentFields
    ? () => setShowAIWriter(true)
    : undefined;
  const onGenerateInviteLink =
    canWritePipeline && job.status === "published" && canCreateInviteLink
      ? () => setShowInviteLink(true)
      : undefined;
  const copyJobLink = () => {
    const url = `${window.location.origin}/jobs/${jobId}`;
    // `navigator.clipboard` nie istnieje w niezabezpieczonym kontekście —
    // bez tej gałęzi klik nic by nie robił i wyglądał na zepsuty.
    if (!navigator?.clipboard?.writeText) {
      showError("Przeglądarka nie pozwala skopiować linku.");
      return;
    }
    void navigator.clipboard
      .writeText(url)
      .then(() => showSuccess("Skopiowano link do rekrutacji."))
      .catch(() => showError("Nie udało się skopiować linku."));
  };
  const kanbanQueryState = {
    isLoading: kanbanLoading,
    isError: kanbanIsError,
    error: kanbanError,
    isSuccess: kanbanIsSuccess,
    refetch: () => void refetchKanban(),
  };

  return (
    <div className="space-y-2">
      <JobDetailCompactHeader
        title={jobDisplayTitle(job)}
        referenceNumber={job.reference_number}
        clientTitle={jobClientTitle(job)}
        clientReference={job.client_reference}
        badges={
          <>
            {/* Status requestu (0341) zastępuje techniczny „Aktywna/Szkic" —
                ta sama reguła co kolumna „Status" na liście. */}
            {requestStatusOf(job.request_status) ? (
              <RequestStatusBadge status={job.request_status} />
            ) : (
              <Badge
                variant={
                  job.status === "published"
                    ? "success"
                    : job.status === "draft"
                      ? "neutral"
                      : "danger"
                }
              >
                {job.status === "published"
                  ? "Aktywna"
                  : job.status === "draft"
                    ? "Szkic"
                    : job.status}
              </Badge>
            )}
            {!canWritePipeline ? (
              <Badge variant="info">Tylko odczyt</Badge>
            ) : null}
            <ManagedInNexusChip
              job={job}
              canRevert={canRevertManaged && !impersonating}
            />
            {/* Rekrutacja z Traffita, jeszcze nieprzełączona — plakietka w linii
                odznak zamiast dużego banera nad Tablicą (24.09.2026). */}
            <ManagedInTraffitNotice job={job} canSwitch={canEditJob} />
          </>
        }
        // Klient · Budżet · Tryb pracy — trzy wyróżnione fakty (02.10.2026).
        // Rekruter, DL, hiring manager, termin i obsada są w „Profil Championa”.
        facts={jobHeaderFacts(job)}
        presence={
          <ActiveViewers
            resourceType="job"
            resourceId={Number.isFinite(jobId) ? jobId : null}
          />
        }
        activeView={showBoard ? "board" : activeView}
        onViewChange={selectView}
        // „Zlecenie" otwiera okno na KAŻDYM widoku — także na „Zlecenie
        // i Champion": portale, zespół i „Zamknij rekrutację" mieszkają tylko
        // w tym oknie, więc muszą być osiągalne zewsząd.
        onOpenOrder={() => openSlideOver("order")}
        onOpenAiTools={
          isAdmin && canWritePipeline ? () => setShowAiTools(true) : undefined
        }
        orderMissingCount={orderMissingCount}
        onOpenHistoryChat={() => openSlideOver("history-chat")}
        onOpenQuestions={() => openSlideOver("questions")}
        teamSummary={teamSummary}
        onOpenTeam={() => openChampion({ panelTab: "team" })}
        onEditFullChampion={canEditChampion ? () => openChampion({ edit: true }) : undefined}
        championFound={job.champion_found_at != null}
        championPending={championPending}
        onToggleChampion={
          canMarkChampion
            ? async () => {
                setChampionPending(true);
                try {
                  // REC-05: odmowa serwera → toast, nie cisza.
                  await toggleChampionFound({
                    jobId,
                    found: job.champion_found_at == null,
                    save: similarJobsApi.setChampionFound,
                    refresh: async () => {
                      await queryClient.invalidateQueries({ queryKey: ["job", id] });
                      void queryClient.invalidateQueries({ queryKey: ["jobs-v2"] });
                    },
                    onError: showError,
                  });
                } finally {
                  setChampionPending(false);
                }
              }
            : undefined
        }
        onAddByName={canWritePipeline ? () => setShowAddCandidates(true) : undefined}
        onAddFromCv={canWritePipeline ? () => setShowAddFromCv(true) : undefined}
        onOpenMyPeople={canOpenMyPeople ? openMyPeople : undefined}
        onStartFullReview={
          canWritePipeline
            ? () => {
                setFullReviewRequest((prev) => (prev ?? 0) + 1);
                openSources("base");
              }
            : undefined
        }
        emptyColumnsHidden={hideEmptyColumns}
        onToggleEmptyColumns={
          showBoard ? () => setHideEmptyColumns(!hideEmptyColumns) : undefined
        }
        onEdit={onEdit}
        onWriteAnnouncement={onWriteAnnouncement}
        onGenerateInviteLink={onGenerateInviteLink}
        chatUnreadCount={chatUnread?.unread_count ?? 0}
        clientCardHref={
          job.client_id != null ? `/help?tab=clients&client=${job.client_id}` : undefined
        }
        onCopyLink={copyJobLink}
        onCloseJob={canCloseJob && job.status !== "closed" ? () => setShowCloseJob(true) : undefined}
        onReopenJob={publishAction === "reopen" ? () => changeReopenOpen(true) : undefined}
        onFinishJob={publishAction === "finish" ? () => changeReopenOpen(true) : undefined}
      />

      {/* Edit Job Modal */}
      {canEditJobContentFields && showEditJob && job && (
        <EditJobModal
          job={job}
          scope={canEditJob ? "full" : "content"}
          onClose={() => setShowEditJob(false)}
          onRequestPublish={publishAction ? () => changeReopenOpen(true) : undefined}
          onSuccess={() => {
            // Okno zmienia też rekrutera i kolejne osoby — odświeżamy
            // rekrutację, listę /jobs z licznikami i pulpit obłożenia.
            invalidateJobTeam(queryClient, jobId);
            setShowEditJob(false);
          }}
        />
      )}

      {/* AI Writer Modal */}
      {canEditJobContentFields && showAIWriter && (
        <AIJobWriterModal
          job={job}
          onClose={() => setShowAIWriter(false)}
          onUse={handleUseDescription}
        />
      )}

      {/* Invite Link Modal — pre-selected current job */}
      <GenerateInviteLinkV2
        open={canWritePipeline && showInviteLink}
        onOpenChange={setShowInviteLink}
        defaultJobId={Number(id)}
      />

      {/* Okno „Kandydaci do dodania” (02.10.2026) — `?win=add&wintab=<źródło>`;
          dawne `?win=similar` otwiera zakładkę „Podobne rekrutacje”. Bez prawa
          zapisu okno jest do odczytu. */}
      <AddCandidatesPanel
        open={slideOver === "add"}
        onOpenChange={slideOverOpenChange("add")}
        jobId={jobId}
        job={job}
        tab={sourceTab ?? "base"}
        onTabChange={openSources}
        budgetHourly={jobBudgetHourly(job)}
        pipelineCandidateIds={pipelineCandidateIds}
        readOnly={!canWritePipeline}
        onOpenManualSearch={() => openSlideOver("manual-search")}
        onOpenChampionSearch={() =>
          openChampion(canEditChampion ? { block: "search" } : {})
        }
        onOpenFullList={() => {
          selectView("people");
          selectSegment("proposals");
        }}
        fullReviewRequest={fullReviewRequest}
        onFullReviewHandled={() => setFullReviewRequest(null)}
      />
      <AddCandidateFromCVModal
        open={canWritePipeline && showAddFromCv}
        onOpenChange={setShowAddFromCv}
        onAdded={(candidateId) => {
          // Nowy kandydat z CV od razu trafia do „Nowych" tej rekrutacji.
          void proposalsBulkApi
            .add(jobId, { candidate_ids: [candidateId], source: "quick_add" })
            .then(() => invalidateKanban())
            .catch((error) => showError(assignErrorMessage(error)));
        }}
      />

      {/* Quick search + bulk-add candidates to this job */}
      <AddCandidatesQuickModal
        open={canWritePipeline && showAddCandidates}
        onClose={() => setShowAddCandidates(false)}
        jobId={Number(id)}
        jobTitle={jobDisplayTitle(job)}
      />

      {/* Narzędzia AI administratora (kryteria, scoring, embedding) — wejście
          z menu „…"; te same akcje co w panelu propozycji. */}
      <Dialog open={isAdmin && canWritePipeline && showAiTools} onOpenChange={setShowAiTools}>
        <DialogContent size="lg" data-testid="ai-tools-dialog">
          <DialogHeader>
            <DialogTitle>Narzędzia AI (administrator)</DialogTitle>
            <DialogDescription>
              Podgląd i odświeżenie kryteriów, przeliczenie scoringu, embedding rekrutacji.
            </DialogDescription>
          </DialogHeader>
          <DialogBody>
            <JobAIActions
              jobId={jobId}
              readOnly={!canWritePipeline}
              onDone={() => {
                void queryClient.invalidateQueries({ queryKey: jobProposalsKeys.all(jobId) });
                void queryClient.invalidateQueries({ queryKey: ["pipeline-scores"] });
              }}
            />
          </DialogBody>
        </DialogContent>
      </Dialog>

      {emailCandidateId != null ? (
        <EmailTemplateModal
          candidateId={emailCandidateId}
          job={job}
          onClose={() => setEmailCandidateId(null)}
        />
      ) : null}

      {/* ── Okna wysuwane: dawne zakładki obok tabeli ───────────────────── */}
      <OrderSlideOver
        open={slideOver === "order"}
        onOpenChange={slideOverOpenChange("order")}
        jobId={jobId}
        canEdit={canEditJob}
        canEditContent={canEditJobContentFields}
        onNavigate={(_target, opts) => openChampion(opts)}
        onOpenSlideOver={openSlideOver}
        onEdit={() => setShowEditJob(true)}
        onOpenAiWriter={onWriteAnnouncement}
        onOpenInviteLink={onGenerateInviteLink}
        initialSection={orderSection}
        hiredCount={kanban ? countHired(kanbanColumns) : 0}
      />
      {canCloseJob && job.status !== "closed" ? (
        <JobCloseWithReasonDialog
          open={showCloseJob}
          onOpenChange={setShowCloseJob}
          jobId={jobId}
          jobTitle={job.title ?? `Rekrutacja #${jobId}`}
          clientId={job.client_id ?? null}
          defaultReason={kanban && countHired(kanbanColumns) > 0 ? "filled_by_us" : "other"}
        />
      ) : null}
      {publishAction ? (
        <JobReopenDialog
          jobId={jobId}
          open={reopenRequest === "1"}
          onOpenChange={changeReopenOpen}
          mode={publishAction}
          recruiter={job.primary_owner ?? null}
          onOpenChampion={() => openChampion({ edit: canEditChampion })}
        />
      ) : null}
      <QuestionBankSlideOver
        open={slideOver === "questions"}
        onOpenChange={slideOverOpenChange("questions")}
        jobId={jobId}
        clientId={job.client_id ?? null}
        readOnly={!canWritePipeline}
      />
      <HistoryChatSlideOver
        open={slideOver === "history-chat"}
        onOpenChange={slideOverOpenChange("history-chat")}
        jobId={jobId}
        clientId={job.client_id ?? null}
        readOnly={!canWritePipeline}
        initialTab={historyTab ?? "all"}
        chatUnreadCount={chatUnread?.unread_count ?? 0}
        columns={kanban ? kanbanColumns : undefined}
      />
      <ManualSearchSlideOver
        open={slideOver === "manual-search"}
        onOpenChange={slideOverOpenChange("manual-search")}
        jobId={jobId}
        job={job}
        readOnly={!canWritePipeline}
        onBulkAdded={invalidateKanban}
      />

      {/* ── „Do przejrzenia" — pełna lista (makieta 4): propozycje z bazy
          i shortlista. Wejście: „Przejrzyj wszystkich" z pierwszej kolumny
          Tablicy; powrót: „← Tablica" w nagłówku. ─────────────────────── */}
      {reviewScreen && (
        <div className="space-y-3">
          <div
            role="tablist"
            aria-label="Do przejrzenia"
            data-help="jobs.proposals.tabs"
            className="inline-flex items-center gap-0.5 rounded-lg bg-muted p-0.5"
          >
            {(
              [
                [
                  "proposals",
                  "Propozycje z bazy",
                  visibleProposalsQuery.data ??
                    (openProposalsQuery.isSuccess ? openProposalsQuery.data.total : null),
                ],
                [
                  "shortlist",
                  "Shortlista",
                  shortlistCountQuery.isSuccess ? (shortlistCountQuery.data?.length ?? 0) : null,
                ],
              ] as const
            ).map(([value, label, count]) => (
              <button
                key={value}
                type="button"
                role="tab"
                aria-selected={segment === value}
                onClick={() => selectSegment(value)}
                className={cn(
                  "inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[13px] font-medium transition-colors",
                  segment === value
                    ? "bg-card text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {label}
                {typeof count === "number" ? (
                  <Badge variant="outline" size="sm" className="tabular-nums">
                    {count}
                  </Badge>
                ) : null}
              </button>
            ))}
          </div>
          {segment === "shortlist" ? (
            <JobShortlist jobId={jobId} readOnly={!canWritePipeline} />
          ) : (
            <ProposalsSegment
              jobId={jobId}
              budgetHourly={jobBudgetHourly(job)}
              pipelineCandidateIds={pipelineCandidateIds}
              readOnly={!canWritePipeline}
              canOpenProfile={canOpenCandidateProfile}
              highlight={highlightProposals}
              onOpenManualSearch={() => openSlideOver("manual-search")}
              onOpenQuickAdd={() => setShowAddCandidates(true)}
              onWriteEmail={setEmailCandidateId}
              // Dawna lewa kolumna AI Matching: lista wymagań + ich edycja.
              renderRequirements={({ onSaved }) => (
                <RequestRequirementsRail
                  jobId={jobId}
                  readOnly={!canWritePipeline}
                  onSaved={onSaved}
                />
              )}
              renderMatchDetails={(candidateId) => (
                <ProposalMatchDetails
                  candidateId={candidateId}
                  jobId={jobId}
                  jobTitle={job.title ?? null}
                  readOnly={!canWritePipeline}
                />
              )}
              // Narzędzia AI (kryteria, scoring, embedding) — tylko admin.
              renderAdminTools={
                isAdmin
                  ? () => (
                      <JobAIActions
                        jobId={jobId}
                        readOnly={!canWritePipeline}
                        onDone={() => {
                          void queryClient.invalidateQueries({
                            queryKey: jobProposalsKeys.all(jobId),
                          });
                          void queryClient.invalidateQueries({
                            queryKey: jobProposalsKeys.recommendations(jobId),
                          });
                        }}
                      />
                    )
                  : undefined
              }
            />
          )}
        </div>
      )}

      {/* ── Widok „Tablica": kafle źródeł, kanban z przeciąganiem, dok osoby ── */}
      {showBoard && (
        <div>
          <PipelineBoardGate
            state={kanbanViewState}
            hasData={Boolean(kanban)}
            onRetry={() => void refetchKanban()}
          >
            <KanbanBoardV2
              columns={kanban?.columns ?? []}
              offTemplate={kanban?.off_template ?? null}
              jobId={jobId}
              jobTitle={job?.title}
              scoreMap={scoreMap}
              scoresLoading={scoresLoading}
              // Panel „Zespół i priorytet" nie stoi już nad tablicą — kolumny
              // dostają pełną wysokość.
              headerCollapsed
              readOnly={!canWritePipeline}
              // SLA klienta na kolumnie Screening i w lewej kolumnie — ten sam
              // klucz zapytania karty klienta co panel osoby.
              clientId={job?.client_id ?? null}
              // Deep link rozstrzygamy dopiero na ŚWIEŻEJ tablicy: z ciepłego
              // cache karta osoby, która właśnie weszła do rekrutacji
              // (powiadomienie), jeszcze nie istnieje, a parametr zostałby
              // zużyty na próżno.
              initialDockCandidateId={
                kanbanIsFetching || panelSection ? null : linkedCandidateId
              }
              onInitialDockHandled={clearCandidateParam}
              initialDockOpensReview={linkedReview}
              // Warsztaty osoby (dawny panel „Tabeli") otwierane z doku.
              workbenchContext={{
                clientId: job.client_id ?? null,
                clientName: job.client_name ?? null,
                onMoved: invalidateKanban,
                onTabChange: handleLegacyTab,
                canCloseJob,
                headcount: typeof job.headcount === "number" ? job.headcount : null,
                jobClosed: job.status === "closed",
                onRequestCloseJob: () => openSlideOver("order", { orderSection: "close" }),
              }}
              kanbanQueryState={kanbanQueryState}
              // „Gotowy do Cpro" — odznaka wyłącznie u Nordei (serwer).
              cproEnabled={job.cpro_enabled === true}
              // Kafle „Kandydaci do dodania” nad tablicą — cztery źródła, jedno okno.
              renderAbove={(viewControls) => (
                <CandidateSourcesStrip
                  jobId={jobId}
                  job={job}
                  canSeeSimilar={canWritePipeline}
                  onOpen={openSources}
                  onAddByName={canWritePipeline ? () => setShowAddCandidates(true) : undefined}
                  onAddFromCv={canWritePipeline ? () => setShowAddFromCv(true) : undefined}
                  trailing={viewControls}
                />
              )}
              // `?candidate=&panel=` (także linki zapisane w powiadomieniach):
              // od razu warsztat tej osoby na właściwej sekcji.
              initialWorkbench={
                !kanbanIsFetching && panelSection && linkedCandidateId != null
                  ? { candidateId: linkedCandidateId, section: panelSection }
                  : null
              }
              onInitialWorkbenchHandled={() => {
                clearCandidateParam();
                selectPanelSection(null);
              }}
            />
          </PipelineBoardGate>
        </div>
      )}

      {/* ── Widok „Profil Championa” (04.10.2026): cztery zakładki albo pełny
          formularz (`?mode=edit`, menu „⋯ → Edytuj cały Profil Championa”). ── */}
      {activeView === "champion" && (
        <div className="space-y-3" data-testid="job-champion-view">
          {championMode === "edit" ? (
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => selectChampionMode("view")}
                className="inline-flex h-8 items-center gap-1 rounded-lg border border-border bg-card px-3 text-[13px] font-medium text-foreground hover:bg-accent"
                data-testid="champion-back-to-tabs"
              >
                ← Wróć do Profilu Championa
                {championDirty ? (
                  <span className="ml-1.5 text-[11px] font-medium text-warning">● niezapisane</span>
                ) : null}
              </button>
              <p className="text-[13px] text-muted-foreground">
                Cały profil naraz. Zmiany zapisuje „Zapisz” na pasku sekcji.
              </p>
            </div>
          ) : null}

          {/* Edytor zostaje zamontowany po pierwszym wejściu — powrót do zakładek
              go tylko chowa, więc niezapisany szkic nie ginie. */}
          {renderChampionEditor ? (
            <div hidden={championMode !== "edit"} data-testid="champion-editor-slot">
              <ChampionProfileEditor
                jobId={Number(id)}
                clientId={job?.client_id ?? null}
                // `can_edit` z serwera (rekruter prowadzący i współpracownicy od
                // 22.09.2026); bez pola — lustro DeliveryLeadPlus (P1-02).
                canEdit={canEditChampion}
                // Stare linki `?intake=1` (sprzed `/jobs/new`) otwierają panel
                // „Wklej opis” od razu z opisem rekrutacji.
                intakeDefaultOpen={searchParams?.get("intake") === "1"}
                intakeSeedText={job?.description ?? undefined}
                layout="workspace"
                onDirtyChange={setChampionDirty}
              />
            </div>
          ) : null}
          {championMode === "view" && championDirty && renderChampionEditor ? (
            <div
              className="flex flex-wrap items-center gap-3 rounded-lg border border-warning/30 bg-warning-muted px-3 py-2 text-[13px] text-warning-muted-foreground"
              data-testid="champion-unsaved-full-form"
            >
              Masz niezapisane zmiany w pełnym formularzu.
              <button
                type="button"
                onClick={() => selectChampionMode("edit")}
                className="font-medium text-foreground underline underline-offset-2"
              >
                Wróć do formularza
              </button>
            </div>
          ) : null}
          {championMode === "view" ? (
            <ChampionWorkspace
              jobId={Number(id)}
              job={job}
              tab={championTab ?? "brief"}
              onTabChange={selectChampionTab}
              editBlock={championEditBlock}
              onEditBlockChange={setChampionEditBlock}
              fullFormDirty={championDirty && renderChampionEditor}
              canEditChampion={canEditChampion}
              canVerifyChampion={
                canEditChampion && hasRole(authUser, "admin", "delivery_lead")
              }
              canWritePipeline={canWritePipeline}
              canSeeGate={
                canSeeReadinessGate && hasSectionAccess(authUser, "pipeline", "read")
              }
              canEditJob={canEditJob}
              canEditJobContent={canEditJobContentFields}
              onEditJob={() => setShowEditJob(true)}
              onEditFull={(anchor) => {
                selectChampionMode("edit");
                if (anchor) scrollToWhenReady(anchor);
              }}
              onOpenManualSearch={
                canWritePipeline ? () => openSlideOver("manual-search") : undefined
              }
              onWriteAnnouncement={onWriteAnnouncement}
              onGenerateInviteLink={onGenerateInviteLink}
              portalsFocus={portalsFocus}
            />
          ) : null}
        </div>
      )}
    </div>
  );
}
