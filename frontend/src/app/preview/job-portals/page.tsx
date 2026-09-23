"use client";

/**
 * Harness wizualny sekcji „Portale ogłoszeniowe” (multiposting, 0358).
 *
 * PRODUKCYJNY `JobPortalsSection` na zasianym cache react-query
 * (`staleTime: Infinity`) — zero zapytań. Na produkcji sekcja jest dziś
 * niewidoczna (portale wyłączone flagami); tu konfiguracja udaje dwa gotowe
 * portale, żeby było widać stany: opublikowane, w kolejce, nieudane, nic.
 * Dane fikcyjne.
 */

import { useMemo } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { JobPortalsSection } from "@/components/v2/recruitment/JobPortalsSection";
import {
  jobPortalKeys,
  type JobPostingRead,
  type PortalConfigResponse,
} from "@/lib/api/jobPortals";

const CONFIG: PortalConfigResponse = {
  any_ready: true,
  portals: [
    { portal: "pracuj_pl", label: "Pracuj.pl", state: "ready", enabled: true },
    { portal: "justjoinit", label: "JustJoinIT", state: "ready", enabled: true },
  ],
};

function posting(overrides: Partial<JobPostingRead>): JobPostingRead {
  return {
    id: 1,
    portal: "pracuj_pl",
    status: "published",
    external_id: "PR-1001",
    url: "https://example.com/ogloszenie/1001",
    published_at: "2026-09-20T09:00:00Z",
    last_synced_at: "2026-09-23T06:00:00Z",
    last_error: null,
    attempts: 1,
    created_at: "2026-09-20T08:59:00Z",
    updated_at: "2026-09-23T06:00:00Z",
    ...overrides,
  };
}

const JOBS: Array<{ id: number; title: string; postings: JobPostingRead[] }> = [
  {
    id: 901,
    title: "Opublikowane na Pracuj.pl, nieudane na JustJoinIT",
    postings: [
      posting({ id: 2, portal: "justjoinit", status: "failed", external_id: null, url: null, published_at: null, last_error: "Integracja z JustJoinIT czeka na dokumentację API portalu — ogłoszenie nie zostało wysłane." }),
      posting({ id: 1 }),
    ],
  },
  {
    id: 902,
    title: "W kolejce do wysłania",
    postings: [posting({ id: 3, status: "publishing", external_id: null, url: null, published_at: null })],
  },
  { id: 903, title: "Jeszcze nie publikowano", postings: [] },
];

function seeded(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false, refetchOnMount: false, refetchInterval: false } },
  });
  qc.setQueryData(jobPortalKeys.config, CONFIG);
  for (const job of JOBS) qc.setQueryData(jobPortalKeys.postings(job.id), job.postings);
  return qc;
}

export default function JobPortalsPreviewPage() {
  const client = useMemo(seeded, []);
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <main className="mx-auto max-w-xl space-y-6 bg-background p-6">
          <h1 className="text-lg font-semibold">Harness: portale ogłoszeniowe</h1>
          {JOBS.map((job) => (
            <section key={job.id} className="rounded-xl border border-border p-4">
              <h2 className="pb-2 text-sm font-semibold">{job.title}</h2>
              <JobPortalsSection jobId={job.id} readOnly={false} defaultOpen pollWhilePublishingMs={false} />
            </section>
          ))}
        </main>
      </ToastProvider>
    </QueryClientProvider>
  );
}
