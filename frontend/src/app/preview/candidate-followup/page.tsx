"use client";

// Publiczny harness follow-upu z kandydatem, gdy klient milczy (0372): lista
// w „Czeka na Ciebie”, blok „Kontakt z kandydatem” z doku Tablicy i okno
// zapisu wyniku telefonu. Dane fikcyjne, ZERO zapytań: panel i szczegóły
// kandydata są zasiane w cache tymi samymi kluczami, których używają
// komponenty, a interceptor odcina sieć — „Zapisz” kończy się komunikatem
// o błędzie, nic nie trafia do API.

import { useEffect, useState } from "react";
import { AxiosError } from "axios";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { BoardTasksPanel } from "@/components/v2/dashboard/BoardTasksPanel";
import { CandidateFollowupDialog } from "@/components/v2/followups/CandidateFollowupDialog";
import { DockFollowupBlock } from "@/components/v2/followups/DockFollowupBlock";
import { api } from "@/lib/api";
import { BOARD_TASKS_QUERY_KEY, type BoardTasksResponse } from "@/lib/api/boardTasks";
import {
  candidateFollowupKeys,
  type FollowupDetail,
  type FollowupRow,
} from "@/lib/api/candidateFollowups";
import { useAuthStore } from "@/store/auth";

const daysAgo = (d: number) => new Date(Date.now() - d * 86_400_000).toISOString();
const dayIso = (d: number) => daysAgo(-d).slice(0, 10);

const JAN: FollowupRow = {
  candidate_id: 21,
  candidate_name: "Jan Wiśniewski",
  phone: "600 214 390",
  due_on: dayIso(-2),
  state: "overdue",
  overdue_days: 2,
  caller_id: 2,
  caller_name: "Anna Kowalczyk",
  caller_reason: "furthest",
  processes: [
    {
      job_id: 1,
      job_title: "Backend Java Developer",
      client_name: "PKO BP",
      column: "client_interview",
      stage_name: "Po Interview",
      sent_at: daysAgo(20),
      silent_since: daysAgo(11),
      silent_days: 11,
      owner_id: 2,
      owner_name: "Anna Kowalczyk",
      last_note:
        "Debrief: poszło dobrze, HM pytał o Kafkę. Decyzja po rozmowach z dwoma innymi osobami.",
      last_note_by: "Anna Kowalczyk",
      last_note_at: daysAgo(11),
    },
    {
      job_id: 2,
      job_title: "Java Developer",
      client_name: "Nordea",
      column: "cv_sent",
      stage_name: "Wysłany do Klienta",
      sent_at: daysAgo(16),
      silent_since: daysAgo(16),
      silent_days: 16,
      owner_id: 3,
      owner_name: "Tomasz Lewandowski",
      last_note: "Nordea wstrzymała rekrutację do października, proces żyje.",
      last_note_by: "Tomasz Lewandowski",
      last_note_at: daysAgo(6),
    },
    {
      job_id: 3,
      job_title: "Senior Java Developer",
      client_name: "Alior Bank",
      column: "cv_sent",
      stage_name: "CV Wysłane",
      sent_at: daysAgo(14),
      silent_since: daysAgo(14),
      silent_days: 14,
      owner_id: 4,
      owner_name: "Ewa Nowak",
      last_note: null,
      last_note_by: null,
      last_note_at: null,
    },
  ],
  last_contact_at: daysAgo(16),
  last_contact_by: "Anna Kowalczyk",
  last_contact_kind: "note",
  no_answer_count: 0,
  pending: null,
};

const OTHERS: FollowupRow[] = [
  {
    ...JAN,
    candidate_id: 22,
    candidate_name: "Karolina Mazur",
    phone: "512 880 104",
    due_on: dayIso(0),
    state: "today",
    overdue_days: 0,
    processes: [{ ...JAN.processes[1], job_title: "Tester automatyzujący", client_name: "Polkomtel", silent_days: 13 }],
    last_contact_by: "Tomasz Lewandowski",
    last_contact_kind: "call",
  },
  {
    ...JAN,
    candidate_id: 23,
    candidate_name: "Aleksandra Dudek",
    phone: "698 031 557",
    due_on: dayIso(0),
    state: "today",
    overdue_days: 0,
    pending: "no_answer",
    no_answer_count: 2,
    processes: [
      { ...JAN.processes[2], client_name: "Credit Agricole", silent_days: 14 },
      { ...JAN.processes[1], client_name: "BIK", silent_days: 12 },
    ],
  },
];

const BOARD_TASKS: BoardTasksResponse = {
  window_days: 14,
  cpro_to_send: [],
  cpro_sent: [],
  followups: [JAN, ...OTHERS],
  followups_by_others: [
    {
      ...JAN,
      candidate_id: 30,
      candidate_name: "Marek Lis",
      caller_id: 4,
      caller_name: "Ewa Nowak",
      due_on: dayIso(5),
      state: "scheduled",
      overdue_days: 0,
    },
  ],
};

const DETAIL: FollowupDetail = {
  candidate_id: 21,
  followup: JAN,
  meetings: [],
  history: [
    {
      outcome: "connected",
      user_name: "Anna Kowalczyk",
      created_at: daysAgo(16),
      callback_on: null,
      note: "Czeka, zainteresowany wszystkimi trzema.",
    },
  ],
};

export default function CandidateFollowupPreviewPage() {
  const [ready, setReady] = useState(false);
  const [open, setOpen] = useState(true);
  const [queryClient] = useState(() => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity, refetchOnWindowFocus: false } },
    });
    qc.setQueryData<BoardTasksResponse>(BOARD_TASKS_QUERY_KEY, BOARD_TASKS);
    qc.setQueryData<FollowupDetail>(candidateFollowupKeys.detail(21), DETAIL);
    for (const row of [...OTHERS, ...(BOARD_TASKS.followups_by_others ?? [])]) {
      qc.setQueryData<FollowupDetail>(candidateFollowupKeys.detail(row.candidate_id), {
        candidate_id: row.candidate_id,
        followup: row,
        history: [],
        meetings: [],
      });
    }
    return qc;
  });

  useEffect(() => {
    const blocker = api.interceptors.request.use((config) =>
      Promise.reject(new AxiosError("preview: sieć wyłączona", "ECONNABORTED", config)),
    );
    useAuthStore.setState({
      user: {
        id: 4,
        email: "preview@example.com",
        name: "Ewa Nowak",
        role: "recruiter",
        roles: ["recruiter"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
      } as never,
      token: "preview",
    } as never);
    setReady(true);
    return () => api.interceptors.request.eject(blocker);
  }, []);

  if (!ready) return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;

  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <main className="mx-auto max-w-6xl space-y-6 px-4 py-6">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h1 className="text-lg font-semibold">Podgląd: follow-up z kandydatem</h1>
            <button type="button" className="text-sm text-primary underline" onClick={() => setOpen(true)}>
              Otwórz okno zapisu wyniku
            </button>
          </div>
          <BoardTasksPanel />
          <section aria-label="Dok osoby na Tablicy" className="max-w-md space-y-2">
            <h2 className="text-sm font-semibold">Dok osoby na Tablicy (Ewa prowadzi Alior, dzwoni Anna)</h2>
            <DockFollowupBlock
              candidateId={21}
              badge={{
                caller_id: 2,
                caller_name: "Anna Kowalczyk",
                due_on: JAN.due_on,
                state: "overdue",
                overdue_days: 2,
                process_count: 3,
              }}
            />
          </section>
        </main>
        <CandidateFollowupDialog candidateId={21} open={open} onOpenChange={setOpen} />
      </ToastProvider>
    </QueryClientProvider>
  );
}
