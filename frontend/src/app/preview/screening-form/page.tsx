"use client";

/**
 * Harness `/preview/screening-form` — jeden formularz screeningu z podglądem
 * obok (0424, decyzje Artura D1–D10, 07.10.2026). Dane fikcyjne (repo jest
 * publiczne): Tomasz Wzorcowy, Bank Przykładowy.
 *
 * `?state=` (domyślnie `nowi`):
 * - `nowi` — osoba w „Nowych”: profil przed telefonem i CV obok,
 * - `filled` — „Screening”: wypełniony formularz i wymagania obok,
 * - `note` — formularz wypełniony z notatki (plakietki „z notatki”,
 *   propozycje „Użyj”, „Ułóż w zdanie” z gotowej listy, bez modelu),
 * - `readonly` — proces zakończony: widok „Screening” tylko do odczytu
 *   (warunki, odpowiedzi, ocena) i historia,
 * - `history` — historia zmian z „Przywróć”.
 *
 * ZERO zapytań: klucze, o które pytają komponenty, są zasiane w cache,
 * interceptor odcina API, a CV idzie z plików statycznych
 * (`public/preview/cv-search/`). Przyciski zapisu kończą się komunikatem
 * o błędzie — nic nie trafia do API.
 */

import { Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AxiosError } from "axios";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { ScreeningWorkbench } from "@/components/v2/jobs/ScreeningWorkbench";
import {
  PersonPanelSide,
  PersonPanelSideProvider,
  PersonPanelSideZone,
} from "@/components/v2/person/PersonPanelSide";
import { reassignContextQueryKey } from "@/components/v2/jobs/ScreeningReassignSuggestions";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";
import { ScreeningSummarySection } from "@/components/v2/screening-form/ScreeningSummaryView";
import {
  CandidatePreviewPane,
  type PreviewTab,
} from "@/components/v2/screening-form/CandidatePreviewPane";
import { NoteFillBar } from "@/components/v2/screening-form/NoteFillBar";
import { ScreeningFormHistoryView } from "@/components/v2/screening-form/ScreeningFormHistory";
import {
  ScreeningFullFormView,
  useScreeningFormModel,
} from "@/components/v2/screening-form/ScreeningFullForm";
import type { CandidateDocument } from "@/components/v2/files/FilePreviewModal";
import type { PhraseController, PhraseSuggestionState } from "@/components/v2/screening/PhraseSuggestion";
import { Button } from "@/components/ui/button";
import { api, type ChampionProfileResponse, type CVBrandedState, type CVOriginalSnapshot } from "@/lib/api";
import { plainBriefQueryKey, type PlainBrief } from "@/lib/api/plainKnowledge";
import {
  recommendationCardQueryKey,
  type NoteProposal,
  type PhraseLanguage,
  type RecommendationCard,
} from "@/lib/api/recommendationCards";
import {
  screeningFormQueryKey,
  screeningFormVersionsQueryKey,
  type ScreeningFormState,
  type ScreeningFormVersion,
} from "@/lib/api/screeningForm";
import { stageBrandedQueryKey } from "@/lib/cv-to-client";
import { useAuthStore } from "@/store/auth";

const JOB_ID = 201;
const CANDIDATE_ID = 101;
const STAGE_ID = 901;
const DAY_MS = 86_400_000;
const SEED_FRESH = { updatedAt: Date.now() + DAY_MS };
const RECRUITER = { id: 31, name: "Marta Testowa" };

type HarnessState = "nowi" | "filled" | "note" | "readonly" | "history" | "cvpick" | "cvconsent" | "cvready";
const STATES: ReadonlyArray<{ value: HarnessState; label: string }> = [
  { value: "nowi", label: "Nowi — przed telefonem" },
  { value: "filled", label: "Screening — wypełniony" },
  { value: "note", label: "Z notatki" },
  { value: "readonly", label: "Proces zakończony" },
  { value: "history", label: "Historia zmian" },
  { value: "cvpick", label: "CV firmowe — wybór z profilu" },
  { value: "cvconsent", label: "CV firmowe — klient ze zgodą" },
  { value: "cvready", label: "CV firmowe — wybrane" },
];

/** Stany wyboru CV z profilu (09.10.2026) — w podglądzie kliknij „CV” → „CV firmowe”. */
function isCvState(state: HarnessState): boolean {
  return state === "cvpick" || state === "cvconsent" || state === "cvready";
}

function harnessState(value: string | null | undefined): HarnessState {
  return STATES.some((s) => s.value === value) ? (value as HarnessState) : "nowi";
}

// ── Pliki CV (statyczne, fikcyjne) ───────────────────────────────────────

const FILES: Record<number, string> = {
  1: "/preview/cv-search/cv-tekst.pdf",
  3: "/preview/cv-search/cv.docx",
  4: "/preview/cv-search/cv.docx",
  5: "/preview/cv-search/cv-tekst.pdf",
};

function doc(id: number, filename: string, contentType: string, isPrimary = false): CandidateDocument {
  return {
    id,
    filename,
    content_type: contentType,
    size_bytes: null,
    document_kind: "cv",
    is_primary: isPrimary,
    uploaded_at: `2026-09-0${id}T08:00:00Z`,
    external_source: null,
    created_at: `2026-09-0${id}T08:00:00Z`,
  };
}

const DOCUMENTS: CandidateDocument[] = [
  doc(1, "Tomasz Wzorcowy — CV.pdf", "application/pdf", true),
  doc(3, "Tomasz Wzorcowy — CV.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
];

async function loadStaticBlob(_candidateId: number, docId: number): Promise<Blob> {
  const response = await fetch(FILES[docId] ?? FILES[1]);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.blob();
}

async function loadStaticOriginal(): Promise<Blob> {
  return loadStaticBlob(CANDIDATE_ID, 1);
}

// CV dla klientów w profilu: plik Word da się wybrać, PDF jest tylko do podglądu.
const CLIENT_DOCUMENTS: CandidateDocument[] = [
  {
    ...doc(4, "CV_B2B_Tomasz_Wzorcowy.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    uploaded_by_name: RECRUITER.name,
  },
  doc(5, "CV_B2B_Tomasz_Wzorcowy_EN.pdf", "application/pdf"),
];

const GENERATED_CVS = [
  {
    id: 71,
    candidate_id: CANDIDATE_ID,
    job_id: JOB_ID,
    client_name: "Bank Przykładowy",
    candidate_name: "Tomasz Wzorcowy",
    position: "Senior Java Developer",
    language: "pl",
    blind: false,
    mode: "new",
    filename: "B2B_Senior_Java_Developer_Tomasz_Wzorcowy.docx",
    status: "ready",
    created_at: "2026-10-02T09:00:00Z",
    created_by_name: RECRUITER.name,
    can_download: true,
    can_delete: false,
  },
  {
    id: 64,
    candidate_id: CANDIDATE_ID,
    job_id: 202,
    client_name: "Ubezpieczyciel Fikcyjny",
    candidate_name: "Tomasz Wzorcowy",
    position: "Java Developer — bankowość mobilna",
    language: "en",
    blind: false,
    mode: "new",
    filename: "B2B_Java_Developer_Tomasz_Wzorcowy.docx",
    status: "ready",
    created_at: "2026-09-12T09:00:00Z",
    created_by_name: "Anna Przykładowa",
    can_download: true,
    can_delete: false,
  },
];

const PREVIEW_LOADERS = {
  loadDocumentBlob: loadStaticBlob,
  loadOriginalBlob: loadStaticOriginal,
  loadStageCvFile: async () => ({ blob: await loadStaticBlob(CANDIDATE_ID, 4), filename: "CV.docx" }),
};

// ── Profil Championa i „Po ludzku” ───────────────────────────────────────

const QUESTIONS = [
  {
    id: "q1",
    question: "Opisz ostatni system w Spring Boocie, który rozwijałeś — co napisałeś sam?",
    ideal_answer: "Konkretny projekt, własny wkład, REST + testy integracyjne.",
    deal_breaker: "Wyłącznie utrzymanie aplikacji (L2/L3).",
  },
  {
    id: "q2",
    question: "Jak używałeś Kafki w produkcji?",
    ideal_answer: "Producent/konsument, obsługa błędów, ponowienia.",
    deal_breaker: "",
  },
  {
    id: "q3",
    question: "Od kiedy możesz zacząć?",
    ideal_answer: "Najpóźniej na początku listopada.",
    deal_breaker: "Okres wypowiedzenia dłuższy niż 2 miesiące.",
  },
];

const CHAMPION_PROFILE = {
  basics: {
    role_name: "Senior Java Developer",
    rate_value: 150,
    work_mode: "hybrydowo",
    onsite_days_per_week: 2,
    candidate_location_pref: "Warszawa",
    start_date: "listopad 2026",
    contract_length: "12 miesięcy z przedłużeniem",
    seniority_min_years: 5,
    language: "PL, EN B2",
  },
  stack: {
    must: [{ name: "Java 17" }, { name: "Spring Boot" }, { name: "Kafka" }],
    nice: [{ name: "Kubernetes" }],
    notes: "",
  },
  screening_questions: QUESTIONS,
};

const PROFILE: ChampionProfileResponse = {
  job_id: JOB_ID,
  job_title: "Senior Java Developer — płatności kartowe",
  champion_profile: CHAMPION_PROFILE as never,
  critical_resolution: {
    stored: ["Java 17"],
    decided: true,
    effective: ["Java 17"],
    source: "dl",
    suggested: ["Java 17"],
  } as never,
};

/** Hasło słowniczka „po ludzku” — zdanie pod wymaganiem w zakładce „Wymagania”. */
function glossaryTerm(
  name: string,
  summary: string | null,
  status: "ready" | "researching" = "ready",
): PlainBrief["glossary"][number] {
  return {
    term_key: name.toLowerCase(),
    display_name: name,
    level: "must",
    level_label: "wymagane",
    status,
    summary,
    does: null,
    cv_hints: [],
    confused_with: null,
    in_this_project: null,
    sources: [],
    origin: null,
  };
}

const BRIEF: PlainBrief = {
  job_id: JOB_ID,
  status: "ready",
  stale: false,
  is_open: true,
  can_refresh: false,
  can_change_role: false,
  generated_at: new Date(Date.now() - DAY_MS).toISOString(),
  message: null,
  one_liner:
    "Szukamy programisty Javy, który rozwija system płatności kartą w Banku Przykładowym — tę część, która w ułamku sekundy mówi sklepowi „płatność przyjęta”.",
  example:
    "Gdy płacisz kartą w sklepie, terminal pyta bank, czy masz środki. Ta osoba pisze program, który odbiera to pytanie i odpowiada, zanim kasjer zdąży zapakować zakupy.",
  day_to_day: [
    "Dopisuje nowe funkcje do systemu płatności.",
    "Poprawia błędy zgłoszone przez wsparcie.",
  ],
  pitch: "Stabilny projekt na lata, nowoczesny stack, dwa dni w biurze w tygodniu, do 150 zł/h netto B2B.",
  candidate_qa: [
    { key: "rate", question: "Ile płacą?", answer: "Do 150 zł za godzinę netto, B2B.", source: "budżet rekrutacji" },
    { key: "office", question: "Ile dni w biurze?", answer: "Dwa w tygodniu, Warszawa.", source: "tryb pracy" },
    { key: "process", question: "Jak wygląda rekrutacja u klienta?", answer: null, source: null },
  ],
  screening_plain: [],
  glossary: [
    glossaryTerm("Kafka", "Kolejka zdarzeń: systemy wysyłają sobie komunikaty i nie czekają na odpowiedź."),
    glossaryTerm("Spring Boot", "Szkielet, na którym buduje się usługi w Javie. Zapytaj, co napisał sam."),
    glossaryTerm("Kubernetes", null, "researching"),
  ],
  role: null,
  client: {
    id: 1,
    name: "Bank Przykładowy",
    about: "Średni bank detaliczny z siedzibą w Warszawie.",
    origin: "manual",
    sources: [],
  },
};

// ── Formularz ────────────────────────────────────────────────────────────

const LABELS: Record<string, string> = {
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

const BASE_STATE: ScreeningFormState = {
  candidate_id: CANDIDATE_ID,
  job_id: JOB_ID,
  version: 0,
  versions_count: 0,
  state_token: "podglad-0",
  editable: true,
  read_only_reason: null,
  read_only_message: null,
  stage_id: STAGE_ID,
  board_column: "new",
  process_state_version: 3,
  claim: null,
  champion_profile: CHAMPION_PROFILE,
  sheet: null,
  sheet_source_stage_id: null,
  legacy_notes: null,
  note_answers: [],
  card: {
    fields: {},
    previous: {},
    suggestions: { nationality: "polska" },
    completeness: { status: "empty", filled: 0, total: 10, missing: Object.keys(LABELS) },
    labels: LABELS,
    editable_fields: Object.keys(LABELS),
  },
  rate: null,
  rate_hints: { card: null, rate_from: { amount: 140, unit: "hourly", currency: "PLN" } },
  rate_change_notifies: false,
  can_edit_rate: true,
  suggestions_from_notes: {},
  assist_enabled: true,
  phrase_language: "pl",
};

const FILLED_STATE: ScreeningFormState = {
  ...BASE_STATE,
  // Ta sama wersja co najnowsza pozycja historii niżej — inaczej plakietka
  // „bieżąca” stałaby przy starszej wersji.
  version: 3,
  versions_count: 3,
  board_column: "screening",
  sheet: {
    answers: [
      {
        question_id: "q1",
        response: "System rozliczeń płatności odroczonych w Spring Boot 3 — sam napisał moduł limitów i testy integracyjne.",
        deal_breaker_hit: false,
        question_text: QUESTIONS[0].question,
      },
      {
        question_id: "q2",
        response: "Kafka od trzech lat na produkcji: zdarzenia płatności, ponowienia przez kolejkę błędów.",
        deal_breaker_hit: false,
        question_text: QUESTIONS[1].question,
      },
      { question_id: "q3", response: "Od 1 listopada, miesiąc wypowiedzenia.", deal_breaker_hit: false, question_text: QUESTIONS[2].question },
    ],
    experience_checks: [],
    overall_fit: "fit",
    notes: "",
    answered_at: "2026-10-06T10:00:00Z",
  },
  legacy_notes: "Rozmowa 30 min, dobry kontakt, pyta o pracę zdalną w piątki.",
  card: {
    ...BASE_STATE.card,
    fields: {
      availability: { raw: "od 1 listopada", source: "manual", by_name: RECRUITER.name },
      work_mode: { raw: "hybrydowo, 2 dni w Warszawie", source: "manual", by_name: RECRUITER.name },
      location: { raw: "Warszawa", source: "note", note_id: 1 },
      english: { raw: "B2", level: "B2", source: "manual", by_name: RECRUITER.name },
      recommendation: {
        raw: "Dziewięć lat w Javie, ostatnie trzy w płatnościach kartowych — zna domenę i stack klienta.",
        source: "manual",
        by_name: RECRUITER.name,
      },
    },
    completeness: { status: "partial", filled: 6, total: 10, missing: ["nationality", "red_flags", "motivation", "worked_at_client"] },
  },
  rate: { amount: 145, unit: "hourly", currency: "PLN", source: "stage", at: "2026-10-06T10:00:00Z" },
};

const PROPOSAL: NoteProposal = {
  fields: [
    {
      key: "rate",
      label: "Stawka",
      current: null,
      current_source: null,
      proposed: "150 zł/h netto B2B",
      quote: "stawka 150 netto b2b",
      origin: "note_ai",
      changed: true,
      rate: { amount: 150, unit: "hourly", currency: "PLN" },
    },
    {
      key: "availability",
      label: "Dostępność",
      current: null,
      current_source: null,
      proposed: "miesiąc wypowiedzenia, start od listopada",
      quote: "wypow. miesiąc, start od listopada",
      origin: "note_ai",
      changed: true,
    },
    {
      key: "work_mode",
      label: "Tryb pracy",
      current: "hybrydowo",
      current_source: "manual",
      proposed: "Hybrydowo, do 2 dni w biurze w Warszawie",
      quote: "hybryda ok, max 2 dni w wawie",
      origin: "note_ai",
      changed: true,
    },
    {
      key: "motivation",
      label: "Motywacja",
      current: null,
      current_source: null,
      proposed: "Obecny projekt się kończy, szuka dłuższego kontraktu w bankowości.",
      quote: "projekt sie konczy, chce cos na dluzej w bankach",
      origin: "note_ai",
      changed: true,
    },
  ],
  answers: [
    {
      question_id: "q2",
      number: 2,
      question: QUESTIONS[1].question,
      current: null,
      keywords: "kafka 3 lata prod, eventy płatności",
      sentence: "Kandydat od trzech lat pracuje z Kafką na produkcji przy zdarzeniach płatności.",
      problem: null,
    },
  ],
  available: true,
  message: null,
  language: "pl",
  rate_change_notifies: false,
  text: "stawka 150 netto b2b\nwypow. miesiąc, start od listopada\nhybryda ok, max 2 dni w wawie\nkafka 3 lata prod, eventy płatności",
};

const NOTE_BASE_STATE: ScreeningFormState = {
  ...BASE_STATE,
  board_column: "screening",
  card: {
    ...BASE_STATE.card,
    fields: { work_mode: { raw: "hybrydowo", source: "manual", by_name: RECRUITER.name } },
  },
};

const ENDED_STATE: ScreeningFormState = {
  ...FILLED_STATE,
  version: 3,
  versions_count: 3,
  editable: false,
  read_only_reason: "process_closed",
  read_only_message: "Proces tej osoby jest zakończony — formularz jest tylko do odczytu.",
  board_column: "closed",
  // Pytania scalone tak, jak oddaje je serwer: odpowiedź z arkusza i „Odpada, gdy…”.
  questions: QUESTIONS.map((question, index) => ({
    number: index + 1,
    question: question.question,
    answer: FILLED_STATE.sheet?.answers[index]?.response ?? "",
    source: "sheet" as const,
    question_id: question.id,
    deal_breaker: question.deal_breaker || null,
    deal_breaker_hit: false,
  })),
};

const VERSIONS: ScreeningFormVersion[] = [
  {
    version_no: 3,
    action: "save",
    source: "form",
    created_at: "2026-10-07T09:15:00Z",
    created_by: RECRUITER.id,
    created_by_name: RECRUITER.name,
    restored_from_version: null,
    note_id: null,
    changes: [
      { section: "rate", key: "rate", label: "Stawka kandydata", before: "140 zł/h", after: "145 zł/h" },
      { section: "terms", key: "availability", label: "Dostępność", before: null, after: "od 1 listopada" },
    ],
  },
  {
    version_no: 2,
    action: "save",
    source: "note_import",
    created_at: "2026-10-06T10:05:00Z",
    created_by: RECRUITER.id,
    created_by_name: RECRUITER.name,
    restored_from_version: null,
    note_id: 7,
    changes: [
      { section: "answers", key: "q2", label: "Pytanie 2", before: null, after: "Kafka od trzech lat na produkcji…" },
      { section: "assessment", key: "overall_fit", label: "Ogólna ocena", before: "Niepewne", after: "Pasuje" },
    ],
  },
  {
    version_no: 1,
    action: "baseline",
    source: "form",
    created_at: "2026-10-05T14:00:00Z",
    created_by: null,
    created_by_name: null,
    restored_from_version: null,
    note_id: null,
    changes: [],
  },
];

const CARD: RecommendationCard = {
  candidate_id: CANDIDATE_ID,
  job_id: JOB_ID,
  exists: true,
  fields: FILLED_STATE.card.fields,
  previous: {},
  suggestions: {},
  questions: [],
  completeness: FILLED_STATE.card.completeness,
  labels: LABELS,
  editable_fields: Object.keys(LABELS),
  legacy_text: "Imię i nazwisko: Tomasz Wzorcowy\nStawka: 145 zł/h\nDostępność: od 1 listopada",
  updated_at: "2026-10-06T10:00:00Z",
};

// ── Tablica (kolumny) ────────────────────────────────────────────────────

const ITEM: KanbanItem = {
  id: STAGE_ID,
  candidate_id: CANDIDATE_ID,
  stage: "new",
  name: "Tomasz",
  lastname: "Wzorcowy",
  days_in_stage: 1,
  added_to_job_by_name: RECRUITER.name,
  added_to_job_at: "2026-10-05T08:00:00Z",
  entry_source: "application",
  entry_ai_screening: { verdict: "fits", assessed: true, must_found: 3, must_total: 3, overridden: false },
  can_take: true,
  claim_user_id: null,
  contact_attempts: 1,
  candidate_rate_from_hourly: 140,
  process_state_version: 3,
};

function columnsFor(state: HarnessState): KanbanColumn[] {
  const column = state === "readonly" ? "rejected" : state === "nowi" ? "new" : "screening";
  const item = { ...ITEM, stage: column };
  const col = (stage: string, name: string, stageDefId: number, extra: Partial<KanbanColumn> = {}): KanbanColumn => ({
    stage,
    name,
    category: "internal",
    stage_def_id: stageDefId,
    count: stage === column ? 1 : 0,
    items: stage === column ? [item] : [],
    ...extra,
  });
  return [
    col("new", "Nowi", 300),
    col("screening", "Screening", 301),
    col("verified", "Zweryfikowany", 302),
    col("rejected", "Odrzucony", 309, { category: "terminal", terminal_type: "rejected" }),
  ];
}

const QUICK_VIEW = {
  candidate: { id: CANDIDATE_ID, name: "Tomasz", lastname: "Wzorcowy", city: "Warszawa", location: "Warszawa" },
  current_position: { title: "Senior Java Developer", started_at: "2023-03-01", precision: "month" },
  availability: { status: "open_to_offers", available_from: null, notice_period: 1, notice_period_unit: "months" },
  current_recruitments: [
    {
      job_id: 202,
      job_title: "Java Developer — bankowość mobilna",
      client_name: "Bank Przykładowy",
      stage_id: 902,
      stage_name: "CV wysłane",
      moved_at: "2026-09-28T09:00:00Z",
      moved_by_name: RECRUITER.name,
    },
  ],
  recent_notes: [
    {
      id: 11,
      content: "Rozmowa wstępna: zainteresowany projektami płatności, prosi o kontakt po 16:00.",
      created_at: "2026-09-30T15:00:00Z",
      author_name: RECRUITER.name,
    },
  ],
  contact_attempts: 1,
  cv_highlights: { years_experience: 9 },
  capabilities: { can_assign: true, can_mark_employed: false, can_view_documents: true, can_open_full_profile: true },
};

const SNAPSHOT: CVOriginalSnapshot = {
  candidate_stage_id: STAGE_ID,
  candidate_id: CANDIDATE_ID,
  job_id: JOB_ID,
  has_snapshot: true,
  original_cv_filename: "Tomasz Wzorcowy — CV.pdf",
  original_cv_language: "pl",
  original_snapshot_at: "2026-10-05T08:00:00Z",
  original_snapshot_source: "application",
  download_url: null,
};

const BRANDED_NONE: CVBrandedState = {
  edit_revision: 0,
  version: 0,
  candidate_stage_id: STAGE_ID,
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
};

function seededClient(state: HarnessState): QueryClient {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity, refetchOnWindowFocus: false } },
  });
  const formState =
    state === "nowi" ? BASE_STATE : state === "readonly" ? ENDED_STATE : state === "note" ? NOTE_BASE_STATE : FILLED_STATE;
  qc.setQueryData(screeningFormQueryKey(JOB_ID, CANDIDATE_ID), formState, SEED_FRESH);
  qc.setQueryData(screeningFormVersionsQueryKey(JOB_ID, CANDIDATE_ID), { items: VERSIONS, total: VERSIONS.length }, SEED_FRESH);
  qc.setQueryData(["job-questions", JOB_ID], [], SEED_FRESH);
  qc.setQueryData(["job-rejection-reasons", JOB_ID], [], SEED_FRESH);
  qc.setQueryData(reassignContextQueryKey(STAGE_ID), { stage_id: STAGE_ID, available: false, source: null, previous_answers_count: 0 }, SEED_FRESH);
  qc.setQueryData(candidateQueryKeys.quickView(CANDIDATE_ID), QUICK_VIEW, SEED_FRESH);
  qc.setQueryData(["cv-original", STAGE_ID], SNAPSHOT, SEED_FRESH);
  const cv = isCvState(state);
  const documents = cv ? [...DOCUMENTS, ...CLIENT_DOCUMENTS] : DOCUMENTS;
  const branded: CVBrandedState =
    state === "cvready"
      ? { ...BRANDED_NONE, status: "draft", source: "document", from_generator: false, edit_revision: 1, version: 1 }
      : BRANDED_NONE;
  qc.setQueryData(candidateQueryKeys.cvDocuments(CANDIDATE_ID), documents, SEED_FRESH);
  qc.setQueryData(stageBrandedQueryKey(STAGE_ID), branded, SEED_FRESH);
  // Wybór gotowego CV z profilu: lista z generatora, reguła klienta i lista
  // podglądu CV etapu — te same klucze co `StageCvPicker` i `StageCvPreview`.
  const policy = { managed: true, effective_policy: { requires_rodo_consent_block: state === "cvconsent" } };
  qc.setQueryData(["candidate-generated-cvs", CANDIDATE_ID], cv ? GENERATED_CVS : [], SEED_FRESH);
  qc.setQueryData(["central-cv-policy", null, STAGE_ID, false], policy, SEED_FRESH);
  qc.setQueryData(["cv-generated", "dl-review", CANDIDATE_ID, JOB_ID], [], SEED_FRESH);
  qc.setQueryData(["champion-profile", JOB_ID], PROFILE, SEED_FRESH);
  qc.setQueryData(plainBriefQueryKey(JOB_ID), BRIEF, SEED_FRESH);
  qc.setQueryData(["job", String(JOB_ID)], { id: JOB_ID, rate_budget_hourly_min: 130, effective_budget_hourly: 150 }, SEED_FRESH);
  qc.setQueryData(recommendationCardQueryKey(CANDIDATE_ID, JOB_ID), CARD, SEED_FRESH);
  return qc;
}

// ── „Ułóż w zdanie” bez modelu ──────────────────────────────────────────

const CANNED: Record<string, string> = {
  recommendation: "Kandydat ma dziewięć lat doświadczenia w Javie, w tym trzy w płatnościach kartowych.",
  motivation: "Obecny projekt kandydata się kończy; szuka dłuższego kontraktu w bankowości.",
  red_flags: "Brak zastrzeżeń.",
};

function useFakePhrase(): PhraseController {
  const [language, setLanguage] = useState<PhraseLanguage>("pl");
  const [results, setResults] = useState<Record<string, PhraseSuggestionState>>({});
  return {
    language,
    setLanguage,
    results,
    isPending: () => false,
    request: async (items) =>
      setResults((prev) => ({
        ...prev,
        ...Object.fromEntries(
          items.map((item) => [
            item.key,
            {
              key: item.key,
              sentence: CANNED[item.key] ?? null,
              problem: CANNED[item.key] ? null : "listopada",
              keywords: item.keywords,
            },
          ]),
        ),
      })),
    dismiss: (key) =>
      setResults((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      }),
  };
}

// ── Widoki ───────────────────────────────────────────────────────────────

/**
 * Panel osoby w trybie dzielonym (09.10.2026): po lewej prawdziwa strefa
 * podglądu (`PersonPanelSideZone`), po prawej kolumna doku tej samej
 * szerokości co w powłoce na Tablicy (460 px, od 1536 px okna 520 px).
 * Poniżej 1024 px zostaje jedna kolumna, a podgląd stoi w miejscu.
 */
function PanelFrame({ children }: { children: ReactNode }) {
  return (
    <PersonPanelSideProvider>
      <div
        className="flex h-[calc(100dvh-9rem)] min-h-[32rem] w-full overflow-hidden rounded-xl border border-border bg-background shadow-sm"
        data-testid="harness-panel"
      >
        <PersonPanelSideZone />
        <div
          className="flex min-h-0 min-w-0 flex-1 flex-col lg:w-[460px] lg:flex-none 2xl:w-[520px]"
          data-testid="harness-panel-column"
        >
          <div className="flex-1 overflow-y-auto p-4" data-person-scroll="">
            {children}
          </div>
        </div>
      </div>
    </PersonPanelSideProvider>
  );
}

/** Formularz bez sieci: ten sam widok co w panelu, zapis tylko na stronie. */
function PresentationalForm({ state, withHistory }: { state: HarnessState; withHistory: boolean }) {
  const formState = state === "note" ? NOTE_BASE_STATE : FILLED_STATE;
  const model = useScreeningFormModel(formState);
  const fakePhrase = useFakePhrase();
  const applied = useRef(false);
  const [tab, setTab] = useState<PreviewTab>("requirements");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (state !== "note" || applied.current) return;
    applied.current = true;
    model.applyNote(PROPOSAL, { text: PROPOSAL.text, source_name: "notatka_wzorcowy.docx" });
  }, [state, model]);

  return (
    <div className="@container space-y-3">
      <PersonPanelSide
        inline={(content) => <div className="flex h-[70dvh] min-w-0 flex-col">{content}</div>}
      >
        <CandidatePreviewPane
          candidateId={CANDIDATE_ID}
          jobId={JOB_ID}
          stageId={STAGE_ID}
          tab={tab}
          onTabChange={setTab}
          budgetHourly={150}
          loadDocumentBlob={loadStaticBlob}
          loadOriginalBlob={loadStaticOriginal}
          className="flex-1"
        />
      </PersonPanelSide>
      <div className="min-w-0">
        <ScreeningFullFormView
          state={formState}
          model={model}
          jobBudgetHourly={150}
          phrase={state === "note" ? fakePhrase : undefined}
          noteBar={
            <NoteFillBar
              candidateId={CANDIDATE_ID}
              jobId={JOB_ID}
              applied={
                model.note
                  ? { filled: model.note.filled, offers: model.offers.length, sourceName: model.note.source.source_name ?? null }
                  : null
              }
              onProposal={() => undefined}
              onUndo={model.undoNote}
            />
          }
          footer={
            <div className="sticky bottom-0 flex flex-wrap items-center gap-2 border-t border-border bg-background/95 py-2.5">
              <p className="mr-auto text-[11px] text-muted-foreground" role="status">
                {saved ? "Zapisano (podgląd — nic nie trafiło do API)" : `Wersja ${formState.version}`}
              </p>
              <Button size="sm" variant="outline" onClick={() => setSaved(true)}>
                Zapisz
              </Button>
              <Button size="sm" onClick={() => setSaved(true)}>
                Zapisz i przekaż dalej → Zweryfikowany
              </Button>
            </div>
          }
          history={
            withHistory ? (
              <ScreeningFormHistoryView
                versions={VERSIONS}
                total={VERSIONS.length}
                currentVersion={formState.version}
                canRestore
                onRestore={() => setSaved(true)}
              />
            ) : null
          }
        />
      </div>
    </div>
  );
}

function Harness() {
  const params = useSearchParams();
  const state = harnessState(params?.get("state"));
  const [client, setClient] = useState<QueryClient | null>(null);

  useEffect(() => {
    const blocker = api.interceptors.request.use((config) =>
      Promise.reject(new AxiosError("preview: sieć wyłączona", "ECONNABORTED", config)),
    );
    return () => api.interceptors.request.eject(blocker);
  }, []);

  useEffect(() => {
    useAuthStore.setState({
      user: {
        id: RECRUITER.id,
        email: "preview@example.com",
        name: RECRUITER.name,
        role: "recruiter",
        roles: ["recruiter"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
        effective_section_access: { sourcing: "write", pipeline: "write" },
      } as never,
      realUser: null,
      hydrated: true,
    });
    setClient(seededClient(state));
  }, [state]);

  if (!client) return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
  const columns = columnsFor(state);
  const presentational = state === "note" || state === "history";

  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <main className="min-h-dvh space-y-4 bg-background p-4 text-foreground md:p-6">
          <header className="space-y-1">
            <h1 className="text-lg font-semibold">Podgląd: formularz screeningu</h1>
            <nav aria-label="Stan formularza" className="flex flex-wrap gap-x-3 gap-y-1 text-sm">
              {STATES.map((option) => (
                <Link
                  key={option.value}
                  href={`/preview/screening-form?state=${option.value}`}
                  aria-current={option.value === state ? "page" : undefined}
                  className={option.value === state ? "font-semibold text-primary" : "hover:underline"}
                >
                  {option.label}
                </Link>
              ))}
            </nav>
            <p className="text-sm text-muted-foreground">
              Tomasz Wzorcowy · Senior Java Developer · Bank Przykładowy. Dane fikcyjne, nic nie jest zapisywane.
            </p>
          </header>
          <PanelFrame>
            {presentational ? (
              <PresentationalForm key={state} state={state} withHistory={state === "history"} />
            ) : (
              <ScreeningWorkbench
                key={state}
                focusCandidateId={CANDIDATE_ID}
                jobId={JOB_ID}
                jobBudgetHourly={150}
                columns={columns}
                isLoading={false}
                isError={false}
                error={null}
                isSuccess
                onRetry={() => undefined}
                onMoved={() => undefined}
                readOnly={false}
                onTabChange={() => undefined}
                onTake={() => undefined}
                previewLoaders={PREVIEW_LOADERS}
                panelFallback={<ScreeningSummarySection candidateId={CANDIDATE_ID} jobId={JOB_ID} showLockNote />}
              />
            )}
          </PanelFrame>
        </main>
      </ToastProvider>
    </QueryClientProvider>
  );
}

export default function ScreeningFormPreviewPage() {
  return (
    <Suspense fallback={null}>
      <Harness />
    </Suspense>
  );
}
