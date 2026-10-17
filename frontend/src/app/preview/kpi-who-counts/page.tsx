"use client";

/**
 * Harness listy „Kto się liczy” (17.10.2026) — publiczny, ZERO zapytań.
 *
 * Rysuje `WhoCountsListView` na danych fikcyjnych: lista własna rekrutera
 * (rekomendacje w tygodniu), lista lidera dla zespołu i ta sama lista w ramie
 * kafla pulpitu (480 px), gdzie tabela przewija się w poziomie zamiast łamać.
 */

import { useState } from "react";

import { Panel } from "@/components/insights/views/ViewKit";
import { WhoCountsListView } from "@/components/v2/kpi/WhoCountsList";
import type {
  RecruitmentActivityDetailItem,
  RecruitmentActivityDetailResponse,
  RecruitmentActivityState,
} from "@/lib/recruitment-activity-api";

const TODAY = "2026-10-17";
const ME = { id: 11, name: "Ola Przykładowa", role: "recruiter" };
const LEAD = { id: 21, name: "Marta Testowa", role: "delivery_lead" };
const LEAD_TWO = { id: 22, name: "Olga Wzorcowa", role: "delivery_lead" };

function row(
  candidate: [number, string],
  job: [number, string, string | null, string],
  reachedAt: string,
  mover: typeof ME,
  state: RecruitmentActivityState,
  extra: Partial<RecruitmentActivityDetailItem> = {},
): RecruitmentActivityDetailItem {
  const [candidateId, name] = candidate;
  const [jobId, title, reference, client] = job;
  return {
    candidate: { id: candidateId, name, href: `/candidates/${candidateId}` },
    job: {
      id: jobId,
      title,
      working_title: title,
      client_reference: reference,
      client_name: client,
      href: `/jobs/${jobId}?candidate=${candidateId}`,
    },
    credited_user: ME,
    reached_at: reachedAt,
    moved_by: mover,
    state,
    state_stage: state === "at_client" ? "client_interview" : state === "waiting" ? "cv_sent" : "rejected",
    state_since: reachedAt,
    candidate_jobs: 1,
    ...extra,
  };
}

const JAVA: [number, string, string | null, string] = [1418, "Senior Java Developer", "ZOB-9001", "Bank Przykładowy"];
const PAYMENTS: [number, string, string | null, string] = [1431, "Java Developer · płatności", null, "Telekom Testowy"];
const ANALYST: [number, string, string | null, string] = [1402, "Analityk biznesowy", "SAP-7001", "Ubezpieczenia Wzorcowe"];
const DEVOPS: [number, string, string | null, string] = [1433, "DevOps Engineer (Azure)", null, "Telekom Testowy"];
const TESTER: [number, string, string | null, string] = [1377, "Tester automatyzujący", null, "Sklep Fikcyjny"];

const ITEMS: RecruitmentActivityDetailItem[] = [
  row([1, "Anna Przykładowa"], JAVA, "2026-10-15T14:42:00Z", LEAD, "waiting", { candidate_jobs: 2 }),
  row([1, "Anna Przykładowa"], PAYMENTS, "2026-10-15T12:05:00Z", ME, "at_client", {
    candidate_jobs: 2,
    state_since: "2026-10-16T09:00:00Z",
  }),
  row([2, "Piotr Testowy"], ANALYST, "2026-10-15T09:20:00Z", LEAD_TWO, "rejected_by_client", {
    state_reason: "Za mało doświadczenia w domenie",
    state_since: "2026-10-16T11:00:00Z",
  }),
  row([3, "Kamil Wzorcowy"], DEVOPS, "2026-10-15T07:12:00Z", LEAD, "waiting"),
  row([4, "Ewa Fikcyjna"], TESTER, "2026-10-14T15:30:00Z", ME, "hired", {
    state_stage: "hired",
    state_since: "2026-10-16T10:00:00Z",
  }),
  row([5, "Marek Próbny"], JAVA, "2026-10-14T11:48:00Z", LEAD, "job_closed", { state_stage: "cv_sent" }),
  row([6, "Julia Makietowa"], ANALYST, "2026-10-12T08:02:00Z", LEAD_TWO, "ended", {
    state_stage: "withdrawn",
    state_reason: "Przyjęła inną ofertę",
  }),
];

const STATES: Partial<Record<RecruitmentActivityState, number>> = {};
for (const item of ITEMS) {
  if (item.state) STATES[item.state] = (STATES[item.state] ?? 0) + 1;
}

const OWN: RecruitmentActivityDetailResponse = {
  generated_at: "2026-10-17T10:00:00Z",
  metric: "recommendation",
  window: "week",
  page: 1,
  page_size: 50,
  total: ITEMS.length,
  period_total: ITEMS.length,
  period_start: "2026-10-12",
  period_end: "2026-10-18",
  scope: "person",
  subject: ME,
  people: 6,
  moved_by_credited: 2,
  states: STATES,
  items: ITEMS,
};

const TEAM: RecruitmentActivityDetailResponse = {
  ...OWN,
  scope: "team",
  subject: null,
};

function Demo({
  response,
  viewerId,
}: {
  response: RecruitmentActivityDetailResponse;
  viewerId: number;
}) {
  const [state, setState] = useState<RecruitmentActivityState | null>(null);
  const shown =
    state === null
      ? response
      : {
          ...response,
          state_filter: state,
          total: response.states?.[state] ?? 0,
          items: response.items.filter((item) => item.state === state),
        };
  return (
    <WhoCountsListView
      metric="recommendation"
      response={shown}
      viewerId={viewerId}
      today={TODAY}
      state={state}
      onStateChange={setState}
      onPageChange={() => undefined}
    />
  );
}

export default function KpiWhoCountsPreviewPage() {
  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-6">
      <h1 className="text-xl font-semibold text-foreground">Kto się liczy — harness</h1>
      <Panel title="Kto się liczy do celów" hint="Rekomendacje · 12–18 paź · ten tydzień">
        <Demo response={OWN} viewerId={ME.id} />
      </Panel>
      <Panel title="Kto się liczy · Ola Przykładowa" hint="widok lidera z Insights → Zespół">
        <Demo response={OWN} viewerId={1} />
      </Panel>
      <Panel title="Cały zespół" hint="kafel „Aktywność rekrutacyjna”, zakres zespołu">
        <Demo response={TEAM} viewerId={1} />
      </Panel>
      <section className="@container w-full max-w-[480px] rounded-xl border border-border bg-muted/20 p-4">
        <h2 className="mb-3 text-sm font-semibold text-foreground">Rama kafla 480 px</h2>
        <Demo response={OWN} viewerId={ME.id} />
      </section>
    </main>
  );
}
