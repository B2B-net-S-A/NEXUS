"use client";

/**
 * Harness wizualny automatu przydziału requestów (0371) — publiczny, ZERO zapytań.
 *
 * Trzy ekrany na danych fikcyjnych (repo jest publiczne — żadnych prawdziwych
 * nazwisk): pulpit „Requesty i obłożenie” (makieta C6), panel „Kategorie
 * kompetencji” i „Porządek w requestach”. Widoki są prezentacyjne (propsy),
 * więc harness nie potrzebuje react-query ani logowania. `?screen=board|team|review`
 * pokazuje jeden ekran; bez parametru — wszystkie trzy.
 */

import { useState } from "react";
import { useSearchParams } from "next/navigation";

import { CompetenceTeamView } from "@/components/v2/competence-team/CompetenceTeamPanel";
import { RequestBoardView } from "@/components/v2/request-board/RequestBoard";
import { RequestReviewView } from "@/components/v2/request-review/RequestReview";
import type {
  CompetenceTeam,
  RequestBoard,
  ReviewResponse,
  TeamPerson,
} from "@/lib/api/requestAllocation";
import { EMPTY_FILTERS, type BoardFilters } from "@/lib/request-board";
import type { VisibleState } from "@/lib/request-work-state";

const TODAY = "2026-09-24";
const noop = () => undefined;

const people = {
  anna: { user_id: 1, name: "Anna Przykładowa" },
  bartek: { user_id: 2, name: "Bartek Testowy" },
  celina: { user_id: 3, name: "Celina Wzorcowa" },
  darek: { user_id: 4, name: "Darek Makietowy" },
  ewa: { user_id: 5, name: "Ewa Fikcyjna" },
};

const BOARD: RequestBoard = {
  mode: "shadow",
  availability_known: false,
  groups: [
    { category_id: 1, name: "Infra & Operations & Security / Data & AI", slug: "infrastructure_operations", total: 2, searching: 2, champion: 0 },
    { category_id: 2, name: "Development", slug: "software_development", total: 3, searching: 2, champion: 1 },
    { category_id: 4, name: "QA", slug: "security_quality", total: 1, searching: 1, champion: 0 },
    { category_id: 5, name: "Management & Delivery (PM & BA)", slug: "management_delivery", total: 1, searching: 1, champion: 0 },
  ],
  requests: [
    { job_id: 11, title: "DevOps Engineer (Azure)", client_name: "Klient Alfa", category_id: 1, deadline: "2026-09-30", sent: 0, champion: false, people: [{ ...people.anna, role: "sourcer", proposed: true, source: "auto" }] },
    { job_id: 12, title: "Data Engineer", client_name: "Klient Beta", category_id: 1, deadline: "2026-09-23", sent: 0, champion: false, people: [{ ...people.bartek, role: "recruiter", proposed: false, source: "manual" }] },
    { job_id: 21, title: "Senior Java Developer", client_name: "Klient Gamma", category_id: 2, deadline: "2026-09-26", sent: 0, champion: false, people: [{ ...people.celina, role: "recruiter", proposed: false, source: "auto" }, { ...people.anna, role: "sourcer", proposed: false, source: "manual" }] },
    { job_id: 22, title: "Kotlin Developer", client_name: "Klient Delta", category_id: 2, deadline: "2026-10-07", sent: 1, champion: false, people: [{ ...people.darek, role: "recruiter", proposed: false, source: "auto" }] },
    { job_id: 23, title: "React Developer", client_name: "Klient Alfa", category_id: 2, deadline: "2026-09-28", sent: 3, champion: true, people: [{ ...people.darek, role: "recruiter", proposed: false, source: "auto" }] },
    { job_id: 41, title: "Tester automatyzujący", client_name: "Klient Beta", category_id: 4, deadline: null, sent: 0, champion: false, people: [] },
    { job_id: 51, title: "Product Owner", client_name: "Klient Gamma", category_id: 5, deadline: "2026-10-09", sent: 2, champion: false, people: [{ ...people.ewa, role: "recruiter", proposed: false, source: "auto" }] },
  ],
  load: [
    { ...people.anna, count: 2, leave_until: null, requests: [
      { job_id: 11, title: "DevOps Engineer (Azure)", client_name: "Klient Alfa", deadline: "2026-09-30", proposed: true },
      { job_id: 21, title: "Senior Java Developer", client_name: "Klient Gamma", deadline: "2026-09-26", proposed: false },
    ] },
    { ...people.bartek, count: 1, leave_until: null, requests: [
      { job_id: 12, title: "Data Engineer", client_name: "Klient Beta", deadline: "2026-09-23", proposed: false },
    ] },
    { ...people.celina, count: 1, leave_until: null, requests: [
      { job_id: 21, title: "Senior Java Developer", client_name: "Klient Gamma", deadline: "2026-09-26", proposed: false },
    ] },
    { ...people.darek, count: 1, leave_until: null, requests: [
      { job_id: 22, title: "Kotlin Developer", client_name: "Klient Delta", deadline: "2026-10-07", proposed: false },
    ] },
    { ...people.ewa, count: 1, leave_until: "2026-09-29", requests: [
      { job_id: 51, title: "Product Owner", client_name: "Klient Gamma", deadline: "2026-10-09", proposed: false },
    ] },
  ],
  changes: [
    { at: "2026-09-24T06:30:00Z", kind: "champion", job_id: 23, title: "React Developer", client_name: "Klient Alfa", user_name: null, reason: "Mamy championa" },
    { at: "2026-09-24T06:30:00Z", kind: "assigned", job_id: 11, title: "DevOps Engineer (Azure)", client_name: "Klient Alfa", user_name: people.anna.name, reason: "propozycja automatu" },
    { at: "2026-09-23T14:10:00Z", kind: "released", job_id: 23, title: "React Developer", client_name: "Klient Alfa", user_name: people.darek.name, reason: "Mamy championa" },
  ],
};

const person = (p: { user_id: number; name: string }, roles: string[], assignment: number | null, excluded = false): TeamPerson => ({
  ...p,
  roles,
  allocation_excluded: excluded,
  assignment_id: assignment,
});

const TEAM: CompetenceTeam = {
  categories: [
    { id: 1, slug: "infrastructure_operations", name: "Infra & Operations & Security / Data & AI", requests_searching: 2, first: [person(people.anna, ["sourcer"], 101)], second: [person(people.ewa, ["recruiter"], 102)] },
    { id: 2, slug: "software_development", name: "Development", requests_searching: 2, first: [person(people.celina, ["recruiter"], 103), person(people.darek, ["recruiter"], 104)], second: [] },
    { id: 4, slug: "security_quality", name: "QA", requests_searching: 1, first: [], second: [person(people.celina, ["recruiter"], 105)] },
    { id: 5, slug: "management_delivery", name: "Management & Delivery (PM & BA)", requests_searching: 1, first: [person(people.ewa, ["recruiter"], 106)], second: [] },
  ],
  unassigned: [person(people.bartek, ["recruiter", "delivery_lead"], null)],
  excluded: [person({ user_id: 9, name: "Filip Nieaktywny" }, ["recruiter"], null, true)],
  people: [
    person(people.anna, ["sourcer"], null),
    person(people.bartek, ["recruiter", "delivery_lead"], null),
    person(people.celina, ["recruiter"], null),
    person(people.darek, ["recruiter"], null),
    person(people.ewa, ["recruiter"], null),
  ],
  rules: { sourcer_threshold: 15, review_time: "08:30" },
};

const REVIEW: ReviewResponse = {
  tab: "to_review",
  counts: { to_review: 307, searching: 14, champion: 0, client_silent: 6, finished: 0 },
  rows: [
    { job_id: 31, title: "Senior Java Developer", client_name: "Klient Gamma", delivery_lead_name: "Gosia Delivery", deadline: "2026-09-26", state: "to_review", state_label: "Do przejrzenia", last_work_at: "2026-09-23T10:00:00Z", last_cv_at: "2026-09-21T10:00:00Z", sent_total: 2, applications_14d: 41, suggested_state: "searching", suggestion_reason: "CV do klienta 3 dni temu" },
    { job_id: 32, title: "Scrum Master", client_name: "Klient Delta", delivery_lead_name: "Gosia Delivery", deadline: null, state: "to_review", state_label: "Do przejrzenia", last_work_at: "2026-08-08T10:00:00Z", last_cv_at: "2026-07-23T10:00:00Z", sent_total: 1, applications_14d: 0, suggested_state: "client_silent", suggestion_reason: "CV wysłane 63 dni temu, potem cisza" },
    { job_id: 33, title: "Tester manualny", client_name: "Klient Beta", delivery_lead_name: null, deadline: "2026-05-30", state: "to_review", state_label: "Do przejrzenia", last_work_at: null, last_cv_at: null, sent_total: 0, applications_14d: 0, suggested_state: "finished", suggestion_reason: "Brak pracy od ponad 90 dni i żadnego CV" },
  ],
};

function BoardScreen() {
  const [filters, setFilters] = useState<BoardFilters>(EMPTY_FILTERS);
  return (
    <RequestBoardView
      board={BOARD}
      today={TODAY}
      filters={filters}
      onFilters={setFilters}
      canEdit
      onAddPerson={noop}
      onRemovePerson={noop}
    />
  );
}

function ReviewScreen() {
  const [tab, setTab] = useState<VisibleState>("to_review");
  const [mine, setMine] = useState(false);
  const [q, setQ] = useState("");
  return (
    <RequestReviewView
      data={{ ...REVIEW, tab, rows: tab === "to_review" ? REVIEW.rows : [] }}
      tab={tab}
      onTab={setTab}
      mine={mine}
      onMine={setMine}
      q={q}
      onQ={setQ}
      actions={{ setState: noop, dropChampion: noop }}
    />
  );
}

export default function RequestAllocationPreview() {
  const screen = useSearchParams()?.get("screen");
  const show = (name: string) => !screen || screen === name;
  return (
    <main className="mx-auto flex max-w-[1440px] flex-col gap-10 bg-background p-6">
      {show("board") && (
        <section aria-label="Pulpit">
          <BoardScreen />
        </section>
      )}
      {show("team") && (
        <section aria-label="Kategorie kompetencji" className="flex flex-col gap-3">
          <h1 className="text-2xl font-bold">Kategorie kompetencji zespołu</h1>
          <CompetenceTeamView
            team={TEAM}
            actions={{ assign: noop, remove: noop, exclude: noop, saveRules: noop }}
          />
        </section>
      )}
      {show("review") && (
        <section aria-label="Porządek w requestach" className="flex flex-col gap-3">
          <h1 className="text-2xl font-bold">Nad którymi requestami naprawdę pracujemy?</h1>
          <ReviewScreen />
        </section>
      )}
    </main>
  );
}
