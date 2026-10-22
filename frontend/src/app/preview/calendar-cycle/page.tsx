"use client";

/**
 * Harness wizualny ekranu „Rozmowy u klienta” (`/calendar`, 0338).
 *
 * Renderuje PRODUKCYJNY `CalendarCycleScreen` na danych fikcyjnych:
 * tablica i panel kandydata dostają `dataOverride` (zapytanie wyłączone), a pozostałe
 * klucze (pytania klienta, debrief, siatka tygodnia) są zasiane w cache
 * z `staleTime: Infinity` — strona nie robi ani jednego zapytania, więc może
 * stać w `PUBLIC_PATHS`. `?as=dl` pokazuje ekran oczami Delivery Leada.
 */

import { Suspense, useMemo } from "react";
import { useSearchParams } from "next/navigation";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { CalendarCycleScreen } from "@/components/calendar/cycle/CalendarCycleScreen";
import { ToastProvider } from "@/components/Toast";
import {
  clientQuestionsQueryKey,
  debriefQueryKey,
  interviewEventQueryKey,
} from "@/lib/api/interviewCycle";
import { rateChangesQueryKey } from "@/lib/rate-change";
import {
  prepOptionsQueryKey,
  prepQueryKey,
  prepTranscriptQueryKey,
  type Prep,
} from "@/lib/api/prepMeetings";
import type { CycleOverview, CycleStep, PairInfo } from "@/lib/interview-cycle";

const BASE = "/preview/calendar-cycle";

function at(now: Date, minutes: number): string {
  return new Date(now.getTime() + minutes * 60_000).toISOString();
}

function mondayOf(date: Date): Date {
  // Lustro `getMonday` z WeekCalendar — klucz tygodnia musi się zgadzać co do ms.
  const d = new Date(date);
  const day = d.getDay();
  const diff = day === 0 ? -6 : 1 - day;
  d.setDate(d.getDate() + diff);
  d.setHours(0, 0, 0, 0);
  return d;
}

const pairs: Record<string, PairInfo> = {
  piotr: { candidate_id: 101, candidate_name: "Piotr Nowak", candidate_email: "piotr@example.com", candidate_phone: "+48 500 100 200", job_id: 1, job_title: "Senior Java Developer", client_id: 11, client_name: "Bank Lambda" },
  anna: { candidate_id: 102, candidate_name: "Anna Kowalska", candidate_email: "anna@example.com", job_id: 2, job_title: "Data Engineer", client_id: 12, client_name: "Bank Północny" },
  tomasz: { candidate_id: 103, candidate_name: "Tomasz Zieliński", candidate_email: "tomasz@example.com", job_id: 3, job_title: "DevOps Engineer", client_id: 13, client_name: "Bank Kappa" },
  michal: { candidate_id: 104, candidate_name: "Michał Lewandowski", candidate_email: "michal@example.com", job_id: 4, job_title: ".NET Developer", client_id: 14, client_name: "Biuro Gamma" },
  ewa: { candidate_id: 105, candidate_name: "Ewa Dąbrowska", candidate_email: "ewa@example.com", job_id: 5, job_title: "Business Analyst", client_id: 11, client_name: "Bank Lambda" },
  oliwia: { candidate_id: 106, candidate_name: "Oliwia Kamińska", candidate_email: "oliwia@example.com", job_id: 6, job_title: "QA Engineer", client_id: 15, client_name: "Bank Iota" },
  // Prep zaplanowany PO rozmowie u klienta (termin rozmowy potwierdzono wcześniej niż prep).
  karol: { candidate_id: 107, candidate_name: "Karol Przykładowy", candidate_email: "karol@example.com", job_id: 7, job_title: "Frontend Developer", client_id: 16, client_name: "Bank Omega" },
  // Zapisany debrief z warunkiem kandydata (04.10.2026: „Zobacz debrief”).
  bartek: { candidate_id: 108, candidate_name: "Bartek Testowy", candidate_email: "bartek@example.com", job_id: 8, job_title: "Senior Java Developer", client_id: 17, client_name: "Bank Sigma" },
  // 0482: rozmowa jutro, Prep 1 dobry — wolno zapisać „bez Prepu 2”.
  zuzanna: { candidate_id: 109, candidate_name: "Zuzanna Próbna", candidate_email: "zuzanna@example.com", job_id: 9, job_title: "Low Code Developer", client_id: 18, client_name: "Ubezpieczenia Delta" },
  // 0482: pominięcie zapisane, telefon przed rozmową do zrobienia.
  filip: { candidate_id: 110, candidate_name: "Filip Fikcyjny", candidate_email: "filip@example.com", job_id: 10, job_title: "Python Developer", client_id: 19, client_name: "Telekom Epsilon" },
};

const SAVED_DEBRIEF = {
  id: 9,
  calendar_event_id: 507,
  candidate_id: 108,
  job_id: 8,
  outcome: "good" as const,
  candidate_comment: "Projekt mu się podoba, zespół w porządku.",
  questions: [
    "Jak sprawdzasz trwałość danych po odświeżeniu?",
    "Kiedy użyjesz @Transactional na poziomie klasy?",
    "Jak debugujesz wyciek pamięci w Spring Boot?",
    "Opisz migrację z Javy 11 na 17 w projekcie.",
  ],
  offer_acceptance: "likely" as const,
  acceptance_condition: "Ma drugą ofertę do piątku",
  no_client_questions: false,
  questions_saved: 0,
  current_rate_label: "125 zł/h",
  current_rate_hourly: "125",
  rate_change: {
    id: 3, status: "requested", requires_decision: true, previous: "110 zł/h",
    requested: "125 zł/h", requested_amount: "125", requested_unit: "hourly",
    negotiable: "maybe" as const, note: "Ma drugą ofertę za 120 zł/h",
  },
};

function st(
  key: CycleStep["key"],
  state: CycleStep["state"],
  atIso: string | null = null,
  meta: string | null = null,
  extra: Partial<CycleStep> = {},
): CycleStep {
  return { key, label: key, state, at: atIso, event_id: null, meta, ...extra };
}

function buildOverview(now: Date, scope: "mine" | "jobs"): CycleOverview {
  const slots = [
    { start: at(now, 60 * 24 + 60), end: at(now, 60 * 24 + 120) },
    { start: at(now, 60 * 48 + 240), end: at(now, 60 * 48 + 300) },
    { start: at(now, 60 * 72), end: at(now, 60 * 72 + 60) },
  ];
  const items: CycleOverview["items"] = [
    {
      ...pairs.piotr,
      steps: [
        st("slots", "done"), st("choice", "done", at(now, -60 * 72)), st("prep", "done", at(now, -60 * 50)),
        st("prep2", "skipped"), st("interview", "done", at(now, -72)), st("call", "current", at(now, 18), "teraz"),
        st("debrief", "todo"),
      ],
      current_step: "call", latest_stage: "client_interview", slot_request: null, interview_event_id: 501, debrief: null,
    },
    {
      ...pairs.anna,
      steps: [
        st("slots", "done"), st("choice", "done", at(now, 60 * 23)),
        st("prep", "done", at(now, -60 * 70), "ocena: dobry", { event_id: 603, quality: "good" }),
        st("prep2", "scheduled", at(now, 150)), st("interview", "scheduled", at(now, 60 * 23)), st("call", "todo", at(now, 60 * 24)),
        st("debrief", "todo"),
      ],
      current_step: "prep2", latest_stage: "client_interview", slot_request: null, interview_event_id: 502, debrief: null,
    },
    {
      ...pairs.tomasz,
      steps: [
        st("slots", "done"), st("choice", "current", at(now, 60 * 20), "3 terminy do wyboru"), st("prep", "todo"),
        st("prep2", "todo"), st("interview", "todo"), st("call", "todo"), st("debrief", "todo"),
      ],
      current_step: "choice", latest_stage: "client_interview",
      slot_request: { id: 71, status: "awaiting_recruiter", slots, chosen_index: null, respond_by: at(now, 60 * 20), recruiter_id: 7, created_by: 8, duration_minutes: 60, note: "Klient prosi o kamerkę", event_id: null },
      tentative_interview_at: slots[0].start,
      interview_event_id: null, debrief: null,
    },
    {
      ...pairs.michal,
      steps: [
        st("slots", "done"), st("choice", "done", at(now, 60 * 70)),
        st("prep", "done", at(now, -180), "ocena: słaby", { event_id: 601, quality: "weak" }),
        st("prep2", "current"), st("interview", "scheduled", at(now, 60 * 70)), st("call", "todo"), st("debrief", "todo"),
      ],
      current_step: "prep2", latest_stage: "client_interview", slot_request: null, interview_event_id: 504, debrief: null,
      prep2_skip_status: "prep1_weak",
    },
    {
      ...pairs.zuzanna,
      steps: [
        st("slots", "done"), st("choice", "done", at(now, 60 * 20)),
        st("prep", "done", at(now, -120), "ocena: dobry", { event_id: 608, quality: "good" }),
        st("prep2", "current"), st("interview", "scheduled", at(now, 60 * 20), null, { event_id: 508 }),
        st("call", "todo"), st("debrief", "todo"),
      ],
      current_step: "prep2", latest_stage: "client_interview", slot_request: null, interview_event_id: 508, debrief: null,
      prep2_skip_status: "allowed",
      prep1_remaining: ["Power Apps w bankowości", "Praca z Dataverse"],
    },
    {
      ...pairs.filip,
      steps: [
        st("slots", "done"), st("choice", "done", at(now, 60 * 22)),
        st("prep", "done", at(now, -60 * 5), "ocena: OK", { event_id: 609, quality: "ok" }),
        st("prep2", "skipped", null, "kandydat nie miał wolnego terminu · Ola Rekruter"),
        st("interview", "scheduled", at(now, 60 * 22), null, { event_id: 509 }),
        st("call", "todo"), st("debrief", "todo"),
      ],
      current_step: "interview", latest_stage: "client_interview", slot_request: null, interview_event_id: 509, debrief: null,
      prep2_skip_status: "skipped",
      prep2_skip: {
        id: 31, interview_event_id: 509, reason: "no_slot", reason_note: null,
        call_at: at(now, 180), call_done_at: null, call_note: null,
        created_by: 7, created_by_name: "Ola Rekruter", created_at: at(now, -30),
      },
    },
    {
      ...pairs.ewa,
      steps: [
        st("slots", "done"), st("choice", "done"), st("prep", "done"), st("prep2", "skipped"),
        st("interview", "done", at(now, -60 * 72)), st("call", "overdue", at(now, -60 * 70)), st("debrief", "overdue"),
      ],
      current_step: "call", latest_stage: "client_interview", slot_request: null, interview_event_id: 505, debrief: null,
    },
    {
      ...pairs.karol,
      steps: [
        st("slots", "done"), st("choice", "done", at(now, 60 * 72)),
        st("prep", "overdue", at(now, 60 * 120), "zaplanowany po rozmowie u klienta — przełóż", { event_id: 604 }),
        st("prep2", "todo"), st("interview", "scheduled", at(now, 60 * 72), null, { event_id: 506 }),
        st("call", "todo"), st("debrief", "todo"),
      ],
      current_step: "prep", latest_stage: "client_interview", slot_request: null, interview_event_id: 506, debrief: null,
    },
    {
      ...pairs.bartek,
      steps: [
        st("slots", "done"), st("choice", "done"), st("prep", "skipped"), st("prep2", "skipped"),
        st("interview", "done", at(now, -60 * 5)), st("call", "done", at(now, -60 * 4)), st("debrief", "done"),
      ],
      current_step: null, latest_stage: "client_interview", slot_request: null, interview_event_id: 507,
      debrief: {
        id: 9, overall_impression: 5, outcome: "good", offer_acceptance: "likely",
        acceptance_condition: SAVED_DEBRIEF.acceptance_condition,
        candidate_comment: SAVED_DEBRIEF.candidate_comment, questions_count: 4, no_client_questions: false,
      },
    },
  ];
  if (scope === "jobs") {
    items.push({
      ...pairs.oliwia,
      steps: [
        st("slots", "current"), st("choice", "todo"), st("prep", "todo"), st("prep2", "todo"),
        st("interview", "todo"), st("call", "todo"), st("debrief", "todo"),
      ],
      current_step: "slots", latest_stage: "client_interview", slot_request: null, interview_event_id: null, debrief: null,
    });
  }
  return {
    generated_at: now.toISOString(),
    scope,
    call_window_minutes: 30,
    items,
    agenda: [
      { ...pairs.michal, kind: "prep", start: at(now, -180), end: at(now, -150), event_id: 601, slot_request_id: null, online_meeting_url: "https://teams.example.com/prep", done: false, from_nexus: true, prep_quality: "weak", prep_meta: "ocena: słaby" },
      { ...pairs.piotr, kind: "interview", start: at(now, -72), end: at(now, -12), event_id: 501, slot_request_id: null, online_meeting_url: null, done: false },
      { ...pairs.piotr, kind: "call", start: at(now, -12), end: at(now, 18), event_id: 501, slot_request_id: null, online_meeting_url: null, done: false },
      { ...pairs.anna, kind: "prep2", start: at(now, 150), end: at(now, 180), event_id: 602, slot_request_id: null, online_meeting_url: "https://teams.example.com/prep2", done: false },
      { ...pairs.anna, kind: "interview", start: at(now, 60 * 23), end: at(now, 60 * 24), event_id: 502, slot_request_id: null, online_meeting_url: null, done: false },
      { ...pairs.anna, kind: "call", start: at(now, 60 * 24), end: at(now, 60 * 24 + 30), event_id: 502, slot_request_id: null, online_meeting_url: null, done: false },
      { ...pairs.michal, kind: "interview", start: at(now, 60 * 70), end: at(now, 60 * 71), event_id: 504, slot_request_id: null, online_meeting_url: null, done: false },
      { ...pairs.karol, kind: "interview", start: at(now, 60 * 72), end: at(now, 60 * 73), event_id: 506, slot_request_id: null, online_meeting_url: null, done: false },
      { ...pairs.bartek, kind: "interview", start: at(now, -60 * 5), end: at(now, -60 * 4), event_id: 507, slot_request_id: null, online_meeting_url: null, done: true },
      { ...pairs.bartek, kind: "call", start: at(now, -60 * 4), end: at(now, -60 * 4 + 30), event_id: 507, slot_request_id: null, online_meeting_url: null, done: true },
      { ...pairs.karol, kind: "prep", start: at(now, 60 * 120), end: at(now, 60 * 120 + 45), event_id: 604, slot_request_id: null, online_meeting_url: "https://teams.example.com/prep-late", done: false, from_nexus: true, late: true },
    ],
    todos: [
      { ...pairs.piotr, kind: "call_now", priority: 0, due: at(now, 18), event_id: 501, slot_request_id: null },
      { ...pairs.ewa, kind: "debrief_overdue", priority: 1, due: at(now, -60 * 70), event_id: 505, slot_request_id: null },
      { ...pairs.tomasz, kind: "slots_pick", priority: 2, due: at(now, 60 * 20), event_id: null, slot_request_id: 71 },
      { ...pairs.michal, kind: "prep_weak", priority: 6, due: at(now, 60 * 70), event_id: 601, slot_request_id: null },
      { ...pairs.michal, kind: "prep2_missing", priority: 6, due: at(now, 60 * 70), event_id: 504, slot_request_id: null },
      { ...pairs.karol, kind: "prep_late", priority: 4, due: at(now, 60 * 72), event_id: 604, slot_request_id: null },
      { ...pairs.zuzanna, kind: "prep2_missing", priority: 1, due: at(now, 60 * 20), event_id: 508, slot_request_id: null, urgent: true },
      { ...pairs.filip, kind: "precall_due", priority: 4, due: at(now, 180), event_id: 509, slot_request_id: null },
      ...(scope === "jobs"
        ? [{ ...pairs.oliwia, kind: "slots_missing" as const, priority: 5, due: null, event_id: null, slot_request_id: null }]
        : []),
    ],
    truncated: false,
  };
}

function Harness() {
  const params = useSearchParams();
  const asDl = params.get("as") === "dl";
  const now = useMemo(() => new Date(), []);
  const data = useMemo(
    () => ({ mine: buildOverview(now, "mine"), jobs: buildOverview(now, "jobs"), all: buildOverview(now, "jobs") }),
    [now],
  );
  const client = useMemo(() => {
    const qc = new QueryClient({
      defaultOptions: { queries: { staleTime: Infinity, retry: false, refetchOnMount: false } },
    });
    const questions = [
      { id: 1, text: "Transakcje w Spring — propagacja REQUIRES_NEW", created_at: null },
      { id: 2, text: "Live coding: refaktor klasy z trzema zależnościami", created_at: null },
      { id: 3, text: "Doświadczenie z Kafką na produkcji", created_at: null },
    ];
    for (const p of Object.values(pairs)) qc.setQueryData(clientQuestionsQueryKey(p.job_id), questions);
    for (const id of [501, 502, 504, 505, 506]) qc.setQueryData(debriefQueryKey(id), null);
    qc.setQueryData(debriefQueryKey(507), SAVED_DEBRIEF);
    // Okno debriefu czyta wydarzenie (para kandydat–rekrutacja) i stawkę pary.
    const eventPairs: Record<number, PairInfo> = {
      501: pairs.piotr, 502: pairs.anna, 504: pairs.michal, 505: pairs.ewa, 506: pairs.karol, 507: pairs.bartek,
    };
    for (const [id, p] of Object.entries(eventPairs)) {
      qc.setQueryData(interviewEventQueryKey(Number(id)), {
        id: Number(id), candidate_id: p.candidate_id, job_id: p.job_id,
        start: at(now, -72), end: at(now, -12), started: true,
      });
      qc.setQueryData(rateChangesQueryKey(p.candidate_id, p.job_id), {
        candidate_id: p.candidate_id, job_id: p.job_id,
        current: { amount: "110", unit: "hourly", currency: "PLN", hourly: "110", label: "110 zł/h" },
        board_column: "client_interview", notifies: true, cv_at_client: true,
        client_rate: null, changes: [],
      });
    }
    // 0370: ocena prepu i transkrypt (okno „Ocena prepu”), podpowiedzi organizatora.
    const weakPrep: Prep = {
      event_id: 601, prep_no: 1, candidate_id: 104, job_id: 4,
      organizer: { id: 8, name: "Kasia DL" }, start: at(now, -180), end: at(now, -150),
      online_meeting_url: null, transcription_setup: "enabled", transcript_status: "fetched",
      talk_share: 0.22, duration_seconds: 28 * 60,
      review: {
        status: "ok", level: "weak", coverage: 0.4,
        criteria: {
          items: [
            { key: "must:.NET", label: ".NET", kind: "must", status: "covered", quote: "od pięciu lat piszę w .NET" },
            { key: "must:Azure", label: "Azure", kind: "must", status: "missing", quote: null },
            { key: "q:1", label: "Transakcje w Spring — propagacja REQUIRES_NEW", kind: "question", status: "partial", quote: "transakcje zagnieżdżone" },
          ],
          own_projects: { told: false, quote: null },
        },
        summary: "Prowadząca mówiła większość czasu, kandydat odpowiadał krótko. Azure nie został omówiony.",
        remaining: ["Azure", "Transakcje w Spring — propagacja REQUIRES_NEW"],
      },
    };
    qc.setQueryData(prepQueryKey(601), weakPrep);
    qc.setQueryData(prepTranscriptQueryKey(601), {
      event_id: 601, speakers: [], fetched_at: at(now, -120),
      text: "Kasia DL: Opowiedz o swoim doświadczeniu.\nMichał Lewandowski: Od pięciu lat piszę w .NET, ostatnio transakcje zagnieżdżone w banku.",
    });
    // Ocena v2 (22.10.2026): tematy prowadzącego, odpowiedzi kandydata, notatka na Prep 2.
    const v2Prep: Prep = {
      ...weakPrep, event_id: 603, candidate_id: 102, job_id: 2, talk_share: 0.58, duration_seconds: 37 * 60,
      online_meeting_url: "https://teams.example.com/prep",
      review: {
        status: "ok", level: "ok", coverage: 0.72, config_version: 2, prompt_version: "prep-review-v2",
        summary: "Kandydatka dobrze opowiada własne projekty i podaje liczby. Ryzykiem na rozmowie jest Kafka i testy: odpowiada ogólnie. Prowadząca nie omówiła przebiegu rozmowy u klienta.",
        remaining: ["Kafka", "Przebieg rozmowy u klienta: kto, ile trwa, live coding", "Jak testujesz integrację?"],
        criteria: {
          version: 2,
          total: 72,
          caps: [],
          scores: { topics: 80, must_answers: 70, client_questions: 67, talk_share: 100 },
          weights_used: { topics: 25, must_answers: 40, client_questions: 20, talk_share: 15 },
          topics: [
            { key: "topic:0", label: "Klient i projekt: zespół, technologia, tryb pracy", required: true, status: "covered", quote: "Klient to zespół płatności, osiem osób" },
            { key: "topic:1", label: "Przebieg rozmowy u klienta: kto, ile trwa, live coding", required: true, status: "missing", quote: null },
            { key: "topic:2", label: "Doświadczenie pod każdy must-have", required: true, status: "covered", quote: "migrowałam moduł rozliczeń na Javę 21" },
            { key: "topic:3", label: "Stawka i dostępność", required: true, status: "covered", quote: "mogę zacząć od pierwszego" },
            { key: "topic:4", label: "Pytania kandydata do klienta", required: false, status: "partial", quote: "a jak wygląda zespół" },
          ],
          answers: [
            { key: "must:Java", label: "Java 17+", kind: "must", grade: "strong", quote: "migrowałam moduł rozliczeń na Javę 21", note: null },
            { key: "must:Spring", label: "Spring Boot", kind: "must", grade: "strong", quote: "sama postawiłam serwis płatności od zera", note: null },
            { key: "must:Kafka", label: "Kafka", kind: "must", grade: "weak", quote: "pracowałam, głównie konsumowanie zdarzeń", note: "Jeden przypadek: ile zdarzeń, jaki problem, co sama zrobiła." },
            { key: "q:11", label: "Jak testujesz integrację?", kind: "question", grade: "general", quote: "piszemy testy, mamy Testcontainers", note: "„Ja” zamiast „my”, jeden konkretny test." },
          ],
          went_well: ["Projekt płatności opowiedziany samodzielnie, z liczbami", "4 z 6 pytań klienta przećwiczone"],
          went_wrong: ["Kafka: odpowiedź bez przykładu", "Testy integracyjne: „mamy”, a nie „zrobiłam”"],
          improve: ["Zacząć od listy tematów: przebieg rozmowy u klienta wypadł"],
          own_projects: { told: true, quote: "sama postawiłam serwis płatności od zera" },
          followup: [
            { key: "must:Kafka", label: "Kafka", kind: "must", reason: "weak", quote: "pracowałam, głównie konsumowanie zdarzeń", note: "Jeden przypadek: ile zdarzeń, jaki problem, co sama zrobiła." },
            { key: "topic:1", label: "Przebieg rozmowy u klienta: kto, ile trwa, live coding", kind: "topic", reason: "missing_topic", quote: null, note: null },
            { key: "q:11", label: "Jak testujesz integrację?", kind: "question", reason: "general", quote: "piszemy testy, mamy Testcontainers", note: "„Ja” zamiast „my”, jeden konkretny test." },
          ],
          comparison: [],
          items: [],
        },
      },
    };
    qc.setQueryData(prepQueryKey(603), v2Prep);
    qc.setQueryData(prepTranscriptQueryKey(603), {
      event_id: 603, fetched_at: at(now, -60 * 60),
      speakers: [{ name: "Kasia DL", role: "staff", user_id: 8, seconds: 900 }, { name: "Anna Kowalska", role: "candidate", user_id: null, seconds: 1250 }],
      text: "Kasia DL: Klient to zespół płatności, osiem osób.",
      cues: [
        { start: 134, speaker: "Kasia DL", role: "staff", text: "Klient to zespół płatności, osiem osób, sprinty dwutygodniowe." },
        { start: 220, speaker: "Anna Kowalska", role: "candidate", text: "W ostatnim projekcie migrowałam moduł rozliczeń na Javę 21, czterdzieści serwisów." },
        { start: 512, speaker: "Anna Kowalska", role: "candidate", text: "Sama postawiłam serwis płatności od zera, w Spring Boot." },
        { start: 845, speaker: "Anna Kowalska", role: "candidate", text: "Z Kafką pracowałam, głównie konsumowanie zdarzeń, konfiguracją zajmował się inny zespół." },
        { start: 892, speaker: "Kasia DL", role: "staff", text: "Klient na pewno dopyta o partycje i ponawianie, przygotuj jeden konkretny przypadek." },
        { start: 1310, speaker: "Anna Kowalska", role: "candidate", text: "Piszemy testy, mamy Testcontainers w pipeline." },
        { start: 1980, speaker: "Anna Kowalska", role: "candidate", text: "Mogę zacząć od pierwszego, a jak wygląda zespół po stronie klienta?" },
      ],
    });
    qc.setQueryData(prepQueryKey(608), { ...v2Prep, event_id: 608 });
    qc.setQueryData(prepQueryKey(609), { ...v2Prep, event_id: 609 });
    for (const p of Object.values(pairs)) {
      qc.setQueryData(prepOptionsQueryKey(p.candidate_id, p.job_id), {
        enabled: true, auto_transcribe: true,
        suggested: { "1": { id: 8, name: "Kasia DL" }, "2": { id: 7, name: "Ola Rekruter" } },
        team: [{ id: 8, name: "Kasia DL" }, { id: 7, name: "Ola Rekruter" }],
        people: [
          { id: 8, name: "Kasia DL", role: "delivery_lead", in_team: true },
          { id: 7, name: "Ola Rekruter", role: "recruiter", in_team: true },
          { id: 9, name: "Marek Przykładowy", role: "delivery_lead", in_team: false },
          { id: 10, name: "Magda Testowa", role: "head_of_recruitment", in_team: false },
        ],
        notice: "Ta rozmowa jest nagrywana i transkrybowana w Microsoft Teams wyłącznie po to, żeby dobrze przygotować Cię do rozmowy z klientem. Administratorem danych jest B2B.NET S.A.",
        invitation: Object.fromEntries(
          [1, 2].map((n) => [
            String(n),
            {
              title: `Przygotowanie do spotkania z Klientem ${p.client_name} - ${p.candidate_name}${n === 2 ? " (spotkanie 2)" : ""}`,
              body: `Dzień dobry,\n\nZapraszam na ${n === 2 ? "drugie " : ""}spotkanie przygotowujące do rozmowy z Klientem ${p.client_name} na stanowisko ${p.job_title}.\n\n{note}\n\nW razie pytań pozostaję do dyspozycji.\n\nPozdrawiam\n{organizer}`,
              interview_line: null,
            },
          ]),
        ),
      });
    }
    // Siatka tygodnia (zakładka „Tydzień”) — te same klucze co WeekCalendar.
    const monday = mondayOf(now);
    const fromDate = monday.toISOString();
    const weekEvents = [
      { id: 501, title: "Rozmowa u klienta: Piotr Nowak", event_type: "client_interview", start_time: at(now, -72), end_time: at(now, -12), all_day: false, status: "completed", candidate_id: 101, candidate_name: "Piotr Nowak", external_source: "manual", feedback_sources: [], can_remove: true },
      { id: 601, title: "Prep: Michał Lewandowski", event_type: "prep_call", start_time: at(now, -180), end_time: at(now, -150), all_day: false, status: "scheduled", external_source: "microsoft365", feedback_sources: [], can_remove: true },
      { id: 700, title: "Daily zespołu", event_type: "meeting", start_time: at(now, 60 * 20), end_time: at(now, 60 * 20 + 30), all_day: false, status: "scheduled", external_source: "microsoft365", feedback_sources: [], can_remove: false },
    ];
    qc.setQueryData(["calendar-events", fromDate], weekEvents);
    // „Przełóż” / „Zmień” prep Karola (wypada po rozmowie) — okno czyta prep po id.
    const latePrep: Prep = {
      event_id: 604, prep_no: 1, candidate_id: pairs.karol.candidate_id, job_id: pairs.karol.job_id,
      organizer: { id: 8, name: "Kasia DL" }, scheduled_by: { id: 7, name: "Ola Rekruter" },
      attendees: [
        { email: "ola.rekruter@example.com", user_id: 7, name: "Ola Rekruter" },
        { email: "gosc@partner.example.com", user_id: null, name: null },
      ],
      status: "scheduled", can_edit: true,
      // 0453: kandydat odrzucił termin i proponuje inny — „Przyjmij termin”.
      candidate_response: "declined", proposed_start: at(now, 60 * 30), proposed_end: at(now, 60 * 30 + 45),
      start: at(now, 60 * 120), end: at(now, 60 * 120 + 45),
      online_meeting_url: "https://teams.example.com/prep-late", transcription_setup: "enabled",
      transcript_status: "waiting", talk_share: null, duration_seconds: null, review: null,
    };
    qc.setQueryData(prepQueryKey(604), latePrep);
    qc.setQueryData(["calendar-conflicts-summary", fromDate], {});
    qc.setQueryData(["calendar-upcoming"], weekEvents);
    return qc;
  }, [now]);

  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <main className="min-h-dvh bg-background p-4 md:p-6">
          <p className="mb-4 text-xs text-muted-foreground">
            Podgląd na danych fikcyjnych · {asDl ? "oczami Delivery Leada" : "oczami rekrutera"} ·{" "}
            <a className="text-primary underline" href={asDl ? BASE : `${BASE}?as=dl`}>
              {asDl ? "pokaż jako rekruter" : "pokaż jako DL"}
            </a>
          </p>
          <CalendarCycleScreen
            nowOverride={now}
            dataOverride={data}
            roleOverride={asDl ? "delivery_lead" : "recruiter"}
            basePath={BASE}
          />
        </main>
      </ToastProvider>
    </QueryClientProvider>
  );
}

export default function CalendarCyclePreviewPage() {
  return (
    <Suspense fallback={null}>
      <Harness />
    </Suspense>
  );
}
