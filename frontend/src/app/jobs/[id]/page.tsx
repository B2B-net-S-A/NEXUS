"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import api, { jobChatApi, matchingApi } from "@/lib/api";
import { resolveViewState } from "@/lib/view-state";
import { useCapability } from "@/hooks/useCapability";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { KanbanBoardV2 } from "@/components/v2/pages/KanbanBoardV2";
import { PipelineBoardGate } from "@/components/v2/jobs/PipelineBoardGate";
import { EditJobModal } from "@/components/AppShell";
import { AIJobWriterModal } from "@/components/v2/jobs/AIJobWriterModal";
import { RequestStatusBadge } from "@/components/v2/jobs/JobListCells";
import { SimilarJobsDialog } from "@/components/v2/jobs/SimilarJobsDialog";
import { CHAMPION_ROLES, requestStatusOf } from "@/lib/request-status";
import { similarJobsApi, useSimilarJobs } from "@/lib/similar-jobs-api";
import { countHired } from "@/lib/pipeline-flow";
import { buildJobHeaderKpis } from "@/lib/job-header-kpis";
import { jobBudgetHourly } from "@/lib/job-budget";
import { positiveIntParam } from "@/lib/client-tab";
import { resolveUrlTab } from "@/lib/url-tab";
import { WS_BACKED_SAFETY_POLL_MS } from "@/lib/polling";
import { buildJobHeaderSubtitle } from "@/lib/job-header-subtitle";
import type { FullSearchSummary } from "@/lib/full-search-summary";
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
import { shortlistApi } from "@/lib/candidate-search-api";
import type { KanbanColumn } from "@/components/v2/pages/kanban-shared";
import { ChampionProfileEditor } from "@/components/ChampionProfileEditor";
import { ChampionSectionNav } from "@/components/v2/jobs/ChampionSectionNav";
import { JobSummaryCard } from "@/components/v2/jobs/JobSummaryCard";
import { JobReadinessDock } from "@/components/v2/jobs/JobReadinessDock";
import {
  ManagedInNexusBanner,
  ManagedInNexusChip,
} from "@/components/v2/jobs/ManagedInNexusSwitch";
import { AddCandidatesQuickModal } from "@/components/v2/modals/AddCandidatesQuickModal";
import {
  JobShortlist,
  jobShortlistQueryKey,
} from "@/components/v2/jobs/JobShortlist";
import { GenerateInviteLinkV2 } from "@/components/v2/modals/GenerateInviteLinkV2";
import { cn } from "@/lib/utils";
import { useTabsStore } from "@/store/tabs";
import { hasRole, useAuthStore } from "@/store/auth";
import { hasSectionAccess } from "@/lib/section-access";
import { ActiveViewers } from "@/components/v2/presence/ActiveViewers";
import { useLocalStorageFlag } from "@/lib/use-local-storage-flag";
import {
  JOB_HEADER_COLLAPSED_DEFAULT,
  JOB_HEADER_COLLAPSED_STORAGE_KEY,
} from "@/lib/job-header-preferences";
import {
  JOB_CHAMPION_DOCK_COLLAPSED_DEFAULT,
  JOB_CHAMPION_DOCK_COLLAPSED_STORAGE_KEY,
} from "@/lib/job-dock-preferences";
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
import { QuestionBankSlideOver } from "@/components/v2/recruitment/slideovers/QuestionBankSlideOver";
import { HistoryChatSlideOver } from "@/components/v2/recruitment/slideovers/HistoryChatSlideOver";
import { ManualSearchSlideOver } from "@/components/v2/recruitment/slideovers/ManualSearchSlideOver";
import type {
  PersonPanelSection,
  RecruitmentSegment,
  RecruitmentSlideOver,
} from "@/components/v2/recruitment/types";

// ── Recruitment type config ───────────────────────────────────────────────────

const RECRUITMENT_TYPE_CONFIG: Record<
  string,
  { label: string; variant: "soft" | "success" | "warning" }
> = {
  body_leasing: { label: "Body Leasing", variant: "soft" },
  sales_project: { label: "Sprzedaż", variant: "success" },
  tender: { label: "Przetarg", variant: "warning" },
};

// ── Main Page ─────────────────────────────────────────────────────────────────

/**
 * Widoki rekrutacji (wersja 3) — każdy może stać w `?tab=`: „Tabela"
 * (`people`, domyślny), „Tablica" (`board`, kanban z przeciąganiem) i pełne
 * „Zlecenie i Champion" (`champion`).
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

/** KPI nagłówka mówią dawnym słownikiem zakładek. */
const KPI_TAB_FOR_VIEW: Record<JobDetailView, JobDetailTab> = {
  people: "pipeline",
  board: "pipeline",
  champion: "champion",
};

const DEFAULT_SEGMENT: RecruitmentSegment = "in-process";

/**
 * Stan trzymany w adresie. Efekt zależy od WARTOŚCI wyczytanej z adresu, nie
 * od tożsamości `searchParams`: miękka nawigacja App Routera (klik
 * w powiadomienie na tej samej rekrutacji) zmienia adres bez odmontowania
 * strony, a inicjalizator `useState` odpala się raz. `null` z adresu NIE
 * cofa ręcznego wyboru — parametr, który zniknął, to nie polecenie.
 */
function useUrlSyncedState<T extends string>(fromUrl: T | null, fallback: T | null) {
  const [value, setValue] = useState<T | null>(fromUrl ?? fallback);
  useEffect(() => {
    if (fromUrl !== null) setValue(fromUrl);
  }, [fromUrl]);
  return [value, setValue] as const;
}

/** Podmienia parametry bieżącego adresu bez dokładania wpisu w historii. */
function writeUrlParams(patch: Record<string, string | null>) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  for (const [name, value] of Object.entries(patch)) {
    if (value == null) url.searchParams.delete(name);
    else url.searchParams.set(name, value);
  }
  const next = `${url.pathname}${url.search}${url.hash}`;
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (next !== current) window.history.replaceState(window.history.state, "", next);
}

export default function JobDetailPage() {
  const { id } = useParams();
  const jobId = Number(id);
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const openTab = useTabsStore((s) => s.openTab);
  const queryClient = useQueryClient();
  const authUser = useAuthStore((s) => s.user);
  const impersonating = useAuthStore((s) => s.realUser !== null);
  const isAdmin = hasRole(authUser, "admin");
  // 0325: powrót rekrutacji do Traffita — tylko admin / Delivery Lead.
  const canRevertManaged = isAdmin || hasRole(authUser, "delivery_lead");
  // Lustro `GATE_ROLES` doku gotowości: `GET /jobs/{id}/readiness` to
  // `DeliveryLeadPlus` — dla innych ról zapytanie zawsze kończy się 403.
  const canSeeReadinessGate = isAdmin || hasRole(authUser, "delivery_lead");
  const canWritePipeline =
    !impersonating && hasSectionAccess(authUser, "pipeline", "write");
  // PATCH /api/jobs/{id} to TacPlus — a TacPlus nie obejmuje HoR. Przez rejestr,
  // żeby nie hodować drugiej listy ról obok niego (F-19).
  const canUpdateJob = useCapability("job.update");
  // 0341: „Mamy championa" oznacza Delivery Lead (lustro `_CHAMPION_ROLES`).
  const canMarkChampion =
    canWritePipeline && CHAMPION_ROLES.some((role) => hasRole(authUser, role));
  const [similarOpen, setSimilarOpen] = useState(false);
  const [championPending, setChampionPending] = useState(false);
  const similarJobs = useSimilarJobs(jobId, canWritePipeline);
  // POST /api/invite-links → RecruiterPlus. Ta sama capability bramkuje akcję
  // na liście ofert — bez niej read-only `user` widział tu przycisk wiodący
  // prosto w 403 (audyt F-19).
  const canCreateInviteLink = useCapability("invite_link.create");
  const canOpenCandidateProfile = useCapability("nav.candidates");
  const [showAIWriter, setShowAIWriter] = useState(false);
  const [showEditJob, setShowEditJob] = useState(false);
  const [showInviteLink, setShowInviteLink] = useState(false);
  const [showAddCandidates, setShowAddCandidates] = useState(false);
  const [emailCandidateId, setEmailCandidateId] = useState<number | null>(null);
  // Narzędzia AI administratora z menu „…" — niezależnie od tego, czy
  // jakakolwiek propozycja jest zaznaczona.
  const [showAiTools, setShowAiTools] = useState(false);
  // Opis oferty potrafi mieć kilkaset linii — domyślnie zwinięty.
  const [showFullDescription, setShowFullDescription] = useState(false);

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
      });
    },
    [setViewState, setSegmentState],
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
      opts: { historyTab?: JobHistoryChatTab; orderSection?: JobOrderSection } = {},
    ) => {
      setSlideOverState(kind);
      setHistoryTab(kind === "history-chat" ? (opts.historyTab ?? "all") : null);
      setOrderSection(kind === "order" ? (opts.orderSection ?? null) : null);
      writeUrlParams({
        win: kind,
        wintab: opts.historyTab ?? opts.orderSection ?? null,
      });
    },
    [setSlideOverState, setHistoryTab, setOrderSection],
  );
  const closeSlideOver = useCallback(() => {
    setSlideOverState(null);
    setHistoryTab(null);
    setOrderSection(null);
    writeUrlParams({ win: null, wintab: null });
  }, [setSlideOverState, setHistoryTab, setOrderSection]);
  const slideOverOpenChange = (kind: RecruitmentSlideOver) => (open: boolean) => {
    if (open) openSlideOver(kind);
    else if (slideOver === kind) closeSlideOver();
  };

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
  // Zwijanie panelu „Zespół i priorytet" (pełny widok „Zlecenie i Champion")
  // oraz — na „Tablicy" — wysokość kolumn. Preferencja globalna w localStorage.
  const [headerCollapsed, setHeaderCollapsed] = useLocalStorageFlag(
    JOB_HEADER_COLLAPSED_STORAGE_KEY,
    JOB_HEADER_COLLAPSED_DEFAULT,
  );
  // Zwijanie doku „Gotowość" na widoku Championa — patrz
  // `lib/job-dock-preferences.ts`.
  const [championDockCollapsed, setChampionDockCollapsed] = useLocalStorageFlag(
    JOB_CHAMPION_DOCK_COLLAPSED_STORAGE_KEY,
    JOB_CHAMPION_DOCK_COLLAPSED_DEFAULT,
  );

  // Parametr jest jednorazowy: po otwarciu osoby znika z adresu, żeby
  // odświeżenie strony albo zamknięcie panelu nie otwierało jej ponownie.
  const clearCandidateParam = useCallback(() => {
    if (!pathname) return;
    const next = new URLSearchParams(searchParams?.toString() ?? "");
    if (!next.has("candidate")) return;
    next.delete("candidate");
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

  // Delivery Lead rekrutacji (M03-B03): `GET /api/jobs/{id}` niesie tylko
  // `delivery_lead_id`, więc nazwisko bierzemy z katalogu użytkowników —
  // tego samego, z którego okno edycji wybiera DL. Katalog zwraca wyłącznie
  // aktywne konta i jest za `OperationalUser`: brak trafienia albo 403
  // (viewer) po prostu nie dokłada segmentu, zamiast udawać „brak DL".
  const deliveryLeadId: number | null = job?.delivery_lead_id ?? null;
  const { data: deliveryLeadDirectory } = useQuery<
    Array<{ id: number; name?: string | null; email?: string | null }>
  >({
    queryKey: ["users-directory", "delivery-lead-roles"],
    queryFn: () =>
      api
        .get("/api/users", {
          params: { roles: ["delivery_lead", "admin", "head_of_recruitment"] },
          paramsSerializer: { indexes: null },
        })
        .then((r) => r.data),
    enabled: deliveryLeadId != null,
    staleTime: 5 * 60_000,
    retry: false,
  });
  const deliveryLeadName: string | null = useMemo(() => {
    if (deliveryLeadId == null) return null;
    const match = deliveryLeadDirectory?.find((u) => u.id === deliveryLeadId);
    return match?.name || match?.email || null;
  }, [deliveryLeadDirectory, deliveryLeadId]);

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
  const orderMissingCount: number | null = useMemo(() => {
    const data = readinessQuery.data;
    if (!readinessQuery.isSuccess || !data) return null;
    if (data.closed || data.ready || data.already_handed_off) return 0;
    return Array.isArray(data.blockers) ? data.blockers.length : null;
  }, [readinessQuery.data, readinessQuery.isSuccess]);

  // ── Jobbar: podtytuł i klaster KPI ───────────────────────────────────────
  //
  // Ranking czytany WYŁĄCZNIE z cache'u (`enabled: false`) — publikuje go
  // segment propozycji, gdy ma żywy przegląd bazy. Brak w cache'u = „—".
  const { data: ranking = null } = useQuery<FullSearchSummary | null>({
    queryKey: ["full-search-summary", authUser?.id, Number(id)],
    queryFn: async () => null,
    enabled: false,
  });
  const headerKpis = useMemo(
    () =>
      buildJobHeaderKpis({
        tab: KPI_TAB_FOR_VIEW[activeView],
        columns: kanban ? kanbanColumns : null,
        ranking,
      }),
    [activeView, kanban, kanbanColumns, ranking],
  );
  const headerSubtitle = useMemo(() => {
    if (!job) return [];
    return buildJobHeaderSubtitle({
      location: job.location,
      remotePolicy: job.remote_policy,
      rateBudgetHourly: jobBudgetHourly(job),
      salaryMin: job.salary_min,
      salaryMax: job.salary_max,
      deadline: job.deadline,
      ownerName: job.primary_owner?.name,
      deliveryLeadName,
      // Widok „jedna tabela" obejmuje wszystkie kroki naraz, więc decydent
      // i obsada — dawniej tylko na krokach 07/08 — są w linijce zawsze.
      hiringManagerName: job.hiring_manager_name,
      hired: kanban ? countHired(kanbanColumns) : null,
      headcount: job.headcount,
    });
  }, [job, kanban, kanbanColumns, deliveryLeadName]);

  // Auto-open tab when job data loads
  useEffect(() => {
    if (job) {
      openTab("job", Number(id), job.title);
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

  const canEditJob = canWritePipeline && canUpdateJob;
  const onEdit = canEditJob ? () => setShowEditJob(true) : undefined;
  const onWriteAnnouncement = canEditJob ? () => setShowAIWriter(true) : undefined;
  const onGenerateInviteLink =
    canWritePipeline && job.status === "published" && canCreateInviteLink
      ? () => setShowInviteLink(true)
      : undefined;
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
        title={job.title}
        clientName={job.client_name}
        referenceNumber={job.reference_number}
        badges={
          <>
            {job.recruitment_type &&
            RECRUITMENT_TYPE_CONFIG[job.recruitment_type] ? (
              <Badge
                variant={
                  RECRUITMENT_TYPE_CONFIG[job.recruitment_type].variant
                }
              >
                {RECRUITMENT_TYPE_CONFIG[job.recruitment_type].label}
              </Badge>
            ) : null}
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
          </>
        }
        // Jedna linia faktów zamiast rzędu odznak z ikonami: lokalizacja, tryb
        // pracy, budżet, widełki, deadline, właściciel, DL, hiring manager
        // i obsada.
        subtitle={
          headerSubtitle.length > 0 ? (
            <span className="text-[12px]">{headerSubtitle.join(" · ")}</span>
          ) : undefined
        }
        kpis={headerKpis}
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
        onOpenSimilar={canWritePipeline ? () => setSimilarOpen(true) : undefined}
        // Odpowiedź spoza kontraktu (brak list) = brak odznaki, nie wywrotka.
        similarLinkedCount={
          Array.isArray(similarJobs.data?.linked) ? similarJobs.data.linked.length : null
        }
        similarSuggestedCount={
          Array.isArray(similarJobs.data?.suggestions)
            ? similarJobs.data.suggestions.filter((s) => s.sent_count > 0).length
            : null
        }
        championFound={job.champion_found_at != null}
        championPending={championPending}
        onToggleChampion={
          canMarkChampion
            ? async () => {
                setChampionPending(true);
                try {
                  await similarJobsApi.setChampionFound(
                    jobId,
                    job.champion_found_at == null,
                  );
                  await queryClient.invalidateQueries({ queryKey: ["job", id] });
                  void queryClient.invalidateQueries({ queryKey: ["jobs-v2"] });
                } finally {
                  setChampionPending(false);
                }
              }
            : undefined
        }
        onAddCandidate={canWritePipeline ? () => setShowAddCandidates(true) : undefined}
        onEdit={onEdit}
        onWriteAnnouncement={onWriteAnnouncement}
        onGenerateInviteLink={onGenerateInviteLink}
        chatUnreadCount={chatUnread?.unread_count ?? 0}
        // Panel „Zespół i priorytet" żyje teraz w oknie „Zlecenie". Zostaje
        // w nagłówku wyłącznie na pełnym widoku „Zlecenie i Champion".
        {...(activeView === "champion"
          ? {
              contextOpen: !headerCollapsed,
              onContextOpenChange: (open: boolean) => setHeaderCollapsed(!open),
              contextContent: (
                <>
                  <p className="text-xs text-muted-foreground">
                    Właściciela, hiring managera i Priority Work znajdziesz
                    w zakładce „Zespół i priorytet" doku obok Profilu Championa.
                  </p>
                  {job.description ? (
                    <div className="border-t border-border pt-3">
                      <button
                        type="button"
                        onClick={() => setShowFullDescription((value) => !value)}
                        className="text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
                      >
                        {showFullDescription ? "Ukryj opis ▲" : "Pokaż opis ▼"}
                      </button>
                      {showFullDescription ? (
                        <div className="mt-2 whitespace-pre-line text-sm text-muted-foreground">
                          {job.description}
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </>
              ),
            }
          : {})}
      />

      {/* Edit Job Modal */}
      {canWritePipeline && showEditJob && job && (
        <EditJobModal
          job={job}
          onClose={() => setShowEditJob(false)}
          onSuccess={() => {
            queryClient.invalidateQueries({ queryKey: ["job", id] });
            setShowEditJob(false);
          }}
        />
      )}

      {similarOpen && (
        <SimilarJobsDialog
          jobId={jobId}
          open
          onOpenChange={(v) => {
            if (!v) setSimilarOpen(false);
          }}
        />
      )}

      {/* AI Writer Modal */}
      {canWritePipeline && showAIWriter && (
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

      {/* Quick search + bulk-add candidates to this job */}
      <AddCandidatesQuickModal
        open={canWritePipeline && showAddCandidates}
        onClose={() => setShowAddCandidates(false)}
        jobId={Number(id)}
        jobTitle={job.title}
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
        readOnly={!canWritePipeline}
        onNavigate={() => selectView("champion")}
        onOpenSlideOver={openSlideOver}
        onEdit={() => setShowEditJob(true)}
        onOpenAiWriter={onWriteAnnouncement}
        onOpenInviteLink={onGenerateInviteLink}
        initialSection={orderSection}
        hiredCount={kanban ? countHired(kanbanColumns) : 0}
      />
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

      {/* ── Widok „Tablica": kanban bez zmian (przeciąganie, filtry, dok) ── */}
      {showBoard && (
        <div>
          <ManagedInNexusBanner job={job} canSwitch={canEditJob} />
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
              // Warsztaty osoby (dawny panel „Tabeli") otwierane z doku.
              workbenchContext={{
                clientId: job.client_id ?? null,
                clientName: job.client_name ?? null,
                onMoved: invalidateKanban,
                onTabChange: handleLegacyTab,
                canCloseJob: canUpdateJob,
                headcount: typeof job.headcount === "number" ? job.headcount : null,
                jobClosed: job.status === "closed",
                onRequestCloseJob: () => openSlideOver("order", { orderSection: "close" }),
              }}
              kanbanQueryState={kanbanQueryState}
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

      {/* ── Widok „Zlecenie i Champion" — pełna strona, bez zmian ────────── */}
      {activeView === "champion" && (
        // Szerokość edytora jest tu celem, nie efektem ubocznym: przy 1440 px
        // (sidebar 240 + zwinięta szyna kart) spis sekcji 230 i dok 360
        // zostawiały edytorowi 451 px. Dlatego spis sekcji pokazuje się
        // dopiero od `2xl` — poniżej każda sekcja edytora i tak ma nagłówek
        // z chipem stanu — a na `xl` siatka ma dwie kolumny: edytor i dok.
        // Dok jest zwijalny WYŁĄCZNIE od `xl` (węziej stoi pod edytorem).
        // Literały klas muszą być PEŁNE (Tailwind skanuje kod źródłowy, nie
        // interpoluje fragmentów w runtime) — stąd gałęzie zamiast
        // wstrzykiwanej szerokości.
        <div
          className={cn(
            "grid grid-cols-1 gap-4",
            championDockCollapsed
              ? "xl:grid-cols-[minmax(0,1fr)_44px] 2xl:grid-cols-[230px_minmax(0,1fr)_44px]"
              : "xl:grid-cols-[minmax(0,1fr)_360px] 2xl:grid-cols-[230px_minmax(0,1fr)_360px]",
          )}
        >
          <aside className="hidden 2xl:block 2xl:sticky 2xl:top-4 2xl:self-start">
            <ChampionSectionNav jobId={Number(id)} />
          </aside>

          <div className="min-w-0 space-y-4">
            <JobSummaryCard
              job={job}
              onEdit={
                canWritePipeline && canUpdateJob
                  ? () => setShowEditJob(true)
                  : undefined
              }
            />
            <ChampionProfileEditor
              jobId={Number(id)}
              clientId={job?.client_id ?? null}
              // Backend PUT /champion-profile is DeliveryLeadPlus — mirror it so a
              // recruiter sees a read-only Champion instead of filling a form that
              // 403s on save (P1-02).
              canEdit={
                canWritePipeline &&
                (isAdmin || hasRole(authUser, "delivery_lead"))
              }
              // `CreateJobModal` ląduje tu z `?intake=1` gdy nowa rekrutacja
              // ma opis do podania AI (stare linki; od 22.09.2026 `/jobs/new`) — otwiera panel „Wklej
              // opis" od razu, zamiast zmuszać DL-a do odnalezienia go samemu.
              intakeDefaultOpen={searchParams?.get("intake") === "1"}
              intakeSeedText={job?.description ?? undefined}
            />
          </div>

          <aside className="xl:sticky xl:top-4 xl:self-start">
            <JobReadinessDock
              jobId={Number(id)}
              variant="champion"
              collapsed={championDockCollapsed}
              onCollapsedChange={setChampionDockCollapsed}
            />
          </aside>
        </div>
      )}
    </div>
  );
}
