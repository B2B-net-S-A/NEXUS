"use client";

/**
 * Harness strony rekrutacji (nagłówek + pasek „Kandydaci do dodania” + Tablica
 * + okno źródeł) w ramce aplikacji — WYŁĄCZNIE dane fikcyjne, zero zapytań
 * (cache zasiany, interceptor odrzuca każde żądanie axiosa).
 *
 * Powstał po zgłoszeniu z 28.09.2026: na laptopie z Windows (skalowanie 150%,
 * okno ≈ 1280 × 650 px CSS) sam nagłówek zajmował ~60% wysokości, a na Macu
 * z oknem 2666 px wszystko mieściło się w jednej linii. Ramka odwzorowuje
 * powłokę (`AppShellV2`: pasek 48 px, `p-6`, menu 240 px od 1280 px, niżej
 * szyna 60 px) i zwiniętą szynę „Otwarte karty” (40 px od `lg`), żeby dało się
 * zmierzyć, ile miejsca zostaje Tablicy przy typowych rozmiarach okna
 * z Windows: 1280 × 720, 1366 × 768, 1536 × 864
 * (`e2e/responsive-preview.spec.ts`).
 *
 * `?empty=1` — puste kolumny widoczne (ustawienie z menu „⋯”),
 * `?rail=1` — menu zwinięte do szyny 60 px także od 1280 px,
 * `?sources=similar|postings|base|search` — okno „Kandydaci do dodania”
 * otwarte od razu na tej zakładce,
 * `?closed=1` — rekrutacja zamknięta („Otwórz ponownie…” w menu „⋯”),
 * `?reopen=1` — zamknięta z otwartym oknem „Otwórz ponownie” i fikcyjnymi
 * brakami (04.10.2026).
 */

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AxiosError } from "axios";

import api from "@/lib/api";
import { ToastProvider } from "@/components/Toast";
import { TooltipProvider } from "@/components/ui/tooltip";
import { CandidateSourcesStrip } from "@/components/v2/jobs/CandidateSourcesStrip";
import { JobDetailCompactHeader } from "@/components/v2/jobs/JobDetailCompactHeader";
import { RequestStatusBadge } from "@/components/v2/jobs/JobListCells";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { KanbanBoardV2 } from "@/components/v2/pages/KanbanBoardV2";
import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";
import { AddCandidatesPanel } from "@/components/v2/recruitment/AddCandidatesPanel";
import { JobReopenDialog } from "@/components/v2/jobs/JobReopenDialog";
import { Badge } from "@/components/ui/badge";
import { CANDIDATE_SOURCE_TABS, type CandidateSourceTab } from "@/components/v2/recruitment/types";
import { searchBaseKey } from "@/components/v2/recruitment/useSearchBaseTab";
import { screenedOutQueryKey } from "@/lib/api/applicationScreenings";
import { jobHeaderFacts } from "@/lib/job-header-facts";
import {
  jobProposalsKeys,
  type ProposalFacts,
  type ProposalInboxItem,
} from "@/lib/job-proposals-api";
import {
  candidatesListFiltersForQuery,
  championSearchRequirements,
  jobListFilters,
} from "@/lib/job-search-filters";
import type { MatchBreakdown } from "@/lib/match-breakdown";
import { requirementLabels, type MatchingRequirements } from "@/lib/matching-requirements";
import {
  similarJobsKey,
  similarPeopleWithRestKey,
  similarPersonScoreKey,
  type SentPerson,
  type SimilarJobItem,
} from "@/lib/similar-jobs-api";
import { useAuthStore } from "@/store/auth";
import { useUiStore } from "@/store/ui";

const JOB_ID = 4344;
const HOUR = 3_600_000;
// Wymaganie wpisane zdaniem — po nim nie szukamy (pokazuje to zakładka „Szukaj w bazie”).
const PROSE_MUST = "Minimum 5 lat doświadczenia w projektach dla sektora finansowego";

const CHAMPION_PROFILE = {
  search: {
    requirements: [["Angular"], ["TypeScript"], ["RxJS", "NgRx"], ["bankow*", "banking"]],
    exclude: ["junior"],
  },
};

const JOB = {
  id: JOB_ID,
  title: "Starszy Programista Frontend (Angular)",
  working_title: "Programista Frontend · Angular, TypeScript · 5+ lat",
  client_name: "Bank Przykładowy S.A.",
  client_reference: "PRZ/001/2026",
  remote_policy: "hybrid",
  onsite_days_per_week: 2,
  onsite_days_per_month: null,
  location: "Warszawa",
  effective_budget_hourly: 95,
  has_budget_hourly: true,
  must_skills: ["Angular", "TypeScript", PROSE_MUST],
  champion_profile: CHAMPION_PROFILE,
};

const REQUIREMENTS: MatchingRequirements = {
  version: 1,
  reviewed: true,
  missing_evidence_policy: "review",
  all_of: [
    { any_of: ["angular"], level: "must", source: "manual", evidence: "" },
    { any_of: ["typescript"], level: "must", source: "manual", evidence: "" },
  ],
};

let nextId = 1;
function card(first: string, last: string, extra: Partial<KanbanItem> = {}): KanbanItem {
  const id = nextId++;
  return {
    id,
    candidate_id: 9100 + id,
    stage: "new",
    name: first,
    lastname: last,
    days_in_stage: 0,
    added_to_job_by_name: "Marta Nowak",
    process_state_version: 1,
    entry_source: "added_manual",
    claim_user_id: 7,
    claim_user_name: "Marta Nowak",
    claim_until: new Date(Date.now() + 11 * HOUR).toISOString(),
    ...extra,
  } as KanbanItem;
}

function col(
  stage: string,
  name: string,
  defId: number,
  items: KanbanItem[],
  category: "internal" | "external" | "terminal" = "internal",
  terminal_type: string | null = null,
): KanbanColumn {
  return {
    stage,
    name,
    category,
    stage_def_id: defId,
    terminal_type,
    count: items.length,
    items: items.map((i) => ({ ...i, stage })),
  } as unknown as KanbanColumn;
}

function columns(): KanbanColumn[] {
  nextId = 1;
  return [
    col("new", "Nowi / Analiza CV", 21, [
      card("Anna", "Przykładowa"),
      card("Jan", "Testowy"),
      card("Ewa", "Fikcyjna"),
      card("Piotr", "Próbny"),
    ]),
    col("screening", "Screening", 22, [
      card("Marek", "Przykładowy", { entry_source: "proposal" }),
    ]),
    col("verified", "Zweryfikowany", 23, []),
    col("interview", "Przepuszczony przez DZ", 24, []),
    col("cv_sent", "CV Wysłane", 25, []),
    col("client_interview", "Rozmowa z klientem", 26, []),
    col("offer_sent", "Umowa", 27, []),
    col("hired", "Zatrudniony", 28, []),
    col("rejected", "Odrzucony", 29, [card("Zofia", "Szkicowa", { claim_until: null } as never)], "terminal", "rejected"),
    col("withdrawn", "Wycofany", 30, [], "terminal", "withdrawn"),
  ];
}

/** Dane ze znacznikiem dzień w przód — zapytanie z własnym `staleTime` nie odświeża ich. */
function seedFresh(qc: QueryClient, key: readonly unknown[], data: unknown): void {
  qc.setQueryData(key, data, { updatedAt: Date.now() + 86_400_000 });
}

interface PersonSeed {
  id: number;
  first: string;
  last: string;
  facts: Partial<ProposalFacts>;
  score: number | null;
  breakdown: MatchBreakdown;
  note?: string;
}

const measured = (total: number, matching: string[], gap: string[] = []): MatchBreakdown => ({
  total,
  measurement: "measured",
  matching_must: matching,
  gap_must: gap,
});

const POSTINGS: PersonSeed[] = [
  {
    id: 501,
    first: "Kamila",
    last: "Wzorcowa",
    facts: { title: "Frontend Developer", years_experience: 6, city: "Warszawa", expected_rate_hourly: 85, max_onsite_days_per_week: 2 },
    score: 82,
    breakdown: measured(82, ["Angular", "TypeScript"]),
    note: "Zgłoszenie z ogłoszenia. Dostępna od listopada.",
  },
  {
    id: 502,
    first: "Tomasz",
    last: "Makietowy",
    facts: { title: "Angular Developer", years_experience: 4, city: "Łódź", expected_rate_hourly: 80 },
    score: 74,
    breakdown: measured(74, ["Angular"], ["TypeScript"]),
  },
  {
    id: 503,
    first: "Adam",
    last: "Podglądowy",
    facts: { title: "Programista JavaScript", years_experience: 7, city: "Kraków" },
    score: 71,
    breakdown: measured(71, ["TypeScript"], ["Angular"]),
  },
];

const BASE: PersonSeed[] = [
  {
    id: 511,
    first: "Ewa",
    last: "Demonstracyjna",
    facts: {
      title: "Senior Frontend Developer",
      company: "Firma Demo",
      years_experience: 9,
      city: "Warszawa",
      expected_rate_hourly: 92,
      client_history: {
        job_id: 1725,
        title: "Programista Frontend",
        furthest_stage: "client_interview",
        furthest_stage_label: "Rozmowa z klientem",
        outcome: "in_progress",
        last_moved_at: "2026-09-03T10:00:00Z",
      },
    },
    score: 88,
    breakdown: measured(88, ["Angular", "TypeScript"]),
    note: "Po rozmowie u klienta we wrześniu. Otwarta na kolejny projekt w bankowości.",
  },
  {
    id: 512,
    first: "Oskar",
    last: "Wzorcowy",
    facts: { title: "Frontend Developer", years_experience: 6, city: "Gdańsk", expected_rate_hourly: 110, max_onsite_days_per_week: 0 },
    score: 79,
    breakdown: measured(79, ["Angular", "TypeScript"]),
  },
  {
    id: 513,
    first: "Agata",
    last: "Szablonowa",
    facts: { title: "Angular Developer", years_experience: 5, city: "Poznań", expected_rate_hourly: 90, cv_uploaded_on: "2022-03-14" },
    score: 76,
    breakdown: measured(76, ["Angular"], ["TypeScript"]),
  },
  {
    id: 514,
    first: "Kamil",
    last: "Bezdanych",
    facts: {},
    score: null,
    breakdown: { total: null, measurement: "missing_index" },
  },
  {
    id: 515,
    first: "Iga",
    last: "Próbna",
    facts: { title: "Fullstack Developer", years_experience: 8, city: "Wrocław", expected_rate_hourly: 95 },
    score: 72,
    breakdown: measured(72, ["TypeScript"], ["Angular"]),
  },
];

const SEARCH: PersonSeed[] = [
  {
    id: 521,
    first: "Marta",
    last: "Fikcyjna",
    facts: { title: "Angular Developer", years_experience: 8, city: "Warszawa", expected_rate_hourly: 90 },
    score: 84,
    breakdown: measured(84, ["Angular", "TypeScript"]),
  },
  {
    id: 522,
    first: "Hubert",
    last: "Przykładowy",
    facts: { title: "Frontend Engineer", years_experience: 6, city: "Katowice", expected_rate_hourly: 88 },
    score: 77,
    breakdown: measured(77, ["Angular", "TypeScript"]),
  },
  {
    id: 523,
    first: "Natalia",
    last: "Testowa",
    facts: { title: "Programistka Angular", years_experience: 5, city: "Lublin" },
    score: 69,
    breakdown: measured(69, ["Angular"], ["TypeScript"]),
  },
];

const SIMILAR_PEOPLE: PersonSeed[] = [
  { id: 531, first: "Paweł", last: "Makietowy", facts: { title: "Angular Developer", years_experience: 7, city: "Warszawa", expected_rate_hourly: 93 }, score: 86, breakdown: measured(86, ["Angular", "TypeScript"]) },
  { id: 532, first: "Julia", last: "Wzorcowa", facts: { title: "Frontend Developer", years_experience: 5, city: "Gdynia" }, score: 78, breakdown: measured(78, ["Angular"], ["TypeScript"]) },
  { id: 533, first: "Robert", last: "Demo", facts: { title: "Programista Frontend", years_experience: 10, city: "Kraków", expected_rate_hourly: 105 }, score: 81, breakdown: measured(81, ["Angular", "TypeScript"]) },
  { id: 534, first: "Lena", last: "Szkicowa", facts: { title: "Junior Frontend Developer", years_experience: 2, city: "Łódź" }, score: 55, breakdown: measured(55, ["TypeScript"], ["Angular"]) },
];

function factsOf(seed: PersonSeed): ProposalFacts {
  return {
    candidate_id: seed.id,
    title: null,
    company: null,
    years_experience: null,
    city: null,
    max_onsite_days_per_week: null,
    remote_modes: [],
    availability_status: null,
    availability_date: null,
    expected_rate_hourly: null,
    expected_rate_currency: "PLN",
    expected_rate_redacted: false,
    client_history: null,
    ...seed.facts,
  };
}

function inboxItem(seed: PersonSeed, source: string, postingRecent: boolean): ProposalInboxItem {
  return {
    candidate: {
      id: seed.id,
      name: seed.first,
      lastname: seed.last,
      title: seed.facts.title ?? null,
      city: seed.facts.city ?? null,
      availability_status: null,
      availability_date: null,
      expected_rate_hourly: seed.facts.expected_rate_hourly ?? null,
      expected_rate_redacted: false,
    },
    sources: [source],
    score: seed.score,
    evidence: { matched_must: seed.breakdown.matching_must ?? [], missing_must: seed.breakdown.gap_must ?? [] },
    first_seen_at: "2026-09-30T06:00:00Z",
    last_seen_at: "2026-10-01T06:00:00Z",
    is_new: postingRecent,
    status: "proposed",
    run_id: null,
    eligibility: null,
    posting_seen_at: postingRecent ? "2026-09-30T06:00:00Z" : null,
    posting_recent: postingRecent,
  };
}

function seedPerson(qc: QueryClient, seed: PersonSeed): void {
  seedFresh(qc, jobProposalsKeys.facts(JOB_ID, [seed.id]), [factsOf(seed)]);
  seedFresh(qc, similarPersonScoreKey(JOB_ID, seed.id), {
    scores: seed.score === null ? {} : { [String(seed.id)]: seed.score },
    breakdowns: { [String(seed.id)]: seed.breakdown },
    non_technology_must: [PROSE_MUST],
  });
  seedFresh(qc, candidateQueryKeys.quickView(seed.id), {
    recent_notes: seed.note
      ? [{ id: seed.id * 10, content: seed.note, author_name: "Marta N.", created_at: "2026-09-18T09:30:00Z" }]
      : [],
  });
}

function similarJob(id: number, title: string, overrides: Partial<SimilarJobItem> = {}): SimilarJobItem {
  return {
    id,
    title,
    reference_number: `DEMO-${id}`,
    status: "closed",
    closed_at: null,
    client_name: "Bank Przykładowy S.A.",
    similarity: 70,
    sent_count: 0,
    linked: false,
    ...overrides,
  };
}

function sentPerson(seed: PersonSeed, overrides: Partial<SentPerson> = {}): SentPerson {
  return {
    candidate_id: seed.id,
    name: `${seed.first} ${seed.last}`,
    furthest_stage: "cv_sent",
    sent_at: "2026-09-12",
    outcome: "in_progress",
    already_in_job: false,
    selectable: true,
    sent: true,
    ...overrides,
  };
}

function seededClient(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { staleTime: Infinity, retry: false, refetchOnMount: false, refetchOnWindowFocus: false },
    },
  });
  // 0404: „Odrzuceni przez AI” — pusta lista.
  seedFresh(qc, screenedOutQueryKey(JOB_ID), { job_id: JOB_ID, total: 0, items: [] });

  // Skrzynka propozycji: trzy osoby z ogłoszeń (7 dni) + pięć z nocnego przeglądu.
  seedFresh(qc, jobProposalsKeys.inbox(JOB_ID, 50), {
    pages: [
      {
        job_id: JOB_ID,
        status: "proposed",
        items: [
          ...POSTINGS.map((p) => inboxItem(p, "job_board", true)),
          ...BASE.map((p) => inboxItem(p, "full_base", false)),
        ],
        dismissed_candidate_ids: [],
        total: POSTINGS.length + BASE.length,
        hidden_on_page: 0,
        limit: 50,
        offset: 0,
        next_offset: null,
      },
    ],
    pageParams: [0],
  });
  seedFresh(qc, jobProposalsKeys.latestRun(JOB_ID), { job_id: JOB_ID, run: null });
  seedFresh(qc, jobProposalsKeys.similar(JOB_ID), {
    candidates: [],
    tier_used: "primary",
    meta: { tier_a_count: 0, tier_b_count: 0, total_sources: 0, reason_if_empty: null, hidden_ineligible: 0 },
  });
  seedFresh(qc, jobProposalsKeys.recommendations(JOB_ID), null);
  seedFresh(qc, jobProposalsKeys.counts(JOB_ID), {
    job_id: JOB_ID,
    days: 7,
    postings_recent: POSTINGS.length,
    base: BASE.length,
    screened_out: 0,
    not_searchable_must: [PROSE_MUST],
  });
  seedFresh(qc, jobProposalsKeys.facts(JOB_ID, POSTINGS.map((p) => p.id)), POSTINGS.map(factsOf));
  seedFresh(qc, jobProposalsKeys.facts(JOB_ID, BASE.map((p) => p.id)), BASE.map(factsOf));

  // Podobne rekrutacje: w każdej najpierw wysłani do klienta, potem pozostali.
  seedFresh(qc, similarJobsKey(JOB_ID), {
    job_id: JOB_ID,
    reassigned_count: 0,
    reassignable_people: 3,
    other_people: 1,
    linked: [],
    suggestions: [
      similarJob(1725, "Programista Frontend (Angular)", { similarity: 78, sent_count: 2, other_count: 1 }),
      similarJob(1794, "Frontend Developer x2", { status: "published", similarity: 71, sent_count: 1 }),
    ],
  });
  seedFresh(qc, similarPeopleWithRestKey(JOB_ID, 1725), {
    people: [
      sentPerson(SIMILAR_PEOPLE[0]),
      sentPerson(SIMILAR_PEOPLE[1], { furthest_stage: "client_interview", sent_at: "2026-09-03" }),
      sentPerson(SIMILAR_PEOPLE[3], { furthest_stage: "screening", sent_at: null, sent: false }),
    ],
    restTotal: 1,
  });
  seedFresh(qc, similarPeopleWithRestKey(JOB_ID, 1794), {
    people: [sentPerson(SIMILAR_PEOPLE[2], { outcome: "rejected_by_client", sent_at: "2026-08-20" })],
    restTotal: 0,
  });

  // „Szukaj w bazie”: te same trzy odczyty i TE SAME funkcje filtrów co okno.
  seedFresh(qc, ["matching-requirements", JOB_ID], REQUIREMENTS);
  seedFresh(qc, ["champion-profile", JOB_ID], { champion_profile: CHAMPION_PROFILE });
  const rows = championSearchRequirements(JOB).rows;
  const techRows = [true, true, true, false];
  seedFresh(qc, ["manual-search-row-kinds", rows], techRows);
  const filters = candidatesListFiltersForQuery(
    jobListFilters(JOB, requirementLabels(REQUIREMENTS, "must"), techRows),
    { jobId: JOB_ID },
  );
  const filtersKey = JSON.stringify(filters);
  const hit = (text: string, word: string) => {
    const at = text.indexOf(word);
    return [{ field: "Treść CV", text, highlights: at >= 0 ? [[at, at + word.length]] : [] }];
  };
  seedFresh(qc, searchBaseKey(JOB_ID, filtersKey), {
    pages: [
      {
        items: SEARCH.map((p, index) => ({
          id: p.id,
          name: p.first,
          lastname: p.last,
          linkedin_current_title: p.facts.title ?? null,
          years_it_experience: p.facts.years_experience ?? null,
          city: p.facts.city ?? null,
          expected_rate_hourly: p.facts.expected_rate_hourly ?? null,
          expected_rate_currency: "PLN",
          match_snippets: hit(
            index === 0
              ? "Aplikacje Angular dla bankowości detalicznej, TypeScript, NgRx"
              : "Projekty w Angular i TypeScript, RxJS",
            "Angular",
          ),
        })),
        total: 42,
        page: 1,
        page_size: 20,
      },
    ],
    pageParams: [1],
  });
  seedFresh(qc, ["job-search-base-count", JOB_ID, filtersKey], 42);
  seedFresh(qc, ["job-search-base-scores", JOB_ID, SEARCH.map((p) => p.id).join(",")], {
    scores: Object.fromEntries(SEARCH.map((p) => [String(p.id), p.score])),
    breakdowns: {},
  });

  for (const seed of [...POSTINGS, ...BASE, ...SEARCH, ...SIMILAR_PEOPLE]) seedPerson(qc, seed);

  // „Otwórz ponownie” (`?closed=1`, `?reopen=1`): braki bramki, lista
  // rekruterów i rekrutacja w cache'u — te same klucze co `JobReopenDialog`.
  seedFresh(qc, ["job", String(JOB_ID)], { ...JOB, status: "closed", primary_owner: null });
  seedFresh(qc, ["job-readiness", JOB_ID], {
    job_id: JOB_ID,
    ready: false,
    closed: true,
    already_handed_off: false,
    allocation_enabled: true,
    allocation_mode: "shadow",
    blockers: REOPEN_BLOCKERS.map((b) => b.message),
    blocker_items: REOPEN_BLOCKERS,
  });
  seedFresh(qc, ["handoff-recruiters"], [
    { id: 7, name: "Marta Nowak", email: "marta@example.com" },
    { id: 8, name: "Piotr Zieliński", email: "piotr@example.com" },
  ]);
  return qc;
}

const REOPEN_BLOCKERS = [
  { code: "hiring_manager", message: "Wskaż hiring managera albo zaznacz „Klient nie podał”." },
  { code: "deadline", message: "Podaj termin albo zaznacz „Klient nie podał”." },
];

const noop = () => undefined;

function JobDetailHarness() {
  const params = useSearchParams();
  const showEmpty = params.get("empty") === "1";
  const railOnly = params.get("rail") === "1";
  const initialSources = params.get("sources");
  const reopenOnStart = params.get("reopen") === "1";
  const closed = reopenOnStart || params.get("closed") === "1";
  const [reopenOpen, setReopenOpen] = useState(reopenOnStart);
  const [client] = useState(seededClient);
  const [sourceTab, setSourceTab] = useState<CandidateSourceTab | null>(
    CANDIDATE_SOURCE_TABS.includes(initialSources as CandidateSourceTab)
      ? (initialSources as CandidateSourceTab)
      : null,
  );
  const [ready, setReady] = useState(false);
  const hideEmptyColumns = useUiStore((s) => s.hideEmptyKanbanColumns);
  useEffect(() => {
    const blocker = api.interceptors.request.use((config) =>
      Promise.reject(new AxiosError("preview: sieć wyłączona", "ECONNABORTED", config)),
    );
    useAuthStore.setState({
      user: {
        id: 7,
        email: "preview@example.com",
        name: "Marta Nowak",
        role: "recruiter",
        roles: ["recruiter"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
        effective_section_access: { sourcing: "write", pipeline: "write" },
      } as never,
      hydrated: true,
    });
    useUiStore.setState({ hideEmptyKanbanColumns: !showEmpty });
    setReady(true);
    return () => api.interceptors.request.eject(blocker);
  }, [showEmpty]);
  if (!ready) return null;

  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <TooltipProvider>
          <div className="app-shell-root flex h-dvh overflow-hidden bg-background text-foreground">
            {/* Menu: 240 px od 1280 px (domyślne przypięcie), niżej szyna 60 px. */}
            <div
              aria-hidden="true"
              className={
                railOnly
                  ? "hidden h-full w-[60px] shrink-0 border-r border-border bg-sidebar md:block"
                  : "hidden h-full w-[60px] shrink-0 border-r border-border bg-sidebar md:block xl:w-60"
              }
            />
            <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
              <div aria-hidden="true" className="h-12 shrink-0 border-b border-border" />
              <main className="relative flex-1 overflow-y-auto" data-testid="harness-main">
                <div className="p-4 pb-24 md:p-6">
                  <div className="flex items-start gap-4 lg:gap-6">
                    {/* Zwinięta szyna „Otwarte karty” (JobTabsRail, w-10). */}
                    <div
                      aria-hidden="true"
                      className="hidden h-24 w-10 shrink-0 rounded-xl border border-border bg-card/60 lg:block"
                    />
                    <div className="min-w-0 flex-1 space-y-2">
                      <JobDetailCompactHeader
                        title={JOB.working_title}
                        clientTitle={JOB.title}
                        clientReference={JOB.client_reference}
                        referenceNumber="REF-4344"
                        badges={
                          closed ? (
                            <Badge variant="danger">Zamknięta</Badge>
                          ) : (
                            <RequestStatusBadge status="searching" />
                          )
                        }
                        facts={jobHeaderFacts(JOB)}
                        presence={
                          <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
                            MN
                          </span>
                        }
                        activeView="board"
                        onViewChange={noop}
                        onOpenOrder={noop}
                        onOpenHistoryChat={noop}
                        onOpenQuestions={noop}
                        championFound={false}
                        onToggleChampion={noop}
                        onAddByName={noop}
                        onAddFromCv={noop}
                        onStartFullReview={() => setSourceTab("base")}
                        onOpenMyPeople={noop}
                        teamSummary="Rekruter: Marta N. +1"
                        onOpenTeam={noop}
                        emptyColumnsHidden={hideEmptyColumns}
                        onToggleEmptyColumns={() =>
                          useUiStore.setState({ hideEmptyKanbanColumns: !hideEmptyColumns })
                        }
                        onCopyLink={noop}
                        onCloseJob={closed ? undefined : noop}
                        onReopenJob={closed ? () => setReopenOpen(true) : undefined}
                      />
                      {closed ? (
                        <JobReopenDialog
                          jobId={JOB_ID}
                          open={reopenOpen}
                          onOpenChange={setReopenOpen}
                          mode="reopen"
                          recruiter={null}
                          onOpenChampion={noop}
                        />
                      ) : null}
                      <KanbanBoardV2
                        columns={columns()}
                        jobId={JOB_ID}
                        jobTitle={JOB.title}
                        renderAbove={(viewControls) => (
                          <CandidateSourcesStrip
                            jobId={JOB_ID}
                            job={JOB}
                            canSeeSimilar
                            onOpen={setSourceTab}
                            onAddByName={noop}
                            onAddFromCv={noop}
                            trailing={viewControls}
                          />
                        )}
                      />
                      <AddCandidatesPanel
                        open={sourceTab !== null}
                        onOpenChange={(open) => {
                          if (!open) setSourceTab(null);
                        }}
                        jobId={JOB_ID}
                        job={JOB}
                        tab={sourceTab ?? "base"}
                        onTabChange={setSourceTab}
                        budgetHourly={JOB.effective_budget_hourly}
                        pipelineCandidateIds={[]}
                        onOpenManualSearch={noop}
                        onOpenChampionSearch={noop}
                        onOpenFullList={noop}
                      />
                    </div>
                  </div>
                </div>
              </main>
            </div>
          </div>
        </TooltipProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
}

export default function JobDetailPreview() {
  return (
    <Suspense fallback={null}>
      <JobDetailHarness />
    </Suspense>
  );
}
