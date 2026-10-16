"use client";

/**
 * Harness wizualny ikon „CV” i „Rekrutacje” z górnego paska (16.10.2026, bez
 * dzwonka) — publiczny, ZERO zapytań. Części prezentacyjne na danych
 * fikcyjnych: ikona w każdym stanie (u DL pigułka z kolorem pilności) i oba
 * okienka obok siebie, żeby awaria nie dała się pomylić z „nic nowego”.
 */

import {
  CvPanel,
  CvTopbarButton,
} from "@/components/v2/shell/CvNotificationsDropdown";
import {
  JobThreadsPanel,
  JobsTopbarButton,
  type JobThreadsPanelProps,
} from "@/components/v2/shell/JobsNotificationsDropdown";
import type { CvTopicResponse, CvTransitRow, DlSendRow } from "@/lib/api/boardTasks";
import type { JobThread } from "@/lib/api/jobTopic";

const NOW = Date.now();

function ago(minutes: number): string {
  return new Date(NOW - minutes * 60_000).toISOString();
}

function transit(
  kind: CvTransitRow["kind"],
  stageId: number,
  name: string,
  extra: Partial<CvTransitRow> = {},
): CvTransitRow {
  return {
    kind,
    stage_id: stageId,
    candidate_id: stageId,
    candidate_name: name,
    job_id: 11,
    job_title: "Senior Java Developer",
    job_working_title: null,
    client_name: "Bank Północny",
    since: ago(90),
    actor_name: null,
    holder_name: null,
    reason: null,
    remark: null,
    card_edited_by: null,
    card_edited_fields: [],
    fix_labels: [],
    qc_status: null,
    ready_since: null,
    waiting_workdays: 0,
    can_nudge: false,
    ...extra,
  };
}

function sendRow(
  stageId: number,
  name: string,
  minutes: number,
  urgency: DlSendRow["urgency"],
): DlSendRow {
  return {
    stage_id: stageId,
    candidate_id: stageId,
    candidate_name: name,
    job_id: 12,
    job_title: "DevOps Engineer",
    job_working_title: null,
    client_name: "Telekom Zachód",
    ready_since: ago(minutes),
    waiting_workdays: urgency === "late" ? 3 : urgency === "due" ? 1 : 0,
    urgency,
    handed_over_by_name: "Kasia Wzorcowa",
    cpro: false,
  };
}

const RECRUITER: CvTopicResponse = {
  badge: 3,
  dl: null,
  recruiter: {
    to_check: [
      {
        document_id: 501,
        stage_id: 21,
        candidate_id: 21,
        candidate_name: "Ewa Lis",
        job_id: 13,
        job_title: "Analityk danych",
        job_working_title: null,
        client_name: "Bank Północny",
        since: ago(20),
      },
    ],
    to_fix: [
      transit("in_review", 22, "Adam Kos", { qc_status: "failed" }),
      transit("sent_back", 23, "Jan Wiśniewski", {
        actor_name: "Piotr Delivery",
        remark: "dopisz okres wypowiedzenia",
        since: ago(60 * 20),
      }),
    ],
    with_dl: [
      transit("in_review", 24, "Ola Nowak", {
        qc_status: "passed",
        holder_name: "Piotr Delivery",
        since: ago(180),
      }),
    ],
    sent: [
      transit("sent", 25, "Marta Zielińska", { actor_name: "Paweł Przykładowy", since: ago(40) }),
    ],
  },
};

const DL: CvTopicResponse = {
  badge: 2,
  recruiter: { to_check: [], to_fix: [], with_dl: [], sent: [] },
  dl: {
    to_send: [
      sendRow(31, "Ola Nowak", 60 * 24 * 3, "late"),
      sendRow(32, "Tomasz Mazur", 120, "fresh"),
    ],
    to_send_total: 2,
    worst_urgency: "late",
    with_recruiters_total: 1,
    sent_today: [
      transit("sent", 33, "Marta Zielińska", { actor_name: "Paweł Przykładowy", since: ago(30) }),
    ],
  },
};

const EMPTY: CvTopicResponse = {
  badge: 0,
  dl: null,
  recruiter: { to_check: [], to_fix: [], with_dl: [], sent: [] },
};

const JOB_THREADS: JobThread[] = [
  {
    job_id: 13,
    title: "Analityk danych",
    subtitle: "Bank Północny",
    unread_count: 1,
    has_task: true,
    last_title: "Nowy request do pracy",
    last_message: "Analityk danych · Bank Północny",
    last_at: ago(35),
    link: "/jobs/13",
  },
  {
    job_id: 11,
    title: "Senior Java Developer",
    subtitle: "Bank Północny",
    unread_count: 3,
    has_task: false,
    last_title: "Preparation Meeting: Ola Nowak",
    last_message:
      "Kandydat Ola Nowak jest na etapie „Preparation Meeting” w rekrutacji „Senior Java Developer” — kartę przesunął(-ęła) Kasia Wzorcowa.",
    last_at: ago(50),
    link: "/jobs/11",
  },
  {
    job_id: null,
    title: "Twoje requesty na dziś",
    subtitle: null,
    unread_count: 1,
    has_task: true,
    last_title: "Twoje requesty na dziś",
    last_message: "Nowe do przejrzenia: 2.",
    last_at: ago(60 * 8),
    link: "/dashboard",
  },
  {
    job_id: 14,
    title: "Frontend Developer z bardzo długą nazwą stanowiska, która się nie mieści",
    subtitle: "Sklep Sieciowy Spółka z ograniczoną odpowiedzialnością",
    unread_count: 0,
    has_task: false,
    last_title: "Umowa podpisana: Ewa Lis",
    last_message: "Kandydat Ewa Lis jest na etapie „Umowa podpisana”.",
    last_at: ago(60 * 26),
    link: "/jobs/14",
  },
];

const noop = () => undefined;

const JOBS_BASE: JobThreadsPanelProps = {
  state: "ready",
  threads: JOB_THREADS,
  unreadJobs: 3,
  onOpenThread: noop,
  onMarkAllRead: noop,
  onRetry: noop,
  onOpenSettings: noop,
};

function Frame({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="w-full max-w-96 shrink-0">
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h2>
      <div className="overflow-hidden rounded-lg border border-border bg-card shadow-md">
        {children}
      </div>
    </section>
  );
}

export default function TopbarTopicsPreviewPage() {
  return (
    <main className="min-h-dvh bg-muted/30 p-4 sm:p-6">
      <h1 className="mb-1 text-lg font-semibold text-foreground">
        Ikony „CV” i „Rekrutacje” — harness
      </h1>
      <p className="mb-4 max-w-3xl text-sm text-muted-foreground">
        Górny pasek bez dzwonka: każda ikona ma jeden temat. Dane fikcyjne, bez
        zapytań do serwera.
      </p>

      <div className="mb-6 flex flex-wrap items-center gap-6 rounded-lg border border-border bg-background px-4 py-2">
        <span className="text-xs text-muted-foreground">CV:</span>
        <CvTopbarButton badge={0} urgency={null} />
        <CvTopbarButton badge={3} urgency={null} />
        <CvTopbarButton badge={2} urgency="fresh" />
        <CvTopbarButton badge={2} urgency="due" />
        <CvTopbarButton badge={120} urgency="late" open />
        <span className="text-xs text-muted-foreground">Rekrutacje:</span>
        <JobsTopbarButton unreadJobs={0} open={false} />
        <JobsTopbarButton unreadJobs={4} open={false} />
        <JobsTopbarButton unreadJobs={120} open />
      </div>

      <div className="flex flex-wrap items-start gap-6">
        <Frame title="CV — rekruter">
          <CvPanel data={RECRUITER} onNavigate={noop} />
        </Frame>
        <Frame title="CV — Delivery Lead">
          <CvPanel data={DL} onNavigate={noop} />
        </Frame>
        <Frame title="CV — nic nie czeka">
          <CvPanel data={EMPTY} onNavigate={noop} />
        </Frame>
        <Frame title="Rekrutacje">
          <JobThreadsPanel {...JOBS_BASE} />
        </Frame>
        <Frame title="Rekrutacje — nic nowego">
          <JobThreadsPanel {...JOBS_BASE} threads={[]} unreadJobs={0} />
        </Frame>
        <Frame title="Rekrutacje — ładowanie">
          <JobThreadsPanel {...JOBS_BASE} state="loading" threads={[]} unreadJobs={0} />
        </Frame>
        <Frame title="Rekrutacje — błąd">
          <JobThreadsPanel {...JOBS_BASE} state="error" threads={[]} unreadJobs={0} />
        </Frame>
      </div>
    </main>
  );
}
