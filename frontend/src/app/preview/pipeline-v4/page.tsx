"use client";

/**
 * Harness Tablicy Pipeline v4 (23.09.2026) — WYŁĄCZNIE mocki.
 *
 * PRODUKCYJNA `KanbanBoardV2` na szablonie „Default B2B” z kartami, które
 * niosą wszystkie odznaki v4: źródło wejścia, blokadę 12 h (własną, cudzą,
 * wolną), przepięcie, „Czeka na DL”, stawkę do klienta, terminarz rozmowy,
 * brak zamówienia i pasek zamkniętych w czterech grupach. Makieta:
 * https://claude.ai/artifact/JQ8qdz16J6wG24WKTSgv6i
 *
 * Żadne zapytanie nie wychodzi z harnessu (interceptor żądania odrzuca je
 * lokalnie) — sekcje, które same pobierają dane (propozycje na górze Nowych),
 * pokazują wtedy swój stan błędu, a nie przerzucają na /login.
 * `?as=dl` — patrzy Delivery Lead (widzi „Przejmij” na cudzej blokadzie).
 *
 * Screening (02.10.2026): arkusz Zielińskiego ma podpowiedzi z dwóch
 * wcześniejszych rozmów, Dąbrowskiej — z przepięcia (odpowiedź i notatka),
 * a dok Lisa pokazuje zapisane pytania z odpowiedziami. Wszystko z zasianego
 * cache'u (`updatedAt` w przyszłości), bez zapytań.
 */

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import {
  api,
  type ScreeningAnswers,
  type ScreeningReassignContext,
  type ScreeningReassignSuggestion,
  type ScreeningReassignSuggestionsResponse,
  type StageScreeningResponse,
} from "@/lib/api";
import { ToastProvider } from "@/components/Toast";
import { TooltipProvider } from "@/components/ui/tooltip";
import { KanbanBoardV2 } from "@/components/v2/pages/KanbanBoardV2";
import {
  reassignContextQueryKey,
  screeningSuggestionsQueryKey,
} from "@/components/v2/jobs/ScreeningReassignSuggestions";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { screenedOutQueryKey } from "@/lib/api/applicationScreenings";
import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";
import { useAuthStore } from "@/store/auth";

const JOB_ID = 4343;
const HOUR = 3_600_000;

function inHours(h: number): string {
  return new Date(Date.now() + h * HOUR).toISOString();
}

let nextId = 1;
function card(
  first: string,
  last: string,
  extra: Partial<KanbanItem> = {},
): KanbanItem {
  const id = nextId++;
  return {
    id,
    candidate_id: 9000 + id,
    stage: "new",
    name: first,
    lastname: last,
    days_in_stage: 1,
    added_to_job_by_name: "Marta Nowak",
    process_state_version: 1,
    ...extra,
  } as KanbanItem;
}

function col(
  stage: string,
  name: string,
  category: "internal" | "external" | "terminal",
  defId: number,
  items: KanbanItem[],
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

function columns(viewerId: number): KanbanColumn[] {
  nextId = 1;
  return [
    col("posting", "Ogłoszenia", "internal", 10, [
      card("Karolina", "Wiśniewska", { entry_source: "application", can_take: true }),
    ]),
    col("new", "Nowi / Analiza CV", "internal", 11, [
      card("Tomasz", "Zieliński", {
        entry_source: "added_manual",
        claim_user_id: viewerId,
        claim_user_name: "Marta Nowak",
        claim_until: inHours(9.2),
      }),
      card("Paweł", "Fikcyjny", {
        entry_source: "added_manual",
        added_to_job_by_name: "Anna Kowal",
        claim_user_id: 3,
        claim_user_name: "Anna Kowal",
        claim_until: inHours(3.4),
        can_take: viewerId !== 7,
      }),
      card("Marek", "Lis", {
        entry_source: "added_manual",
        added_to_job_by_name: "Piotr Szkicowy",
        can_take: true,
        days_in_stage: 2,
        screening_done: true,
      }),
      card("Ewa", "Dąbrowska", {
        entry_source: "reassign",
        reassign_from_title: "Java Developer · Bank Kappa",
        claim_user_id: viewerId,
        claim_user_name: "Marta Nowak",
        claim_until: inHours(11.5),
      }),
      card("Jakub", "Mazur", { entry_source: "proposal", can_take: true }),
    ]),
    col("screening", "Screening", "internal", 12, []),
    col("verified", "Zweryfikowany", "internal", 13, [
      card("Anna", "Kowalczyk", {
        days_in_stage: 1,
        expected_rate_value: 150,
        expected_rate_unit: "hourly",
        auto_cv_ready: true,
      }),
      card("Michał", "Wójcik", { days_in_stage: 0, auto_cv_ready: true }),
    ]),
    col("interview", "Przepuszczony przez DZ", "internal", 14, []),
    col("new", "Wysłać do Cpro", "internal", 15, []),
    col("cv_sent", "CV Wysłane", "internal", 16, [
      card("Łukasz", "Kamiński", {
        client_rate_value: 165,
        client_rate_unit: "hourly",
        client_rate_currency: "PLN",
        days_in_stage: 5,
      }),
      card("Natalia", "Lewandowska", {
        client_rate_value: 158,
        client_rate_unit: "hourly",
        client_rate_currency: "PLN",
        days_in_stage: 2,
      }),
    ]),
    col("new", "Preparation Meeting", "external", 17, []),
    col("client_interview", "Interview Klient", "external", 18, [
      card("Katarzyna", "Woźniak", {
        interview_badge: { kind: "choose_slot", label: "Wybierz termin · 3 propozycje", tone: "wait" },
      }),
      card("Grzegorz", "Jankowski", {
        interview_badge: {
          kind: "prep_done",
          label: "czw 25.09 · 14:00 · Prep ✓",
          tone: "info",
          steps: [
            { key: "slots", state: "done" },
            { key: "choice", state: "done" },
            { key: "prep", state: "done" },
            { key: "prep2", state: "current" },
            { key: "interview", state: "scheduled" },
            { key: "call", state: "todo" },
            { key: "debrief", state: "todo" },
          ],
        },
      }),
      card("Magdalena", "Pawlak", {
        interview_badge: { kind: "call_due", label: "Zadzwoń · 18 min po rozmowie", tone: "urgent" },
      }),
      card("Tomasz", "Mazur", {
        interview_badge: { kind: "prep_missing", label: "Brak prepu · rozmowa jutro", tone: "urgent" },
      }),
    ]),
    col("acceptance", "Akceptacja", "external", 19, [
      card("Joanna", "Kaczmarek", {
        client_rate_value: 175,
        client_rate_unit: "hourly",
        client_rate_currency: "PLN",
        // Karta przesunięta dalej z zaległym telefonem — odznaka zostaje (24.09.2026).
        interview_badge: {
          kind: "call_due",
          label: "Zadzwoń · debrief zaległy",
          tone: "urgent",
          interview_event_id: 901,
          steps: [
            { key: "slots", state: "done" },
            { key: "choice", state: "done" },
            { key: "prep", state: "skipped" },
            { key: "prep2", state: "skipped" },
            { key: "interview", state: "done" },
            { key: "call", state: "overdue" },
            { key: "debrief", state: "todo" },
          ],
        },
      }),
    ]),
    col("new", "Umowa wysłana", "external", 20, [card("Krzysztof", "Piotrowski", { days_in_stage: 2 })]),
    col("new", "Umowa podpisana", "external", 21, []),
    col("hired", "Zatrudniony", "terminal", 22, [
      card("Agnieszka", "Grabowska", { order_status: "missing" }),
      card("Bartosz", "Zając", { order_status: "complete" }),
    ], "hired"),
    col("onboarding", "Onboarding", "external", 23, []),
    col("rejected", "Odrzucony", "terminal", 24, [
      card("Robert", "Szymański", { ended_by: "client" }),
      card("Dawid", "Król", { ended_by: "recruiter" }),
      card("Iga", "Wrona", { ended_by: null }),
      card("Olek", "Nowy", { ended_by: "delivery_lead" }),
    ], "rejected"),
    col("withdrawn", "Wycofany", "terminal", 25, [card("Zofia", "Kot", { ended_by: "candidate" })], "withdrawn"),
  ];
}

const daysAgo = (days: number): string => new Date(Date.now() - days * 24 * HOUR).toISOString();

const SCREENING_QUESTIONS = [
  {
    id: "q1",
    question: "Czy pracowałeś na mikroserwisach? Na jakiej skali?",
    ideal_answer: "Co najmniej 2 lata, kilka usług na produkcji.",
    deal_breaker: "Brak doświadczenia produkcyjnego.",
  },
  { id: "q2", question: "Od kiedy możesz zacząć?", ideal_answer: "Do 4 tygodni.", deal_breaker: "" },
  {
    id: "q3",
    question: "Ile dni w tygodniu możesz być w biurze w Warszawie?",
    ideal_answer: "2 dni.",
    deal_breaker: "Tylko zdalnie.",
  },
];

/** Zapisany arkusz (dok Lisa): pytania z odpowiedziami, pominięte, sprawdzone w rozmowie. */
const SAVED_SHEET: ScreeningAnswers = {
  answers: [
    {
      question_id: "q1",
      question_text: SCREENING_QUESTIONS[0].question,
      response: "Tak, 4 lata. 20 usług w systemie rozliczeń, Kafka i Spring Boot.",
      deal_breaker_hit: false,
    },
    {
      question_id: "q2",
      question_text: SCREENING_QUESTIONS[1].question,
      response: "Od 1 listopada.",
      deal_breaker_hit: false,
    },
    {
      question_id: "q3",
      question_text: SCREENING_QUESTIONS[2].question,
      response: "",
      deal_breaker_hit: false,
      skipped: true,
    },
  ],
  experience_checks: [{ kind: "domains", name: "Bankowość", status: "confirmed", note: "3 lata" }],
  overall_fit: "fit",
  notes: "Konkretny, podaje liczby.",
  internal_note: null,
  answered_at: daysAgo(1),
  answered_by: 7,
};

const HISTORY_HINTS: ScreeningReassignSuggestion[] = [
  {
    question_id: "q1",
    text: "Tak, 3 lata: 12 usług w systemie płatności, Kafka i Spring Boot.",
    source_kind: "answer",
    source_quote: "12 usług w systemie płatności",
    confidence: "high",
    source: { job_id: 4100, job_title: "Java Developer", client_name: "Telekom Demo", date: daysAgo(49) },
    source_question: "Mikroserwisy — ile lat i jaka skala?",
  },
  {
    question_id: "q3",
    text: "Dwa dni w tygodniu, w Warszawie bez problemu.",
    source_kind: "answer",
    source_quote: "Dwa dni w tygodniu",
    confidence: "high",
    source: { job_id: 4212, job_title: "Backend Engineer", client_name: "Ubezpieczenia Demo", date: daysAgo(12) },
    source_question: "Ile dni w biurze?",
  },
];

const REASSIGN_SOURCE = { job_id: 4100, job_title: "Java Developer · Bank Kappa", date: daysAgo(12) };

const REASSIGN_HINTS: ScreeningReassignSuggestion[] = [
  {
    question_id: "q1",
    text: "Tak, 5 lat. Ostatnio 30 usług, sama prowadziła migrację z monolitu.",
    source_kind: "answer",
    source_quote: "30 usług",
    confidence: "high",
    source: { job_id: 4100, job_title: "Java Developer", client_name: "Bank Kappa", date: daysAgo(12) },
    source_question: SCREENING_QUESTIONS[0].question,
  },
  {
    question_id: "q2",
    text: "Dostępna od połowy października.",
    source_kind: "note",
    source_quote: "kończy projekt 15.10, potem wolna",
    confidence: "medium",
    source: null,
    source_question: null,
  },
];

/** Zasiewa arkusz, kontekst wcześniejszych rozmów i podpowiedzi dla każdej karty. */
function seedScreening(client: QueryClient, cols: KanbanColumn[]) {
  // Hooki mają własne `staleTime` — bez daty w przyszłości odświeżałyby dane.
  const fresh = { updatedAt: Date.now() + 365 * 24 * HOUR };
  for (const column of cols) {
    for (const item of column.items) {
      const history = item.lastname === "Zieliński";
      const reassign = item.lastname === "Dąbrowska";
      const sheet: StageScreeningResponse = {
        stage_id: item.id,
        candidate_id: item.candidate_id,
        job_id: JOB_ID,
        champion_profile: { screening_questions: SCREENING_QUESTIONS } as never,
        screening_answers: item.lastname === "Lis" ? SAVED_SHEET : null,
      };
      client.setQueryData(["screening-v2", item.id], sheet, fresh);
      client.setQueryData(["pipeline-stage-screening", item.id], sheet, fresh);
      const context: ScreeningReassignContext = {
        stage_id: item.id,
        candidate_id: item.candidate_id,
        available: history || reassign,
        kind: reassign ? "reassign" : history ? "history" : null,
        source: reassign ? REASSIGN_SOURCE : null,
        previous_answers_count: history ? 5 : reassign ? 3 : 0,
        earlier_conversations: history ? 2 : reassign ? 1 : 0,
      };
      client.setQueryData(reassignContextQueryKey(item.id), context, fresh);
      if (history || reassign) {
        const hints: ScreeningReassignSuggestionsResponse = {
          stage_id: item.id,
          available: true,
          message: null,
          kind: context.kind,
          source: context.source,
          suggestions: reassign ? REASSIGN_HINTS : HISTORY_HINTS,
        };
        client.setQueryData(screeningSuggestionsQueryKey(item.id), hints, fresh);
      }
    }
  }
}

function useNetworkBlocked() {
  const [interceptorId] = useState(() =>
    api.interceptors.request.use(() =>
      Promise.reject(
        Object.assign(new Error("Harness /preview/pipeline-v4 nie wysyła zapytań."), {
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

function PipelineV4Harness() {
  useNetworkBlocked();
  const params = useSearchParams();
  const asDl = params.get("as") === "dl";
  const viewerId = asDl ? 5 : 7;
  const [client] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } }),
  );
  const [ready, setReady] = useState(false);
  useEffect(() => {
    // Pełny profil: bez `profile_completed` powłoka przerzuca na /onboarding.
    useAuthStore.setState({
      user: {
        id: viewerId,
        email: "preview@example.com",
        name: asDl ? "Kamil Próbny" : "Marta Nowak",
        role: asDl ? "delivery_lead" : "recruiter",
        roles: [asDl ? "delivery_lead" : "recruiter"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
        effective_section_access: { sourcing: "write", pipeline: "write" },
      } as never,
      hydrated: true,
    });
    setReady(true);
  }, [asDl, viewerId]);
  const cols = useMemo(() => columns(viewerId), [viewerId]);
  // 0404: „Odrzuceni przez AI” — pusta lista, bez zapytania.
  useMemo(() => {
    client.setQueryData(screenedOutQueryKey(JOB_ID), { job_id: JOB_ID, total: 0, items: [] });
  }, [client]);
  useMemo(() => seedScreening(client, cols), [client, cols]);
  // Notatki w doku osoby (sekcja „Notatki”): ta sama lista co w profilu —
  // odpowiedź pod notatką i notatka automatu za „Pokaż systemowe (1)”.
  useMemo(() => {
    for (const column of cols) {
      for (const item of column.items) {
        client.setQueryData([...candidateQueryKeys.notes(item.candidate_id), JOB_ID], {
          items: [
            {
              id: item.candidate_id,
              author_id: 3,
              author_name: "Ola Rekruterka",
              created_at: "2026-09-12T09:30:00Z",
              pinned_at: "2026-09-13T08:00:00Z",
              content:
                "<p>@Kamil Próbny</p><p>&nbsp;</p><p>&nbsp;</p><p>Rozmowa wstępna — dostępny od października.</p><p>&nbsp;</p><p>Preferuje pracę hybrydową, 2 dni w biurze.</p><p>&nbsp;</p><p>Stawka 150 zł/h netto B2B.</p><p>Czeka na decyzję w innym procesie.</p>",
              replies: [
                {
                  id: 100_000 + item.candidate_id,
                  author_id: 5,
                  author_name: "Kamil Próbny",
                  created_at: "2026-09-13T10:15:00Z",
                  content: "Klient potwierdził, że hybryda jest OK.",
                  parent_note_id: item.candidate_id,
                  replies: [],
                },
              ],
            },
            {
              id: 200_000 + item.candidate_id,
              author_id: null,
              author_name: null,
              created_at: "2026-09-10T07:00:00Z",
              content: "Auto-match 72/100 — kandydat dodany automatycznie.",
              external_source: "system",
              is_system: true,
              replies: [],
            },
          ],
          total: 2,
        });
      }
    }
  }, [client, cols]);
  if (!ready) return null;

  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <TooltipProvider>
          <main className="min-h-dvh bg-background p-4 text-foreground">
            <h1 className="mb-3 text-lg font-semibold">
              Tablica Pipeline v4 — harness ({asDl ? "Delivery Lead" : "rekruterka Marta"})
            </h1>
            <KanbanBoardV2 columns={cols} jobId={JOB_ID} jobTitle="Senior Java Developer" />
          </main>
        </TooltipProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
}

export default function PipelineV4Preview() {
  return (
    <Suspense fallback={null}>
      <PipelineV4Harness />
    </Suspense>
  );
}
