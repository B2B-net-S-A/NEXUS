"use client";

/**
 * Harness „Telefony na dziś” (praktykant, 0371) — publiczny, ZERO zapytań.
 *
 * `?state=today` (domyślnie) · `done` (dzień zaliczony) · `handover` (otwarte
 * okno „Przekaż rekruterowi”) · `employment_only` (zaznaczone „Nie, tylko etat”).
 *
 * Cache react-query jest zasiany tymi samymi kluczami co ekran
 * (`traineeKeys.today()`), a warstwa `traineeApi` jest na czas życia harnessu
 * podmieniona na stan lokalny — zapis rozmowy i wyniki działają, ale żadne
 * żądanie nie wychodzi (interceptor dodatkowo odcina sieć).
 */

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import {
  PREVIEW_LIST_DATE,
  PREVIEW_NOW,
  PREVIEW_OPEN_JOBS,
  PREVIEW_TRAINEE_NAME,
  applyPreviewCall,
  applyPreviewOutcome,
  previewDoneToday,
  previewToday,
} from "@/components/trainee/preview-fixtures";
import { TraineeTodayView } from "@/components/trainee/TraineeTodayView";
import { TraineeTopBar, traineeDateLabel } from "@/components/trainee/TraineeShell";
import { api } from "@/lib/api";
import { traineeApi, traineeKeys, type TraineeToday } from "@/lib/api/trainee";

type HarnessState = "today" | "done" | "handover" | "employment_only";
const STATES: HarnessState[] = ["today", "done", "handover", "employment_only"];

function useNetworkBlocked() {
  const [interceptorId] = useState(() =>
    api.interceptors.request.use(() =>
      Promise.reject(
        Object.assign(new Error("Harness /preview/trainee nie wysyła zapytań."), {
          isAxiosError: true,
          code: "ERR_PREVIEW_OFFLINE",
        }),
      ),
    ),
  );
  useEffect(() => () => api.interceptors.request.eject(interceptorId), [interceptorId]);
}

/** Prawdziwa warstwa API — przywracana przy odmontowaniu harnessu. */
const REAL_TRAINEE_API = { ...traineeApi };

/**
 * Podmiana `traineeApi` na stan lokalny. W efekcie, nie w renderze: pierwsze
 * zapytanie i tak nie wychodzi (cache zasiany, `staleTime: Infinity`), a efekt
 * z przywróceniem przeżywa podwójne montowanie trybu Strict.
 */
function useLocalTraineeApi(initial: TraineeToday) {
  useEffect(() => {
    let state = initial;
    Object.assign(traineeApi, {
      today: async () => state,
      saveCall: async (itemId: number, body: Parameters<typeof traineeApi.saveCall>[1]) => {
        const next = applyPreviewCall(state, itemId, body);
        state = next.today;
        return next.response;
      },
      saveOutcome: async (itemId: number, body: Parameters<typeof traineeApi.saveOutcome>[1]) => {
        const next = applyPreviewOutcome(state, itemId, body);
        state = next.today;
        return next.response;
      },
      openJobs: async () => PREVIEW_OPEN_JOBS,
      handover: async () => ({ ok: true }),
    });
    return () => {
      Object.assign(traineeApi, REAL_TRAINEE_API);
    };
  }, [initial]);
}

function seededClient(today: TraineeToday): QueryClient {
  const client = new QueryClient({
    defaultOptions: {
      queries: { staleTime: Infinity, gcTime: Infinity, retry: false, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  });
  client.setQueryData(traineeKeys.today(), today);
  for (const item of today.items) {
    client.setQueryData(traineeKeys.openJobs(item.id), PREVIEW_OPEN_JOBS);
  }
  return client;
}

function Harness() {
  const params = useSearchParams();
  const raw = params.get("state") as HarnessState | null;
  const state: HarnessState = raw && STATES.includes(raw) ? raw : "today";
  const [initial] = useState(() => (state === "done" ? previewDoneToday() : previewToday()));
  const [client] = useState(() => seededClient(initial));
  useNetworkBlocked();
  useLocalTraineeApi(initial);

  return (
    <QueryClientProvider client={client}>
      <div className="flex min-h-dvh flex-col bg-background text-foreground">
        <TraineeTopBar
          userName={PREVIEW_TRAINEE_NAME}
          dateLabel={traineeDateLabel(PREVIEW_LIST_DATE)}
          programDay={{ day: 12, total: 40 }}
          onLogout={() => undefined}
        />
        <main className="flex-1 p-4 md:p-6">
          <TraineeTodayView
            key={state}
            now={PREVIEW_NOW}
            traineeName={PREVIEW_TRAINEE_NAME}
            initialHandoverOpen={state === "handover"}
            initialForm={
              state === "employment_only"
                ? { b2b: "employment_only" }
                : state === "handover"
                  ? { b2b: "b2b", rateValue: "145", acceptsBelowMin: true, workTime: "also_part_time", remoteModes: ["hybrid"], maxOnsiteDays: "2", officeCities: "Kraków", acceptsMoreOfficeDays: false, availability: "within_1m", openToOffers: "yes", wants: "Kafkę zna produkcyjnie (3 lata). Nie chce bankowości." }
                  : undefined
            }
          />
        </main>
      </div>
    </QueryClientProvider>
  );
}

export default function TraineePreviewPage() {
  return (
    <Suspense fallback={null}>
      <Harness />
    </Suspense>
  );
}
