"use client";

/**
 * Harness widoku „rekrutacja = jedna tabela" (wersja 3) — WYŁĄCZNIE mocki.
 *
 * Renderuje PRODUKCYJNE `RecruitmentWorkspace` i `ProposalsSegmentView` na
 * zasianym cache react-query (`staleTime: Infinity`), więc żaden `queryFn` się
 * nie odpala i strona nie robi ani jednego zapytania — dzięki temu może stać
 * w `PUBLIC_PATHS`. Strażnik `harness-seeds.test.ts` pilnuje, że każdy STAŁY
 * klucz zamontowanych komponentów jest tu zasiany.
 *
 * Drugi bezpiecznik: klucze z parametrami, których nie da się zasiać z góry
 * (warsztaty w panelu osoby pytają o kartę klienta, CV etapu, arkusz…), nie
 * mogą wyjść w sieć. Na czas życia harnessu interceptor axios ODRZUCA więc
 * każde żądanie lokalnie — komponent pokazuje wtedy swój stan błędu, a nie
 * przerzuca na `/login` po 401.
 *
 * Co tu sprawdzać oczami: 250 osób (wirtualizacja, grupowanie „kto ma ruch"),
 * 47 osób (płaska lista), oraz cztery stany segmentu propozycji — brak
 * przeglądu, skan w toku, przegląd przerwany i lista — które NIE mogą
 * wyglądać tak samo.
 */

import { useEffect, useMemo, useState } from "react";
import { QueryClient, QueryClientProvider, type InfiniteData } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { candidateContactQueryKeys } from "@/lib/candidate-contact";
import type { CandidateSearchPage } from "@/lib/full-candidate-search-api";
import {
  jobProposalsKeys,
  type ProposalInboxItem,
  type ProposalInboxPage,
} from "@/lib/job-proposals-api";
import {
  DEFAULT_PROPOSAL_FILTERS,
  countBySource,
  filterProposals,
  mergeProposals,
  type ProposalViewFilters,
} from "@/lib/proposals-merge";
import { ToastProvider } from "@/components/Toast";
import { jobShortlistQueryKey } from "@/components/v2/jobs/JobShortlist";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";
import { ProposalsSegmentView } from "@/components/v2/recruitment/ProposalsSegment";
import { RecruitmentWorkspace } from "@/components/v2/recruitment/RecruitmentWorkspace";
import type { JobProposalsState } from "@/components/v2/recruitment/useJobProposals";
import type {
  PersonPanelSection,
  RecruitmentSegment,
  RecruitmentSlideOver,
} from "@/components/v2/recruitment/types";

const JOB_ID = 4242;
const BUDGET_HOURLY = 190;

// ── Mocki osób ───────────────────────────────────────────────────────────────

const FIRST = ["Anna", "Marek", "Ewa", "Paweł", "Katarzyna", "Tomasz", "Ola", "Jan", "Magda", "Piotr", "Zofia", "Adam"];
const LAST = ["Nowak", "Zieliński", "Pawlak", "Król", "Wójcik", "Lis", "Kot", "Mazur", "Dąbrowska", "Kaczmarek", "Szymański", "Wrona"];
const RECRUITERS = ["Marta Rekruter", "Igor Sourcer", "Beata TAC"];

/** Deterministyczny „los" — harness ma wyglądać tak samo przy każdym wejściu. */
function pick(seed: number, mod: number): number {
  return (((seed * 2654435761) >>> 0) % 9973) % mod;
}

interface StageSpec {
  stage: string;
  id: number;
  name: string;
  category: "internal" | "external" | "terminal";
  terminal?: "hired" | "rejected" | "withdrawn";
  share: number;
}

const TEMPLATE: StageSpec[] = [
  { stage: "new", id: 1, name: "Nowy", category: "internal", share: 22 },
  { stage: "screening", id: 2, name: "Screening", category: "internal", share: 16 },
  { stage: "verified", id: 3, name: "Zweryfikowany", category: "internal", share: 10 },
  { stage: "cv_sent", id: 4, name: "CV Wysłane", category: "external", share: 12 },
  { stage: "client_interview", id: 5, name: "Rozmowa z klientem", category: "external", share: 8 },
  { stage: "acceptance", id: 6, name: "Oferta", category: "external", share: 4 },
  { stage: "hired", id: 7, name: "Zatrudniony", category: "terminal", terminal: "hired", share: 2 },
  { stage: "rejected", id: 8, name: "Odrzucony", category: "terminal", terminal: "rejected", share: 22 },
  { stage: "withdrawn", id: 9, name: "Wycofany", category: "terminal", terminal: "withdrawn", share: 4 },
];

function buildColumns(total: number): KanbanColumn[] {
  const columns: KanbanColumn[] = TEMPLATE.map((spec) => ({
    stage: spec.stage,
    stage_def_id: spec.id,
    name: spec.name,
    category: spec.category,
    terminal_type: spec.terminal ?? null,
    count: 0,
    items: [],
  }));
  const shareTotal = TEMPLATE.reduce((sum, spec) => sum + spec.share, 0);
  for (let i = 0; i < total; i += 1) {
    // Rozkład po etapach wg `share`, deterministycznie.
    let slot = pick(i + 7, shareTotal);
    let index = 0;
    while (slot >= TEMPLATE[index].share) {
      slot -= TEMPLATE[index].share;
      index += 1;
    }
    const spec = TEMPLATE[index];
    const candidateId = 1000 + i;
    const hasRate = pick(i + 3, 10) < 7;
    const rate = 120 + pick(i + 11, 110);
    const item: KanbanItem = {
      id: 50_000 + i,
      candidate_id: candidateId,
      stage: spec.stage,
      stage_def_id: spec.id,
      name: FIRST[pick(i + 1, FIRST.length)],
      lastname: `${LAST[pick(i + 5, LAST.length)]} ${i + 1}`,
      days_in_stage: pick(i + 13, 21),
      added_to_job_by_name: RECRUITERS[pick(i + 17, RECRUITERS.length)],
      added_to_job_at: "2026-09-01T08:00:00Z",
      expected_rate_value: hasRate ? rate : null,
      expected_rate_unit: hasRate ? "hourly" : null,
      expected_rate_currency: hasRate ? "PLN" : null,
      process_state_version: 1,
      hm_veto:
        pick(i + 19, 40) === 0
          ? {
              hiring_manager_contact_id: 1,
              hiring_manager_name: "Jan Manager",
              source_job_id: 7,
              source_job_title: "Java Developer (wcześniejsza rekrutacja)",
              rejected_at: "2026-08-10T10:00:00Z",
              rejection_reason_name: "Za słaba komunikacja",
            }
          : null,
    };
    columns[index].items.push(item);
  }
  for (const column of columns) column.count = column.items.length;
  return columns;
}

// ── Mocki propozycji ─────────────────────────────────────────────────────────

function inboxItem(i: number): ProposalInboxItem {
  const id = 9000 + i;
  const sources: ProposalInboxItem["sources"] =
    i % 5 === 0 ? ["new_cv"] : i % 7 === 0 ? ["marketplace"] : i % 3 === 0 ? ["full_base", "similar_projects"] : ["full_base"];
  return {
    candidate: {
      id,
      name: FIRST[pick(i + 2, FIRST.length)],
      lastname: `${LAST[pick(i + 9, LAST.length)]} P${i + 1}`,
      title: i % 2 === 0 ? "Senior Java Developer" : "Java Developer",
      city: ["Warszawa", "Kraków", "Łódź", "Gdańsk"][pick(i, 4)],
      availability_status: i % 4 === 0 ? "actively_looking" : "open_to_offers",
      availability_date: null,
      expected_rate_hourly: i % 6 === 0 ? null : 140 + pick(i + 4, 90),
      expected_rate_redacted: false,
    },
    sources,
    // Nowe CV bez policzonego dopasowania: „nie policzono", nigdy zero.
    score: i % 5 === 0 ? null : 95 - i * 2,
    evidence: {
      requirements: [
        { name: "Java 17", level: "must", status: "met" },
        { name: "Spring Boot", level: "must", status: i % 4 === 0 ? "unknown" : "met" },
        { name: "Kafka", level: "must", status: i % 3 === 0 ? "not_met" : "met" },
        { name: "AWS", level: "nice", status: "unknown" },
      ],
      previously_dismissed: i === 3,
    },
    first_seen_at: "2026-09-20T07:00:00Z",
    last_seen_at: "2026-09-21T07:00:00Z",
    is_new: i < 4,
    status: "proposed",
    run_id: "auto-run-1",
    eligibility: null,
  };
}

const INBOX_ITEMS = Array.from({ length: 18 }, (_, i) => inboxItem(i));

function runPage(state: CandidateSearchPage["state"]): CandidateSearchPage {
  const running = state === "running";
  return {
    run_id: "preview-run",
    state,
    error_code: state === "failed" ? "worker_restarted" : null,
    counts: {
      population: 58_400,
      pending: running ? 31_200 : 0,
      failed: 0,
      evaluated: running ? 27_200 : 58_400,
      eligible: running ? 0 : 52,
      strong: running ? 0 : 9,
      excluded: running ? 0 : 58_348,
      needs_verification: 0,
    },
    results: [],
    versions: {},
    coverage_complete: !running && state !== "failed",
    ranking_complete: !running && state !== "failed",
  };
}

type ProposalsScenario = "no-run" | "running" | "failed" | "rows";

const SCENARIO_LABEL: Record<ProposalsScenario, string> = {
  "no-run": "Brak przeglądu",
  running: "Skan w toku",
  failed: "Przegląd przerwany",
  rows: "Lista propozycji",
};

const noop = () => undefined;

function proposalsState(
  scenario: ProposalsScenario,
  filters: ProposalViewFilters,
): JobProposalsState {
  const all =
    scenario === "rows"
      ? mergeProposals({ inbox: INBOX_ITEMS, budgetHourly: BUDGET_HOURLY })
      : [];
  const entries = filterProposals(all, filters, { budgetHourly: BUDGET_HOURLY });
  const data =
    scenario === "running" ? runPage("running") : scenario === "failed" ? runPage("failed") : scenario === "rows" ? runPage("complete") : undefined;
  const state = {
    rows: entries.map((e) => e.row),
    entries,
    entryById: new Map(all.map((e) => [e.row.candidateId, e])),
    totalBeforeFilters: all.length,
    sourceCounts: countBySource(
      filterProposals(all, { ...filters, source: "all" }, { budgetHourly: BUDGET_HOURLY }),
    ),
    status: {
      run: {
        start: noop,
        clear: noop,
        refresh: noop,
        runId: data ? data.run_id : null,
        offset: 0,
        setOffset: noop,
        setMinScore: noop,
        minScore: 0,
        data,
        error: null,
        starting: false,
        running: scenario === "running",
        loading: false,
        fetching: false,
        needsNewRun: scenario === "failed",
      },
      startRun: noop,
      retryRun: noop,
      latestRun:
        scenario === "no-run"
          ? null
          : { run_id: "preview-run", state: "complete", completed_at: "2026-09-21T07:00:00Z", origin: "auto", own: false },
      engineDegraded: false,
      inbox: {
        total: all.length,
        hidden: 0,
        isSuccess: true,
        isLoading: false,
        isError: false,
        error: null,
        hasMore: false,
        loadingMore: false,
        loadMore: noop,
        retry: noop,
      },
      similar: { degraded: false, hiddenIneligible: scenario === "rows" ? 2 : 0, isError: false },
      recommendations: {
        degraded: scenario === "rows",
        stale: false,
        pending: false,
        isError: false,
        regenerate: noop,
        regenerating: false,
      },
    },
    addToJob: noop,
    adding: false,
    dismiss: noop,
    dismissing: false,
    addToShortlist: noop,
    shortlisting: false,
  };
  // Atrapa stanu hooka: te same pola, bez sieci. Rzutowanie w jednym miejscu —
  // kształt `run` to wynik `useFullCandidateSearch`, którego nie odtwarzamy.
  return state as unknown as JobProposalsState;
}

// ── Zasiew cache'u ───────────────────────────────────────────────────────────

function seededClient(columns: KanbanColumn[]): QueryClient {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: Infinity,
        gcTime: Infinity,
        retry: false,
        refetchOnMount: false,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
      },
      mutations: { retry: false },
    },
  });

  const scores: Record<string, number> = {};
  for (const column of columns) {
    for (const item of column.items) {
      // Co piąta osoba bez policzonego dopasowania — „—", nie zero.
      if (pick(item.candidate_id, 5) !== 0) scores[String(item.candidate_id)] = 35 + pick(item.candidate_id + 3, 60);
      client.setQueryData(candidateQueryKeys.detail(item.candidate_id), {
        id: item.candidate_id,
        name: item.name,
        lastname: item.lastname,
        city: ["Warszawa", "Kraków", "Wrocław"][pick(item.candidate_id, 3)],
        linkedin_current_title: "Java Developer",
        email: null,
      });
      client.setQueryData([...candidateQueryKeys.notes(item.candidate_id), JOB_ID], {
        items: [
          {
            id: item.candidate_id,
            content: "Rozmowa wstępna: dostępny od października, preferuje pracę hybrydową.",
            author_name: "Marta Rekruter",
            created_at: "2026-09-12T09:30:00Z",
          },
        ],
      });
    }
  }
  client.setQueryData(["pipeline-scores", String(JOB_ID)], {
    scores,
    pipeline_candidate_ids: Object.keys(scores).map(Number),
  });
  client.setQueryData(["pipeline-scores", JOB_ID], { scores, pipeline_candidate_ids: [] });
  // Flaga modułu „kontakt z kandydatem" — wyłączona: żadnych plakietek PII.
  client.setQueryData(candidateContactQueryKeys.status(), {
    enabled: false,
    assignment_enabled: false,
    traffit_intake_enabled: false,
  });
  // Shortlista i katalog właścicieli (`JobShortlist` nie jest tu montowany,
  // ale klucz jest stały — zasiany na wypadek podmiany atrapy na komponent).
  client.setQueryData(jobShortlistQueryKey(JOB_ID), []);
  client.setQueryData(["users-directory"], []);
  // Skrzynka propozycji i jej źródła — segment w harnessie dostaje stan wprost
  // (`ProposalsSegmentView`), zasiew jest drugim pasem bezpieczeństwa.
  const inbox: InfiniteData<ProposalInboxPage, number> = {
    pageParams: [0],
    pages: [
      {
        job_id: JOB_ID,
        status: "proposed",
        items: INBOX_ITEMS,
        total: INBOX_ITEMS.length,
        hidden_on_page: 0,
        limit: 50,
        offset: 0,
        next_offset: null,
      },
    ],
  };
  client.setQueryData(jobProposalsKeys.inbox(JOB_ID, 50), inbox);
  client.setQueryData(jobProposalsKeys.latestRun(JOB_ID), { job_id: JOB_ID, run: null });
  client.setQueryData(jobProposalsKeys.similar(JOB_ID), {
    job_id: JOB_ID,
    tier_used: "primary",
    similar_jobs: [],
    candidates: [],
    meta: { tier_a_count: 0, tier_b_count: 0, total_sources: 0, reason_if_empty: null, hidden_ineligible: 0 },
  });
  client.setQueryData(jobProposalsKeys.recommendations(JOB_ID), null);
  return client;
}

/**
 * Żadne żądanie nie wychodzi z harnessu. Interceptor ŻĄDANIA, nie adapter:
 * axios uruchamia interceptory żądań od ostatnio dodanego, więc ten odrzuca
 * wywołanie ZANIM ruszy interceptor aplikacji (który przy pierwszym żądaniu
 * sonduje `/api/health` zwykłym `fetch`-em — adapter by tego nie zatrzymał).
 * Instalowany w FAZIE RENDERU (inicjalizator stanu), bo efekty dzieci — a w nich
 * pierwsze zapytania — odpalają się przed efektem rodzica.
 */
function useNetworkBlocked() {
  const [interceptorId] = useState(() =>
    api.interceptors.request.use(() =>
      // Błąd BEZ `config`: interceptor odpowiedzi aplikacji ponawia odczyty bez
      // odpowiedzi przez ~22 s, ale tylko gdy zna konfigurację żądania — tu
      // sekcja ma pokazać swój stan błędu od razu.
      Promise.reject(
        Object.assign(new Error("Harness /preview/recruitment-v3 nie wysyła zapytań."), {
          isAxiosError: true,
          code: "ERR_PREVIEW_OFFLINE",
        }),
      ),
    ),
  );
  useEffect(
    () => () => {
      api.interceptors.request.eject(interceptorId);
    },
    [interceptorId],
  );
}

// ── Strona ───────────────────────────────────────────────────────────────────

function Pill({ active, children, onClick }: { active: boolean; children: React.ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={
        active
          ? "h-7 rounded-full border border-primary bg-primary px-3 text-xs font-medium text-primary-foreground"
          : "h-7 rounded-full border border-border bg-card px-3 text-xs font-medium text-foreground hover:bg-muted"
      }
    >
      {children}
    </button>
  );
}

function Harness() {
  const [size, setSize] = useState<250 | 47>(250);
  const [scenario, setScenario] = useState<ProposalsScenario>("rows");
  const [filters, setFilters] = useState<ProposalViewFilters>(DEFAULT_PROPOSAL_FILTERS);
  const [segment, setSegment] = useState<RecruitmentSegment>("in-process");
  const [activeCandidateId, setActiveCandidateId] = useState<number | null>(null);
  const [panelSection, setPanelSection] = useState<PersonPanelSection | null>(null);
  const [lastSlideOver, setLastSlideOver] = useState<RecruitmentSlideOver | null>(null);

  const columns = useMemo(() => buildColumns(size), [size]);
  // Osobny klient na rozmiar: zasiew jest per osoba.
  const client = useMemo(() => seededClient(columns), [columns]);
  const proposals = useMemo(() => proposalsState(scenario, filters), [scenario, filters]);

  return (
    <QueryClientProvider client={client}>
      <div className="mx-auto max-w-[1500px] space-y-4 p-4">
        <header className="space-y-2">
          <h1 className="text-lg font-semibold text-foreground">Rekrutacja v3 — jedna tabela (harness)</h1>
          <p className="text-sm text-muted-foreground">
            Same mocki, zero zapytań. Ruch etapu, notatka i akcje zbiorcze otwierają prawdziwe okna, ale zapis
            jest lokalnie odrzucany (harness nie ma sieci).
          </p>
          <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Rozmiar rekrutacji">
            <span className="text-xs font-semibold text-muted-foreground">Osób:</span>
            <Pill active={size === 250} onClick={() => { setSize(250); setActiveCandidateId(null); }}>250 (grupowanie)</Pill>
            <Pill active={size === 47} onClick={() => { setSize(47); setActiveCandidateId(null); }}>47 (płaska lista)</Pill>
            <span className="ml-4 text-xs font-semibold text-muted-foreground">Propozycje z bazy:</span>
            {(Object.keys(SCENARIO_LABEL) as ProposalsScenario[]).map((key) => (
              <Pill
                key={key}
                active={scenario === key}
                onClick={() => {
                  setScenario(key);
                  setSegment("proposals");
                }}
              >
                {SCENARIO_LABEL[key]}
              </Pill>
            ))}
            {lastSlideOver ? (
              <span className="ml-auto text-xs text-muted-foreground" role="status">
                Strona otworzyłaby okno: {lastSlideOver}
              </span>
            ) : null}
          </div>
        </header>

        <RecruitmentWorkspace
          key={size}
          jobId={JOB_ID}
          job={{
            title: "Senior Java Developer",
            budgetHourly: BUDGET_HOURLY,
            rejectionReasons: [
              { id: "1", label: "Za wysoka stawka", applies_to: ["rejected"] },
              { id: "2", label: "Kandydat wybrał inną ofertę", applies_to: ["withdrawn"] },
            ],
            slaDays: 5,
            stagesWithScorecard: new Set([5]),
          }}
          kanban={{ columns, off_template: null }}
          kanbanQueryState={{ isLoading: false, isError: false, error: null, isSuccess: true, refetch: noop }}
          canWritePipeline
          canWriteClientRate
          openProposalsCount={scenario === "rows" ? INBOX_ITEMS.length : 0}
          shortlistCount={3}
          segment={segment}
          onSegmentChange={setSegment}
          activeCandidateId={activeCandidateId}
          onActiveCandidateChange={setActiveCandidateId}
          panelSection={panelSection}
          onPanelSectionChange={setPanelSection}
          workbenchContext={{ clientId: null, clientName: "Bank Alfa", onMoved: noop, canCloseJob: false }}
          onOpenSlideOver={setLastSlideOver}
          renderShortlist={() => (
            <p className="rounded-lg border border-dashed border-border px-6 py-10 text-center text-sm text-muted-foreground">
              Shortlista (3 osoby) — w harnessie atrapa; produkcyjnie renderuje się tu `JobShortlist`.
            </p>
          )}
          renderProposals={() => (
            <ProposalsSegmentView
              jobId={JOB_ID}
              budgetHourly={BUDGET_HOURLY}
              proposals={proposals}
              filters={filters}
              onFiltersChange={setFilters}
              onOpenManualSearch={() => setLastSlideOver("manual-search")}
              onOpenQuickAdd={noop}
            />
          )}
        />
      </div>
    </QueryClientProvider>
  );
}

export default function RecruitmentV3PreviewPage() {
  useNetworkBlocked();
  return (
    <ToastProvider>
      <Harness />
    </ToastProvider>
  );
}
