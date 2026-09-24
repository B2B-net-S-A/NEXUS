"use client";

/**
 * Harness wizualny ekranu „Rozmowy u klienta” (`/calendar`, 0338).
 *
 * Renderuje PRODUKCYJNY `CalendarCycleScreen` na danych fikcyjnych:
 * agenda i tablica dostają `dataOverride` (zapytanie wyłączone), a pozostałe
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
} from "@/lib/api/interviewCycle";
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
  piotr: { candidate_id: 101, candidate_name: "Piotr Nowak", candidate_email: "piotr@example.com", job_id: 1, job_title: "Senior Java Developer", client_id: 11, client_name: "Alior" },
  anna: { candidate_id: 102, candidate_name: "Anna Kowalska", candidate_email: "anna@example.com", job_id: 2, job_title: "Data Engineer", client_id: 12, client_name: "Nordea" },
  tomasz: { candidate_id: 103, candidate_name: "Tomasz Zieliński", candidate_email: "tomasz@example.com", job_id: 3, job_title: "DevOps Engineer", client_id: 13, client_name: "PKO BP" },
  michal: { candidate_id: 104, candidate_name: "Michał Lewandowski", candidate_email: "michal@example.com", job_id: 4, job_title: ".NET Developer", client_id: 14, client_name: "BIK" },
  ewa: { candidate_id: 105, candidate_name: "Ewa Dąbrowska", candidate_email: "ewa@example.com", job_id: 5, job_title: "Business Analyst", client_id: 11, client_name: "Alior" },
  oliwia: { candidate_id: 106, candidate_name: "Oliwia Kamińska", candidate_email: "oliwia@example.com", job_id: 6, job_title: "QA Engineer", client_id: 15, client_name: "mBank" },
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
    },
    {
      ...pairs.ewa,
      steps: [
        st("slots", "done"), st("choice", "done"), st("prep", "done"), st("prep2", "skipped"),
        st("interview", "done", at(now, -60 * 72)), st("call", "overdue", at(now, -60 * 70)), st("debrief", "overdue"),
      ],
      current_step: "call", latest_stage: "client_interview", slot_request: null, interview_event_id: 505, debrief: null,
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
    ],
    todos: [
      { ...pairs.piotr, kind: "call_now", priority: 0, due: at(now, 18), event_id: 501, slot_request_id: null },
      { ...pairs.ewa, kind: "debrief_overdue", priority: 1, due: at(now, -60 * 70), event_id: 505, slot_request_id: null },
      { ...pairs.tomasz, kind: "slots_pick", priority: 2, due: at(now, 60 * 20), event_id: null, slot_request_id: 71 },
      { ...pairs.michal, kind: "prep_weak", priority: 6, due: at(now, 60 * 70), event_id: 601, slot_request_id: null },
      { ...pairs.michal, kind: "prep2_missing", priority: 6, due: at(now, 60 * 70), event_id: 504, slot_request_id: null },
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
    for (const id of [501, 502, 504, 505]) qc.setQueryData(debriefQueryKey(id), null);
    // 0369: ocena prepu i transkrypt (okno „Ocena prepu”), podpowiedzi organizatora.
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
    qc.setQueryData(prepQueryKey(603), { ...weakPrep, event_id: 603, candidate_id: 102, job_id: 2, talk_share: 0.61, review: { ...weakPrep.review!, level: "good", coverage: 0.9, remaining: [], summary: "Kandydatka opowiedziała projekty, przećwiczono pytania klienta." } });
    for (const p of Object.values(pairs)) {
      qc.setQueryData(prepOptionsQueryKey(p.candidate_id, p.job_id), {
        enabled: true, auto_transcribe: true,
        suggested: { "1": { id: 8, name: "Kasia DL" }, "2": { id: 7, name: "Ola Rekruter" } },
        team: [{ id: 8, name: "Kasia DL" }, { id: 7, name: "Ola Rekruter" }],
        notice: "Ta rozmowa jest nagrywana i transkrybowana w Microsoft Teams wyłącznie po to, żeby dobrze przygotować Cię do rozmowy z klientem.",
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
    qc.setQueryData(["calendar-conflicts-summary", fromDate], {});
    qc.setQueryData(["calendar-upcoming"], weekEvents);
    return qc;
  }, [now]);

  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <main className="min-h-screen bg-background p-6">
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
