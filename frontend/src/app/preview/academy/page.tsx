"use client";

/**
 * Harness wizualny Akademii — publiczny, ZERO zapytań.
 *
 * Renderuje `AcademyWorkspace` na danych fikcyjnych (repo jest publiczne —
 * żadnych prawdziwych nazwisk). Przyciski działają na stanie lokalnym, więc
 * da się przeklikać cały przepływ: telefon → termin → zadanie → umowa.
 * `?view=calls|sessions|excluded|settings` otwiera od razu zakładkę.
 */

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import {
  ACADEMY_VIEWS,
  AcademyWorkspace,
  type AcademyHandlers,
  type AcademyView,
} from "@/components/academy/AcademyWorkspace";
import { nextCohort, toIsoDate } from "@/lib/academy-flow";
import type {
  AcademyApplication,
  AcademyProgramDetail,
  AcademySessionRow,
  ActionBody,
} from "@/lib/api/academy";

const NOW = new Date(2026, 9, 24, 9, 30);

function at(days: number, hour = 10): string {
  return new Date(2026, 9, 24 + days, hour, 0).toISOString();
}

const PROGRAM: AcademyProgramDetail = {
  id: 1,
  name: "Akademia Rekrutera",
  is_active: true,
  max_experience_years: 6,
  require_polish: true,
  luna_enabled: true,
  conditions: ["Umowa zlecenie — pasuje?", "Praca stacjonarna w biurze — pasuje?"],
  session_capacity: 8,
  task_due_days: 5,
  sources: [
    { job_id: 101, title: "Akademia Rekrutera — Warszawa", status: "published", since: "2026-10-01", applicants: 64 },
    { job_id: 102, title: "Młodszy rekruter IT — staż", status: "published", since: "2026-10-01", applicants: 31 },
  ],
  counts: {},
  can_manage: true,
  next_cohort: { month: "2026-11-01", start: "2026-11-02", end: "2026-11-16" },
};

function person(id: number, name: string, overrides: Partial<AcademyApplication>): AcademyApplication {
  return {
    id,
    candidate_id: 1000 + id,
    full_name: name,
    email: `osoba${id}@example.com`,
    phone: `600 100 ${String(200 + id)}`,
    city: "Warszawa",
    has_cv: true,
    source_job_id: 101,
    source_job_title: "Akademia Rekrutera — Warszawa",
    applied_at: at(-3 - (id % 5)),
    status: "to_call",
    screening_verdict: "call",
    screening_reasons: [
      { code: "experience_ok", text: "1 rok pracy po studiach (koniec 2025)." },
      { code: "polish_ok", text: "Polski: ojczysty." },
    ],
    screening_facts: { experience_basis: "after_studies", studies_end_year: 2025 },
    screened_at: at(-2),
    experience_years: 1,
    call_attempts: 0,
    last_call_at: null,
    session_id: null,
    session_starts_at: null,
    attended: null,
    task_due: null,
    task_result: null,
    contract_sent_at: null,
    signed_at: null,
    cohort_month: null,
    closed_stage: null,
    closed_reason: null,
    closed_at: null,
    reapplied_at: null,
    note: null,
    updated_at: at(-1),
    ...overrides,
  };
}

const SESSIONS: AcademySessionRow[] = [
  { id: 1, starts_at: at(-2), location: "Biuro, sala 2", capacity: 8, taken: 3, people: 3, cancelled: false },
  { id: 2, starts_at: at(3), location: "Biuro, sala 2", capacity: 8, taken: 2, people: 2, cancelled: false },
  { id: 3, starts_at: at(5), location: "Biuro, sala 2", capacity: 8, taken: 7, people: 7, cancelled: false },
  { id: 4, starts_at: at(6), location: "Biuro, sala 2", capacity: 8, taken: 0, people: 0, cancelled: false },
];

const APPS: AcademyApplication[] = [
  person(1, "Mateusz Przykładowy", { screening_facts: { experience_basis: "all_work" }, experience_years: 3, screening_reasons: [{ code: "experience_ok", text: "3 lata pracy, bez ukończonych studiów." }, { code: "polish_ok", text: "Polski: ojczysty." }] }),
  person(2, "Natalia Testowa", { experience_years: 0, screening_facts: { still_studying: true }, screening_reasons: [{ code: "experience_ok", text: "0 lat pracy, studiuje." }] }),
  person(3, "Kacper Fikcyjny", { screening_verdict: "review", experience_years: null, screening_reasons: [{ code: "experience_unknown", text: "Nie da się policzyć doświadczenia — brak dat w CV." }] }),
  person(4, "Oliwia Wzorcowa", { call_attempts: 1 }),
  person(5, "Jakub Próbny", {}),
  person(6, "Zuzanna Szablonowa", { status: "scheduled", session_id: 2, session_starts_at: at(3) }),
  person(7, "Julia Makietowa", { status: "scheduled", session_id: 2, session_starts_at: at(3) }),
  person(8, "Wiktor Demo", { status: "task_given", session_id: 1, session_starts_at: at(-2), attended: true, task_due: toIsoDate(new Date(2026, 9, 27)) }),
  person(9, "Maja Przykład", { status: "task_given", session_id: 1, session_starts_at: at(-2), attended: true, task_due: toIsoDate(new Date(2026, 9, 22)) }),
  person(10, "Hubert Testowy", { status: "task_passed", session_id: 1, task_result: "passed" }),
  person(11, "Emilia Fikcyjna", { status: "contract_sent", contract_sent_at: at(-1) }),
  person(12, "Filip Wzór", { status: "signed", signed_at: at(-2), cohort_month: toIsoDate(nextCohort(NOW)) }),
  person(13, "Aleksandra Próbna", { status: "new", screening_verdict: "skip", experience_years: 9.5, screening_reasons: [{ code: "experience_over", text: "9,5 roku pracy po studiach (koniec 2016) — limit 6 lat." }, { code: "polish_ok", text: "Polski: ojczysty." }] }),
  person(14, "Piotr Demonstracyjny", { status: "new", screening_verdict: "skip", screening_reasons: [{ code: "polish_basic", text: "Polski poniżej poziomu biegłego — praca wymaga rozmów po polsku.", quote: "polski B1" }] }),
  person(15, "Kamil Makieta", { status: "rejected", closed_stage: "to_call", closed_reason: "Nie pasują warunki z ogłoszenia: szuka pracy zdalnej", closed_at: at(-40), reapplied_at: at(-1) }),
  person(16, "Marta Szkicowa", { status: "rejected", closed_stage: "task_given", closed_reason: "Nie zaliczył zadania", closed_at: at(-30) }),
  person(17, "Adam Zrezygnowany", { status: "withdrew", closed_stage: "scheduled", closed_reason: "Zrezygnował sam", closed_at: at(-5) }),
];

const STATUS_AFTER: Partial<Record<ActionBody["action"], AcademyApplication["status"]>> = {
  call: "to_call",
  schedule: "scheduled",
  give_task: "task_given",
  task_passed: "task_passed",
  task_failed: "rejected",
  contract_sent: "contract_sent",
  signed: "signed",
  reject: "rejected",
  withdraw: "withdrew",
  restore: "to_call",
};

function PreviewInner() {
  const params = useSearchParams();
  const initial = params.get("view");
  const [view, setView] = React.useState<AcademyView>(
    (ACADEMY_VIEWS as readonly string[]).includes(initial ?? "") ? (initial as AcademyView) : "edition",
  );
  const [apps, setApps] = React.useState(APPS);
  const [sessions, setSessions] = React.useState(SESSIONS);

  const handlers: AcademyHandlers = {
    act: async (app, body) => {
      setApps((prev) =>
        prev.map((a) => {
          if (a.id !== app.id) return a;
          const status = STATUS_AFTER[body.action] ?? a.status;
          const session = sessions.find((s) => s.id === body.session_id);
          return {
            ...a,
            status,
            call_attempts: body.action === "no_answer" ? a.call_attempts + 1 : a.call_attempts,
            session_id: body.action === "schedule" ? body.session_id ?? null : a.session_id,
            session_starts_at: body.action === "schedule" ? session?.starts_at ?? null : a.session_starts_at,
            attended: body.action === "absent" ? false : body.action === "give_task" ? true : a.attended,
            task_due: body.action === "give_task" ? toIsoDate(new Date(2026, 9, 29)) : a.task_due,
            cohort_month: body.cohort_month ?? a.cohort_month,
            closed_reason: body.reason ?? (status === "to_call" ? null : a.closed_reason),
            closed_stage: status === "rejected" || status === "withdrew" ? a.status : null,
            closed_at: status === "rejected" || status === "withdrew" ? NOW.toISOString() : null,
            note: body.action === "note" ? body.note ?? null : a.note,
          };
        }),
      );
      if (body.action === "schedule") {
        setSessions((prev) => prev.map((s) => (s.id === body.session_id ? { ...s, taken: s.taken + 1, people: s.people + 1 } : s)));
      }
      return true;
    },
    bulk: async (ids, body) => {
      for (const app of apps.filter((a) => ids.includes(a.id))) {
        await handlers.act(app, { ...body, reason: body.reason ?? app.screening_reasons[0]?.text ?? "Luna odłożyła" });
      }
    },
    sync: async () => undefined,
    rhythm: async () => undefined,
    createSession: async () => undefined,
    cancelSession: async (id) => setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, cancelled: true } : s))),
    saveProgram: async () => undefined,
    addSource: async () => undefined,
    removeSource: async () => undefined,
    searchJobs: async (q) => [{ id: 103, title: `${q} — Kraków`, status: "published", external_source: "traffit" }],
    // Harness nie pobiera plików (zero zapytań) — pokazuje tylko okno.
    downloadDocuments: async () => true,
  };

  return (
    <div className="min-h-screen bg-background p-6">
      <AcademyWorkspace
        program={PROGRAM}
        apps={apps}
        sessions={sessions}
        view={view}
        onViewChange={setView}
        handlers={handlers}
        busyIds={new Set()}
        syncing={false}
        now={NOW}
        currentUserName="Jan Rekruter"
      />
    </div>
  );
}

export default function AcademyPreviewPage() {
  return (
    <Suspense>
      <PreviewInner />
    </Suspense>
  );
}
