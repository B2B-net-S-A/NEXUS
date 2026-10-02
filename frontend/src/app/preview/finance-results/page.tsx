"use client";

/**
 * Harness modułu Finanse — widoki bez własnego harnessu: „Wyniki miesięczne”,
 * „Archiwum” i „Import zużycia MD”. Renderuje PRODUKCYJNĄ stronę
 * `app/finance/page.tsx` (zakładki modułu, `FinanceResultsTab` z kaflami,
 * paskiem importu i tabelą, `FinanceArchiveTab`, `MdImportWorkspace`).
 *
 * Zero zapytań do API: cache react-query jest zasiany z góry
 * (`staleTime: Infinity`), odczyty `financeApi` / `mdConsumptionApi` odpowiada
 * lokalnie `installLocalFinanceBackend` (sortowanie, szukanie, zmiana
 * miesiąca i otwarcie importu MD działają bez sieci), a przechwytujący
 * `axios` odrzuca każde inne żądanie, w tym zapisy. Użytkownik w store to
 * fikcyjny admin z zapisem w sekcji Finanse.
 *
 * Widok wybiera `?view=` — ten sam parametr co na `/finance`:
 * brak = wyniki, `?view=archive`, `?view=md` (harness otwiera wtedy pierwszy
 * import z listy, żeby było widać jego wiersze). „Zmiany w zamówieniach”
 * i „Zamówienia PDF” mają własne harnessy; tu są zasiane minimalnie.
 *
 * Osoby, firmy, numery zamówień i kwoty są zmyślone (repo jest publiczne).
 */

import { Suspense, useEffect, useState } from "react";
import { AxiosError } from "axios";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import FinancePage from "@/app/finance/page";
import { ORDER_CHANGES_SUMMARY_KEY } from "@/components/finance/OrderChangesTab";
import { ToastProvider } from "@/components/Toast";
import { api } from "@/lib/api";
import type {
  FinanceImportRun,
  FinancePeriod,
  FinanceResultsResponse,
  OrderChangesResponse,
  OrderChangesSummary,
  OrderPdfMonth,
} from "@/lib/api/finance";
import type { ImportSummary } from "@/lib/api/orderGroups";
import type { ClientRef } from "@/lib/contract-client-filter";
import { parseFinanceView } from "@/lib/finance-view";
import { useAuthStore } from "@/store/auth";

import {
  CLIENTS_LOOKUP,
  DEFAULT_PERIOD,
  IMPORT_RUNS,
  MD_IMPORTS,
  ORDER_PDF_MONTHS,
  PERIODS,
  PREVIEW_USER,
  buildOrderChanges,
  buildOrderChangesSummary,
  buildResults,
  currentOrderChangesMonth,
  installLocalFinanceBackend,
} from "./fixtures";

function seededClient(today: Date): QueryClient {
  const qc = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: Infinity,
        retry: false,
        refetchOnMount: false,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
      },
    },
  });

  // „Wyniki miesięczne”: lista miesięcy i wyniki miesiąca otwieranego
  // domyślnie (klucz jak w `FinanceResultsTab`: rok, miesiąc, szukanie,
  // sortowanie, kierunek).
  qc.setQueryData<FinancePeriod[]>(["finance-periods"], PERIODS);
  const results = buildResults({
    year: DEFAULT_PERIOD.year,
    month: DEFAULT_PERIOD.month,
    sort: "row_number",
    direction: "asc",
  });
  if (results) {
    qc.setQueryData<FinanceResultsResponse>(
      ["finance-results", DEFAULT_PERIOD.year, DEFAULT_PERIOD.month, "", "row_number", "asc"],
      results,
    );
  }

  // „Archiwum” i „Import zużycia MD”.
  qc.setQueryData<FinanceImportRun[]>(["finance-imports"], IMPORT_RUNS);
  qc.setQueryData<{ imports: ImportSummary[] }>(["md-imports"], { imports: MD_IMPORTS });

  // Licznik przy zakładce „Zmiany w zamówieniach” i minimum dla dwóch
  // zakładek z własnymi harnessami — kliknięcie w nie nie odpala zapytania.
  const current = currentOrderChangesMonth(today);
  qc.setQueryData<OrderChangesSummary>(
    ORDER_CHANGES_SUMMARY_KEY,
    buildOrderChangesSummary(today),
  );
  qc.setQueryData<OrderChangesResponse>(
    ["finance-order-changes", current.year, current.month, {}],
    buildOrderChanges(current.year, current.month, today),
  );
  qc.setQueryData<ClientRef[]>(["clients-lookup-order-changes"], CLIENTS_LOOKUP);
  qc.setQueryData<OrderPdfMonth[]>(["finance-order-pdf-months"], ORDER_PDF_MONTHS);
  return qc;
}

/** Fikcyjny admin w store; wraca, gdy powłoka nadpisze go stanem z localStorage. */
function applyPreviewUser(): void {
  const state = useAuthStore.getState();
  if (state.user !== PREVIEW_USER || state.realUser !== null || !state.hydrated) {
    useAuthStore.setState({ user: PREVIEW_USER, realUser: null, hydrated: true });
  }
}

export default function FinanceResultsPreview() {
  const [queryClient, setQueryClient] = useState<QueryClient | null>(null);

  // Wszystko po zamontowaniu: bieżący miesiąc zna tylko przeglądarka, a blokada
  // sieci, lokalne odpowiedzi i fikcyjny użytkownik mają zniknąć z harnessem.
  useEffect(() => {
    const blocker = api.interceptors.request.use((config) =>
      Promise.reject(
        new AxiosError("Podgląd: zapisy i sieć są wyłączone", "ECONNABORTED", config),
      ),
    );
    const restoreBackend = installLocalFinanceBackend();
    applyPreviewUser();
    const unsubscribeAuth = useAuthStore.subscribe(applyPreviewUser);
    setQueryClient(seededClient(new Date()));
    return () => {
      unsubscribeAuth();
      restoreBackend();
      api.interceptors.request.eject(blocker);
      // Stan logowania oglądającego wraca z localStorage.
      useAuthStore.getState().hydrate();
    };
  }, []);

  // `?view=md`: wybrany import żyje w stanie `MdImportWorkspace`, więc harness
  // otwiera pierwszy z listy tak, jak zrobiłby to użytkownik.
  useEffect(() => {
    if (!queryClient) return;
    const view = parseFinanceView(new URLSearchParams(window.location.search).get("view"));
    if (view !== "md") return;
    let tries = 0;
    const timer = window.setInterval(() => {
      tries += 1;
      const first = document.querySelector<HTMLButtonElement>('button[title="Otwórz import"]');
      if (first) first.click();
      if (first || tries > 40) window.clearInterval(timer);
    }, 50);
    return () => window.clearInterval(timer);
  }, [queryClient]);

  if (!queryClient) {
    return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
  }

  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <main className="flex flex-col gap-4 p-4 sm:p-6">
          <header>
            <h1 className="text-lg font-semibold">Harness — moduł Finanse</h1>
            <p className="text-sm text-muted-foreground">
              Publiczny podgląd na fikcyjnych danych. Zero zapytań do API. Widoki:{" "}
              <a className="underline" href="/preview/finance-results">
                wyniki miesięczne
              </a>
              ,{" "}
              <a className="underline" href="/preview/finance-results?view=archive">
                <code>?view=archive</code>
              </a>
              ,{" "}
              <a className="underline" href="/preview/finance-results?view=md">
                <code>?view=md</code>
              </a>
              . Pozostałe zakładki mają własne harnessy:{" "}
              <a className="underline" href="/preview/finance-order-changes">
                zmiany w zamówieniach
              </a>
              ,{" "}
              <a className="underline" href="/preview/finance-order-pdfs">
                zamówienia PDF
              </a>
              .
            </p>
          </header>
          <Suspense fallback={null}>
            <FinancePage />
          </Suspense>
        </main>
      </ToastProvider>
    </QueryClientProvider>
  );
}
