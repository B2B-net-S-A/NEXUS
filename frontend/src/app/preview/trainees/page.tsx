"use client";

/**
 * Harness panelu „Praktykanci” i reguł listy (0372) — publiczny, ZERO zapytań.
 *
 * `?view=panel` (domyślnie) · `rules` (Ustawienia → Lista telefonów praktykantów).
 * Cache zasiany kluczami `traineeKeys`, warstwa `traineeApi` podmieniona na
 * stan lokalny na czas życia harnessu, sieć odcięta interceptorem.
 */

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import {
  PREVIEW_RULES,
  previewOverview,
  previewQualitySample,
  previewRulesPreview,
} from "@/components/trainee/preview-fixtures";
import { TraineeRulesForm } from "@/components/trainee/TraineeRulesForm";
import { TraineesPanel } from "@/components/trainee/TraineesPanel";
import { api } from "@/lib/api";
import { traineeApi, traineeKeys, type TraineeRules } from "@/lib/api/trainee";

function useNetworkBlocked() {
  const [interceptorId] = useState(() =>
    api.interceptors.request.use(() =>
      Promise.reject(
        Object.assign(new Error("Harness /preview/trainees nie wysyła zapytań."), {
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

function useLocalTraineeApi() {
  useEffect(() => {
    let overview = previewOverview();
    let rules: TraineeRules = PREVIEW_RULES;
    Object.assign(traineeApi, {
      overview: async () => overview,
      qualitySample: async () => previewQualitySample(),
      qualityVerdict: async () => ({ ok: true }),
      updateProgram: async (userId: number, body: Parameters<typeof traineeApi.updateProgram>[1]) => {
        overview = {
          ...overview,
          trainees: overview.trainees.map((row) =>
            row.user_id === userId && row.program
              ? {
                  ...row,
                  program: {
                    ...row.program,
                    start_date: body.start_date ?? row.program.start_date,
                    workdays: body.workdays ?? row.program.workdays,
                    total_days: body.workdays ?? row.program.total_days,
                    daily_list_size: body.daily_list_size ?? row.program.daily_list_size,
                  },
                }
              : row,
          ),
        };
        return { ok: true };
      },
      decision: async (userId: number) => {
        overview = {
          ...overview,
          trainees: overview.trainees.map((row) =>
            row.user_id === userId && row.program
              ? { ...row, program: { ...row.program, decision_due: false } }
              : row,
          ),
        };
        return { ok: true };
      },
      rules: async () => rules,
      saveRules: async (body: TraineeRules) => {
        rules = body;
        return body;
      },
      rulesPreview: async (body: TraineeRules | null) => previewRulesPreview(body),
    });
    return () => {
      Object.assign(traineeApi, REAL_TRAINEE_API);
    };
  }, []);
}

function seededClient(): QueryClient {
  const client = new QueryClient({
    defaultOptions: {
      queries: { staleTime: Infinity, gcTime: Infinity, retry: false, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  });
  const overview = previewOverview();
  client.setQueryData(traineeKeys.overview(), overview);
  for (const row of overview.trainees) {
    client.setQueryData(traineeKeys.qualitySample(row.user_id), previewQualitySample());
  }
  client.setQueryData(traineeKeys.rules(), PREVIEW_RULES);
  client.setQueryData(traineeKeys.rulesPreview(PREVIEW_RULES), previewRulesPreview(PREVIEW_RULES));
  return client;
}

function Harness() {
  const params = useSearchParams();
  const view = params.get("view") === "rules" ? "rules" : "panel";
  const [client] = useState(seededClient);
  useNetworkBlocked();
  useLocalTraineeApi();
  return (
    <QueryClientProvider client={client}>
      <main className="min-h-dvh bg-background p-4 text-foreground md:p-6">
        {view === "rules" ? (
          <div className="mx-auto max-w-7xl space-y-6">
            <h1 className="text-2xl font-bold text-foreground">Lista telefonów praktykantów</h1>
            <TraineeRulesForm />
          </div>
        ) : (
          <TraineesPanel />
        )}
      </main>
    </QueryClientProvider>
  );
}

export default function TraineesPreviewPage() {
  return (
    <Suspense fallback={null}>
      <Harness />
    </Suspense>
  );
}
