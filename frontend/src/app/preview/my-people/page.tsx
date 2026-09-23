"use client";

/**
 * Harness wizualny panelu „Moi ludzie" — publiczny, ZERO zapytań.
 *
 * Renderuje prezentacyjne widoki (`MyPeopleViews`, `MyPeopleBuddyView`) na
 * danych fikcyjnych (repo jest publiczne — żadnych prawdziwych nazwisk).
 * Stany obok siebie, żeby „awaria wektorów" nie dała się pomylić z „nikt nie
 * pasuje", a pusta lista z błędem.
 */

import type { ForJobResponse, MyPeopleRow, MyPeopleSummary } from "@/lib/api/myPeople";
import { splitPeople, summarySentences } from "@/lib/my-people-summary";
import {
  EmptyListView,
  ErrorView,
  ForJobView,
  PeopleListView,
  type RowActions,
} from "@/components/v2/my-people/MyPeopleViews";
import { MyPeopleBuddyView } from "@/components/v2/my-people/MyPeopleLauncher";

const CATEGORIES = [
  { id: 1, name_pl: "Infrastruktura i operacje" },
  { id: 2, name_pl: "Wytwarzanie oprogramowania" },
  { id: 3, name_pl: "Dane i AI" },
];

function person(overrides: Partial<MyPeopleRow>): MyPeopleRow {
  return {
    candidate_id: 1,
    full_name: "Anna Przykładowa",
    category_id: 2,
    furthest_stage: "cv_sent",
    last_sent_at: "2026-08-20T10:00:00Z",
    last_sent_job_title: "Java Developer",
    last_sent_client_name: "Klient Alfa",
    sent_count: 1,
    days_since_last_send: 32,
    expected_rate_hourly: 140,
    availability_status: "open_to_offers",
    city: "Warszawa",
    source: "auto",
    active_processes: 0,
    working: false,
    snoozed: false,
    snooze_reason: null,
    snoozed_at: null,
    new_matches: 0,
    ...overrides,
  };
}

const ROWS: MyPeopleRow[] = [
  person({ candidate_id: 1, furthest_stage: "client_interview", new_matches: 2, days_since_last_send: 12 }),
  person({ candidate_id: 2, full_name: "Bartek Testowy", sent_count: 3, active_processes: 1, days_since_last_send: 3 }),
  person({ candidate_id: 3, full_name: "Celina Fikcyjna", category_id: 1, last_sent_client_name: "Klient Beta", days_since_last_send: 91, expected_rate_hourly: 175 }),
  person({ candidate_id: 4, full_name: "Dawid Wzorcowy", category_id: 3, source: "pinned", last_sent_at: null, furthest_stage: null, days_since_last_send: null, sent_count: 0, last_sent_client_name: null }),
  person({ candidate_id: 5, full_name: "Ewa Bezkategorii", category_id: null, days_since_last_send: 44 }),
  person({ candidate_id: 6, full_name: "Filip Pracujący", working: true }),
  person({ candidate_id: 7, full_name: "Grażyna Uśpiona", snoozed: true, snooze_reason: "found_job" }),
];

const SUMMARY: MyPeopleSummary = {
  total: 5,
  new_matches: 3,
  jobs_with_matches: 2,
  latest_matches: [
    { job_id: 11, job_title: "Senior Java Developer", candidate_id: 1, full_name: "Anna Przykładowa", score: 84, created_at: "2026-09-21T08:00:00Z" },
  ],
  idle_count: 2,
  idle_top: [{ candidate_id: 5, full_name: "Ewa Bezkategorii", days_since_last_send: 44 }],
  idle_days: 30,
};

const FOR_JOB: ForJobResponse = {
  job_id: 11,
  job_title: "Senior Java Developer",
  in_job_count: 1,
  degraded: false,
  rows: [
    { candidate_id: 1, full_name: "Anna Przykładowa", category_id: 2, score: 84, measurement: "measured", eligibility: null, sent_to_client_at: "2026-05-04T09:00:00Z", last_sent_client_name: "Klient Alfa", days_since_last_send: 12, expected_rate_hourly: 140, active_processes: 0 },
    {
      candidate_id: 2, full_name: "Bartek Testowy", category_id: 2, score: 71, measurement: "measured",
      eligibility: { reason_code: "client_nda", reason: "Obowiązuje NDA z tym klientem", assignment_allowed: true, visibility: "warn", severity: "warning", secondary: [] },
      sent_to_client_at: null, last_sent_client_name: "Klient Beta", days_since_last_send: 3, expected_rate_hourly: 150, active_processes: 1,
    },
    { candidate_id: 5, full_name: "Ewa Bezkategorii", category_id: null, score: null, measurement: "missing_vector", eligibility: null, sent_to_client_at: null, last_sent_client_name: null, days_since_last_send: 44, expected_rate_hourly: null, active_processes: 0 },
  ],
};

const noop = () => undefined;
const ACTIONS: RowActions = { onAdd: noop, onSnooze: noop, onUnsnooze: noop };

function Frame({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="w-full max-w-[420px] shrink-0 rounded-xl border border-border bg-background shadow-sm">
      <h2 className="border-b border-border px-4 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h2>
      <div className="max-h-[560px] overflow-y-auto p-3">{children}</div>
    </section>
  );
}

export default function MyPeoplePreviewPage() {
  const split = splitPeople(ROWS);
  return (
    <main className="min-h-screen bg-muted/30 p-6">
      <h1 className="mb-1 text-lg font-semibold text-foreground">Moi ludzie — harness</h1>
      <p className="mb-4 max-w-3xl text-sm text-muted-foreground">
        {summarySentences(SUMMARY).join(" ")}
      </p>
      <div className="flex flex-wrap gap-4">
        <Frame title="Wszyscy — dane">
          <PeopleListView
            active={split.active}
            working={split.working}
            snoozed={split.snoozed}
            categories={CATEGORIES}
            actions={ACTIONS}
          />
        </Frame>
        <Frame title="Do tej rekrutacji">
          <ForJobView data={FOR_JOB} actions={{ onAdd: noop }} />
        </Frame>
        <Frame title="Do tej rekrutacji — wektory niedostępne">
          <ForJobView
            data={{ ...FOR_JOB, degraded: true, rows: FOR_JOB.rows.map((r) => ({ ...r, score: null, measurement: "unavailable", eligibility: null })) }}
            actions={{ onAdd: noop }}
          />
        </Frame>
        <Frame title="Pusta lista">
          <EmptyListView />
        </Frame>
        <Frame title="Błąd">
          <ErrorView message="Nie udało się wczytać Twojej listy." onRetry={noop} />
        </Frame>
      </div>
      <MyPeopleBuddyView
        count={SUMMARY.new_matches}
        sentences={summarySentences(SUMMARY)}
        showBubble
        onOpen={noop}
        onDismissBubble={noop}
        onHide={noop}
        animate={false}
      />
    </main>
  );
}
