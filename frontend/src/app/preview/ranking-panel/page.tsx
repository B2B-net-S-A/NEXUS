"use client";

/**
 * Harness „Ranking kandydatów” — prawdziwy `RankingPanel` na zasianym cache'u,
 * fikcyjne dane (`previewFixtures.ts`), zero zapytań przy ładowaniu. Zapisy
 * blokuje layout `/preview` — przyciski pokażą komunikat błędu, nie zmienią
 * niczego. Scenariusz w adresie: `?stan=szkic|pomiar|spadek|awaria`.
 */

import { Suspense, useMemo } from "react";
import { useSearchParams } from "next/navigation";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { RankingPanel } from "@/components/settings/ranking/RankingPanel";
import {
  DRAFT_STATE,
  MEASUREMENT_DONE,
  PREVIEW,
  PREVIEW_JOBS,
  panelState,
} from "@/components/settings/ranking/previewFixtures";
import type { RankingPanelState } from "@/lib/api";

const SCENARIOS: Record<string, { label: string; state: RankingPanelState }> = {
  bez: { label: "Bez szkicu", state: panelState() },
  szkic: { label: "Szkic sprawdzony", state: DRAFT_STATE },
  pomiar: {
    label: "Pomiar w toku",
    state: {
      ...DRAFT_STATE,
      measurement: {
        ...MEASUREMENT_DONE,
        status: "running",
        result: null,
        finished_at: null,
        progress: { done: 47, target: 120, at: "2026-10-21T18:38:00+02:00" },
      },
    },
  },
  spadek: {
    label: "Spadek > 2 pkt",
    state: {
      ...DRAFT_STATE,
      measurement: {
        ...MEASUREMENT_DONE,
        result: {
          ...MEASUREMENT_DONE.result!,
          after: { ...MEASUREMENT_DONE.result!.after, page1_hit: 82.5, top50_share: 57.4 },
          max_drop_pt: 3.6,
          needs_reason: true,
        },
      },
    },
  },
  awaria: {
    label: "Pomiar przerwany",
    state: {
      ...DRAFT_STATE,
      measurement: {
        ...MEASUREMENT_DONE,
        status: "failed",
        result: null,
        error: "Pomiar przerwany (np. wdrożeniem nowej wersji) — uruchom go ponownie.",
      },
    },
  },
};

function Harness() {
  const params = useSearchParams();
  const key = params?.get("stan") ?? "bez";
  const scenario = SCENARIOS[key] ?? SCENARIOS.bez;
  const queryClient = useMemo(() => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, retryOnMount: false, staleTime: Infinity } },
    });
    qc.setQueryData(["scoring-panel"], scenario.state);
    qc.setQueryData(["scoring-panel-preview-jobs"], PREVIEW_JOBS);
    qc.setQueryData(["scoring-panel-preview", PREVIEW.job_id], PREVIEW);
    return qc;
  }, [scenario]);

  return (
    <QueryClientProvider client={queryClient}>
      <main className="mx-auto max-w-7xl space-y-5 bg-background p-6">
        <div className="space-y-1.5">
          <h1 className="text-2xl font-bold text-foreground">Ranking kandydatów — podgląd</h1>
          <p className="text-sm text-muted-foreground">
            Scenariusz: {scenario.label} (dane fikcyjne). Inne:{" "}
            {Object.keys(SCENARIOS)
              .map((name) => `?stan=${name}`)
              .join(" · ")}
          </p>
        </div>
        <RankingPanel insightsWrite isAdmin={false} pollMeasurement={false} />
      </main>
    </QueryClientProvider>
  );
}

export default function RankingPanelPreviewPage() {
  return (
    <Suspense fallback={null}>
      <Harness />
    </Suspense>
  );
}
