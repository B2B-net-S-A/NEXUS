"use client";

// Publiczny harness pasa „Do wysłania do klienta” (13.10.2026) — sam pas
// Delivery Leada, bez reszty pulpitu. Dane fikcyjne, ZERO zapytań do API:
// kolejka i przegląd każdej osoby są zasiane ze znacznikiem czasu w przyszłości,
// sieć odcina interceptor, a pliki CV to pliki statyczne
// (`public/preview/cv-search/`).
// `?state=filled` (domyślnie) — cztery gotowe osoby w trzech tonach pilności
//   (po dwie z jednej rekrutacji, więc z „porównaj”; jedna ponad budżet, jedna
//   ze stawką dzienną), dwie jeszcze u rekrutera i jedna z importu Traffita.
// `?state=empty` — pusta kolejka: jedno zdanie.
// `?state=sequence` — przegląd „po kolei” otwarty na drugiej osobie („2 z 4”):
//   harness wchodzi linkiem z górnego paska (`?wysylka=po-kolei`), a gdy okno
//   się otworzy, zdejmuje pierwszą osobę z kolejki — jak po wysłaniu jej do
//   klienta. Decyzje nie są wysyłane (sieć odcięta, zapisy blokuje layout).

import { useEffect, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AxiosError } from "axios";

import { ToastProvider } from "@/components/Toast";
import {
  DL_SEND_SEQUENCE_PARAM,
  DL_SEND_SEQUENCE_VALUE,
  DlSendQueueBand,
} from "@/components/v2/dashboard/DlSendQueueBand";
import type { CandidateDocument } from "@/components/v2/files/FilePreviewModal";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import type { CvPreviewLoaders } from "@/components/v2/recruitment/dl-review/CvColumn";
import api, { type CVBrandedState, type CVOriginalSnapshot } from "@/lib/api";
import {
  BOARD_TASKS_QUERY_KEY,
  countsForDlSend,
  type BoardTaskRow,
  type BoardTasksResponse,
  type DlSendQueueResponse,
} from "@/lib/api/boardTasks";
import {
  dlReviewContextQueryKey,
  dlReviewQueueQueryKey,
  type DlReviewContext,
  type DlReviewQueue,
  type DlReviewRate,
} from "@/lib/api/dlReview";
import { recommendationCardQueryKey, type RecommendationCard } from "@/lib/api/recommendationCards";
import { screeningFormQueryKey, type ScreeningFormState } from "@/lib/api/screeningForm";
import { stageBrandedQueryKey } from "@/lib/cv-to-client";
import { useUrlWriter } from "@/lib/url-selection";
import { coverSheetKey } from "@/lib/api/coverSheet";
import { DlSendPanel, DlSendPill } from "@/components/v2/shell/DlSendTopbarButton";
import { useAuthStore } from "@/store/auth";

type State = "filled" | "empty" | "sequence" | "topbar";

const STATE_LABEL: Record<State, string> = {
  filled: "Kolejka",
  empty: "Pusta kolejka",
  sequence: "Przegląd po kolei",
  topbar: "Górny pasek",
};

function parseState(value: string | null): State {
  return value === "empty" || value === "sequence" || value === "topbar" ? value : "filled";
}

const hoursAgo = (h: number) => new Date(Date.now() - h * 3_600_000).toISOString();
const daysAgo = (d: number) => hoursAgo(d * 24);
const dayAhead = (d: number) => new Date(Date.now() + d * 86_400_000).toISOString().slice(0, 10);

// ── Kolejka ──────────────────────────────────────────────────────────────────

const JAVA_JOB = 4101;
const DATA_JOB = 4102;
const DEVOPS_JOB = 4103;
const TESTER_JOB = 4104;

/** Pierwsza osoba przeglądu po kolei — stan `sequence` zdejmuje ją z kolejki. */
const FIRST_STAGE_ID = 9101;

function taskRow(
  over: Partial<BoardTaskRow> & Pick<BoardTaskRow, "stage_id" | "candidate_id" | "candidate_name">,
): BoardTaskRow {
  return {
    kind: "dl_review",
    job_id: JAVA_JOB,
    job_title: "Java Developer (ZOB-0001)",
    job_working_title: "Java · Spring · Kafka",
    client_id: 7,
    client_name: "Bank Północny",
    since: daysAgo(1),
    process_state_version: 4,
    target_stage_def_id: 305,
    rejected_stage_def_id: 399,
    return_stage_def_id: 302,
    assignee_id: null,
    assignee_name: null,
    verified_by_id: 3,
    verified_by_name: "Olga Przykładowa",
    verified_at: daysAgo(2),
    expected_rate_value: 150,
    expected_rate_unit: "hourly",
    expected_rate_currency: "PLN",
    screening_stage_id: over.stage_id,
    qc_status: "passed",
    qc_blocking_failed: 0,
    card_status: "complete",
    card_missing: 0,
    ready: true,
    ready_since: daysAgo(1),
    waiting_workdays: 1,
    urgency: "due",
    imported: false,
    handed_over_by_name: "Olga Przykładowa",
    budget_min_hourly: null,
    budget_max_hourly: 170,
    deadline: dayAhead(11),
    ...over,
  };
}

// Rekrutacja „nordycka” (fikcyjna): od 13.10.2026 przegląd kończy tu
// akceptacja do kolejki Cpro — wiersz z plakietką „do Cpro” i przyciskiem
// „Przejrzyj → Cpro” (14.10.2026).
const DATA_ROW: Partial<BoardTaskRow> = {
  job_id: DATA_JOB,
  job_title: "Analityk danych (ZOB-0002)",
  job_working_title: "Analityk danych · SQL, Power BI",
  client_id: 8,
  client_name: "Bank Nordycki",
  cpro: true,
  target_stage_def_id: 304,
  budget_min_hourly: 110,
  budget_max_hourly: 130,
  deadline: dayAhead(18),
};

// Kolejność jak z serwera nie ma znaczenia — pas sam układa gotowych od
// najdłużej czekającej osoby.
const ROWS: BoardTaskRow[] = [
  taskRow({
    stage_id: FIRST_STAGE_ID,
    candidate_id: 3101,
    candidate_name: "Marta Wzorcowa",
    since: daysAgo(8),
    ready_since: daysAgo(6),
    waiting_workdays: 4,
    urgency: "late",
  }),
  taskRow({
    ...DATA_ROW,
    stage_id: 9102,
    candidate_id: 3102,
    candidate_name: "Tomasz Makietowy",
    since: daysAgo(3),
    ready_since: daysAgo(3),
    waiting_workdays: 1,
    urgency: "due",
    expected_rate_value: 120,
    card_status: "partial",
    card_missing: 1,
  }),
  taskRow({
    ...DATA_ROW,
    stage_id: 9103,
    candidate_id: 3103,
    candidate_name: "Adam Fikcyjny",
    ready_since: daysAgo(1),
    waiting_workdays: 0,
    urgency: "fresh",
    expected_rate_value: 135,
    handed_over_by_name: "Kamil Przykładowy",
  }),
  taskRow({
    stage_id: 9104,
    candidate_id: 3104,
    candidate_name: "Lena Przykładowa",
    since: daysAgo(0),
    ready_since: hoursAgo(2),
    waiting_workdays: 0,
    urgency: "fresh",
    expected_rate_value: 1100,
    expected_rate_unit: "daily",
    qc_status: "overridden",
    card_status: null,
    handed_over_by_name: "Kamil Przykładowy",
  }),
  taskRow({
    stage_id: 9105,
    candidate_id: 3105,
    candidate_name: "Paweł Zmyślony",
    since: daysAgo(5),
    ready: false,
    ready_since: null,
    waiting_workdays: 0,
    urgency: null,
    expected_rate_value: 145,
    qc_status: "failed",
    qc_blocking_failed: 2,
    card_status: "partial",
    card_missing: 2,
  }),
  taskRow({
    stage_id: 9106,
    candidate_id: 3106,
    candidate_name: "Karolina Testowa",
    job_id: DEVOPS_JOB,
    job_title: "DevOps Engineer (ZOB-0003)",
    job_working_title: "DevOps · Azure, Terraform",
    client_id: 9,
    client_name: "Ubezpieczenia Wzorcowe",
    since: daysAgo(2),
    ready: false,
    ready_since: null,
    waiting_workdays: 0,
    urgency: null,
    expected_rate_value: 140,
    qc_status: "unchecked",
    handed_over_by_name: "Kamil Przykładowy",
    budget_max_hourly: 160,
    deadline: null,
  }),
  taskRow({
    stage_id: 9107,
    candidate_id: 3107,
    candidate_name: "Igor Przeniesiony",
    job_id: TESTER_JOB,
    job_title: "Tester automatyzujący (ZOB-0004)",
    job_working_title: null,
    since: daysAgo(40),
    ready: false,
    ready_since: null,
    waiting_workdays: 0,
    urgency: null,
    imported: true,
    expected_rate_value: null,
    expected_rate_unit: null,
    expected_rate_currency: null,
    qc_status: "unchecked",
    card_status: null,
    handed_over_by_name: null,
    verified_by_id: null,
    verified_by_name: null,
    verified_at: null,
    budget_max_hourly: null,
    deadline: null,
  }),
];

function boardTasks(rows: BoardTaskRow[]): BoardTasksResponse {
  return {
    window_days: 14,
    dl_review_window_days: 30,
    can_send_to_client: true,
    cpro_to_send: [],
    cpro_sent: [],
    dl_review: rows,
  };
}

// ── Przegląd jednej osoby (każdy wiersz otwiera się bez sieci) ───────────────

const GENERATED_CV_ID = 77;
const COMPANY_CV_URL = `/api/cv-generator/generated/${GENERATED_CV_ID}/docx`;
const COMPANY_CV_FILE = "/preview/cv-search/cv.docx";
const ORIGINAL_CV_FILE = "/preview/cv-search/cv-tekst.pdf";

async function loadStaticFile(path: string): Promise<Blob> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.blob();
}

const PREVIEW_LOADERS: CvPreviewLoaders = {
  loadDocumentBlob: (_candidateId, docId) => loadStaticFile(docId === 3 ? COMPANY_CV_FILE : ORIGINAL_CV_FILE),
  loadOriginalBlob: () => loadStaticFile(ORIGINAL_CV_FILE),
};

function cvDocuments(row: BoardTaskRow): CandidateDocument[] {
  const base = {
    size_bytes: null,
    document_kind: "cv" as const,
    uploaded_at: "2026-10-01T08:00:00Z",
    external_source: null,
    created_at: "2026-10-01T08:00:00Z",
  };
  return [
    { ...base, id: 1, filename: `${row.candidate_name} — CV.pdf`, content_type: "application/pdf", is_primary: true },
    {
      ...base,
      id: 3,
      filename: `${row.candidate_name} — CV.docx`,
      content_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      is_primary: false,
    },
  ];
}

function cvSnapshot(row: BoardTaskRow): CVOriginalSnapshot {
  return {
    candidate_stage_id: row.stage_id,
    candidate_id: row.candidate_id,
    job_id: row.job_id,
    has_snapshot: true,
    original_cv_filename: `${row.candidate_name} — CV.pdf`,
    original_cv_language: "pl",
    original_snapshot_at: "2026-10-05T08:00:00Z",
    original_snapshot_source: "application",
    download_url: null,
  };
}

function brandedNone(row: BoardTaskRow): CVBrandedState {
  return {
    edit_revision: 0,
    version: 0,
    candidate_stage_id: row.stage_id,
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
}

function candidateRate(row: BoardTaskRow): DlReviewRate | null {
  const amount = row.expected_rate_value;
  const unit = row.expected_rate_unit;
  if (amount == null || !unit) return null;
  const hourly = unit === "hourly" ? amount : unit === "daily" ? amount / 8 : amount / 168;
  return { amount, unit, currency: "PLN", hourly_pln: Math.round(hourly * 100) / 100 };
}

const QUESTIONS = [
  {
    id: "q1",
    question: "Rozwiązanie rozwijane w ostatnim projekcie",
    answer: "System rozliczeń — rozwój i utrzymanie, zespół sześciu osób.",
  },
  {
    id: "q2",
    question: "Praca z danymi — hurtownia czy systemy transakcyjne",
    answer: "Głównie systemy transakcyjne, raporty w hurtowni.",
  },
];

const CARD_LABELS = {
  rate: "Stawka",
  availability: "Dostępność",
  work_mode: "Tryb pracy",
  location: "Lokalizacja",
  english: "Angielski",
  red_flags: "Red flags",
  recommendation: "Dlaczego ten kandydat",
  motivation: "Motywacja",
};

const CARD_FIELDS = {
  availability: { raw: "1 miesiąc", source: "manual" as const, by_name: "Olga Przykładowa" },
  work_mode: { raw: "hybrydowo, 2 dni w tygodniu", source: "manual" as const, by_name: "Olga Przykładowa" },
  location: { raw: "Łódź", source: "manual" as const, by_name: "Olga Przykładowa" },
  english: { raw: "C1", level: "C1", source: "manual" as const, by_name: "Olga Przykładowa" },
  recommendation: {
    raw: "Samodzielna osoba z doświadczeniem w sektorze finansowym, dobrze wypadła w rozmowie.",
    source: "manual" as const,
    by_name: "Olga Przykładowa",
  },
};

function reviewContext(row: BoardTaskRow): DlReviewContext {
  return {
    candidate_id: row.candidate_id,
    candidate_name: row.candidate_name,
    job_id: row.job_id,
    stage_id: row.stage_id,
    client_id: row.client_id,
    client_name: row.client_name,
    category_name: "Rozwój oprogramowania",
    qc_status: row.qc_status ?? "unchecked",
    qc_blocking_failed: row.qc_blocking_failed ?? 0,
    qc_override:
      row.qc_status === "overridden"
        ? {
            reason: "Brak daty w jednej roli potwierdzony z kandydatem — klient zna tę osobę.",
            by_name: row.handed_over_by_name ?? null,
            at: row.ready_since ?? row.since,
          }
        : null,
    can_see_amounts: true,
    can_see_client_rates: true,
    candidate_rate: candidateRate(row),
    rate_from_hourly: null,
    budget: { min_hourly: row.budget_min_hourly ?? null, max_hourly: row.budget_max_hourly ?? null },
    client_rate_hint: null,
    client_rates: null,
    requirements: [
      { key: "must:0", label: "Doświadczenie w sektorze finansowym", level: "critical", status: "met", sources: ["CV", "rozmowa"], candidate_value: "…trzy lata w zespole rozliczeń…" },
      { key: "must:1", label: "SQL", level: "must", status: "met", sources: ["CV"], candidate_value: "…zapytania analityczne, optymalizacja…" },
      { key: "must:2", label: "Praca w zespole zwinnym", level: "must", status: "met", sources: ["notatka"], candidate_value: "Scrum, dwutygodniowe sprinty" },
      { key: "must:3", label: "Angielski B2", level: "must", status: "missing", sources: [], candidate_value: null },
      { key: "nice:0", label: "Chmura", level: "nice", status: "unknown", sources: [], candidate_value: null },
    ],
    requirements_met: 3,
    requirements_total: 4,
    assessment: {
      overall_fit: "fit",
      overall_fit_label: "Pasuje",
      fields: {
        recommendation: CARD_FIELDS.recommendation.raw,
        motivation: null,
        red_flags: null,
        availability: CARD_FIELDS.availability.raw,
        work_mode: CARD_FIELDS.work_mode.raw,
        location: CARD_FIELDS.location.raw,
        english: CARD_FIELDS.english.raw,
      },
      answers: QUESTIONS.map((q) => ({
        question: q.question,
        question_id: q.id,
        answer: q.answer,
        deal_breaker_hit: false,
      })),
    },
    risks: [],
    start: CARD_FIELDS.availability.raw,
    fix_rounds: 0,
    previous_sends: [],
    job_sends: [],
    last_contract: null,
    fix_options: [
      { key: "question:q1", label: `Pytanie 1: ${QUESTIONS[0].question}`, group: "answers" },
      { key: "field:availability", label: "Dostępność", group: "terms" },
      { key: "field:recommendation", label: "Dlaczego ten kandydat", group: "assessment" },
      { key: "candidate_rate", label: "Stawka kandydata", group: "rate" },
      { key: "cv", label: "CV firmowe", group: "cv" },
    ],
  };
}

function screeningForm(row: BoardTaskRow): ScreeningFormState {
  const rate = candidateRate(row);
  return {
    candidate_id: row.candidate_id,
    job_id: row.job_id,
    version: 2,
    versions_count: 2,
    state_token: `podglad-${row.stage_id}`,
    editable: false,
    read_only_reason: null,
    read_only_message: null,
    stage_id: row.stage_id,
    board_column: "cv_qc",
    process_state_version: row.process_state_version,
    claim: null,
    champion_profile: {
      screening_questions: QUESTIONS.map((q) => ({ id: q.id, question: q.question })),
    },
    sheet: {
      answers: QUESTIONS.map((q) => ({ question_id: q.id, response: q.answer, deal_breaker_hit: false })),
      experience_checks: [],
      overall_fit: "fit",
      notes: "",
    } as never,
    sheet_source_stage_id: row.stage_id,
    legacy_notes: null,
    note_answers: [],
    questions: QUESTIONS.map((q, index) => ({
      number: index + 1,
      question: q.question,
      answer: q.answer,
      source: "sheet" as const,
      question_id: q.id,
      deal_breaker: null,
      deal_breaker_hit: false,
    })),
    card: {
      fields: CARD_FIELDS,
      previous: {},
      suggestions: {},
      completeness: { status: "partial", filled: 6, total: 8, missing: ["red_flags", "motivation"] },
      labels: CARD_LABELS,
      editable_fields: Object.keys(CARD_LABELS).filter((key) => key !== "rate"),
    },
    rate: rate ? { amount: rate.amount, unit: rate.unit, currency: "PLN", source: "stage", at: row.verified_at ?? null } : null,
    rate_hints: { card: null, rate_from: null },
    rate_change_notifies: true,
    can_edit_rate: false,
    suggestions_from_notes: {},
    assist_enabled: false,
    phrase_language: "pl",
  };
}

function recommendationCard(row: BoardTaskRow): RecommendationCard {
  return {
    candidate_id: row.candidate_id,
    job_id: row.job_id,
    exists: true,
    fields: CARD_FIELDS,
    previous: {},
    suggestions: {},
    questions: QUESTIONS.map((q, index) => ({
      number: index + 1,
      question: q.question,
      answer: q.answer,
      source: "sheet" as const,
    })),
    completeness: { status: "partial", filled: 6, total: 8, missing: ["red_flags", "motivation"] },
    labels: CARD_LABELS,
    editable_fields: Object.keys(CARD_LABELS),
    legacy_text: `Dostępność: ${CARD_FIELDS.availability.raw}\nAngielski: ${CARD_FIELDS.english.raw}\n\nP1: ${QUESTIONS[0].question}\nO: ${QUESTIONS[0].answer}`,
    updated_at: "2026-10-08T10:00:00Z",
  };
}

/** „porównaj” — gotowe osoby jednej rekrutacji obok siebie. */
function compareQueue(jobId: number, rows: BoardTaskRow[]): DlReviewQueue {
  const items = rows.filter((row) => row.job_id === jobId && countsForDlSend(row));
  return {
    job_id: jobId,
    cpro_client: false,
    total: items.length,
    limit: 50,
    items: items.map((task) => ({
      candidate_id: task.candidate_id,
      candidate_name: task.candidate_name,
      stage_id: task.stage_id,
      since: task.ready_since ?? task.since,
      qc_status: task.qc_status ?? null,
      overall_fit: "fit" as const,
      overall_fit_label: "Pasuje",
      requirements_met: 3,
      requirements_total: 4,
      candidate_rate: candidateRate(task),
      start: CARD_FIELDS.availability.raw,
      risks: [],
      fix_rounds: 0,
      task,
    })),
  };
}

// Znacznik w przyszłości: zapytania z własnym `staleTime` nie odświeżają się.
const freshSeed = () => ({ updatedAt: Date.now() + 24 * 60 * 60 * 1000 });

function seededClient(state: State): QueryClient {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { staleTime: Infinity, retry: false, refetchOnMount: false, refetchOnWindowFocus: false },
    },
  });
  const fresh = freshSeed();
  const rows = state === "empty" ? [] : ROWS;
  qc.setQueryData<BoardTasksResponse>(BOARD_TASKS_QUERY_KEY, boardTasks(rows), fresh);
  for (const row of rows) {
    qc.setQueryData(
      candidateQueryKeys.quickView(row.candidate_id),
      {
        candidate: { city: "Łódź", expected_rate_hourly: null, expected_rate_currency: "PLN" },
        current_position: { title: row.job_working_title ?? row.job_title },
        availability: { status: "open_to_offers", available_from: null, notice_period: 1, notice_period_unit: "months" },
      },
      fresh,
    );
    // CV firmowe: jeden gotowy dokument — jego plik podaje interceptor niżej.
    qc.setQueryData(
      ["cv-generated", "dl-review", row.candidate_id, row.job_id],
      [{ id: GENERATED_CV_ID, status: "ready", filename: `${row.candidate_name} — CV B2B.docx`, origin: "auto", needs_review: false }],
      fresh,
    );
    qc.setQueryData(["cv-original", row.stage_id], cvSnapshot(row), fresh);
    qc.setQueryData(candidateQueryKeys.cvDocuments(row.candidate_id), cvDocuments(row), fresh);
    qc.setQueryData(stageBrandedQueryKey(row.stage_id), brandedNone(row), fresh);
    qc.setQueryData(dlReviewContextQueryKey(row.job_id, row.candidate_id), reviewContext(row), fresh);
    qc.setQueryData(coverSheetKey(row.candidate_id, row.job_id), { enabled: false }, fresh);
    qc.setQueryData(screeningFormQueryKey(row.job_id, row.candidate_id), screeningForm(row), fresh);
    qc.setQueryData(recommendationCardQueryKey(row.candidate_id, row.job_id), recommendationCard(row), fresh);
    qc.setQueryData(
      ["job-rejection-reasons", row.job_id],
      [
        { id: "5", label: "Stawka ponad budżet klienta", applies_to: ["rejected"], disqualifies_person: false },
        { id: "6", label: "Brak wymaganej technologii", applies_to: ["rejected"], disqualifies_person: false },
      ],
      fresh,
    );
    qc.setQueryData(dlReviewQueueQueryKey(row.job_id), compareQueue(row.job_id, rows), fresh);
  }
  return qc;
}

/**
 * Stan `sequence`: wejście linkiem z górnego paska uruchamia przegląd po kolei
 * („1 z 4”). Gdy okno się otworzy, pierwsza osoba znika z kolejki — tak wygląda
 * lista po wysłaniu jej do klienta — i przegląd stoi na drugiej („2 z 4”).
 * Adres zmienia dziecko strony po jej zamontowaniu, kiedy router Next ma już
 * historię przeglądarki (patrz `useUrlWriter`).
 */
function SequenceAtSecondPerson({ client }: { client: QueryClient }) {
  const { replaceUrl } = useUrlWriter();
  useEffect(() => {
    replaceUrl(
      `${window.location.pathname}?state=sequence&${DL_SEND_SEQUENCE_PARAM}=${DL_SEND_SEQUENCE_VALUE}`,
    );
    const observer = new MutationObserver(() => {
      if (!document.querySelector("[data-testid='dl-review-sequence']")) return;
      observer.disconnect();
      client.setQueryData<BoardTasksResponse>(
        BOARD_TASKS_QUERY_KEY,
        boardTasks(ROWS.filter((row) => row.stage_id !== FIRST_STAGE_ID)),
        freshSeed(),
      );
    });
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [client, replaceUrl]);
  return null;
}

// ── Górny pasek ──────────────────────────────────────────────────────────────

const TOPBAR_QUEUE: DlSendQueueResponse = {
  ready: [
    {
      stage_id: 9101,
      candidate_id: 8101,
      candidate_name: "Marta Przykładowa",
      job_id: 7101,
      job_title: "Java Developer",
      job_working_title: null,
      client_name: "Bank Przykładowy",
      ready_since: daysAgo(6),
      waiting_workdays: 4,
      urgency: "late",
      handed_over_by_name: "Ola Rekruterska",
    },
    {
      stage_id: 9102,
      candidate_id: 8102,
      candidate_name: "Tomasz Testowy",
      job_id: 7102,
      job_title: "Analityk danych",
      job_working_title: null,
      client_name: "Telko Przykładowe",
      ready_since: daysAgo(1),
      waiting_workdays: 1,
      urgency: "due",
      handed_over_by_name: "Kamil Rekruterski",
    },
    {
      stage_id: 9103,
      candidate_id: 8103,
      candidate_name: "Adam Fikcyjny",
      job_id: 7103,
      job_title: "Analityk danych (ZOB-0002)",
      job_working_title: "Analityk danych · SQL, Power BI",
      client_name: "Bank Nordycki",
      ready_since: hoursAgo(2),
      waiting_workdays: 0,
      urgency: "fresh",
      handed_over_by_name: "Ola Rekruterska",
      // Klient z kolejką Cpro: plakietka „do Cpro” przy nazwisku (14.10.2026).
      cpro: true,
    },
  ],
  ready_total: 3,
  not_ready_total: 2,
  imported_total: 1,
  worst_urgency: "late",
};

/** Pigułka w trzech tonach i okienko — same komponenty prezentacyjne, bez zapytań. */
function TopbarStates() {
  return (
    <div className="flex flex-wrap items-start gap-6 border-b border-border px-6 py-4">
      <div className="flex flex-wrap items-center gap-3">
        <DlSendPill total={2} urgency="fresh" />
        <DlSendPill total={5} urgency="due" />
        <DlSendPill total={12} urgency="late" />
      </div>
      <div className="w-96 max-w-full overflow-hidden rounded-md border border-border bg-popover shadow-md">
        <DlSendPanel queue={TOPBAR_QUEUE} onNavigate={() => undefined} />
      </div>
    </div>
  );
}

export default function DlSendPreviewPage() {
  const [state, setState] = useState<State | null>(null);
  const [client, setClient] = useState<QueryClient | null>(null);

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
    const next = parseState(new URLSearchParams(window.location.search).get("state"));
    useAuthStore.setState({
      user: {
        id: 1,
        email: "preview@example.com",
        name: "Preview Delivery Lead",
        role: "delivery_lead",
        roles: ["delivery_lead"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
      } as never,
      realUser: null,
      hydrated: true,
    });
    setClient(seededClient(next));
    setState(next);
    return () => api.interceptors.request.eject(blocker);
  }, []);

  if (!state || !client) return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;

  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <div className="min-h-dvh bg-background">
          <div className="flex flex-wrap gap-x-3 gap-y-1 border-b border-border px-6 py-3 text-sm">
            <span className="text-muted-foreground">Podgląd pasa „Do wysłania do klienta”:</span>
            {(Object.keys(STATE_LABEL) as State[]).map((key) => (
              <a
                key={key}
                href={`?state=${key}`}
                aria-current={state === key ? "page" : undefined}
                className={state === key ? "font-semibold text-primary" : "hover:underline"}
              >
                {STATE_LABEL[key]}
              </a>
            ))}
          </div>

          {/* Licznik z górnego paska: trzy tony pilności i otwarte okienko. */}
          {state === "topbar" ? <TopbarStates /> : null}

          {/* Padding powłoki (`<main>` ma `p-4 md:p-6`) — pas nie dokłada własnego. */}
          <div className="p-4 md:p-6">
            <DlSendQueueBand previewLoaders={PREVIEW_LOADERS} />
          </div>
          {state === "sequence" ? <SequenceAtSecondPerson client={client} /> : null}
        </div>
      </ToastProvider>
    </QueryClientProvider>
  );
}
