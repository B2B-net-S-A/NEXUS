"use client";

/**
 * Harness wizualny sekcji „Portale ogłoszeniowe” (multiposting, 0360).
 *
 * PRODUKCYJNY `JobPortalsSection` na zasianym cache react-query
 * (`staleTime: Infinity`) — zero zapytań. Na produkcji sekcja jest dziś
 * niewidoczna (portale wyłączone flagami); tu konfiguracja udaje RocketJobs
 * i Pracuj.pl gotowe oraz JustJoin.IT z niepołączonym kontem, żeby było widać
 * stany: opublikowane, aktualizacja w kolejce, w kolejce, nieudane, nic.
 * `?dialog=1` otwiera okno publikacji na RocketJobs (ostatnia rekrutacja).
 * Dane fikcyjne.
 */

import { Suspense, useMemo } from "react";
import { useSearchParams } from "next/navigation";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { JobPortalsSection } from "@/components/v2/recruitment/JobPortalsSection";
import {
  EMPTY_LISTING_OPTIONS,
  jobPortalKeys,
  type BoardDictionaries,
  type JobPostingRead,
  type PortalConfigResponse,
  type PortalListingOptions,
} from "@/lib/api/jobPortals";

const CONFIG: PortalConfigResponse = {
  any_ready: true,
  portals: [
    { portal: "rocketjobs", label: "RocketJobs", state: "ready", enabled: true },
    { portal: "justjoinit", label: "JustJoin.IT", state: "not_connected", enabled: true },
    { portal: "pracuj_pl", label: "Pracuj.pl", state: "ready", enabled: true },
  ],
};

const OPTIONS: PortalListingOptions = {
  ...EMPTY_LISTING_OPTIONS,
  category: "java",
  experience_level: "senior",
  working_time: "freelance",
  workplace_type: "hybrid",
  office_days: 2,
  city: "Warszawa",
  salary: { from: 150, to: 180, unit: "hour" },
};

const DEFAULTS: PortalListingOptions = {
  ...EMPTY_LISTING_OPTIONS,
  workplace_type: "remote",
  city: "Kraków",
};

const DICTIONARY: BoardDictionaries = {
  categories: [
    { key: "java", name: "Java" },
    { key: "devops", name: "DevOps" },
    { key: "testing", name: "Testing" },
  ],
  experience_levels: [
    { key: "junior", name: "Junior" },
    { key: "mid", name: "Mid" },
    { key: "senior", name: "Senior" },
  ],
  working_times: [
    { key: "full_time", name: "Pełny etat" },
    { key: "freelance", name: "Freelance" },
  ],
  workplace_types: [
    { key: "remote", name: "Zdalnie" },
    { key: "hybrid", name: "Hybrydowo" },
    { key: "office", name: "Biuro" },
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
    options: OPTIONS,
    pending_action: null,
    ...overrides,
  };
}

const JOBS: Array<{ id: number; title: string; postings: JobPostingRead[] }> = [
  {
    id: 901,
    title: "RocketJobs: aktualizacja w kolejce; Pracuj.pl nieudane",
    postings: [
      posting({ id: 2, portal: "pracuj_pl", status: "failed", external_id: null, url: null, published_at: null, last_error: "Integracja z Pracuj.pl czeka na dokumentację API portalu — ogłoszenie nie zostało wysłane." }),
      posting({ id: 1, portal: "rocketjobs", pending_action: "update" }),
    ],
  },
  {
    id: 902,
    title: "W kolejce do wysłania",
    postings: [
      posting({ id: 3, portal: "rocketjobs", status: "publishing", external_id: null, url: null, published_at: null, pending_action: "publish" }),
      posting({ id: 4, portal: "pracuj_pl", pending_action: "close" }),
    ],
  },
  { id: 903, title: "Jeszcze nie publikowano", postings: [] },
];

function seeded(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false, refetchOnMount: false, refetchInterval: false } },
  });
  qc.setQueryData(jobPortalKeys.config, CONFIG);
  for (const job of JOBS) {
    qc.setQueryData(jobPortalKeys.postings(job.id), job.postings);
    qc.setQueryData(jobPortalKeys.listingDefaults(job.id), DEFAULTS);
  }
  qc.setQueryData(jobPortalKeys.dictionaries("rocketjobs"), DICTIONARY);
  qc.setQueryData(jobPortalKeys.dictionaries("justjoinit"), DICTIONARY);
  return qc;
}

export default function JobPortalsPreviewPage() {
  return (
    <Suspense fallback={null}>
      <Harness />
    </Suspense>
  );
}

function Harness() {
  const client = useMemo(seeded, []);
  const dialog = useSearchParams()?.get("dialog") === "1";
  const lastJobId = JOBS[JOBS.length - 1].id;
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <main className="mx-auto max-w-xl space-y-6 bg-background p-6">
          <h1 className="text-lg font-semibold">Harness: portale ogłoszeniowe</h1>
          {JOBS.map((job) => (
            <section key={job.id} className="rounded-xl border border-border p-4">
              <h2 className="pb-2 text-sm font-semibold">{job.title}</h2>
              <JobPortalsSection
                jobId={job.id}
                readOnly={false}
                defaultOpen
                pollWhilePublishingMs={false}
                defaultDialogPortal={dialog && job.id === lastJobId ? "rocketjobs" : undefined}
              />
            </section>
          ))}
        </main>
      </ToastProvider>
    </QueryClientProvider>
  );
}
