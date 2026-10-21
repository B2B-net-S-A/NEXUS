"use client";

/**
 * Harness wizualny okna „Ogłoszenie” (strona kariery, Pracuj.pl, JustJoin.IT).
 *
 * PRODUKCYJNE `JobAdWindow` z API podanym z pamięci (prop `api`) — zero
 * zapytań; layout `/preview` i tak odrzuca zapisy. „Przygotuj”, „Zapisz”
 * i „Usuń fragment” działają na danych w pamięci, a teksty do skopiowania
 * składa uproszczony odpowiednik serwerowego `render` (bez kontroli treści:
 * znaleziska w stanie `findings` są zasiane i znikają po pierwszym zapisie).
 *
 * `?state=ready|findings|template|empty|published` (domyślnie `ready`), `?tab=jjit`.
 * `published` = strona kariery i Pracuj.pl wiszą, treść zmieniona po publikacji.
 * Dane fikcyjne.
 */

import { Suspense, useMemo } from "react";
import { useSearchParams } from "next/navigation";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { JobAdWindow } from "@/components/v2/job-ad/JobAdWindow";

import { memoryApi, type HarnessState } from "../job-ad-fixtures";

const JOB_ID = 901;
const JOB_TITLE = "Senior Java Developer — płatności";

export default function JobAdPreviewPage() {
  return (
    <Suspense fallback={null}>
      <Harness />
    </Suspense>
  );
}

function Harness() {
  const params = useSearchParams();
  const raw = params?.get("state");
  const state: HarnessState =
    raw === "findings" || raw === "template" || raw === "empty" || raw === "published"
      ? raw
      : "ready";
  const tab = params?.get("tab") === "jjit" ? "jjit" : "pracuj";
  const client = useMemo(
    () => new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } }),
    [],
  );
  const api = useMemo(() => memoryApi(state), [state]);
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <main className="min-h-dvh bg-background p-6">
          <h1 className="text-lg font-semibold">Harness: ogłoszenie na portale</h1>
          <JobAdWindow
            jobId={JOB_ID}
            jobTitle={JOB_TITLE}
            open
            onClose={() => undefined}
            api={api}
            initialTab={tab}
          />
        </main>
      </ToastProvider>
    </QueryClientProvider>
  );
}
