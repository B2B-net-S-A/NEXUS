"use client";

// Publiczny harness kolejki Cpro (Rekrutacja v5): panel „Czeka na Ciebie”
// z linią per rekrutacja i okno „Wrzucaj po kolei”. Dane fikcyjne, ZERO
// zapytań: kolejka, osoba od Cpro, zespół i panel pulpitu są zasiane w cache
// tymi samymi kluczami, których używa komponent, a interceptor odcina sieć —
// „✓ Wrzucone” i „Zmień” kończą się komunikatem o błędzie, nic nie trafia do
// API (pilnuje `harness-seeds.test.ts`).

import { useEffect, useState } from "react";
import { AxiosError } from "axios";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { BoardTasksPanel } from "@/components/v2/dashboard/BoardTasksPanel";
import { CproQueueDialog } from "@/components/v2/dashboard/CproQueueDialog";
import { api } from "@/lib/api";
import {
  BOARD_TASKS_QUERY_KEY,
  CPRO_QUEUE_QUERY_KEY,
  CPRO_SENDER_QUERY_KEY,
  type BoardTaskRow,
  type BoardTasksResponse,
  type CproQueueItem,
  type CproQueueResponse,
  type CproSender,
} from "@/lib/api/boardTasks";
import { useAuthStore } from "@/store/auth";

const daysAgo = (d: number) => new Date(Date.now() - d * 86_400_000).toISOString();

const SENDER: CproSender = {
  user_id: 2,
  user_name: "Kinga Przykładowa",
  until: null,
  fallback_user_id: null,
  fallback_user_name: null,
  set_by_name: "Marta Kowalska",
  set_at: daysAgo(5),
};

const item = (over: Partial<CproQueueItem>): CproQueueItem => ({
  stage_id: 1,
  candidate_id: 1,
  candidate_name: "Kandydat",
  since: daysAgo(1),
  process_state_version: 1,
  target_stage_def_id: 44,
  return_stage_def_id: 41,
  client_rate_value: 150,
  client_rate_unit: "hourly",
  client_rate_currency: "PLN",
  availability: null,
  qc_status: "passed",
  cv: { generated_document_id: 5, document_id: null },
  ...over,
});

const QUEUE: CproQueueResponse = {
  sender: SENDER,
  sent_today: 5,
  jobs: [
    {
      job_id: 1,
      job_title: "Java Backend Developer",
      client_name: "Nordea",
      oldest_since: daysAgo(2),
      items: [
        item({ stage_id: 11, candidate_id: 21, candidate_name: "Robert Przykładowy", since: daysAgo(2), client_rate_value: 158, availability: "2026-11-01" }),
        item({ stage_id: 12, candidate_id: 22, candidate_name: "Magdalena Testowa", since: daysAgo(1), client_rate_value: 149 }),
        item({ stage_id: 13, candidate_id: 23, candidate_name: "Jan Wzorcowy", since: daysAgo(1), client_rate_value: 162, qc_status: "overridden" }),
        item({ stage_id: 14, candidate_id: 24, candidate_name: "Ewa Fikcyjna", since: daysAgo(0), client_rate_value: 140, cv: { generated_document_id: null, document_id: 9 } }),
      ],
    },
    {
      job_id: 2,
      job_title: "Data Engineer (Azure)",
      client_name: "Nordea",
      oldest_since: daysAgo(0),
      items: [
        item({ stage_id: 15, candidate_id: 25, candidate_name: "Piotr Próbny", client_rate_value: 170, availability: "2026-10-15" }),
        item({ stage_id: 16, candidate_id: 26, candidate_name: "Ola Przykład", client_rate_value: 165 }),
      ],
    },
    {
      job_id: 3,
      job_title: "Test Automation Engineer",
      client_name: "Nordea",
      oldest_since: daysAgo(0),
      items: [item({ stage_id: 17, candidate_id: 27, candidate_name: "Tomasz Wzór", client_rate_value: 130, cv: null })],
    },
  ],
};

const row = (over: Partial<BoardTaskRow>): BoardTaskRow => ({
  kind: "cpro_to_send",
  stage_id: 1,
  candidate_id: 1,
  candidate_name: "Kandydat",
  job_id: 1,
  job_title: "Java Backend Developer",
  client_id: 5,
  client_name: "Nordea",
  since: daysAgo(1),
  process_state_version: 1,
  target_stage_def_id: 44,
  assignee_id: null,
  assignee_name: null,
  ...over,
});

const BOARD_TASKS: BoardTasksResponse = {
  window_days: 14,
  cpro_to_send: QUEUE.jobs.flatMap((j) =>
    j.items.map((i) =>
      row({ stage_id: i.stage_id, candidate_id: i.candidate_id, candidate_name: i.candidate_name, job_id: j.job_id, job_title: j.job_title, since: i.since }),
    ),
  ),
  cpro_sent: [row({ kind: "cpro_sent", stage_id: 31, candidate_id: 41, candidate_name: "Paweł Wysłany", since: daysAgo(6), target_stage_def_id: null })],
};

export default function CproQueuePreviewPage() {
  const [ready, setReady] = useState(false);
  const [open, setOpen] = useState(true);
  const [queryClient] = useState(() => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity, refetchOnWindowFocus: false } },
    });
    qc.setQueryData<CproQueueResponse>(CPRO_QUEUE_QUERY_KEY, QUEUE);
    qc.setQueryData<CproSender>(CPRO_SENDER_QUERY_KEY, SENDER);
    qc.setQueryData<BoardTasksResponse>(BOARD_TASKS_QUERY_KEY, BOARD_TASKS);
    qc.setQueryData(["users-directory", "cpro-assignees"], [
      { id: 1, name: "Preview Rekruter" },
      { id: 2, name: "Kinga Przykładowa" },
      { id: 3, name: "Marta Kowalska" },
    ]);
    return qc;
  });

  useEffect(() => {
    const blocker = api.interceptors.request.use((config) =>
      Promise.reject(new AxiosError("preview: sieć wyłączona", "ECONNABORTED", config)),
    );
    useAuthStore.setState({
      user: {
        id: 2,
        email: "preview@example.com",
        name: "Kinga Przykładowa",
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
        <main className="mx-auto max-w-6xl space-y-4 px-4 py-6">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h1 className="text-lg font-semibold">Podgląd: kolejka Cpro</h1>
            <button type="button" className="text-sm text-primary underline" onClick={() => setOpen(true)}>
              Otwórz okno „Wrzucaj po kolei”
            </button>
          </div>
          <BoardTasksPanel />
        </main>
        <CproQueueDialog open={open} onClose={() => setOpen(false)} initialJobId={1} />
      </ToastProvider>
    </QueryClientProvider>
  );
}
