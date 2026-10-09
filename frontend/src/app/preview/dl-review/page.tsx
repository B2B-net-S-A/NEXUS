"use client";

// Publiczny harness przeglądu Delivery Leada (03.10.2026, v2 08.10.2026 —
// D6, D9, D10; układ D4, 09.10.2026): CV po lewej na całą wysokość, decyzja
// w stałej kolumnie po prawej (marża na żywo, podpowiedź stawki do klienta,
// punkty odniesienia, przyciski zawsze na widoku), „Wymagania i ocena” jako
// zakładka obok CV albo — od 1640 px szerokości przeglądu — środkowa kolumna;
// poniżej 1100 px wszystko jedno pod drugim. „Wróć do poprawy…” z listą pól.
// Dane fikcyjne, ZERO zapytań do API: cache react-query jest zasiany ze
// znacznikiem czasu w przyszłości, sieć odcina interceptor, a pliki CV to
// pliki statyczne (`public/preview/cv-search/`).
// `?layout=panel` — przegląd jak w panelu osoby na Tablicy (ramka na całą
// szerokość strony zamiast okna): zmieniaj szerokość okna, żeby zobaczyć
// wszystkie trzy układy.
// `?as=recruiter` — osoba, która tylko przegląda (bez decyzji).
// `?state=queue` — porównanie osób w „QC CV” jednej rekrutacji (D10).
// `?state=returned` — formularz rekrutera po „Wróć do poprawy” (baner
// „Delivery Lead prosi o poprawki”, pola do poprawy i „Zapisz i oddaj”).

import { useEffect, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AxiosError } from "axios";

import { ToastProvider } from "@/components/Toast";
import type { CandidateDocument } from "@/components/v2/files/FilePreviewModal";
import { reassignContextQueryKey } from "@/components/v2/jobs/ScreeningReassignSuggestions";
import { DlReviewQueueDialog } from "@/components/v2/recruitment/dl-review/DlReviewQueueDialog";
import { ScreeningFullForm } from "@/components/v2/screening-form/ScreeningFullForm";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { DlReviewBody, DlReviewPanel } from "@/components/v2/recruitment/DlReviewPanel";
import api, { type CVBrandedState, type CVOriginalSnapshot } from "@/lib/api";
import type { BoardTaskRow } from "@/lib/api/boardTasks";
import { stageBrandedQueryKey } from "@/lib/cv-to-client";
import {
  dlReviewContextQueryKey,
  dlReviewQueueQueryKey,
  type DlReviewContext,
  type DlReviewQueue,
} from "@/lib/api/dlReview";
import { screeningFormQueryKey, type ScreeningFormState } from "@/lib/api/screeningForm";
import {
  recommendationCardQueryKey,
  type RecommendationCard,
} from "@/lib/api/recommendationCards";
import { useAuthStore } from "@/store/auth";

const CANDIDATE_ID = 101;
const JOB_ID = 201;
const STAGE_ID = 9001;

const TASK: BoardTaskRow = {
  kind: "dl_review",
  stage_id: STAGE_ID,
  candidate_id: CANDIDATE_ID,
  candidate_name: "Tomasz Wzorcowy",
  job_id: JOB_ID,
  job_title: "Senior Java Developer (ZOB-0001)",
  job_working_title: "Java · Spring · Kafka",
  client_id: 7,
  client_name: "Bank Kappa",
  since: new Date(Date.now() - 26 * 3_600_000).toISOString(),
  process_state_version: 4,
  target_stage_def_id: 305,
  rejected_stage_def_id: 399,
  return_stage_def_id: 302,
  assignee_id: null,
  assignee_name: null,
  verified_by_id: 3,
  verified_by_name: "Marta Testowa",
  verified_at: new Date(Date.now() - 30 * 3_600_000).toISOString(),
  expected_rate_value: 135,
  expected_rate_unit: "hourly",
  expected_rate_currency: "PLN",
  screening_stage_id: STAGE_ID,
  qc_status: "passed",
  qc_blocking_failed: 0,
  card_status: "partial",
  card_missing: 2,
};

// ── Pliki CV (statyczne, fikcyjne — te same co w `/preview/screening-form`) ──

const GENERATED_CV_ID = 77;
const COMPANY_CV_URL = `/api/cv-generator/generated/${GENERATED_CV_ID}/docx`;
const COMPANY_CV_FILE = "/preview/cv-search/cv.docx";

const FILES: Record<number, string> = {
  1: "/preview/cv-search/cv-tekst.pdf",
  3: COMPANY_CV_FILE,
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

const PREVIEW_LOADERS = { loadDocumentBlob: loadStaticBlob, loadOriginalBlob: loadStaticOriginal };

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

// Podgląd oryginału pyta też o CV firmowe etapu (wspólna zakładka CV).
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

const LABELS = {
  rate: "Stawka",
  availability: "Dostępność",
  work_mode: "Tryb pracy",
  location: "Lokalizacja",
  nationality: "Narodowość",
  worked_at_client: "Czy pracował u Klienta",
  english: "Angielski",
  red_flags: "Red flags",
  recommendation: "Notatka",
  motivation: "Motywacja",
  client_manager: "Manager u Klienta",
};

const CARD: RecommendationCard = {
  candidate_id: CANDIDATE_ID,
  job_id: JOB_ID,
  exists: true,
  fields: {
    rate: { raw: "135 zł/h", value: 135, source: "note", note_id: 1 },
    availability: { raw: "1 miesiąc", source: "note", note_id: 1 },
    work_mode: { raw: "hybrydowo, 2 dni w tygodniu, Łódź", source: "note", note_id: 1 },
    location: { raw: "Łódź", source: "note", note_id: 1 },
    nationality: { raw: "polska", source: "note", note_id: 1 },
    worked_at_client: { raw: "nie", value: "no", source: "note", note_id: 1 },
    english: { raw: "C1", level: "C1", source: "manual", by_name: "Marta Testowa" },
    recommendation: {
      raw: "Senior Java developer, dziewięć lat doświadczenia, ostatnie trzy w bankowości.",
      source: "manual",
      by_name: "Marta Testowa",
    },
  },
  previous: {},
  suggestions: {},
  questions: [
    {
      number: 1,
      question: "Rozwiązanie rozwijane w Javie 17+ i Spring Boot",
      answer: "Panel administracyjny i integracje systemu kredytowego. Java 21, Spring Boot 3.",
      source: "sheet",
    },
    {
      number: 2,
      question: "Komunikacja między usługami — synchroniczna czy przez kolejki",
      answer: "REST między usługami, Kafka do zdarzeń kredytowych.",
      source: "note",
    },
    { number: 3, question: "Chmura w projektach komercyjnych", answer: "", source: null },
  ],
  completeness: { status: "partial", filled: 8, total: 10, missing: ["red_flags", "motivation"] },
  labels: LABELS,
  editable_fields: Object.keys(LABELS),
  // Tekst pod „W starym formacie” w bloku „Screening”.
  legacy_text:
    "Imię i nazwisko: Jan Przykładowy\nStawka: 135 zł/h\nDostępność: 1 miesiąc\nAngielski: C1\n\nP1: Rozwiązanie rozwijane w Javie 17+ i Spring Boot\nO: Panel administracyjny, Java 21.",
  updated_at: "2026-09-30T10:00:00Z",
};

const FIX_OPTIONS: DlReviewContext["fix_options"] = [
  { key: "question:q1", label: "Pytanie 1: Rozwiązanie rozwijane w Javie 17+ i Spring Boot", group: "answers" },
  { key: "question:q2", label: "Pytanie 2: Komunikacja między usługami", group: "answers" },
  { key: "field:availability", label: "Dostępność", group: "terms" },
  { key: "field:work_mode", label: "Tryb pracy", group: "terms" },
  { key: "field:overall_fit", label: "Ocena rekrutera", group: "assessment" },
  { key: "field:recommendation", label: "Dlaczego ten kandydat", group: "assessment" },
  { key: "field:red_flags", label: "Red flags", group: "assessment" },
  { key: "candidate_rate", label: "Stawka kandydata", group: "rate" },
  { key: "cv", label: "CV firmowe", group: "cv" },
];

const CONTEXT: DlReviewContext = {
  candidate_id: CANDIDATE_ID,
  candidate_name: TASK.candidate_name,
  job_id: JOB_ID,
  stage_id: STAGE_ID,
  client_id: 7,
  client_name: "Bank Kappa",
  category_name: "Rozwój oprogramowania",
  qc_status: "passed",
  qc_blocking_failed: 0,
  can_see_amounts: true,
  can_see_client_rates: true,
  candidate_rate: { amount: 135, unit: "hourly", currency: "PLN", hourly_pln: 135 },
  rate_from_hourly: 110,
  budget: { min_hourly: 120, max_hourly: 150 },
  client_rate_hint: {
    amount: 178,
    unit: "hourly",
    currency: "PLN",
    hourly_pln: 178,
    at: "2026-06-12T09:00:00Z",
    source: "same_client",
    job_id: 180,
    job_title: "Java Developer — kredyty",
  },
  client_rates: {
    consultants: 14,
    client_margin_median_hourly: 38,
    category_name: "Rozwój oprogramowania",
    category_count: 6,
    category_cost_min: 120,
    category_cost_max: 165,
    category_revenue_min: 160,
    category_revenue_max: 205,
    category_margin_median_hourly: 40,
  },
  requirements: [
    { key: "must:0", label: "Java 17", level: "critical", status: "met", sources: ["CV", "rozmowa"], candidate_value: "…Java 21, Spring Boot 3 w systemie kredytowym…" },
    { key: "must:1", label: "Spring Boot", level: "must", status: "met", sources: ["CV"], candidate_value: "…Spring Boot 3, integracje REST…" },
    { key: "must:2", label: "Kafka", level: "must", status: "met", sources: ["notatka"], candidate_value: "Kafka do zdarzeń kredytowych" },
    { key: "must:3", label: "Oracle", level: "must", status: "missing", sources: [], candidate_value: null },
    { key: "nice:0", label: "Kubernetes", level: "nice", status: "met", sources: ["profil"], candidate_value: null },
    { key: "experience:domains:0", label: "Bankowość (min. 3 lat)", level: "experience", status: "unknown", sources: [], candidate_value: null },
  ],
  requirements_met: 3,
  requirements_total: 4,
  assessment: {
    overall_fit: "fit",
    overall_fit_label: "Pasuje",
    fields: {
      recommendation: "Senior Java developer, dziewięć lat doświadczenia, ostatnie trzy w bankowości.",
      motivation: "Chce wrócić do projektu produktowego.",
      red_flags: null,
      availability: "1 miesiąc",
      work_mode: "hybrydowo, 2 dni w tygodniu, Łódź",
      location: "Łódź",
      english: "C1",
      worked_at_client: "nie",
    },
    answers: [
      { question: "Rozwiązanie rozwijane w Javie 17+ i Spring Boot", question_id: "q1", answer: "Panel administracyjny i integracje systemu kredytowego. Java 21, Spring Boot 3.", deal_breaker_hit: false },
    ],
  },
  risks: [
    { code: "sent_to_client_before", label: "Już u tego klienta: „Java Developer — kredyty” (2026-06-12, Odrzucony)", severity: "medium" },
  ],
  start: "1 miesiąc",
  fix_rounds: 0,
  previous_sends: [
    {
      candidate_id: CANDIDATE_ID,
      candidate_name: TASK.candidate_name,
      job_id: 180,
      job_title: "Java Developer — kredyty",
      client_name: "Bank Kappa",
      sent_at: "2026-06-12T09:00:00Z",
      outcome: "Odrzucony",
      same_client: true,
      candidate_rate: { amount: 130, unit: "hourly", currency: "PLN", hourly_pln: 130 },
      client_rate: { amount: 178, unit: "hourly", currency: "PLN", hourly_pln: 178 },
    },
  ],
  job_sends: [
    {
      candidate_id: 102,
      candidate_name: "Anna Przykładowa",
      job_id: JOB_ID,
      job_title: TASK.job_title,
      client_name: "Bank Kappa",
      sent_at: "2026-10-01T09:00:00Z",
      outcome: "Rozmowa u klienta",
      same_client: true,
      candidate_rate: { amount: 140, unit: "hourly", currency: "PLN", hourly_pln: 140 },
      client_rate: { amount: 182, unit: "hourly", currency: "PLN", hourly_pln: 182 },
    },
  ],
  last_contract: {
    client_name: "Ubezpieczenia Delta",
    status: "ended",
    start_date: "2024-03-01",
    end_date: "2026-02-28",
    cost_hourly: 125,
    redacted: false,
  },
  fix_options: FIX_OPTIONS,
};

const QUEUE: DlReviewQueue = {
  job_id: JOB_ID,
  cpro_client: false,
  total: 3,
  limit: 50,
  items: [
    {
      candidate_id: CANDIDATE_ID,
      candidate_name: TASK.candidate_name,
      stage_id: STAGE_ID,
      since: TASK.since,
      qc_status: "passed",
      overall_fit: "fit",
      overall_fit_label: "Pasuje",
      requirements_met: 3,
      requirements_total: 4,
      candidate_rate: { amount: 135, unit: "hourly", currency: "PLN", hourly_pln: 135 },
      start: "1 miesiąc",
      risks: CONTEXT.risks,
      fix_rounds: 0,
      task: TASK,
    },
    {
      candidate_id: 103,
      candidate_name: "Piotr Wymyślony",
      stage_id: 9003,
      since: new Date(Date.now() - 50 * 3_600_000).toISOString(),
      qc_status: "overridden",
      overall_fit: "uncertain",
      overall_fit_label: "Nie wiadomo",
      requirements_met: 4,
      requirements_total: 4,
      candidate_rate: { amount: 1100, unit: "daily", currency: "PLN", hourly_pln: 137.5 },
      start: "od zaraz",
      risks: [{ code: "red_flags", label: "Red flags: długi okres wypowiedzenia", severity: "info" }],
      fix_rounds: 1,
      task: { ...TASK, stage_id: 9003, candidate_id: 103, candidate_name: "Piotr Wymyślony" },
    },
    {
      candidate_id: 104,
      candidate_name: "Ewa Fikcyjna",
      stage_id: 9004,
      since: new Date(Date.now() - 4 * 3_600_000).toISOString(),
      qc_status: "failed",
      overall_fit: "miss",
      overall_fit_label: "Nie pasuje",
      requirements_met: 2,
      requirements_total: 4,
      candidate_rate: { amount: 160, unit: "hourly", currency: "PLN", hourly_pln: 160 },
      start: "3 miesiące",
      risks: [
        { code: "qc_failed", label: "CV nie przeszło QC", severity: "high" },
        { code: "over_budget", label: "Stawka ponad budżet o 10 zł/h", severity: "medium" },
      ],
      fix_rounds: 0,
      task: { ...TASK, stage_id: 9004, candidate_id: 104, candidate_name: "Ewa Fikcyjna" },
    },
  ],
};

const RETURNED_FORM: ScreeningFormState = {
  candidate_id: CANDIDATE_ID,
  job_id: JOB_ID,
  version: 4,
  versions_count: 4,
  state_token: "podglad-4",
  editable: true,
  read_only_reason: null,
  read_only_message: null,
  stage_id: STAGE_ID,
  board_column: "verified",
  process_state_version: 6,
  claim: null,
  champion_profile: {
    screening_questions: [
      { id: "q1", question: "Rozwiązanie rozwijane w Javie 17+ i Spring Boot" },
      { id: "q2", question: "Komunikacja między usługami — synchroniczna czy przez kolejki" },
    ],
  },
  sheet: {
    answers: [
      { question_id: "q1", response: "Panel administracyjny, Java 21.", deal_breaker_hit: false },
      { question_id: "q2", response: "REST.", deal_breaker_hit: false },
    ],
    experience_checks: [],
    overall_fit: "fit",
    notes: "",
  } as never,
  sheet_source_stage_id: STAGE_ID,
  legacy_notes: null,
  note_answers: [],
  // Pytania scalone jak na serwerze — blok „Screening” w przeglądzie.
  questions: [
    {
      number: 1,
      question: "Rozwiązanie rozwijane w Javie 17+ i Spring Boot",
      answer: "Panel administracyjny, Java 21.",
      source: "sheet",
      question_id: "q1",
      deal_breaker: "Wyłącznie utrzymanie aplikacji.",
      deal_breaker_hit: false,
    },
    {
      number: 2,
      question: "Komunikacja między usługami — synchroniczna czy przez kolejki",
      answer: "REST.",
      source: "sheet",
      question_id: "q2",
      deal_breaker: null,
      deal_breaker_hit: false,
    },
  ],
  card: {
    fields: {
      availability: { raw: "1 miesiąc", source: "manual", by_name: "Marta Testowa" },
      work_mode: { raw: "hybrydowo, 2 dni w tygodniu, Łódź", source: "note", note_id: 1 },
      location: { raw: "Łódź", source: "note", note_id: 1 },
      nationality: { raw: "polska", source: "note", note_id: 1 },
      worked_at_client: { raw: "nie", value: "no", source: "note", note_id: 1 },
      english: { raw: "C1", level: "C1", source: "manual", by_name: "Marta Testowa" },
      recommendation: { raw: "Dziewięć lat w Javie, trzy w bankowości.", source: "manual", by_name: "Marta Testowa" },
    },
    previous: {},
    suggestions: {},
    // Stawka stoi na etapie, więc liczy się jako wypełnione pole (8 z 10).
    completeness: { status: "partial", filled: 8, total: 10, missing: ["red_flags", "motivation"] },
    labels: { ...LABELS, recommendation: "Dlaczego ten kandydat" },
    editable_fields: Object.keys(LABELS).filter((k) => k !== "rate" && k !== "client_manager"),
  },
  rate: { amount: 135, unit: "hourly", currency: "PLN", source: "stage", at: "2026-10-07T10:00:00Z" },
  rate_hints: { card: null, rate_from: { amount: 110, unit: "hourly", currency: "PLN" } },
  rate_change_notifies: true,
  can_edit_rate: true,
  suggestions_from_notes: {},
  assist_enabled: false,
  phrase_language: "pl",
  fix_request: {
    version_no: 4,
    stage_id: STAGE_ID,
    requested_at: "2026-10-08T08:30:00Z",
    requested_by_name: "Dorota Delivery",
    remark: "Dopisz, jak używał Kafki, i potwierdź stawkę — klient ma budżet do 150.",
    fields: [
      { key: "question:q2", label: "Pytanie 2: Komunikacja między usługami", changed: false },
      { key: "field:availability", label: "Dostępność", changed: true },
      { key: "candidate_rate", label: "Stawka kandydata", changed: false },
      { key: "cv", label: "CV firmowe", changed: false },
    ],
    count: 4,
    changed_count: 1,
  },
  handback_stage_def_id: 303,
};

function seededClient(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { staleTime: Infinity, retry: false, refetchOnMount: false, refetchOnWindowFocus: false },
    },
  });
  // Znacznik w przyszłości: zapytania z własnym `staleTime` nie odświeżają się.
  const fresh = { updatedAt: Date.now() + 24 * 60 * 60 * 1000 };
  qc.setQueryData(
    candidateQueryKeys.quickView(CANDIDATE_ID),
    {
      candidate: {
        city: "Łódź",
        expected_rate_hourly: 135,
        expected_rate_currency: "PLN",
        // „Stawka od” (0414): rok temu zgodził się na 110 na inną rolę.
        rate_from_hourly: 110,
      },
      current_position: { title: "Senior Java Developer" },
      availability: {
        status: "open_to_offers",
        available_from: null,
        notice_period: 1,
        notice_period_unit: "months",
      },
    },
    fresh,
  );
  // CV firmowe: jeden gotowy dokument — jego plik podaje interceptor niżej.
  qc.setQueryData(
    ["cv-generated", "dl-review", CANDIDATE_ID, JOB_ID],
    [
      {
        id: GENERATED_CV_ID,
        status: "ready",
        filename: "Tomasz Wzorcowy — CV B2B.docx",
        origin: "auto",
        needs_review: true,
      },
    ],
    fresh,
  );
  // CV oryginalne i inne pliki kandydata (przełącznik nad CV).
  qc.setQueryData(["cv-original", STAGE_ID], SNAPSHOT, fresh);
  qc.setQueryData(candidateQueryKeys.cvDocuments(CANDIDATE_ID), DOCUMENTS, fresh);
  qc.setQueryData(stageBrandedQueryKey(STAGE_ID), BRANDED_NONE, fresh);
  qc.setQueryData(recommendationCardQueryKey(CANDIDATE_ID, JOB_ID), CARD, fresh);
  qc.setQueryData(dlReviewContextQueryKey(JOB_ID, CANDIDATE_ID), CONTEXT, fresh);
  qc.setQueryData(dlReviewQueueQueryKey(JOB_ID), QUEUE, fresh);
  qc.setQueryData(screeningFormQueryKey(JOB_ID, CANDIDATE_ID), RETURNED_FORM, fresh);
  qc.setQueryData(
    reassignContextQueryKey(STAGE_ID),
    { stage_id: STAGE_ID, available: false, source: null, previous_answers_count: 0 },
    fresh,
  );
  qc.setQueryData(
    ["job-rejection-reasons", JOB_ID],
    [
      { id: "5", label: "Stawka ponad budżet klienta", applies_to: ["rejected"], disqualifies_person: false },
      { id: "6", label: "Brak wymaganej technologii", applies_to: ["rejected"], disqualifies_person: false },
    ],
    fresh,
  );
  return qc;
}

export default function DlReviewPreviewPage() {
  const [client, setClient] = useState<QueryClient | null>(null);
  const [canSend, setCanSend] = useState(true);
  const [view, setView] = useState<"review" | "queue" | "returned">("review");
  const [inPanel, setInPanel] = useState(false);
  const [task, setTask] = useState<BoardTaskRow>(TASK);

  useEffect(() => {
    const blocker = api.interceptors.request.use((config) => {
      // Plik CV firmowego: statyczny DOCX zamiast API (podgląd i „Pobierz DOCX”).
      if ((config.method ?? "get").toLowerCase() === "get" && config.url === COMPANY_CV_URL) {
        config.adapter = async () => {
          const response = await fetch(COMPANY_CV_FILE);
          if (!response.ok) {
            throw new AxiosError(`preview: HTTP ${response.status}`, "ERR_BAD_RESPONSE", config);
          }
          return { data: await response.blob(), status: 200, statusText: "OK", headers: {}, config };
        };
        return config;
      }
      return Promise.reject(new AxiosError("preview: sieć wyłączona", "ECONNABORTED", config));
    });
    const params = new URLSearchParams(window.location.search);
    const state = params.get("state");
    setView(state === "queue" ? "queue" : state === "returned" ? "returned" : "review");
    setInPanel(params.get("layout") === "panel");
    const recruiter = params.get("as") === "recruiter" || state === "returned";
    useAuthStore.setState({
      user: {
        id: 1,
        email: "preview@example.com",
        name: recruiter ? "Preview Rekruter" : "Preview Delivery Lead",
        role: recruiter ? "recruiter" : "delivery_lead",
        roles: [recruiter ? "recruiter" : "delivery_lead"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
      } as never,
      realUser: null,
      hydrated: true,
    });
    setCanSend(!recruiter);
    setClient(seededClient());
    return () => api.interceptors.request.eject(blocker);
  }, []);

  if (!client) return null;
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        {view === "returned" ? (
          <main className="mx-auto max-w-3xl p-4 sm:p-6">
            <p className="mb-3 text-sm text-muted-foreground">
              Harness: formularz rekrutera po „Wróć do poprawy” — zapis nie trafia do API.
            </p>
            <ScreeningFullForm
              candidateId={CANDIDATE_ID}
              jobId={JOB_ID}
              candidateName={TASK.candidate_name}
              jobBudgetHourly={150}
              showHistory={false}
            />
          </main>
        ) : (
          <>
            {inPanel && view === "review" ? (
              <main className="p-3 sm:p-4">
                <p className="mb-3 text-sm text-muted-foreground">
                  Harness przeglądu Delivery Leada w panelu na całą szerokość (jak na Tablicy). Zmień
                  szerokość okna: poniżej 1100 px jedna kolumna, do 1639 px CV i decyzja z zakładką
                  wymagań, szerzej trzy kolumny. Decyzje nie są wysyłane (sieć odcięta).
                </p>
                {/* Ramka zamiast przyklejonego panelu: ta sama wysokość „do dołu okna”. */}
                <div className="h-[calc(100dvh-8rem)] min-h-[32rem] w-full overflow-hidden rounded-lg border border-border">
                  <DlReviewBody
                    task={task}
                    canSendToClient={canSend}
                    onClose={() => undefined}
                    layout="panel"
                    previewLoaders={PREVIEW_LOADERS}
                  />
                </div>
              </main>
            ) : (
              <main className="p-6 text-sm text-muted-foreground">
                Harness przeglądu Delivery Leada — panel jest otwarty po prawej. Decyzje nie
                są wysyłane (sieć odcięta).
              </main>
            )}
            <DlReviewPanel
              task={task}
              open={view === "review" && !inPanel}
              onOpenChange={() => undefined}
              canSendToClient={canSend}
              previewLoaders={PREVIEW_LOADERS}
            />
            <DlReviewQueueDialog
              jobId={JOB_ID}
              jobTitle={TASK.job_working_title}
              open={view === "queue"}
              onOpenChange={() => undefined}
              onReview={(next) => {
                setTask(next);
                setView("review");
              }}
            />
          </>
        )}
      </ToastProvider>
    </QueryClientProvider>
  );
}
