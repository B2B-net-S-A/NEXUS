"use client";

/**
 * Harness panelu „Podobne rekrutacje” (przepięcia jednym kliknięciem,
 * 25.09.2026) — produkcyjny `SimilarJobsPanel` na ZASIANYM cache react-query,
 * bez API i bez logowania. Interceptor odrzuca każde żądanie axiosa, więc
 * kliknięcie „Przepnij” kończy się komunikatem błędu — to podgląd wyglądu.
 *
 * W polu wyszukiwania wpisz „analityk pko”, żeby zobaczyć wyniki. Dane są
 * fikcyjne — repo jest publiczne.
 */

import { useEffect, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AxiosError } from "axios";

import api from "@/lib/api";
import { ToastProvider } from "@/components/Toast";
import { SimilarJobsPanel } from "@/components/v2/jobs/SimilarJobsPanel";
import {
  similarJobsKey,
  similarPeopleKey,
  similarSearchKey,
  type SentPerson,
  type SimilarJobItem,
} from "@/lib/similar-jobs-api";

const JOB_ID = 5;

function job(id: number, title: string, overrides: Partial<SimilarJobItem> = {}): SimilarJobItem {
  return {
    id,
    title,
    reference_number: `DEMO-${id}`,
    status: "closed",
    closed_at: null,
    client_name: "Klient Demo",
    similarity: 70,
    sent_count: 0,
    linked: false,
    ...overrides,
  };
}

function person(candidate_id: number, name: string, overrides: Partial<SentPerson> = {}): SentPerson {
  return {
    candidate_id,
    name,
    furthest_stage: "cv_sent",
    sent_at: "2026-09-12",
    outcome: "in_progress",
    already_in_job: false,
    selectable: true,
    ...overrides,
  };
}

function seededClient(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { staleTime: Infinity, retry: false, refetchOnMount: false, refetchOnWindowFocus: false },
    },
  });
  qc.setQueryData(similarJobsKey(JOB_ID), {
    job_id: JOB_ID,
    reassigned_count: 2,
    linked: [job(1500, "Analityk Biznesowy", { linked: true, sent_count: 2, similarity: null })],
    suggestions: [
      job(1725, "Analityk Systemowy", { similarity: 78, sent_count: 3 }),
      job(1794, "Analityk Systemowy x3", { status: "published", similarity: 71, sent_count: 2 }),
      job(2770, "Analityk Biznesowy Senior", { similarity: 58, sent_count: 0 }),
    ],
  });
  qc.setQueryData(similarPeopleKey(JOB_ID, 1725), [
    person(10, "Ewa Przykładowa"),
    person(11, "Tomasz Testowy", { furthest_stage: "client_interview", sent_at: "2026-09-03" }),
    person(12, "Marek Fikcyjny", { outcome: "rejected_by_client", sent_at: "2026-08-20" }),
  ]);
  qc.setQueryData(similarPeopleKey(JOB_ID, 1794), [
    person(13, "Agata Demonstracyjna"),
    person(14, "Oskar Wzorcowy", { furthest_stage: "hired", outcome: "hired", selectable: false }),
    person(10, "Ewa Przykładowa"),
  ]);
  qc.setQueryData(similarPeopleKey(JOB_ID, 2770), []);
  qc.setQueryData(similarPeopleKey(JOB_ID, 1500), [
    person(15, "Kamil Bezdanych", { already_in_job: true, selectable: false }),
  ]);
  qc.setQueryData(similarSearchKey(JOB_ID, "analityk pko"), [
    job(1837, "Analityk Systemowy", { sent_count: 4, similarity: null }),
    job(2931, "Analityk Biznesowy", { sent_count: 1, similarity: null }),
  ]);
  qc.setQueryData(similarPeopleKey(JOB_ID, 1837), [
    person(16, "Piotr Wzorcowy", { sent_at: "2026-07-11" }),
    person(17, "Kamil Demo", { furthest_stage: "client_interview" }),
  ]);
  return qc;
}

export default function SimilarReassignPreview() {
  const [ready, setReady] = useState(false);
  const [qc] = useState(seededClient);
  const [open, setOpen] = useState(true);

  useEffect(() => {
    const blocker = api.interceptors.request.use((config) =>
      Promise.reject(new AxiosError("preview: sieć wyłączona", "ECONNABORTED", config)),
    );
    setReady(true);
    return () => api.interceptors.request.eject(blocker);
  }, []);

  if (!ready) return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;

  return (
    <ToastProvider>
      <QueryClientProvider client={qc}>
        <div className="min-h-dvh bg-background p-6">
          <button
            type="button"
            className="rounded-md border border-border px-3 py-1.5 text-sm"
            onClick={() => setOpen(true)}
          >
            Otwórz „Podobne rekrutacje”
          </button>
          <SimilarJobsPanel jobId={JOB_ID} open={open} onOpenChange={setOpen} />
        </div>
      </QueryClientProvider>
    </ToastProvider>
  );
}
