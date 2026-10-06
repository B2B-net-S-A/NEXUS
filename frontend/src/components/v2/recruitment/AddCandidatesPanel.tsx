"use client";

/**
 * Okno „Kandydaci do dodania” (02.10.2026, makieta
 * https://claude.ai/artifact/ASHNaTXA9omvTH393cQjCv) — JEDNO okno dla
 * wszystkich źródeł kandydatów, z tym samym podglądem osoby w każdej zakładce:
 *
 *  - „Podobne rekrutacje” — osoby wysłane do klienta w podobnych rekrutacjach
 *    (przepięcie) i pozostali z tych rekrutacji (`useSimilarJobsTab`),
 *  - „Nowi z ogłoszeń” — propozycje z ogłoszeń z ostatnich 7 dni
 *    (źródła `new_cv`, `job_board`; podział liczy serwer) i zgłoszenia
 *    odłożone przez przegląd AI,
 *  - „Propozycje z bazy” — reszta scalonej listy (`useJobProposals`: nocny
 *    przegląd bazy, rekomendacje, przepięcia z połączonych rekrutacji,
 *    przekazania od praktykantów),
 *  - „Szukaj w bazie” — wyszukiwanie po słowach z Championa
 *    (`useSearchBaseTab`); zastąpiło „Znajdź w bazie (AI)”.
 *
 * Do 02.10.2026 okno nazywało się „Dodaj kandydatów” i miało zakładki
 * „Szukaj w bazie (AI)”, „Propozycje”, „Moi ludzie”, „Po nazwisku”. „Moi
 * ludzie” mają własny panel w pasku górnym, dodanie po nazwisku i z pliku CV
 * jest pod kaflami i w menu „⋯”, a ręczny start przeglądu bazy — w menu „⋯”.
 *
 * Dodanie idzie przez `proposals/bulk` jak dotąd (źródło z pochodzenia
 * wiersza). Serwer zakłada blokadę 12 h dla dodającego. Ostrzeżenia (NDA,
 * konkurent, ponad budżet) zostają widoczne; weto hiring managera blokuje
 * zaznaczenie.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles, UserPlus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { FullCandidateSearchStatus } from "@/components/talent-radar/FullCandidateSearchStatus";
import { ScreenedOutSection } from "@/components/v2/jobs/ScreenedOutSection";
import { SIMILAR_TAB_DESCRIPTION, useSimilarJobsTab } from "@/components/v2/jobs/SimilarJobsPanel";
import { useCapability } from "@/hooks/useCapability";
import { apiErrorMessage } from "@/lib/api-error";
import type { MatchEligibility } from "@/lib/api";
import {
  OFFICE_DAYS_WARNING,
  REMOTE_ONLY_BADGE_PL,
  REMOTE_ONLY_WARNING,
  overBudgetLabel,
} from "@/lib/fit-badges";
import { searchIsRunning } from "@/lib/full-candidate-search-api";
import type { ManualSearchJob } from "@/lib/job-search-filters";
import {
  CITY_MISMATCH_WARNING_PL,
  DEFAULT_PROPOSAL_FILTERS,
  EMPLOYMENT_ONLY_WARNING_PL,
  WORK_TIME_FIT_WARNING_PL,
  splitByPostings,
  type ProposalEntry,
} from "@/lib/proposals-merge";
import {
  jobProposalsApi,
  jobProposalsKeys,
  PROPOSAL_FACTS_MAX_IDS,
  type ProposalFacts,
} from "@/lib/job-proposals-api";
import { unmeasuredReason } from "@/lib/match-breakdown";
import {
  clientHistoryLine,
  proposalFactsLine,
  cvYearBadge,
  sortByClientHistory,
  type ProposalSortMode,
} from "@/lib/proposal-facts";
import { useSimilarJobs } from "@/lib/similar-jobs-api";
import { similarPeopleTotal } from "@/lib/similar-reassign";
import { cn, formatRelativeTime } from "@/lib/utils";
import { useVisibleMatchScores } from "@/hooks/useVisibleMatchScores";

import { useDismissReasonPrompt } from "./DismissReasonDialog";
import { PersonPreview } from "./PersonPreview";
import { PickList, ScoreBadge, type PickRow } from "./pick-list";
import { RecruitmentSheet } from "./slideovers/RecruitmentSheet";
import { CANDIDATE_SOURCE_TABS, PROPOSAL_SOURCE_LABEL, type CandidateSourceTab } from "./types";
import { useJobProposals } from "./useJobProposals";
import { useJobSearchSeed } from "./useJobSearchSeed";
import { useSearchBaseTab } from "./useSearchBaseTab";

export { CvBadge } from "./pick-list";

export type AddCandidatesTab = CandidateSourceTab;

export interface AddCandidatesPanelProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  jobId: number;
  /** Rekrutacja — filtry startowe „Szukaj w bazie”. */
  job: ManualSearchJob;
  tab: CandidateSourceTab;
  onTabChange: (tab: CandidateSourceTab) => void;
  budgetHourly: number | null;
  /** Osoby już w rekrutacji (z tablicy) — nie pojawiają się w wynikach. */
  pipelineCandidateIds?: readonly number[];
  readOnly?: boolean;
  /** „Zmień słowa i filtry” — pełne ręczne wyszukiwanie. */
  onOpenManualSearch: () => void;
  /** Sekcja 2 Championa (słowa do wyszukiwania wpisuje Delivery Lead). */
  onOpenChampionSearch?: () => void;
  /** Pełna lista „Do przejrzenia” z filtrami i shortlistą. */
  onOpenFullList?: () => void;
  /**
   * „Przeszukaj całą bazę (AI)” z menu „⋯”: każda nowa wartość startuje
   * przegląd (raz). Start idzie stanem strony, nigdy adresem — odświeżenie
   * karty nie może uruchomić trzyminutowego skanu.
   */
  fullReviewRequest?: number | null;
  /**
   * Okno obsłużyło żądanie (wystartowało przegląd albo uznało, że trwa) —
   * strona je zeruje. Bez tego ponowne otwarcie okna startowałoby kolejny
   * trzyminutowy skan: treść okna montuje się od nowa przy każdym otwarciu.
   */
  onFullReviewHandled?: () => void;
}

const WARNING_LABEL: Record<string, string> = {
  hm_veto: "Weto HM",
  over_budget: "Ponad budżet",
  [OFFICE_DAYS_WARNING]: "Mniej dni w biurze",
  [REMOTE_ONLY_WARNING]: REMOTE_ONLY_BADGE_PL,
  rejected_by_same_client: "Odrzucony przez tego klienta",
  employment_only: EMPLOYMENT_ONLY_WARNING_PL,
  city_mismatch: CITY_MISMATCH_WARNING_PL,
  ...WORK_TIME_FIT_WARNING_PL,
};

function eligibilityWarning(eligibility: MatchEligibility | null | undefined) {
  if (!eligibility || eligibility.reason_code === "eligible") return null;
  return {
    key: eligibility.reason_code,
    label:
      eligibility.assignment_allowed === false
        ? `Weto HM: ${eligibility.reason}`
        : eligibility.reason || eligibility.reason_code,
    blocking: eligibility.assignment_allowed === false,
  };
}

/** 30.09.2026: budżet nie ukrywa — plakietka mówi, o ile ponad (gdy wiemy). */
function overBudgetWarning(rateHourly: number | null | undefined, budgetHourly: number | null) {
  const label = overBudgetLabel(rateHourly, budgetHourly);
  return { key: "over_budget", label: label.charAt(0).toUpperCase() + label.slice(1), blocking: false };
}

function proposalRow(
  entry: ProposalEntry,
  facts?: ProposalFacts | null,
  budgetHourly: number | null = null,
): PickRow {
  const { row, detail } = entry;
  const source = row.sources.includes("reassign") ? "reassign" : row.sources[0];
  const warnings: PickRow["warnings"] = [];
  const elig = eligibilityWarning(detail.eligibility);
  if (elig) warnings.push(elig);
  for (const code of row.warnings) {
    if (code === "over_budget") {
      warnings.push(overBudgetWarning(detail.rateHourly, budgetHourly));
      continue;
    }
    if (
      code === OFFICE_DAYS_WARNING ||
      code === REMOTE_ONLY_WARNING ||
      code === "rejected_by_same_client" ||
      code === "part_time_only" ||
      code === "full_time_only" ||
      code === "employment_only" ||
      code === "city_mismatch"
    ) {
      warnings.push({ key: code, label: WARNING_LABEL[code], blocking: false });
    }
  }
  return {
    candidateId: row.candidateId,
    fullName: row.fullName,
    fitScore: row.fitScore,
    rateLabel: row.rateLabel,
    availabilityLabel: row.availabilityLabel,
    // Historia u TEGO klienta mówi więcej niż „był w podobnym projekcie”.
    note: clientHistoryLine(facts?.client_history) ?? row.reason ?? (facts ? null : detail.title),
    facts: proposalFactsLine(facts),
    cvBadge: cvYearBadge(facts?.cv_uploaded_on),
    sourceLabel: source ? PROPOSAL_SOURCE_LABEL[source] : null,
    warnings,
  };
}

const TAB_LABEL: Record<CandidateSourceTab, string> = {
  similar: "Podobne rekrutacje",
  postings: "Nowi z ogłoszeń",
  base: "Propozycje z bazy",
  search: "Szukaj w bazie",
};

const TAB_DESCRIPTION: Record<CandidateSourceTab, string> = {
  similar: SIMILAR_TAB_DESCRIPTION,
  postings:
    "Osoby z ogłoszeń z ostatnich 7 dni, które pasują do tej rekrutacji. Kliknij osobę, żeby ją podejrzeć.",
  base: "Osoby wybrane przez nocny przegląd bazy i pozostałe propozycje. Kliknij osobę, żeby ją podejrzeć.",
  search: "Wyniki wyszukiwania po słowach, które Delivery Lead wpisał w Championie.",
};

/** „Z portalu (JJIT/RocketJobs) · 2 dni temu”. */
function sourceLine(entry: ProposalEntry): string {
  const labels = entry.row.sources.map((s) => PROPOSAL_SOURCE_LABEL[s]).filter(Boolean);
  const seen = entry.detail.postingRecent
    ? (entry.detail.postingSeenAt ?? entry.detail.firstSeenAt)
    : entry.detail.firstSeenAt;
  return [labels.join(", ") || "Propozycja", seen ? formatRelativeTime(seen) : null]
    .filter(Boolean)
    .join(" · ");
}

export function AddCandidatesPanel(props: AddCandidatesPanelProps) {
  // Treść (i jej zapytania) żyje wyłącznie przy otwartym oknie — wejście na
  // stronę rekrutacji nie może odpalać skrzynki propozycji ani wyszukiwania.
  if (!props.open) return null;
  return <AddCandidatesPanelOpen {...props} />;
}

function AddCandidatesPanelOpen({
  onOpenChange,
  jobId,
  job,
  tab,
  onTabChange,
  budgetHourly,
  pipelineCandidateIds,
  readOnly = false,
  onOpenManualSearch,
  onOpenChampionSearch,
  onOpenFullList,
  fullReviewRequest = null,
  onFullReviewHandled,
}: AddCandidatesPanelProps) {
  const canOpenProfile = useCapability("nav.candidates");
  // Zakładka pyta o swoje dane dopiero po pierwszym wejściu; stan (zaznaczenia,
  // wybrane rekrutacje) przeżywa przełączanie, bo hooki zostają zamontowane.
  const [visited, setVisited] = useState<ReadonlySet<CandidateSourceTab>>(() => new Set([tab]));
  useEffect(() => {
    setVisited((prev) => (prev.has(tab) ? prev : new Set([...prev, tab])));
  }, [tab]);

  const [selected, setSelected] = useState<ReadonlySet<number>>(() => new Set());
  const [previewId, setPreviewId] = useState<number | null>(null);
  const previewTrigger = useRef<HTMLElement | null>(null);

  const proposals = useJobProposals(jobId, {
    filters: DEFAULT_PROPOSAL_FILTERS,
    budgetHourly,
    pipelineCandidateIds,
    readOnly,
  });
  const dismissPrompt = useDismissReasonPrompt(proposals.dismiss);
  const counts = useQuery({
    queryKey: jobProposalsKeys.counts(jobId),
    queryFn: ({ signal }) => jobProposalsApi.counts(jobId, signal),
    staleTime: 30_000,
    retry: false,
  });
  const similarJobs = useSimilarJobs(jobId, !readOnly);
  const similarTab = useSimilarJobsTab(jobId, {
    enabled: visited.has("similar"),
    readOnly,
  });
  const searchSeed = useJobSearchSeed(jobId, job, visited.has("search"));
  const searchTab = useSearchBaseTab(jobId, {
    enabled: visited.has("search"),
    seed: searchSeed,
    notSearchable: counts.data?.not_searchable_must ?? [],
    readOnly,
    canOpenProfile,
    onOpenManualSearch: () => {
      onOpenChange(false);
      onOpenManualSearch();
    },
    onOpenChampionSearch: onOpenChampionSearch
      ? () => {
          onOpenChange(false);
          onOpenChampionSearch();
        }
      : undefined,
  });

  const split = useMemo(() => splitByPostings(proposals.entries), [proposals.entries]);
  // Kafle nad Tablicą mają mówić to samo, co zakładki: lista łączy skrzynkę
  // z żywym przeglądem i podobnymi projektami, więc bywa dłuższa niż licznik
  // samej skrzynki. Publikujemy dopiero, gdy każde źródło się rozstrzygnęło.
  const queryClient = useQueryClient();
  const postingsCount = split.postings.length;
  const baseCount = split.base.length;
  const sourcesSettled = proposals.status.settled;
  // Skrzynka ma kolejne strony (od 07.10.2026 nocny przegląd publikuje każdego
  // powyżej progu, więc bywa ich kilkaset): wczytana część zaniżyłaby liczbę
  // na kaflu. Wtedy kafle wracają do liczb serwera (`…/proposal-counts`).
  const inboxHasMore = proposals.status.inbox.hasMore;
  useEffect(() => {
    if (!sourcesSettled) return;
    queryClient.setQueryData(
      jobProposalsKeys.visibleSplit(jobId),
      inboxHasMore ? null : { postings: postingsCount, base: baseCount },
    );
  }, [queryClient, jobId, sourcesSettled, inboxHasMore, postingsCount, baseCount]);

  // Telemetria otwarcia „Propozycji z bazy” — raz na wejście w zakładkę
  // (serwer i tak zapisuje najwyżej raz dziennie). Błąd nie ma znaczenia.
  const openedSent = useRef(false);
  useEffect(() => {
    if (tab !== "base" || readOnly || openedSent.current) return;
    openedSent.current = true;
    void Promise.resolve()
      .then(() => jobProposalsApi.opened(jobId))
      .catch(() => undefined);
  }, [tab, readOnly, jobId]);
  const listTab: "postings" | "base" | null = tab === "postings" || tab === "base" ? tab : null;
  const listEntries = listTab === "postings" ? split.postings : split.base;

  // Klucz ze zbioru id — odświeżenie listy z tymi samymi osobami nie gubi
  // faktów ani policzonych dopasowań.
  const listIdsKey = listEntries.map((e) => e.row.candidateId).join(",");
  const listIds = useMemo(
    () => (listIdsKey ? listIdsKey.split(",").map(Number) : []),
    [listIdsKey],
  );
  const factsQuery = useQuery({
    queryKey: jobProposalsKeys.facts(jobId, listIds),
    queryFn: async ({ signal }) => {
      const chunks: number[][] = [];
      for (let i = 0; i < listIds.length; i += PROPOSAL_FACTS_MAX_IDS) {
        chunks.push(listIds.slice(i, i + PROPOSAL_FACTS_MAX_IDS));
      }
      const pages = await Promise.all(chunks.map((ids) => jobProposalsApi.facts(jobId, ids, signal)));
      return pages.flatMap((page) => page.items);
    },
    enabled: listTab !== null && listIds.length > 0,
    staleTime: 60_000,
  });
  const factsById = useMemo(
    () => new Map((factsQuery.data ?? []).map((f) => [f.candidate_id, f] as const)),
    [factsQuery.data],
  );
  const [sortMode, setSortMode] = useState<ProposalSortMode>("client_first");
  const anyClientHistory = useMemo(
    () => (factsQuery.data ?? []).some((f) => f.client_history != null),
    [factsQuery.data],
  );
  const listRows = useMemo(() => {
    const rows = listEntries.map((e) =>
      proposalRow(e, factsById.get(e.row.candidateId) ?? null, budgetHourly),
    );
    return sortMode === "client_first" ? sortByClientHistory(rows, factsById) : rows;
  }, [listEntries, factsById, sortMode, budgetHourly]);

  // Dopasowanie na żądanie — ta sama ścieżka co kolumna wyszukiwarki
  // (`/api/search/candidates/scores`, paczki po 20, limit i ponowienia 429
  // w `useVisibleMatchScores`). Liczymy tylko osoby bez wyniku.
  const unscoredKey = proposals.entries
    .filter((e) => e.row.fitScore == null)
    .map((e) => e.row.candidateId)
    .join(",");
  const unscoredNow = useMemo(
    () => new Set(unscoredKey ? unscoredKey.split(",").map(Number) : []),
    [unscoredKey],
  );
  // Lista dla `useVisibleMatchScores` tylko ROŚNIE: hook traktuje każdą nową
  // tożsamość listy jako nowy zestaw i czyści wyniki. Dodanie osoby do
  // rekrutacji zdejmuje ją z propozycji — bez tego pozostali traciliby
  // policzone dopasowanie i zostawali na „liczę…” bez przycisku „Policz”.
  const [scoreIds, setScoreIds] = useState<readonly number[]>([]);
  useEffect(() => {
    setScoreIds((prev) => {
      const known = new Set(prev);
      const added = [...unscoredNow].filter((id) => !known.has(id));
      return added.length > 0 ? [...prev, ...added] : prev;
    });
  }, [unscoredNow]);
  const scoreItems = useMemo(() => scoreIds.map((id) => ({ id })), [scoreIds]);
  const matchScores = useVisibleMatchScores(jobId, scoreItems);
  const [scoreRequested, setScoreRequested] = useState<ReadonlySet<number>>(() => new Set());
  // Nowa osoba na liście = nowy zestaw w hooku (wyniki wyzerowane), więc
  // „liczę…” nie może zostać przy osobach, o które pytaliśmy wcześniej.
  useEffect(() => {
    setScoreRequested(new Set());
  }, [scoreItems]);
  // Do policzenia: osoby z TEJ zakładki, o które jeszcze nie pytaliśmy.
  // Odpowiedź „ocena niepełna” i błąd mają własne stany wiersza (błąd — „ponów”).
  const onThisTab = useMemo(() => new Set(listIds), [listIds]);
  const scoreCandidates = scoreItems.filter(
    ({ id }) =>
      onThisTab.has(id) &&
      unscoredNow.has(id) &&
      !scoreRequested.has(id) &&
      matchScores.scores[String(id)] == null &&
      matchScores.breakdowns[String(id)] == null &&
      matchScores.failures[String(id)] == null,
  );
  const requestScores = () => {
    const ids = scoreCandidates.map(({ id }) => id);
    setScoreRequested((prev) => new Set([...prev, ...ids]));
    for (const id of ids) matchScores.onRowVisible(id);
  };
  const renderProposalScore = (row: PickRow): ReactNode => {
    if (row.fitScore != null) return <ScoreBadge score={row.fitScore} />;
    const key = String(row.candidateId);
    const score = matchScores.scores[key];
    if (typeof score === "number") return <ScoreBadge score={score} />;
    const failure = matchScores.failures[key];
    if (failure === "forbidden") {
      return <span className="shrink-0 text-xs text-muted-foreground">brak dostępu</span>;
    }
    if (failure === "retry") {
      return (
        <button
          type="button"
          onClick={matchScores.retry}
          className="shrink-0 text-xs font-medium text-primary hover:underline"
        >
          nie policzono — ponów
        </button>
      );
    }
    const breakdown = matchScores.breakdowns[key];
    if (breakdown) {
      const reason = unmeasuredReason(breakdown.measurement);
      return (
        <span
          className="shrink-0 cursor-help text-xs text-muted-foreground"
          title={reason ? `Ocena niepełna: ${reason}` : "Ocena niepełna"}
        >
          Ocena niepełna
        </span>
      );
    }
    if (scoreRequested.has(row.candidateId)) {
      return <span className="shrink-0 text-xs text-muted-foreground" role="status">liczę…</span>;
    }
    return <ScoreBadge score={null} />;
  };

  const toggle = useCallback((candidateId: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(candidateId)) next.delete(candidateId);
      else next.add(candidateId);
      return next;
    });
  }, []);
  // Zaznaczenie obejmuje obie zakładki propozycji; liczymy tylko osoby, które
  // nadal są na liście (dodane i pominięte z niej znikają).
  const entryIds = useMemo(
    () => new Set(proposals.entries.map((e) => e.row.candidateId)),
    [proposals.entries],
  );
  const selectedIds = useMemo(
    () => new Set([...selected].filter((id) => entryIds.has(id))),
    [selected, entryIds],
  );
  const count = selectedIds.size;
  const addSelected = () => {
    if (readOnly || count === 0) return;
    // Wspólna ścieżka z ekranem „Do przejrzenia” (źródło i przegląd
    // z pochodzenia wiersza, własny komunikat wyniku).
    proposals.addToJob([...selectedIds]);
    setSelected(new Set());
  };

  // „Przeszukaj całą bazę (AI)” z menu „⋯” — jedno żądanie = jeden start.
  const run = proposals.status.run;
  const runData = run.data;
  // Przegląd w toku: drugi start dublowałby trzyminutowy skan.
  const scanning = runData != null && searchIsRunning(runData.state);
  const handledReview = useRef<number | null>(null);
  const { startRun } = proposals.status;
  // Stan przeglądu znamy dopiero po pierwszym renderze: zapamiętany przegląd
  // wraca z pamięci przeglądarki w efekcie, a jego dane dochodzą zapytaniem.
  // Start przed tym dublowałby skan, który już trwa.
  const [armed, setArmed] = useState(false);
  useEffect(() => setArmed(true), []);
  const reviewStateKnown =
    armed &&
    proposals.status.settled &&
    (run.runId == null || runData != null || run.error != null);
  useEffect(() => {
    if (fullReviewRequest == null || handledReview.current === fullReviewRequest) return;
    if (!reviewStateKnown) return;
    handledReview.current = fullReviewRequest;
    if (!readOnly && !scanning && !run.running && !run.starting) startRun();
    onFullReviewHandled?.();
    // Stan przeglądu czytamy z chwili, w której stał się znany — późniejsza
    // zmiana stanu nie startuje przeglądu ponownie.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fullReviewRequest, reviewStateKnown]);

  // ── Podgląd osoby (zakładki propozycji) ─────────────────────────────────
  const entryById = useMemo(
    () => new Map(listEntries.map((e) => [e.row.candidateId, e] as const)),
    [listEntries],
  );
  const previewIndex = previewId == null ? -1 : listRows.findIndex((r) => r.candidateId === previewId);
  const previewRow = previewIndex >= 0 ? listRows[previewIndex] : null;
  const previewEntry = previewRow ? (entryById.get(previewRow.candidateId) ?? null) : null;
  const closePreview = () => {
    setPreviewId(null);
    const trigger = previewTrigger.current;
    if (trigger?.isConnected) trigger.focus();
  };
  // Zmiana zakładki zamyka kartę osoby z poprzedniej listy.
  useEffect(() => {
    setPreviewId(null);
  }, [tab]);

  const similarTotal = similarPeopleTotal(similarJobs.data);
  // Gdy skrzynka ma kolejne strony, liczba z serwera mówi, ile osób naprawdę
  // czeka; bez niej wczytana część z „+”.
  const listCount = (loaded: number, server: number | undefined): string =>
    !inboxHasMore ? String(loaded) : server != null ? String(Math.max(loaded, server)) : `${loaded}+`;
  const tabCount: Record<CandidateSourceTab, string | null> = {
    similar: similarTotal ? String(similarTotal.total) : null,
    postings: proposals.status.settled
      ? listCount(split.postings.length, counts.data?.postings_recent)
      : null,
    base: proposals.status.settled ? listCount(split.base.length, counts.data?.base) : null,
    search: searchTab.total != null ? String(searchTab.total) : null,
  };

  const tablist = (
    <div role="tablist" aria-label="Źródło kandydatów" className="flex flex-wrap gap-1 pb-2">
      {CANDIDATE_SOURCE_TABS.map((key) => (
        <button
          key={key}
          type="button"
          role="tab"
          id={`add-candidates-tab-${key}`}
          aria-selected={tab === key}
          aria-controls={`add-candidates-panel-${key}`}
          onClick={() => onTabChange(key)}
          className={cn(
            "inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            tab === key ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:text-foreground",
          )}
        >
          {TAB_LABEL[key]}
          {tabCount[key] != null ? <span className="tabular-nums">· {tabCount[key]}</span> : null}
        </button>
      ))}
    </div>
  );

  const proposalsFooter = (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="text-xs text-muted-foreground" aria-live="polite" data-testid="add-candidates-summary">
        {readOnly
          ? "Masz tu tylko podgląd — dodawać może zespół rekrutacji."
          : count > 0
            ? `${count} zaznaczonych trafi do »Nowych«, zarezerwowanych dla Ciebie na 12 h.`
            : "Zaznacz osoby — trafią do »Nowych«, zarezerwowane dla Ciebie na 12 h."}
      </p>
      {readOnly ? null : (
        <Button
          onClick={addSelected}
          disabled={count === 0 || proposals.adding}
          loading={proposals.adding}
          data-testid="add-candidates-submit"
        >
          <UserPlus className="h-4 w-4" aria-hidden="true" />
          Dodaj {count} do Nowych
        </Button>
      )}
    </div>
  );

  const proposalsList = (label: string, emptyText: string) =>
    proposals.status.inbox.isError ? (
      <p role="alert" className="text-sm text-destructive">
        {apiErrorMessage(proposals.status.inbox.error, "Nie wczytano propozycji.")}{" "}
        <button type="button" className="underline" onClick={proposals.status.retryEngine}>
          Ponów
        </button>
      </p>
    ) : !proposals.status.settled ? (
      <p role="status" className="text-sm text-muted-foreground">
        Wczytuję propozycje…
      </p>
    ) : (
      <>
        {listRows.length > 0 && (scoreCandidates.length > 0 || anyClientHistory) ? (
          <div className="flex flex-wrap items-center gap-2" data-testid="proposals-toolbar">
            {scoreCandidates.length > 0 && (
              <Button size="sm" variant="outline" onClick={requestScores}>
                <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
                Policz dopasowanie dla {scoreCandidates.length}
              </Button>
            )}
            {anyClientHistory && (
              <div role="group" aria-label="Kolejność propozycji" className="ml-auto flex gap-1">
                {(
                  [
                    ["client_first", "Najpierw byli u tego klienta"],
                    ["proposals", "Kolejność propozycji"],
                  ] as const
                ).map(([mode, text]) => (
                  <button
                    key={mode}
                    type="button"
                    aria-pressed={sortMode === mode}
                    onClick={() => setSortMode(mode)}
                    className={cn(
                      "inline-flex h-7 items-center rounded-full border px-2.5 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      sortMode === mode
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-border bg-card text-foreground hover:bg-muted",
                    )}
                  >
                    {text}
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : null}
        {factsQuery.isError && (
          <p role="alert" className="text-xs text-muted-foreground">
            {apiErrorMessage(factsQuery.error, "Nie wczytano szczegółów osób.")}{" "}
            <button type="button" className="font-medium text-primary underline" onClick={() => void factsQuery.refetch()}>
              Ponów
            </button>
          </p>
        )}
        <PickList
          label={label}
          rows={listRows}
          selected={selectedIds}
          onToggle={(row) => toggle(row.candidateId)}
          readOnly={readOnly}
          emptyText={emptyText}
          renderScore={renderProposalScore}
          activeId={previewRow?.candidateId ?? null}
          onPreview={(row, trigger) => {
            previewTrigger.current = trigger;
            setPreviewId(row.candidateId);
          }}
          onClosePreview={closePreview}
          onDismiss={(row) => dismissPrompt.ask([row.candidateId])}
        />
        {proposals.status.inbox.hasMore ? (
          <Button
            size="sm"
            variant="outline"
            onClick={proposals.status.inbox.loadMore}
            loading={proposals.status.inbox.loadingMore}
          >
            Pokaż więcej
          </Button>
        ) : null}
      </>
    );

  const baseBody = (
    <>
      {proposals.status.engineDegraded && (
        <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive">
          Silnik dopasowań AI jest chwilowo niedostępny — brak liczby znaczy „nie policzono”, nie „nie pasuje”.
        </p>
      )}
      {run.error != null && (
        <p role="alert" className="text-xs text-destructive">
          {apiErrorMessage(run.error, "Nie udało się odczytać przeglądu bazy.")}{" "}
          <button type="button" className="underline" onClick={proposals.status.retryRun}>
            Ponów
          </button>
        </p>
      )}
      {/* Stan przeglądu bazy uruchomionego ręcznie z menu „⋯” — wyniki lądują na tej liście. */}
      {runData && (run.error == null || scanning) && (scanning || run.runId) ? (
        <section aria-label="Przegląd bazy" className="space-y-1">
          {scanning ? (
            <p className="text-xs text-muted-foreground">Przeglądamy całą bazę — potrwa ok. 3 minut.</p>
          ) : null}
          <FullCandidateSearchStatus
            data={runData}
            offset={run.offset}
            onPage={run.setOffset}
            fetching={run.fetching}
            onRestart={readOnly ? undefined : proposals.status.startRun}
            restarting={run.running}
            compact
          />
        </section>
      ) : null}
      {proposalsList("Propozycje z bazy", "Nikt nie czeka w propozycjach z bazy.")}
      {onOpenFullList ? (
        <button
          type="button"
          onClick={() => {
            onOpenChange(false);
            onOpenFullList();
          }}
          className="text-xs font-semibold text-primary hover:underline"
        >
          Pełna lista z filtrami i shortlista
        </button>
      ) : null}
    </>
  );

  const postingsBody = (
    <>
      {proposalsList(
        "Nowi z ogłoszeń",
        "Nikt nowy z ogłoszeń z ostatnich 7 dni nie pasuje do tej rekrutacji.",
      )}
      <ScreenedOutSection jobId={jobId} readOnly={readOnly} />
    </>
  );

  const listSidePane =
    previewRow && previewEntry ? (
      <PersonPreview
        key={previewRow.candidateId}
        jobId={jobId}
        candidateId={previewRow.candidateId}
        name={previewRow.fullName}
        source={{
          title: "Skąd ta osoba",
          line: sourceLine(previewEntry),
          // Historię u klienta karta pokazuje w „Profilu” — tu sam powód propozycji.
          subline: previewEntry.row.reason,
        }}
        position={{ index: previewIndex, total: listRows.length }}
        onPrev={() => setPreviewId(listRows[previewIndex - 1]?.candidateId ?? previewRow.candidateId)}
        onNext={() => setPreviewId(listRows[previewIndex + 1]?.candidateId ?? previewRow.candidateId)}
        onClose={closePreview}
        canOpenProfile={canOpenProfile}
        selection={{
          checked: selectedIds.has(previewRow.candidateId),
          disabled: readOnly || previewRow.warnings.some((w) => w.blocking),
          onToggle: () => toggle(previewRow.candidateId),
          label:
            previewRow.warnings.find((w) => w.blocking)?.label ?? "Dodaj tę osobę do „Nowych”",
        }}
      />
    ) : undefined;

  const slots =
    tab === "similar"
      ? similarTab
      : tab === "search"
        ? searchTab
        : {
            toolbar: null,
            body: tab === "postings" ? postingsBody : baseBody,
            footer: proposalsFooter,
            sidePane: listSidePane,
            onEscapeKeyDown: (event: KeyboardEvent) => {
              if (!previewRow) return;
              event.preventDefault();
              closePreview();
            },
          };

  return (
    <RecruitmentSheet
      open
      onOpenChange={onOpenChange}
      title="Kandydaci do dodania"
      description={TAB_DESCRIPTION[tab]}
      toolbar={
        <>
          {tablist}
          {slots.toolbar}
        </>
      }
      footer={slots.footer}
      sidePane={slots.sidePane}
      onEscapeKeyDown={slots.onEscapeKeyDown}
      data-testid="add-candidates-panel"
    >
      <div
        role="tabpanel"
        id={`add-candidates-panel-${tab}`}
        aria-labelledby={`add-candidates-tab-${tab}`}
        className="space-y-3"
      >
        {slots.body}
        {dismissPrompt.dialog}
      </div>
    </RecruitmentSheet>
  );
}
