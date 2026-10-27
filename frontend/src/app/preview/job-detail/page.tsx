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
 * `?rail=1` — menu zwinięte do szyny 60 px także od 1280 px,
 * `?sources=similar|postings|base|search|manual` — okno „Kandydaci do dodania”
 * otwarte od razu na tej zakładce (14.10.2026: dopasowanie liczone bez
 * przycisku — `/api/search/candidates/scores` odpowiada lokalnie z zasiewu,
 * „+ Dodaj” w wierszach, po jednej osobie w stanie „Dodano · Cofnij” na
 * „Propozycjach z bazy” i w „Szukaj w bazie”, „Szukaj ręcznie” jako zakładka;
 * 19.10.2026: plakietka stawki względem budżetu 95 zł/h — w budżecie, równo
 * budżet, +7%, +25% i osoba bez stawki w `base` i `search`),
 * `?closed=1` — rekrutacja zamknięta („Otwórz ponownie…” i „Zmień powód
 * zamknięcia…” w menu „⋯”); `?reason=duplicate|competitor|filled_by_us|other`
 * — powód w plakietce (domyślnie duplikat), `?change=1` — otwarte okno
 * „Zmień powód zamknięcia” (21.10.2026),
 * `?reopen=1` — zamknięta z otwartym oknem „Otwórz ponownie” i fikcyjnymi
 * brakami (04.10.2026),
 * `?files=1` — otwarte okno „Pliki” z menu „⋯” (0428, 09.10.2026),
 * `?close=1` — otwarte okno „Zamknij rekrutację z powodem”; pierwsze
 * zamknięcie dostaje fikcyjne ostrzeżenie o osobach w toku (13.10.2026).
 *
 * Nagłówek K1–K3 (14.10.2026): `?prio=p2|accepting` — poziom priorytetu
 * (domyślnie P1), `?team=me|none|proposal` — obsada (domyślnie dwie inne
 * osoby), `?client=long` — długa nazwa klienta, `?collapsed=1` — nagłówek
 * zwinięty, `?readonly=1` — rola bez zmiany priorytetu i przydziału.
 *
 * Championi (15.10.2026, D1–D9): `?champion=none|two|seats|legacy` — bez
 * championów (domyślnie), dwóch championów z „Rozmowy u klienta” (status
 * „Championi: Karol W. +1”, P1 wstrzymany, karty i panel ze znakiem),
 * rekrutacja na 2 miejsca z jednym championem („Szukamy · 1 z 2”), stara
 * flaga bez osób („Mamy championa”). Plakietka statusu otwiera okienko
 * „Championi tej rekrutacji” (z `?readonly=1` — lista do odczytu); zapis
 * odpowiada lokalnie.
 */

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AxiosError } from "axios";

import api from "@/lib/api";
import { ToastProvider } from "@/components/Toast";
import { TooltipProvider } from "@/components/ui/tooltip";
import { CandidateSourcesStrip } from "@/components/v2/jobs/CandidateSourcesStrip";
import { JobDetailCompactHeader } from "@/components/v2/jobs/JobDetailCompactHeader";
import { JobPriorityMenu } from "@/components/v2/jobs/JobPriorityMenu";
import { JobRecruiterFact } from "@/components/v2/jobs/JobRecruiterFact";
import type { JobRecruiter } from "@/lib/job-team";
import { isPriorityLevel } from "@/lib/request-priority";
import { warsawToday } from "@/lib/warsaw-date";
import { reassignContextQueryKey } from "@/components/v2/jobs/ScreeningReassignSuggestions";
import { JobChampionsStatus } from "@/components/v2/jobs/JobChampionsStatus";
import {
  jobChampionsQueryKey,
  type JobChampionEligible,
  type JobChampionsView,
} from "@/lib/job-champions-api";
import { candidateQueryKeys, candidateViewerScopeKey } from "@/components/v2/pages/candidate-query-keys";
import {
  CANDIDATES_BASE_TOTAL_QUERY_KEY,
  candidatesListApiParams,
  candidatesListQueryKey,
} from "@/components/v2/pages/CandidatesListV2";
import { cloudTalkStatusQueryKey } from "@/hooks/useCloudTalkEnabled";
import { pairMovesQueryKey } from "@/components/v2/recruitment/JobMoveLog";
import { pinnedNotesQueryKey } from "@/components/v2/recruitment/PinnedCandidateNotes";
import { KanbanBoardV2 } from "@/components/v2/pages/KanbanBoardV2";
import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";
import { rateChangesQueryKey } from "@/lib/rate-change";
import { AddCandidatesPanel } from "@/components/v2/recruitment/AddCandidatesPanel";
import { JobCloseReasonBadge } from "@/components/v2/jobs/JobCloseReasonBadge";
import { JobCloseWithReasonDialog } from "@/components/v2/jobs/JobCloseWithReasonDialog";
import { JOB_CLOSE_REASONS, type JobCloseReason } from "@/types/client-profile";
import { JobReopenDialog } from "@/components/v2/jobs/JobReopenDialog";
import { JobFilesSlideOver } from "@/components/v2/recruitment/slideovers/JobFilesSlideOver";
import type { JobFilesResponse } from "@/lib/api/jobFiles";
import { CANDIDATE_WINDOW_TABS, type CandidateWindowTab } from "@/components/v2/recruitment/types";
import { searchBaseKey } from "@/components/v2/recruitment/useSearchBaseTab";
import { screenedOutQueryKey } from "@/lib/api/applicationScreenings";
import { recruitmentRateHintsQueryKey } from "@/lib/api/recruitmentRateHints";
import type { MoveRequirementsResponse } from "@/lib/api/moveRequirements";
import { plainBriefQueryKey, type PlainBrief } from "@/lib/api/plainKnowledge";
import {
  screeningFormQueryKey,
  screeningFormVersionsQueryKey,
  type ScreeningFormState,
} from "@/lib/api/screeningForm";
import { candidateContactQueryKeys } from "@/lib/candidate-contact";
import { isClientCvFilename } from "@/lib/candidate-files";
import { stageBrandedQueryKey } from "@/lib/cv-to-client";
import { jobHeaderFacts } from "@/lib/job-header-facts";
import {
  jobProposalsKeys,
  type ProposalFacts,
  type ProposalHistory,
  type ProposalInboxItem,
} from "@/lib/job-proposals-api";
import type { CriticalResolution } from "@/lib/critical-skills";
import { candidatesListFiltersForQuery, jobListFilters } from "@/lib/job-search-filters";
import type { MatchBreakdown } from "@/lib/match-breakdown";
import { requirementLabels, type MatchingRequirements } from "@/lib/matching-requirements";
import {
  similarJobsKey,
  similarPeopleWithRestKey,
  similarPersonScoreKey,
  type SentPerson,
  type SimilarJobItem,
} from "@/lib/similar-jobs-api";
import {
  ADDED_BY_ALL,
  addedByOptions,
  peopleInProgress,
  type AddedByFilter,
} from "@/lib/board-added-by";
import { AddedByFilterButton } from "@/components/v2/jobs/AddedByFilter";
import { useAuthStore } from "@/store/auth";

import {
  currentJobNotes,
  NO_NOTES,
  pairMoves,
  RICH_HISTORY_OUTCOMES,
  richHistoryNotes,
} from "@/app/preview/person-history-fixtures";

const JOB_ID = 4344;
const HOUR = 3_600_000;
const DAY = 24 * HOUR;

/**
 * „W bazie od” (13.10.2026): Anna z Traffita od 2019, Jan z importu bez daty
 * u źródła („przed 16.04.2026”), Piotr i Marek świeżo w bazie (pigułka „Nowy
 * w bazie”), reszta sprzed pół roku. Anna i Jan bez pigułki — ich panel mierzy
 * test wysokości doku. Dane fikcyjne.
 */
function previewInBase(candidateId: number) {
  const ago = (days: number) => new Date(Date.now() - days * DAY).toISOString();
  const marta = { id: 7, name: "Marta Nowak" };
  switch (candidateId) {
    case 9101:
      return { added_to_base_at: "2019-05-11T22:00:00Z", added_to_base_exact: true, added_via: "Traffit · Aktywny Search", created_by_user: null };
    case 9102:
      return { added_to_base_at: "2026-04-16T10:00:00Z", added_to_base_exact: false, added_via: "Traffit", created_by_user: null };
    case 9104:
      return { added_to_base_at: ago(3), added_to_base_exact: true, added_via: "CV upload", created_by_user: marta };
    case 9105:
      return { added_to_base_at: ago(10), added_to_base_exact: true, added_via: "E-mail", created_by_user: marta };
    default:
      return { added_to_base_at: ago(200), added_to_base_exact: true, added_via: "CV upload", created_by_user: marta };
  }
}

function previewInBaseCard(candidateId: number): Partial<KanbanItem> {
  const inBase = previewInBase(candidateId);
  return {
    candidate_added_at: inBase.added_to_base_at,
    candidate_added_exact: inBase.added_to_base_exact,
    candidate_added_by_name: inBase.created_by_user?.name ?? null,
  };
}
// Wymaganie wpisane zdaniem — po nim nie szukamy (pokazuje to zakładka „Szukaj w bazie”).
const PROSE_MUST = "Minimum 5 lat doświadczenia w projektach dla sektora finansowego";

const CHAMPION_PROFILE = {
  search: {
    requirements: [["Angular"], ["TypeScript"], ["RxJS", "NgRx"], ["bankow*", "banking"]],
    exclude: ["junior"],
  },
};

/** Krytyczne liczone przez serwer (`critical_resolution`, 06.10.2026). */
const CRITICAL_RESOLUTION: CriticalResolution = {
  stored: ["Angular"],
  decided: true,
  effective: ["Angular"],
  source: "dl",
  suggested: ["Angular"],
  search_rows: [["Angular", "AngularJS"]],
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

/** Obsada rekrutacji w nagłówku (`?team=`) — wyłącznie fikcyjne osoby. */
const HARNESS_TEAM: Record<string, JobRecruiter[]> = {
  others: [
    { user_id: 12, name: "Ewa Testowa", via: "owner", proposed: false, assigned_by_name: "Olga Wzorcowa" },
    { user_id: 13, name: "Piotr Makietowy", via: "collaborator", proposed: false, assigned_by_name: null },
  ],
  me: [
    { user_id: 7, name: "Marta Nowak", via: "owner", proposed: false, assigned_by_name: "Olga Wzorcowa" },
    { user_id: 13, name: "Piotr Makietowy", via: "collaborator", proposed: false, assigned_by_name: null },
  ],
  none: [],
  proposal: [
    { user_id: 14, name: "Jan Próbny", via: "assignment", proposed: true, assigned_by_name: null },
  ],
};

const LONG_CLIENT_NAME = "Powszechna Kasa Przykładowa Bank Polski Spółka Akcyjna";

const REQUIREMENTS: MatchingRequirements = {
  version: 1,
  reviewed: true,
  missing_evidence_policy: "review",
  all_of: [
    { any_of: ["angular"], level: "must", source: "manual", evidence: "" },
    { any_of: ["typescript"], level: "must", source: "manual", evidence: "" },
  ],
};

/** Znacznik „Pracuje u nas” u innego klienta niż klient tej rekrutacji. */
function PREVIEW_EMPLOYED(phase: "working" | "ending", orderEnd: string | null) {
  return {
    phase,
    source: "contract",
    elsewhere: true,
    clients: [
      {
        client_id: 31,
        client_name: "Bank Przykładowy",
        contract_id: 77,
        phase,
        order_end_date: orderEnd,
        delivery_lead_name: "Olga Wzorcowa",
      },
    ],
    // Termin z umowy (15.10.2026) — jak liczy serwer: dzień po końcu pracy.
    free_from: orderEnd
      ? new Date(Date.parse(`${orderEnd}T00:00:00Z`) + 86_400_000).toISOString().slice(0, 10)
      : null,
    free_from_basis: orderEnd ? "work_end" : "no_end_date",
  };
}

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
    added_to_job_by_id: 7,
    process_state_version: 1,
    entry_source: "added_manual",
    claim_user_id: 7,
    claim_user_name: "Marta Nowak",
    claim_until: new Date(Date.now() + 11 * HOUR).toISOString(),
    ...previewInBaseCard(9100 + id),
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

/**
 * `?autofill=1` (23.10.2026): dwie osoby od silnika „Nowi na 20” na końcu
 * „Nowych” — jedna czeka 3 dni na decyzję, druga dodana dziś. Bez parametru
 * Tablica zostaje taka jak dotąd (pomiary wysokości doku).
 */
function autofillCards(): KanbanItem[] {
  if (typeof window === "undefined") return [];
  if (new URLSearchParams(window.location.search).get("autofill") !== "1") return [];
  const system = {
    entry_source: "system" as const,
    added_to_job_by_id: null,
    added_to_job_by_name: null,
    claim_user_id: null,
    claim_user_name: null,
    claim_until: null,
    can_take: true,
  };
  return [
    card("Ewa", "Systemowa", {
      ...system,
      entry_autofill: {
        score: 81,
        matched_must: ["Java", "Spring Boot", "Kafka"],
        missing_must: ["AWS"],
        rate_known: false,
        availability_known: false,
        decided: false,
        waiting_days: 3,
        decision_due: true,
      },
    }),
    card("Karol", "Dobrany", {
      ...system,
      entry_autofill: {
        score: 63,
        matched_must: ["Java"],
        missing_must: ["Kafka", "AWS"],
        rate_known: true,
        availability_known: true,
        decided: false,
        waiting_days: 0,
        decision_due: false,
        // 27.10.2026: ostrzeżenia — osoba za resztą, karta mówi dlaczego.
        cautions: [
          { key: "budget", label: "+12% budżetu", title: "„Stawka od” 106 zł/h, budżet 95 zł/h." },
          {
            key: "office_days",
            label: "Biuro: 1 z 2 dni",
            title: "Według profilu przyjmie 1 dzień w biurze w tygodniu, klient chce 2 dni.",
          },
        ],
      },
    }),
  ];
}

function columns(): KanbanColumn[] {
  nextId = 1;
  return [
    col("new", "Nowi / Analiza CV", 21, [
      ...autofillCards(),
      // „+1 rekrutacja” (14.10.2026): czeka też w Nowych innej rekrutacji.
      card("Anna", "Przykładowa", {
        other_open_jobs: [
          { job_id: 4411, title: "Angular Developer", client_name: "Ubezpieczenia Demo", column: "new" },
        ],
      }),
      // Filtr „Kto dodał” (14.10.2026): część osób dodali inni, jedna bez danych.
      card("Jan", "Testowy", { added_to_job_by_id: 12, added_to_job_by_name: "Piotr Szkicowy" }),
      // Osoby, które u nas pracują (12.10.2026): znacznik na karcie, pigułka
      // w panelu osoby, ostrzeżenie pary z serwera. Poza dwiema osobami,
      // których panel mierzy test wysokości doku.
      card("Ewa", "Fikcyjna", {
        warnings: ["client_nda"],
        employment_marker: PREVIEW_EMPLOYED("working", "2026-12-31"),
      } as never),
      card("Piotr", "Próbny", {
        employment_marker: PREVIEW_EMPLOYED("ending", "2026-10-30"),
        added_to_job_by_id: 13,
        added_to_job_by_name: "Anna Kowal",
      } as never),
    ]),
    col("screening", "Screening", 22, [
      card("Marek", "Przykładowy", {
        entry_source: "proposal",
        added_to_job_by_id: 12,
        added_to_job_by_name: "Piotr Szkicowy",
        // 0506: umowa przedwstępna wysłana, kandydat jeszcze nie odesłał.
        pre_contract: {
          id: 501,
          state: "sent",
          label: "Przedwstępna wysłana · czeka 2 dni",
          tone: "wait",
          detail: "Wysłana kandydatowi.",
        },
      }),
    ]),
    col("verified", "Zweryfikowany", 23, []),
    col("interview", "Przepuszczony przez DZ", 24, []),
    col("cv_sent", "CV Wysłane", 25, []),
    // 04.10.2026: umowa wygenerowana po rozmowie u klienta (karta niesie
    // `agreement`) i osoba na „Umowie” bez umowy — panel „Umowa”.
    col("client_interview", "Rozmowa z klientem", 26, [
      card("Karol", "Wzorcowy", {
        claim_until: null,
        agreement: PREVIEW_AGREEMENT,
        added_to_job_by_id: null,
        added_to_job_by_name: null,
      } as never),
      // 0418: kandydat po rozmowie u klienta chce wyższej stawki.
      card("Bartek", "Testowy", {
        candidate_id: RATE_CASE_CANDIDATE_ID,
        claim_until: null,
        // 20.10.2026: od „Zweryfikowanego” karta pokazuje weryfikującą osobę.
        verified_by_id: 14,
        verified_by_name: "Olga Weryfikująca",
        verified_at: "2026-10-20T09:00:00Z",
        expected_rate_value: 125,
        expected_rate_unit: "hourly",
        expected_rate_currency: "PLN",
        rate_change: {
          id: 3,
          status: "requested",
          requires_decision: true,
          previous_hourly: 110,
          requested_hourly: 125,
          requested_label: "125 zł/h",
          agreed_hourly: null,
          negotiator_name: null,
          negotiation_due: null,
          created_at: null,
        },
      } as never),
    ]),
    // Iza ma trwającą umowę u innego klienta — ruch na „Zatrudniony” pyta
    // „Co z obecną współpracą?”. 16.10.2026 (D1–D6): etapy jak w szablonie
    // produkcyjnym — „Akceptacja”, „Umowa wysłana” i „Umowa podpisana” składają
    // się w kolumnę „Akceptacja i umowa”; Iza ma zapisaną akceptację klienta.
    col(
      "acceptance",
      "Akceptacja",
      27,
      [
        card("Iza", "Umowna", {
          claim_until: null,
          employment_marker: PREVIEW_EMPLOYED("working", null),
          client_acceptance: {
            stage_id: 9900,
            accepted_on: previewDay(-1),
            planned_start_on: previewDay(14),
            marked_at: new Date(Date.now() - DAY).toISOString(),
            marked_by_name: "Olga Wzorcowa",
          },
        } as never),
      ],
      "external",
    ),
    col("new", "Umowa wysłana", 31, [], "external"),
    col("new", "Umowa podpisana", 32, [], "external"),
    col("hired", "Zatrudniony", 28, []),
    // Powód zamknięcia na karcie i w panelu osoby (19.10.2026): z powodem
    // i komentarzem, bez powodu (Traffit) i rezygnacja.
    col(
      "rejected",
      "Odrzucony",
      29,
      [
        card("Zofia", "Szkicowa", {
          claim_until: null,
          moved_at: new Date(Date.now() - 2 * DAY).toISOString(),
          rejection_reason_name: "Za wysokie oczekiwania finansowe",
          closed_by_name: "Marta Nowak",
          notes: "Oczekuje 190 zł/h na B2B, budżet rekrutacji do 150. Wrócić przy innej rekrutacji C++.",
        } as never),
        card("Teodor", "Archiwalny", {
          claim_until: null,
          days_in_stage: 120,
          rejection_reason_name: "Powód nieznany (import z Traffita)",
        } as never),
      ],
      "terminal",
      "rejected",
    ),
    col(
      "withdrawn",
      "Wycofany",
      30,
      [
        card("Ewa", "Zajęta", {
          claim_until: null,
          moved_at: new Date(Date.now() - DAY).toISOString(),
          rejection_reason_name: "Przyjął inną ofertę",
          closed_by_name: "Marta Nowak",
          notes: "Dostała ofertę w innym banku, start od listopada.",
        } as never),
      ],
      "terminal",
      "withdrawn",
    ),
  ];
}

const RATE_CASE_CANDIDATE_ID = 9300;
const previewRate = (n: number) => ({
  amount: String(n),
  unit: "hourly",
  currency: "PLN",
  hourly: String(n),
  label: `${n} zł/h`,
});
const PREVIEW_RATE_CHANGES = {
  candidate_id: RATE_CASE_CANDIDATE_ID,
  job_id: JOB_ID,
  current: previewRate(125),
  board_column: "client_interview",
  notifies: true,
  cv_at_client: true,
  client_rate: previewRate(150),
  can_manage: true,
  can_decide: true,
  negotiator_options: [
    { id: 7, name: "Marta Nowak", role_label: "Delivery Lead" },
    { id: 8, name: "Olaf Przykładowy", role_label: "Head of Recruitment" },
  ],
  changes: [
    {
      id: 3,
      status: "requested",
      requires_decision: true,
      board_column: "client_interview",
      previous: previewRate(110),
      requested: previewRate(125),
      agreed: null,
      source: "debrief",
      source_label: "Debrief po rozmowie",
      reason: "conversation",
      reason_label: "Rozmowa z kandydatem",
      note: "ma drugą ofertę, decyzja do piątku",
      negotiable: "maybe",
      created_at: new Date().toISOString(),
      created_by_name: "Sandra Testowa",
      negotiator_id: null,
      negotiator_name: null,
      negotiation_target_hourly: null,
      negotiation_due: null,
      outcome: null,
      outcome_note: null,
      decision: null,
      decided_at: null,
      decided_by_name: null,
      can_record_outcome: true,
    },
  ],
};

const PREVIEW_AGREEMENT = {
  id: 7001,
  number: "1601/2026",
  contract_status: "in_progress",
  signature_status: "unsigned",
  created_at: new Date(Date.now() - 3 * 24 * HOUR).toISOString(),
  signed_at: null,
  signature_requested_at: null,
  contract_id: null,
  // 21.10.2026 (etap 1b): umowa wysłana do podpisu w NEXUSIE.
  esign: {
    status: "sent",
    expires_at: new Date(Date.now() + 11 * 24 * HOUR).toISOString(),
    contractor_signed_at: null,
  },
};

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
  /** Znani zespołowi (07.10.2026): punkty tylko do kolejności i ich powód. */
  history?: ProposalHistory;
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
    // D3 (19.10.2026): plakietka stawki przy budżecie 95 — +25% ponad budżet.
    facts: { title: "Frontend Developer", years_experience: 6, city: "Gdańsk", expected_rate_hourly: 119, max_onsite_days_per_week: 0 },
    score: 79,
    breakdown: measured(79, ["Angular", "TypeScript"]),
  },
  {
    id: 513,
    first: "Agata",
    last: "Szablonowa",
    // +7% ponad budżet (ton ostrzeżenia).
    facts: { title: "Angular Developer", years_experience: 5, city: "Poznań", expected_rate_hourly: 102, cv_uploaded_on: "2022-03-14" },
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
    // Równo górna granica budżetu — „w budżecie”.
    facts: { title: "Fullstack Developer", years_experience: 8, city: "Wrocław", expected_rate_hourly: 95 },
    score: 72,
    breakdown: measured(72, ["TypeScript"], ["Angular"]),
    // 72 + 6 punktów historii = wyżej niż Agata (76), procent zostaje 72.
    history: {
      points: 6,
      similar: [
        { job_id: 9001, title: "Frontend Developer (Angular)", reference_number: "ZOB-2614", client_name: "Bank Przykładowy", stage: "cv_sent", at: "2026-07-14T10:00:00Z" },
      ],
      recent: null,
    },
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
    // D3: +7% ponad budżet 95 (osoba „dodana w tym oknie” — plakietka zostaje).
    facts: { title: "Frontend Engineer", years_experience: 6, city: "Katowice", expected_rate_hourly: 102 },
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
  {
    id: 524,
    first: "Wiktor",
    last: "Atrapowy",
    // D3: +25% ponad budżet — ton „destructive-muted”.
    facts: { title: "Senior Frontend Developer", years_experience: 12, city: "Warszawa", expected_rate_hourly: 119 },
    score: 75,
    breakdown: measured(75, ["Angular", "TypeScript"]),
  },
];

const SIMILAR_PEOPLE: PersonSeed[] = [
  { id: 531, first: "Paweł", last: "Makietowy", facts: { title: "Angular Developer", years_experience: 7, city: "Warszawa", expected_rate_hourly: 93 }, score: 86, breakdown: measured(86, ["Angular", "TypeScript"]) },
  { id: 532, first: "Julia", last: "Wzorcowa", facts: { title: "Frontend Developer", years_experience: 5, city: "Gdynia" }, score: 78, breakdown: measured(78, ["Angular"], ["TypeScript"]) },
  { id: 533, first: "Robert", last: "Demo", facts: { title: "Programista Frontend", years_experience: 10, city: "Kraków", expected_rate_hourly: 105 }, score: 81, breakdown: measured(81, ["Angular", "TypeScript"]) },
  { id: 534, first: "Lena", last: "Szkicowa", facts: { title: "Junior Frontend Developer", years_experience: 2, city: "Łódź" }, score: 55, breakdown: measured(55, ["TypeScript"], ["Angular"]) },
];

/** „Szukaj ręcznie” (zakładka okna, 14.10.2026): wyniki pełnej wyszukiwarki. */
const MANUAL: PersonSeed[] = [
  ...SEARCH,
  { id: 541, first: "Zofia", last: "Próbkowa", facts: { title: "Frontend Developer", years_experience: 4, city: "Szczecin", expected_rate_hourly: 78 }, score: 66, breakdown: measured(66, ["Angular"], ["TypeScript"]) },
  { id: 542, first: "Michał", last: "Atrapowy", facts: { title: "Senior Angular Developer", years_experience: 11, city: "Warszawa", expected_rate_hourly: 120 }, score: 80, breakdown: measured(80, ["Angular", "TypeScript"]) },
];

/** Osoby „dodane w tym oknie” — wiersz „Dodano do „Nowych” · rezerwacja 12 h · Cofnij”. */
const ADDED_IN_WINDOW: readonly number[] = [BASE[1].id, SEARCH[1].id];

/** „Pasuje też do” (14.10.2026) — fikcyjne rekrutacje dla osób dodanych w oknie. */
const ALSO_FITS_JOBS: Record<number, unknown[]> = {
  [BASE[1].id]: [
    {
      job_id: 4411,
      title: "Angular Developer",
      client_name: "Ubezpieczenia Demo",
      score: 84,
      matching_must: ["Angular", "RxJS", "TypeScript"],
      gap_must: [],
    },
    {
      job_id: 4412,
      title: "Frontend Lead (Angular)",
      client_name: "Logistyka Demo",
      score: 72,
      matching_must: ["Angular"],
      gap_must: ["Prowadzenie zespołu"],
    },
  ],
  [SEARCH[1].id]: [],
};

/** Dopasowanie każdej fikcyjnej osoby — odpowiedź lokalna na `/scores`. */
const SCORE_SEEDS = new Map(
  [...POSTINGS, ...BASE, ...SEARCH, ...SIMILAR_PEOPLE, ...MANUAL].map((p) => [p.id, p] as const),
);

function fakeMatchScores(candidateIds: readonly number[]) {
  const scores: Record<string, number> = {};
  const breakdowns: Record<string, MatchBreakdown> = {};
  for (const id of candidateIds) {
    const seed = SCORE_SEEDS.get(id);
    if (!seed) continue;
    if (seed.score !== null) scores[String(id)] = seed.score;
    breakdowns[String(id)] = seed.breakdown;
  }
  return { scores, breakdowns, profile_key: "preview" };
}

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
    history: seed.history ?? null,
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

// ── Panel osoby: dane każdej karty Tablicy (fikcyjne) ───────────────────
// Bez nich panel otwarty z karty pokazywał „Nie udało się wczytać…” w pięciu
// miejscach — sieć harnessu jest wyłączona, więc każdy odczyt musi być zasiany.

const SCREENING_QUESTIONS = [
  {
    id: "q1",
    question: "Opisz ostatnią aplikację w Angularze, którą rozwijałeś — co napisałeś sam?",
    ideal_answer: "Konkretny projekt, własne moduły, testy.",
    deal_breaker: "Wyłącznie utrzymanie gotowej aplikacji.",
  },
  {
    id: "q2",
    question: "Od kiedy możesz zacząć?",
    ideal_answer: "Najpóźniej za miesiąc.",
    deal_breaker: "Okres wypowiedzenia dłuższy niż 2 miesiące.",
  },
];

const PANEL_PROFILE = {
  ...CHAMPION_PROFILE,
  basics: { role_name: "Programista Frontend", rate_value: 95, work_mode: "hybrydowo", onsite_days_per_week: 2 },
  stack: { must: [{ name: "Angular" }, { name: "TypeScript" }], nice: [{ name: "RxJS" }], notes: "" },
  screening_questions: SCREENING_QUESTIONS,
};

const CARD_LABELS: Record<string, string> = {
  rate: "Stawka",
  availability: "Dostępność",
  work_mode: "Tryb pracy",
  location: "Lokalizacja",
  nationality: "Narodowość",
  worked_at_client: "Czy pracował u Klienta",
  english: "Angielski",
  red_flags: "Red flags",
  recommendation: "Dlaczego ten kandydat",
  motivation: "Motywacja",
};

const PANEL_BRIEF: PlainBrief = {
  job_id: JOB_ID,
  status: "ready",
  stale: false,
  is_open: true,
  can_refresh: false,
  can_change_role: false,
  generated_at: new Date(Date.now() - 24 * HOUR).toISOString(),
  message: null,
  one_liner:
    "Szukamy programisty, który rozwija bankowość internetową Banku Przykładowego — ekrany, które klient widzi po zalogowaniu.",
  example: "Gdy klient robi przelew w przeglądarce, ta osoba pisze formularz i to, co dzieje się po kliknięciu „Wyślij”.",
  day_to_day: ["Dopisuje nowe ekrany.", "Poprawia błędy zgłoszone przez testerów."],
  pitch: "Stabilny projekt, dwa dni w biurze w tygodniu, do 95 zł/h netto B2B.",
  candidate_qa: [],
  screening_plain: [],
  glossary: [],
  role: null,
  client: null,
};

/**
 * Ramka „Następny etap” odświeża wymagania sama (zmiana odznaki rozmowy,
 * zamknięcie okna akcji), więc zasiany cache nie wystarcza — harness odpowiada
 * na to jedno zapytanie lokalnie, bez sieci.
 */
const MOVE_REQUIREMENTS_URL = "/api/pipeline/move-requirements";
/** Okno „Klient zaakceptował” (16.10.2026): kto dostanie dzwonek — fikcyjne osoby. */
const CLIENT_ACCEPTANCE_RECIPIENTS_URL = "/api/pipeline/client-acceptance/recipients";
const CLIENT_ACCEPTANCE_RECIPIENTS = {
  recipients: [
    { user_id: 7, name: "Marta Nowak", role: "recruiter", role_label: "rekruter kandydata" },
    { user_id: 12, name: "Ewa Testowa", role: "owner", role_label: "prowadzi rekrutację" },
    { user_id: 8, name: "Olaf Przykładowy", role: "head_of_recruitment", role_label: "Head of Recruitment" },
  ],
};
/** Dzień kalendarza firmy przesunięty o `offset` dni (RRRR-MM-DD). */
function previewDay(offset: number): string {
  return warsawToday(new Date(Date.now() + offset * DAY));
}
const MOVE_REQUIREMENTS: MoveRequirementsResponse = {
  from_column: null,
  to_column: null,
  skipped_columns: [],
  items: [],
  primary: { kind: "move", label: "Przesuń dalej" },
};

/** Osoba, na której harness pokazuje „Wcześniej u nas” (pierwsza karta „Nowych”). */
const RICH_HISTORY_CANDIDATE_ID = 9101;
/** Osoba z notatką tylko w tej rekrutacji — zakładka bez historii. */
const CURRENT_JOB_NOTES_CANDIDATE_ID = 9102;
/** Ten sam zakres widza co konto ustawiane w `useEffect` strony. */
const PREVIEW_VIEWER_SCOPE = candidateViewerScopeKey({ id: 7, role: "recruiter", roles: ["recruiter"] }) ?? "";

function seedCardPanel(qc: QueryClient, item: KanbanItem, columnName: string): void {
  const candidateId = item.candidate_id;
  // 12.10.2026: para z czasów Traffita — „Karol” nie ma stawek na etapie,
  // leżą w karcie rekomendacji i w notatce Delivery Leada z dnia wysyłki.
  const fromNotes = item.name === "Karol";
  seedFresh(qc, recruitmentRateHintsQueryKey(candidateId, JOB_ID), {
    candidate_id: candidateId,
    job_id: JOB_ID,
    expected_rate_hint: fromNotes
      ? {
          amount_hourly: 90,
          raw: "90 zł/h",
          at: new Date(Date.now() - 21 * 24 * HOUR).toISOString(),
          source: "card",
          author_name: "Marta Nowak",
        }
      : null,
    client_rate_note: fromNotes
      ? {
          note_id: 9001,
          text: "Wysłany 150/100-110, dostępny od zaraz",
          at: new Date(Date.now() - 20 * 24 * HOUR).toISOString(),
          author_name: "Piotr Zieliński",
        }
      : null,
  });
  // Notatki osoby (ta rekrutacja + „Wcześniej u nas”), wyniki rekrutacji i ruchy pary.
  seedFresh(
    qc,
    candidateQueryKeys.notes(candidateId),
    candidateId === RICH_HISTORY_CANDIDATE_ID
      ? richHistoryNotes(candidateId)
      : candidateId === CURRENT_JOB_NOTES_CANDIDATE_ID
        ? currentJobNotes(candidateId, JOB_ID, "Starszy Programista Frontend (Angular)")
        : NO_NOTES,
  );
  seedFresh(
    qc,
    candidateQueryKeys.recruitmentOutcomes(candidateId, PREVIEW_VIEWER_SCOPE),
    candidateId === RICH_HISTORY_CANDIDATE_ID ? RICH_HISTORY_OUTCOMES : [],
  );
  seedFresh(qc, [...pairMovesQueryKey(JOB_ID, candidateId), item.id], pairMoves(candidateId, item.id, columnName));
  seedFresh(qc, ["cv-share-tokens-recruitment", candidateId, JOB_ID], {
    items: [],
    branded_cv: { status: "none", stage_id: null, stage_name: null, finalized_at: null },
  });
  const fullName = { name: item.name, lastname: item.lastname };
  const formState: ScreeningFormState = {
    candidate_id: candidateId,
    job_id: JOB_ID,
    version: 0,
    versions_count: 0,
    state_token: `podglad-${item.id}`,
    editable: true,
    read_only_reason: null,
    read_only_message: null,
    stage_id: item.id,
    board_column: item.stage,
    process_state_version: 1,
    claim: null,
    champion_profile: PANEL_PROFILE,
    sheet: null,
    sheet_source_stage_id: null,
    legacy_notes: null,
    note_answers: [],
    // Pytania scalone jak na serwerze — sekcja „Screening” doku (09.10.2026).
    questions: SCREENING_QUESTIONS.map((question, index) => ({
      number: index + 1,
      question: question.question,
      answer: "",
      source: null,
      question_id: question.id,
      deal_breaker: question.deal_breaker || null,
      deal_breaker_hit: false,
    })),
    card: {
      fields: {},
      previous: {},
      suggestions: {},
      completeness: { status: "empty", filled: 0, total: 10, missing: Object.keys(CARD_LABELS) },
      labels: CARD_LABELS,
      editable_fields: Object.keys(CARD_LABELS),
    },
    rate: null,
    rate_hints: { card: null, rate_from: null },
    rate_change_notifies: false,
    can_edit_rate: true,
    suggestions_from_notes: {},
    assist_enabled: false,
    phrase_language: "pl",
  } as unknown as ScreeningFormState;
  seedFresh(qc, screeningFormQueryKey(JOB_ID, candidateId), formState);
  seedFresh(qc, screeningFormVersionsQueryKey(JOB_ID, candidateId), { items: [], total: 0 });
  seedFresh(qc, reassignContextQueryKey(item.id), {
    stage_id: item.id,
    available: false,
    source: null,
    previous_answers_count: 0,
  });
  seedFresh(qc, ["pipeline-stage-screening", item.id], {
    stage_id: item.id,
    candidate_id: candidateId,
    job_id: JOB_ID,
    champion_profile: PANEL_PROFILE,
    screening_answers: null,
  });
  seedFresh(qc, candidateQueryKeys.detail(candidateId), {
    id: candidateId,
    ...fullName,
    status: "active",
    city: "Warszawa",
    // Dane fikcyjne — linia kontaktu pod nazwiskiem w panelu osoby.
    phone: "+48 600 100 200",
    email: `kandydat${candidateId}@example.com`,
    linkedin_current_title: "Frontend Developer",
    linkedin_current_company: "Firma Przykładowa",
    // Warunki, które pokazuje profil przed telefonem i fakty doku.
    availability_date: null,
    availability_status: "open_to_offers",
    notice_period: 1,
    notice_period_unit: "months",
    max_onsite_days_per_week: 2,
    ...previewInBase(candidateId),
  });
  seedFresh(qc, candidateQueryKeys.rateOverview(candidateId), {
    candidate_id: candidateId,
    enabled: true,
    window_start: "2025-04-12",
    rate_from: null,
    latest_amount: candidateId === RICH_HISTORY_CANDIDATE_ID ? 130 : null,
    latest_at: candidateId === RICH_HISTORY_CANDIDATE_ID ? "2025-03-14T15:20:00Z" : null,
    count: candidateId === RICH_HISTORY_CANDIDATE_ID ? 2 : 0,
    observations: [],
    paid: [],
  });
  const quickView = {
    candidate: { id: candidateId, ...fullName, city: "Warszawa", location: "Warszawa" },
    current_position: { title: "Frontend Developer", started_at: "2023-03-01", precision: "month" },
    availability: { status: "open_to_offers", available_from: null, notice_period: 1, notice_period_unit: "months" },
    current_recruitments: [],
    recent_notes: [],
    contact_attempts: 0,
    cv_highlights: { years_experience: 6 },
    capabilities: { can_assign: true, can_view_documents: true, can_open_full_profile: true },
  };
  seedFresh(qc, candidateQueryKeys.quickView(candidateId), quickView);
  // „Co już wiemy” w panelu pyta o inne rekrutacje osoby — bez bieżącej (14.10.2026).
  seedFresh(qc, candidateQueryKeys.quickViewExcluding(candidateId, JOB_ID), { ...quickView, current_recruitments_total: 0 });
  seedFresh(qc, pinnedNotesQueryKey(candidateId), { items: [] });
  seedFresh(qc, candidateQueryKeys.cvDocuments(candidateId), []);
  seedFresh(qc, ["cv-original", item.id], {
    candidate_stage_id: item.id,
    candidate_id: candidateId,
    job_id: JOB_ID,
    has_snapshot: false,
    original_cv_filename: null,
    original_cv_language: null,
    original_snapshot_at: null,
    original_snapshot_source: null,
    download_url: null,
  });
  seedFresh(qc, stageBrandedQueryKey(item.id), {
    edit_revision: 0,
    version: 0,
    candidate_stage_id: item.id,
    status: "none",
    content_html: null,
    template: null,
    language: null,
    updated_at: null,
    updated_by: null,
    updated_by_name: null,
    finalized_at: null,
    finalized_by: null,
    finalized_by_name: null,
    snapshot_filename: null,
    rendered_from_default: false,
  });
  // D1–D3 (14.10.2026): „Karol” jest u klienta, a zatwierdzone CV firmowe leży
  // na wierszu etapu sprzed ruchu — dok pokazuje „Pobierz Word / PDF” tego CV.
  if (fromNotes) {
    const pairStageId = 9000 + item.id;
    seedFresh(qc, stageBrandedQueryKey(item.id), {
      edit_revision: 0,
      version: 0,
      candidate_stage_id: item.id,
      status: "none",
      pair_source_stage_id: pairStageId,
      pair_source_status: "finalized",
    });
    seedFresh(qc, stageBrandedQueryKey(pairStageId), {
      edit_revision: 3,
      version: 1,
      candidate_stage_id: pairStageId,
      status: "finalized",
      from_generator: true,
      content_html: "<p>CV</p>",
      updated_at: "2026-10-13T15:00:00Z",
      finalized_at: "2026-10-13T15:00:00Z",
      consent_missing: false,
    });
  }
}

function seededClient(championMode: HarnessChampionMode = "none"): QueryClient {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { staleTime: Infinity, retry: false, refetchOnMount: false, refetchOnWindowFocus: false },
    },
  });
  // Rejestr umów tej rekrutacji (sekcja „Umowa” panelu osoby).
  seedFresh(qc, ["b2b-generated", "job", JOB_ID], [
    {
      id: PREVIEW_AGREEMENT.id,
      contract_number: PREVIEW_AGREEMENT.number,
      candidate_id: 9100 + 6,
      job_id: JOB_ID,
      contract_status: "in_progress",
      signature_status: "unsigned",
      created_at: PREVIEW_AGREEMENT.created_at,
      created_by_name: "Marta Nowak",
      can_confirm_signed: false,
      can_edit: false, // wysłana do podpisu — „Popraw” po wycofaniu
      can_download: true,
      partner_name: "Karol Wzorcowy",
      client_name: "Bank Przykładowy",
      esign: {
        request_id: 31,
        status: "sent",
        contractor_signed_at: null,
        completed_at: null,
        expires_at: PREVIEW_AGREEMENT.esign.expires_at,
        company_signer_name: "Osoba Testowa",
      },
      can_withdraw_esign: true,
    },
  ]);
  // 0404: „Odrzuceni przez AI” — pusta lista.
  // 0418: otwarta sprawa zmiany stawki „Bartka” — baner w panelu osoby.
  seedFresh(qc, rateChangesQueryKey(RATE_CASE_CANDIDATE_ID, JOB_ID), PREVIEW_RATE_CHANGES);
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
    // Wariant A (13.10.2026): „Rekruter sprawdza w rozmowie” — fikcyjne pozycje.
    talk_checks: [
      { label: "bankowość detaliczna", kind: "domains" },
      { label: "ISTQB Foundation", kind: "certifications" },
      { label: "angielski B2", kind: "language" },
      { label: PROSE_MUST, kind: "must" },
    ],
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
  for (const column of columns()) column.items.forEach((item) => seedCardPanel(qc, item, column.name ?? ""));
  // Generator CV w panelu osoby: reguły klienta (tu bez reguł centralnych).
  seedFresh(qc, ["central-cv-policy", null, null, false], { managed: false, content_mode: "polished" });
  seedFresh(qc, ["job-questions", JOB_ID], []);
  seedFresh(qc, ["job-rejection-reasons", JOB_ID], []);
  seedFresh(qc, plainBriefQueryKey(JOB_ID), PANEL_BRIEF);
  seedFresh(qc, candidateContactQueryKeys.status(), {
    enabled: false,
    assignment_enabled: false,
    traffit_intake_enabled: false,
  });
  // Osoby do oznaczenia przez „@” w notatce doku osoby (fikcyjne).
  seedFresh(qc, ["mentionable-users", `job:${JOB_ID}`, false], [
    { id: 7, name: "Marta Nowak", email: "marta@example.com", role: "recruiter" },
    { id: 8, name: "Piotr Zieliński", email: "piotr@example.com", role: "delivery_lead" },
    { id: 9, name: "Łucja Żak", email: "lucja@example.com", role: "head_of_recruitment" },
    { id: 10, name: "Adam Wrona", email: "adam@example.com", role: "recruiter" },
  ]);
  seedFresh(qc, ["champion-profile", JOB_ID], {
    champion_profile: CHAMPION_PROFILE,
    critical_resolution: CRITICAL_RESOLUTION,
  });
  const filters = candidatesListFiltersForQuery(
    jobListFilters(JOB, requirementLabels(REQUIREMENTS, "must"), CRITICAL_RESOLUTION),
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
          // „Stawka od” — tę czyta plakietka stawki względem budżetu (D3).
          rate_from_hourly: p.facts.expected_rate_hourly ?? null,
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
  seedFresh(
    qc,
    ["job-search-base-scores", JOB_ID, SEARCH.map((p) => p.id).join(",")],
    fakeMatchScores(SEARCH.map((p) => p.id)),
  );

  // „Szukaj ręcznie” (zakładka okna): lista tym samym kluczem co wyszukiwarka
  // osadzona (`CandidatesListV2 embed`, strona 1 po 50) i jej stałe odczyty.
  seedFresh(qc, candidatesListQueryKey(candidatesListApiParams(filters, 1, 50)), {
    items: MANUAL.map((p) => ({
      id: p.id,
      name: p.first,
      lastname: p.last,
      status: "active",
      linkedin_current_title: p.facts.title ?? null,
      years_it_experience: p.facts.years_experience ?? null,
      city: p.facts.city ?? null,
      expected_rate_hourly: p.facts.expected_rate_hourly ?? null,
      skills: ["Angular", "TypeScript"],
    })),
    total: 57,
    page: 1,
    page_size: 50,
    text_mode_applied: "literal",
  });
  seedFresh(qc, CANDIDATES_BASE_TOTAL_QUERY_KEY, { items: [], total: 12481, page: 1, page_size: 1 });
  seedFresh(qc, ["saved-searches", "candidates"], []);
  seedFresh(qc, ["candidate-pins"], []);
  seedFresh(qc, ["competence-categories-active"], []);
  seedFresh(qc, cloudTalkStatusQueryKey, { enabled: false });
  seedFresh(qc, ["clients-lookup"], []);
  seedFresh(qc, ["users-directory"], []);

  for (const seed of [...POSTINGS, ...BASE, ...SEARCH, ...SIMILAR_PEOPLE]) seedPerson(qc, seed);

  // „Otwórz ponownie” (`?closed=1`, `?reopen=1`): braki bramki, lista
  // rekruterów i rekrutacja w cache'u — te same klucze co `JobReopenDialog`.
  seedFresh(qc, ["job", String(JOB_ID)], {
    ...JOB,
    status: "closed",
    primary_owner: null,
    client_id: REOPEN_CLIENT_ID,
    // Okno odrzucenia championa czyta championów z tego detalu (D7).
    ...harnessChampionJob(championMode, "p1"),
  });
  seedFresh(qc, jobChampionsQueryKey(JOB_ID), harnessChampionsView(championMode));
  // Hiring managera i termin ustawia się w oknie — lista kontaktów klienta.
  seedFresh(qc, ["hiring-manager-options", REOPEN_CLIENT_ID], [
    { id: 31, name: "Anna Przykładowa", position: "Kierowniczka zespołu" },
    { id: 32, name: "Jan Przykładowy", position: "Architekt" },
  ]);
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

// ── Championi (`?champion=`, 15.10.2026) — wyłącznie osoby z kart harnessu ──

type HarnessChampionMode = "none" | "two" | "seats" | "legacy";

function harnessChampionMode(raw: string | null): HarnessChampionMode {
  return raw === "two" || raw === "seats" || raw === "legacy" ? raw : "none";
}

/** Karty z `columns()`: Karol (6. karta), Bartek (sprawa stawki), Iza (umowa). */
const KAROL_ID = 9100 + 6;
const IZA_ID = 9100 + 8;
const HARNESS_CHAMPION_PEOPLE: Record<number, Omit<JobChampionEligible, "is_champion">> = {
  [IZA_ID]: { candidate_id: IZA_ID, name: "Iza Umowna", column: "contract", stage_label: "Umowa" },
  [RATE_CASE_CANDIDATE_ID]: {
    candidate_id: RATE_CASE_CANDIDATE_ID,
    name: "Bartek Testowy",
    column: "client_interview",
    stage_label: "Rozmowa z klientem",
  },
  [KAROL_ID]: {
    candidate_id: KAROL_ID,
    name: "Karol Wzorcowy",
    column: "client_interview",
    stage_label: "Rozmowa z klientem",
  },
};

const HARNESS_CHAMPION_IDS: Record<HarnessChampionMode, readonly number[]> = {
  none: [],
  two: [KAROL_ID, RATE_CASE_CANDIDATE_ID],
  seats: [KAROL_ID],
  legacy: [],
};

/** Championi zapisani w okienku tej karty przeglądarki (bez sieci). */
let harnessSavedChampionIds: readonly number[] | null = null;

function harnessChampionsView(mode: HarnessChampionMode): JobChampionsView {
  const ids = harnessSavedChampionIds ?? HARNESS_CHAMPION_IDS[mode];
  const seats = mode === "seats" ? 2 : 1;
  const legacy = mode === "legacy" && harnessSavedChampionIds == null;
  return {
    job_id: JOB_ID,
    can_edit: true,
    seats,
    hired_count: 0,
    search_stopped: legacy || ids.length >= seats,
    legacy_flag: legacy,
    work_state: "searching",
    champions: ids.map((id) => ({
      ...HARNESS_CHAMPION_PEOPLE[id],
      marked_by_name: "Olga Wzorcowa",
      marked_at: "2026-10-15T10:12:00Z",
    })),
    // Jak serwer: od najdalszej kolumny, w kolumnie alfabetycznie.
    eligible: [IZA_ID, RATE_CASE_CANDIDATE_ID, KAROL_ID].map((id) => ({
      ...HARNESS_CHAMPION_PEOPLE[id],
      is_champion: ids.includes(id),
    })),
  };
}

/** Pola championów w detalu rekrutacji (`GET /api/jobs/{id}`). */
function harnessChampionJob(mode: HarnessChampionMode, priority: string) {
  const ids = HARNESS_CHAMPION_IDS[mode];
  const seats = mode === "seats" ? 2 : 1;
  const stopped = mode === "legacy" || (ids.length > 0 && ids.length >= seats);
  return {
    request_status: stopped ? "champion" : "searching",
    champions: ids.map((id) => ({ candidate_id: id, name: HARNESS_CHAMPION_PEOPLE[id].name })),
    champion_seats: seats,
    headcount: seats,
    hired_count: 0,
    priority_paused: stopped && priority === "p1",
  };
}

/** Karty championów na Tablicy (`is_champion`). */
function withChampionCards(cols: KanbanColumn[], mode: HarnessChampionMode): KanbanColumn[] {
  const ids = HARNESS_CHAMPION_IDS[mode];
  if (ids.length === 0) return cols;
  return cols.map((column) => ({
    ...column,
    items: column.items.map((item) =>
      ids.includes(item.candidate_id) ? { ...item, is_champion: true } : item,
    ),
  }));
}

const REOPEN_CLIENT_ID = 11;
const REOPEN_BLOCKERS = [
  { code: "hiring_manager", message: "Wskaż hiring managera albo zaznacz „Klient nie podał”." },
  { code: "deadline", message: "Ustaw termin albo zaznacz „Klient nie podał”." },
];

const noop = () => undefined;

/** Pliki rekrutacji w oknie z menu „⋯” — nazwy fikcyjne, bez klienta i osób. */
const PREVIEW_FILES: JobFilesResponse = {
  can_edit: true,
  max_files: 20,
  max_file_bytes: 20 * 1024 * 1024,
  items: [
    {
      id: 9101,
      filename: "Zapytanie - Angular Developer.pdf",
      content_type: "application/pdf",
      size_bytes: 284_300,
      source: "request",
      uploaded_by: 1,
      uploaded_by_name: "Marta Testowa",
      created_at: new Date(Date.now() - 3 * 24 * HOUR).toISOString(),
    },
    {
      id: 9102,
      filename: "Opis projektu i zespołu.docx",
      content_type:
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      size_bytes: 61_200,
      source: "upload",
      uploaded_by: 1,
      uploaded_by_name: "Marta Testowa",
      created_at: new Date(Date.now() - 3 * 24 * HOUR).toISOString(),
    },
    {
      id: 9103,
      filename: "Widełki i warunki współpracy.xlsx",
      content_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      size_bytes: 18_900,
      source: "upload",
      uploaded_by: 2,
      uploaded_by_name: "Olaf Przykładowy",
      created_at: new Date(Date.now() - 1 * 24 * HOUR).toISOString(),
    },
  ],
};

// Fikcyjna odpowiedź `POST /api/jobs/{id}/close` bez potwierdzenia.
const CLOSE_WARNING = {
  code: "active_cards_warning",
  message:
    "W tej rekrutacji jest 5 osób w toku (ostatni ruch karty 12.10.2026). Zamknięcie nie zamyka kart — zostaną w zamkniętej rekrutacji.",
  active_cards: 5,
  columns: { new: 3, screening: 2 },
};

/** Kopie CV etapu po „Wgraj nowe CV” w tej karcie przeglądarki (bez sieci). */
const harnessStageCopies = new Map<number, Record<string, unknown>>();

/**
 * CV do klienta po wgraniu pliku „B2B_…docx” (15.10.2026) — `GET …/cv/branded`
 * czyta stąd, inaczej odświeżenie po wgraniu kończyłoby się „nie udało się
 * sprawdzić”. „Cofnij” zostawia stan „brak”, jak zasiew.
 */
const harnessClientCvs = new Map<number, Record<string, unknown>>();

function harnessClientCv(stageId: number, filename: string | null): Record<string, unknown> {
  const now = new Date().toISOString();
  const blank = {
    edit_revision: filename ? 1 : 2,
    version: filename ? 1 : 0,
    candidate_stage_id: stageId,
    template: null,
    language: filename ? "pl" : null,
    updated_at: filename ? now : null,
    updated_by: filename ? 7 : null,
    updated_by_name: filename ? "Marta Nowak" : null,
    finalized_at: null,
    finalized_by: null,
    finalized_by_name: null,
    snapshot_filename: null,
    rendered_from_default: false,
  };
  if (!filename) return { ...blank, status: "none", content_html: null };
  return {
    ...blank,
    status: "draft",
    source: "document",
    from_generator: false,
    generated_document_id: null,
    origin: { kind: "upload", label: filename, selected_at: now },
    docx_available: true,
    docx_filename: filename,
    consent_required: false,
    consent_attached: false,
    consent_missing: false,
    content_html: "<h1>Senior Java Developer</h1><p>CV wczytane z pliku Word — treść fikcyjna.</p>",
  };
}

function JobDetailHarness() {
  const params = useSearchParams();
  const railOnly = params.get("rail") === "1";
  const initialSources = params.get("sources");
  const reopenOnStart = params.get("reopen") === "1";
  const closed = reopenOnStart || params.get("closed") === "1";
  const [reopenOpen, setReopenOpen] = useState(reopenOnStart);
  const [filesOpen, setFilesOpen] = useState(params.get("files") === "1");
  const [closeOpen, setCloseOpen] = useState(params.get("close") === "1");
  const [changeOpen, setChangeOpen] = useState(params.get("change") === "1");
  const reasonParam = params.get("reason");
  const closeReason: JobCloseReason = JOB_CLOSE_REASONS.some((r) => r.value === reasonParam)
    ? (reasonParam as JobCloseReason)
    : "duplicate";
  const prioParam = params.get("prio");
  const priorityLevel = isPriorityLevel(prioParam) ? prioParam : "p1";
  const team = HARNESS_TEAM[params.get("team") ?? "others"] ?? HARNESS_TEAM.others;
  const readOnlyRole = params.get("readonly") === "1";
  const championMode = harnessChampionMode(params.get("champion"));
  const [championsOpen, setChampionsOpen] = useState(false);
  const [headerCollapsed, setHeaderCollapsed] = useState(params.get("collapsed") === "1");
  const headerJob = useMemo(
    () => ({
      ...JOB,
      ...harnessChampionJob(championMode, priorityLevel),
      client_name: params.get("client") === "long" ? LONG_CLIENT_NAME : JOB.client_name,
      priority_level: priorityLevel,
      recruiters: team,
      // Prowadzący jak z serwera — bez niego panel zespołu proponuje „Biorę”.
      primary_owner: (() => {
        const owner = team.find((person) => person.via === "owner");
        return owner
          ? { id: owner.user_id, name: owner.name, email: "owner@example.com", role: "recruiter" as const }
          : null;
      })(),
      delivery_lead_user: { name: "Olga Wzorcowa" },
      can_staff: !readOnlyRole,
      status: closed ? "closed" : "published",
    }),
    [params, priorityLevel, team, readOnlyRole, closed, championMode],
  );
  const [client] = useState(() => seededClient(championMode));
  const [sourceTab, setSourceTab] = useState<CandidateWindowTab | null>(
    CANDIDATE_WINDOW_TABS.includes(initialSources as CandidateWindowTab)
      ? (initialSources as CandidateWindowTab)
      : null,
  );
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const blocker = api.interceptors.request.use((config) => {
      // Dopasowanie liczone bez przycisku (14.10.2026) — odpowiedź z zasiewu.
      if (config.url === "/api/search/candidates/scores") {
        const ids = (config.data as { candidate_ids?: number[] } | undefined)?.candidate_ids ?? [];
        config.adapter = async () => ({
          data: fakeMatchScores(ids),
          status: 200,
          statusText: "OK",
          headers: {},
          config,
        });
        return config;
      }
      // 0506: sekcja „Umowa przedwstępna” w zakładce „Umowa” — bez prośby.
      if (config.url === "/api/pre-contracts/pair") {
        config.adapter = async () => ({
          data: { current: null, history: [], documents: [] },
          status: 200,
          statusText: "OK",
          headers: {},
          config,
        });
        return config;
      }
      if (config.url === CLIENT_ACCEPTANCE_RECIPIENTS_URL) {
        config.adapter = async () => ({
          data: CLIENT_ACCEPTANCE_RECIPIENTS,
          status: 200,
          statusText: "OK",
          headers: {},
          config,
        });
        return config;
      }
      // „Zapisz akceptację” — ruch na etap „Akceptacja” i werdykt „Akceptuje”
      // odpowiadają lokalnie (tylko ruch z datą akceptacji; reszta ruchów bez zmian).
      const acceptanceMove =
        config.url === "/api/pipeline/move" &&
        Boolean((config.data as { client_accepted_on?: string } | undefined)?.client_accepted_on);
      if (acceptanceMove || config.url === `/api/jobs/${JOB_ID}/hiring-manager-feedback`) {
        config.adapter = async () => ({ data: {}, status: 200, statusText: "OK", headers: {}, config });
        return config;
      }
      if (config.url === MOVE_REQUIREMENTS_URL) {
        config.adapter = async () => ({
          data: MOVE_REQUIREMENTS,
          status: 200,
          statusText: "OK",
          headers: {},
          config,
        });
        return config;
      }
      if (config.url === `/api/jobs/${JOB_ID}/close-reason`) {
        config.adapter = async () => ({ data: {}, status: 200, statusText: "OK", headers: {}, config });
        return config;
      }
      if (config.url === `/api/jobs/${JOB_ID}/close`) {
        // Adapter per żądanie: nic nie wychodzi do sieci, a okno dostaje
        // ostrzeżenie przy pierwszym zamknięciu i zgodę po potwierdzeniu.
        const acknowledged = Boolean(
          (config.data as { acknowledge_active_cards?: boolean } | undefined)
            ?.acknowledge_active_cards,
        );
        config.adapter = async () => {
          if (acknowledged) {
            return { data: {}, status: 200, statusText: "OK", headers: {}, config };
          }
          throw new AxiosError("HTTP 409", "ERR_BAD_REQUEST", config, null, {
            data: { detail: CLOSE_WARNING },
            status: 409,
            statusText: "Conflict",
            headers: {},
            config,
          });
        };
        return config;
      }
      // „Pasuje też do” (14.10.2026): podpowiedzi dla osób dodanych w oknie,
      // dodanie do innej rekrutacji i „Cofnij” — bez sieci.
      const alsoFits = config.url?.match(/^\/api\/candidates\/(\d+)\/also-fits$/);
      if (alsoFits) {
        const candidateId = Number(alsoFits[1]);
        config.adapter = async () => ({
          data: {
            candidate_id: candidateId,
            from_job_id: JOB_ID,
            status: "ok",
            jobs: ALSO_FITS_JOBS[candidateId] ?? [],
          },
          status: 200,
          statusText: "OK",
          headers: {},
          config,
        });
        return config;
      }
      const otherJobAdd = config.url?.match(/^\/api\/jobs\/(\d+)\/proposals\/bulk$/);
      if (otherJobAdd && Number(otherJobAdd[1]) !== JOB_ID) {
        const ids = (config.data as { candidate_ids?: number[] } | undefined)?.candidate_ids ?? [];
        config.adapter = async () => ({
          data: { added: ids, skipped: [], warnings: [], total_added: ids.length, total_skipped: 0 },
          status: 200,
          statusText: "OK",
          headers: {},
          config,
        });
        return config;
      }
      // „Szukaj ręcznie” → „Dodani teraz” (15.10.2026): dodanie do tej rekrutacji
      // i „Cofnij” w pamięci strony, żeby pasek z „Pasuje też do” dało się przeklikać.
      const manualAdd = config.data as { source?: string; candidate_ids?: number[] } | undefined;
      if (otherJobAdd && Number(otherJobAdd[1]) === JOB_ID && manualAdd?.source === "manual_search") {
        const ids = manualAdd.candidate_ids ?? [];
        config.adapter = async () => ({
          data: { added: ids, skipped: [], warnings: [], total_added: ids.length, total_skipped: 0 },
          status: 200,
          statusText: "OK",
          headers: {},
          config,
        });
        return config;
      }
      const otherJobUndo = config.url?.match(/^\/api\/candidates\/\d+\/recruitments\/(\d+)$/);
      if (otherJobUndo && config.method === "delete" && Number(otherJobUndo[1]) === JOB_ID && config.params?.quick_undo) {
        config.adapter = async () => ({ data: {}, status: 200, statusText: "OK", headers: {}, config });
        return config;
      }
      if (otherJobUndo && config.method === "delete" && Number(otherJobUndo[1]) !== JOB_ID) {
        config.adapter = async () => ({ data: {}, status: 200, statusText: "OK", headers: {}, config });
        return config;
      }
      // Championi (15.10.2026): lista i zapis w pamięci strony.
      if (config.url === `/api/jobs/${JOB_ID}/champions`) {
        if (config.method === "put") {
          const body =
            typeof config.data === "string" ? JSON.parse(config.data) : config.data;
          harnessSavedChampionIds = (body as { candidate_ids?: number[] }).candidate_ids ?? [];
        }
        const view = harnessChampionsView(championMode);
        config.adapter = async () => ({
          data: config.method === "put" ? { ...view, changed: true, work_state_changed: false } : view,
          status: 200,
          statusText: "OK",
          headers: {},
          config,
        });
        return config;
      }
      const clientCvRead = config.url?.match(/^\/api\/candidates\/stages\/(\d+)\/cv\/branded$/);
      const clientCvState = clientCvRead ? harnessClientCvs.get(Number(clientCvRead[1])) : undefined;
      if (clientCvState && config.method === "get") {
        config.adapter = async () => ({ data: clientCvState, status: 200, statusText: "OK", headers: {}, config });
        return config;
      }
      // „Wgraj nowe CV” i „Użyj w tej rekrutacji” (13.10.2026): kopia CV etapu
      // w pamięci strony, żeby po wgraniu panel pokazał nowy stan.
      const stageCv = config.url?.match(/^\/api\/candidates\/stages\/(\d+)\/cv\/original(\/upload|\/refresh)?$/);
      if (stageCv) {
        const stageId = Number(stageCv[1]);
        const form = config.data instanceof FormData ? config.data : null;
        const uploaded = form?.get("file");
        const uploadedName = uploaded instanceof File ? uploaded.name : null;
        // Plik „B2B_…docx” (15.10.2026) zostaje CV do klienta — oryginał bez zmian.
        if (
          stageCv[2] === "/upload" &&
          form?.get("mode") !== "original" &&
          uploadedName &&
          isClientCvFilename(uploadedName) &&
          uploadedName.toLowerCase().endsWith(".docx")
        ) {
          const clientCv = harnessClientCv(stageId, uploadedName);
          harnessClientCvs.set(stageId, clientCv);
          const result = {
            candidate_stage_id: stageId,
            candidate_id: 0,
            job_id: JOB_ID,
            has_snapshot: false,
            original_cv_filename: null,
            original_cv_language: null,
            original_snapshot_at: null,
            original_snapshot_source: null,
            download_url: null,
            ...harnessStageCopies.get(stageId),
            outcome: "client_cv",
            client_cv: clientCv,
            client_cv_stage_id: stageId,
            replaced: "none",
            undo_available: true,
            stored_in_profile: true,
            uploaded_filename: uploadedName,
          };
          config.adapter = async () => ({ data: result, status: 200, statusText: "OK", headers: {}, config });
          return config;
        }
        // „Cofnij”: plik wraca jako CV kandydata, CV do klienta do stanu sprzed wgrania.
        if (stageCv[2] === "/upload" && form?.get("mode") === "original" && harnessClientCvs.has(stageId)) {
          harnessClientCvs.set(stageId, harnessClientCv(stageId, null));
        }
        if (stageCv[2]) {
          const file = uploaded ?? null;
          harnessStageCopies.set(stageId, {
            candidate_stage_id: stageId,
            candidate_id: 0,
            job_id: JOB_ID,
            has_snapshot: true,
            original_cv_filename: file instanceof File ? file.name : "CV_z_profilu.pdf",
            original_cv_language: "pl",
            original_snapshot_at: new Date().toISOString(),
            original_snapshot_source: stageCv[2] === "/upload" ? "manual_upload" : "manual_refresh",
            download_url: null,
          });
        }
        const copy = harnessStageCopies.get(stageId);
        if (copy) {
          config.adapter = async () => ({ data: copy, status: 200, statusText: "OK", headers: {}, config });
          return config;
        }
      }
      return Promise.reject(new AxiosError("preview: sieć wyłączona", "ECONNABORTED", config));
    });
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
    setReady(true);
    return () => api.interceptors.request.eject(blocker);
  }, [championMode]);
  // Filtr „Kto dodał” (14.10.2026) — harness nie czyta adresu, trzyma go w stanie.
  const [addedBy, setAddedBy] = useState<AddedByFilter>(ADDED_BY_ALL);
  const addedByMenuOptions = useMemo(
    () => addedByOptions(peopleInProgress(columns()), { id: 7, name: "Marta Nowak" }),
    [],
  );
  if (!ready) return null;

  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <TooltipProvider>
          <div className="app-shell-root flex h-dvh overflow-hidden bg-background text-foreground">
            {/* Menu: 240 px od 1280 px (domyślne przypięcie), niżej szyna 60 px.
                Jak w `SidebarV2`: szyna jest `absolute z-40` z atrybutem
                `data-app-sidebar` — panel osoby na całą szerokość okna ma ją
                zakryć (reguła w `globals.css`), a harness to sprawdza. */}
            <div
              aria-hidden="true"
              className={
                railOnly
                  ? "relative hidden h-full w-[60px] shrink-0 md:block"
                  : "relative hidden h-full w-[60px] shrink-0 md:block xl:w-60"
              }
            >
              <div
                data-app-sidebar=""
                data-testid="harness-sidebar"
                className="absolute inset-y-0 left-0 z-40 w-full border-r border-border bg-sidebar"
              />
            </div>
            <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
              <div aria-hidden="true" className="h-12 shrink-0 border-b border-border" />
              <main className="relative flex-1 overflow-y-auto" data-testid="harness-main">
                {/* `animate-fadeIn` jak w powłoce: tworzy kontekst warstw,
                    w którym siedzi panel osoby (`z-30`). */}
                <div className="p-4 pb-24 md:p-6 animate-fadeIn">
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
                            <JobCloseReasonBadge
                              reason={closeReason}
                              notes="Ten sam request założony drugi raz z maila klienta."
                            />
                          ) : (
                            <JobChampionsStatus
                              jobId={JOB_ID}
                              job={headerJob}
                              canEdit={!readOnlyRole}
                              open={championsOpen}
                              onOpenChange={setChampionsOpen}
                              onOpenPerson={noop}
                            />
                          )
                        }
                        facts={jobHeaderFacts(headerJob)}
                        priority={
                          <JobPriorityMenu
                            jobId={JOB_ID}
                            level={priorityLevel}
                            canSet={!readOnlyRole}
                            paused={headerJob.priority_paused}
                            // Jak strona rekrutacji: zejście z P1 pyta o zespół.
                            team={{
                              workingNames: team
                                .filter((person) => !person.proposed)
                                .map((person) => person.name),
                              closed,
                            }}
                          />
                        }
                        recruiter={
                          <JobRecruiterFact
                            jobId={JOB_ID}
                            jobTitle={JOB.working_title}
                            job={headerJob}
                            canEdit={!readOnlyRole}
                            onOpenTeam={noop}
                          />
                        }
                        recruiterCompact={
                          <JobRecruiterFact
                            jobId={JOB_ID}
                            jobTitle={JOB.working_title}
                            job={headerJob}
                            canEdit={!readOnlyRole}
                            onOpenTeam={noop}
                            compact
                          />
                        }
                        sources={
                          <CandidateSourcesStrip
                            jobId={JOB_ID}
                            job={JOB}
                            canSeeSimilar
                            onOpen={setSourceTab}
                            onAddByName={noop}
                            onAddFromCv={noop}
                          />
                        }
                        sourcesTrailing={
                          <AddedByFilterButton
                            options={addedByMenuOptions}
                            value={addedBy}
                            onChange={setAddedBy}
                          />
                        }
                        collapsed={headerCollapsed}
                        onToggleCollapsed={() => setHeaderCollapsed((value) => !value)}
                        collapsedExtras={
                          addedBy.kind !== "all" ? (
                            <AddedByFilterButton
                              options={addedByMenuOptions}
                              value={addedBy}
                              onChange={setAddedBy}
                            />
                          ) : undefined
                        }
                        presence={
                          <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
                            MN
                          </span>
                        }
                        activeView="board"
                        onViewChange={noop}
                        viewHref={(view) =>
                          view === "board" ? `/jobs/${JOB_ID}` : `/jobs/${JOB_ID}?tab=${view}`
                        }
                        onOpenOrder={noop}
                        onWriteAnnouncement={readOnlyRole ? undefined : noop}
                        adChannels={{ career: true, pracuj: false, jjit: false }}
                        onOpenHistoryChat={noop}
                        onOpenFiles={() => setFilesOpen(true)}
                        filesCount={PREVIEW_FILES.items.length}
                        onAddByName={noop}
                        onAddFromCv={noop}
                        onStartFullReview={() => setSourceTab("base")}
                        onOpenMyPeople={noop}
                        onCopyLink={noop}
                        onCloseJob={closed ? undefined : () => setCloseOpen(true)}
                        onReopenJob={closed ? () => setReopenOpen(true) : undefined}
                        onChangeCloseReason={closed ? () => setChangeOpen(true) : undefined}
                      />
                      {closed ? (
                        <JobCloseWithReasonDialog
                          mode="change"
                          open={changeOpen}
                          onOpenChange={setChangeOpen}
                          jobId={JOB_ID}
                          jobTitle="Senior Java Developer"
                          initial={{
                            reason: closeReason,
                            notes: "Ten sam request założony drugi raz z maila klienta.",
                            duplicateOfJobId: null,
                          }}
                        />
                      ) : null}
                      {closed ? null : (
                        <JobCloseWithReasonDialog
                          open={closeOpen}
                          onOpenChange={setCloseOpen}
                          jobId={JOB_ID}
                          jobTitle="Senior Java Developer"
                          defaultReason={null}
                        />
                      )}
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
                        columns={withChampionCards(columns(), championMode)}
                        headerCollapsed={headerCollapsed}
                        addedBy={addedBy}
                        onAddedByChange={setAddedBy}
                        jobId={JOB_ID}
                        jobTitle={JOB.title}
                        // Jeden panel osoby (04.10.2026): „Rozwiń” w panelu
                        // pokazuje pełne narzędzia; sieć jest odcięta, więc
                        // zakładki pokażą stany ładowania i błędu.
                        workbenchContext={{
                          clientId: null,
                          clientName: null,
                          onMoved: noop,
                          canCloseJob: false,
                        }}
                        kanbanQueryState={{
                          isLoading: false,
                          isError: false,
                          error: null,
                          isSuccess: true,
                          refetch: noop,
                        }}
                      />
                      <JobFilesSlideOver
                        open={filesOpen}
                        onOpenChange={setFilesOpen}
                        jobId={JOB_ID}
                        seed={PREVIEW_FILES}
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
                        initialAddedIds={ADDED_IN_WINDOW}
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
