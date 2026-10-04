"use client";

// Publiczny harness przeglądu Delivery Leada (03.10.2026): karta rekomendacji
// z odpowiedziami na pytania Championa, „Uwagi dla rekrutera”, stawka do
// klienta i trzy decyzje — „Wróć do poprawy”, „Odrzuć (DL)”, „Wyślij do
// klienta”. Dane fikcyjne, ZERO zapytań: cache react-query jest zasiany ze
// znacznikiem czasu w przyszłości, a sieć odcina interceptor.
// `?as=recruiter` — osoba, która tylko przegląda (bez decyzji).

import { useEffect, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AxiosError } from "axios";

import { ToastProvider } from "@/components/Toast";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { DlReviewPanel } from "@/components/v2/recruitment/DlReviewPanel";
import api from "@/lib/api";
import type { BoardTaskRow } from "@/lib/api/boardTasks";
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
  legacy_text: "",
  updated_at: "2026-09-30T10:00:00Z",
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
  qc.setQueryData(["cv-generated", "dl-review", CANDIDATE_ID, JOB_ID], [], fresh);
  qc.setQueryData(recommendationCardQueryKey(CANDIDATE_ID, JOB_ID), CARD, fresh);
  qc.setQueryData(["pipeline-stage-screening", STAGE_ID], { screening_answers: null }, fresh);
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

  useEffect(() => {
    const blocker = api.interceptors.request.use((config) =>
      Promise.reject(new AxiosError("preview: sieć wyłączona", "ECONNABORTED", config)),
    );
    const recruiter = new URLSearchParams(window.location.search).get("as") === "recruiter";
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
        <main className="p-6 text-sm text-muted-foreground">
          Harness przeglądu Delivery Leada — panel jest otwarty po prawej. Decyzje nie
          są wysyłane (sieć odcięta).
        </main>
        <DlReviewPanel task={TASK} open onOpenChange={() => undefined} canSendToClient={canSend} />
      </ToastProvider>
    </QueryClientProvider>
  );
}
