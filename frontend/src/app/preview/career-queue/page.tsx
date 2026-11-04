"use client";

/**
 * Harness „Strona kariery do uzupełnienia” (21.10.2026): PRODUKCYJNY
 * `CareerQueue` z API w pamięci — zero zapytań. Cztery rekrutacje: treść
 * gotowa, treść z fragmentem blokującym, złożona bez modelu i bez treści.
 * „Opublikuj i następna” zdejmuje rekrutację z listy. Dane fikcyjne.
 */

import { useMemo } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { CareerQueue, type CareerQueueApi } from "@/components/v2/job-ad/CareerQueue";
import type { CareerQueueItem } from "@/lib/api/jobAd";

import { memoryApi, type HarnessState } from "../job-ad-fixtures";

const BASE: Omit<CareerQueueItem, "job_id" | "title" | "ad"> = {
  city: "Warszawa",
  remote_policy: "hybrid",
  delivery_lead_name: "Gosia Przykładowa",
  opened_at: "2026-10-18T09:00:00Z",
};

const JOBS: ReadonlyArray<{ item: CareerQueueItem; state: HarnessState }> = [
  {
    item: { ...BASE, job_id: 901, title: "Senior Java Developer — płatności", ad: "ready" },
    state: "ready",
  },
  {
    item: { ...BASE, job_id: 902, title: "Analityk biznesowy — kredyty", ad: "ready" },
    state: "findings",
  },
  {
    item: {
      ...BASE,
      job_id: 903,
      title: "Tester automatyzujący (Playwright)",
      remote_policy: "remote",
      ad: "template",
    },
    state: "template",
  },
  {
    item: { ...BASE, job_id: 904, title: "Data Engineer (Databricks)", ad: "missing" },
    state: "empty",
  },
];

function harnessApi(): CareerQueueApi {
  const apis = new Map(JOBS.map(({ item, state }) => [item.job_id, memoryApi(state)]));
  const published = new Set<number>();
  const forJob = (jobId: number) => apis.get(jobId) ?? memoryApi("empty");
  return {
    careerQueue: async (scope) => {
      const items = JOBS.map(({ item }) => item).filter((item) => !published.has(item.job_id));
      return { scope, mine_count: items.length, all_count: items.length + 41, items };
    },
    get: (jobId) => forJob(jobId).get(jobId),
    generate: (jobId, lang, version) => forJob(jobId).generate(jobId, lang, version),
    save: (jobId, input) => forJob(jobId).save(jobId, input),
    markPublished: (jobId, portal, url, updated) =>
      forJob(jobId).markPublished(jobId, portal, url, updated),
    markRemoved: (jobId, portal) => forJob(jobId).markRemoved(jobId, portal),
    publishCareer: async (jobId, version) => {
      published.add(jobId);
      return forJob(jobId).publishCareer(jobId, version);
    },
  };
}

export default function CareerQueuePreviewPage() {
  const client = useMemo(
    () => new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } }),
    [],
  );
  const api = useMemo(() => harnessApi(), []);
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <div className="mx-auto max-w-[1440px] space-y-4 p-4 md:p-6">
          <div>
            <p className="text-sm text-muted-foreground">Rekrutacje</p>
            <h1 className="text-2xl font-bold tracking-[-0.02em] text-foreground">
              Strona kariery do uzupełnienia
            </h1>
          </div>
          <CareerQueue api={api} />
        </div>
      </ToastProvider>
    </QueryClientProvider>
  );
}
