"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import {
  financeApi,
  orderChangesExportPath,
  type OrderChangesResponse,
} from "@/lib/api/finance";
import {
  downloadBlob,
  fetchAuthenticatedBlob,
} from "@/lib/authenticated-files";
import {
  monthOptions,
  monthValue,
  parseMonthValue,
} from "@/lib/finance-order-changes";
import { ORDER_CHANGES_POLL_MS } from "@/lib/polling";
import { resolveViewState } from "@/lib/view-state";

import {
  OrderChangesList,
  OrderChangesPanel,
  subTabFromParam,
  type OrderChangesSubTab,
} from "./OrderChangesPanel";

function readParam(name: string): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get(name);
}

function writeParams(sub: OrderChangesSubTab, month: string, defaultMonth: string) {
  const params = new URLSearchParams(window.location.search);
  if (sub === "changes") params.delete("sub");
  else params.set("sub", sub);
  if (month === defaultMonth) params.delete("month");
  else params.set("month", month);
  const query = params.toString();
  window.history.replaceState(
    null,
    "",
    query ? `${window.location.pathname}?${query}` : window.location.pathname,
  );
}

/**
 * Finanse → „Zmiany w zamówieniach": comiesięczny audyt Wejść, Zejść, zmian
 * stawek i dat oraz Braków kolejnego zamówienia.
 *
 * „Na bieżąco": dane liczy serwer przy każdym odczycie z aktualnego stanu
 * zamówień, a braki zamyka zapis zamówienia. Widok odświeża się przy powrocie
 * do karty i co kilka minut (`ORDER_CHANGES_POLL_MS`), bez ręcznego
 * przełączania miesiąca.
 */
export function OrderChangesTab() {
  const { showToast } = useToast();
  const months = useMemo(() => monthOptions(new Date()), []);
  const defaultMonth = months[1]?.value ?? months[0].value; // bieżący miesiąc
  // Strona Finansów montuje zakładkę dopiero po stronie przeglądarki, więc
  // adres da się przeczytać od razu — bez pierwszego zapytania o zły miesiąc.
  const [subTab, setSubTab] = useState<OrderChangesSubTab>(() =>
    subTabFromParam(readParam("sub")),
  );
  const [month, setMonth] = useState(() => {
    const fromUrl = parseMonthValue(readParam("month"));
    return fromUrl ? monthValue(fromUrl.year, fromUrl.month) : defaultMonth;
  });
  const [exporting, setExporting] = useState(false);

  const period = parseMonthValue(month) ?? parseMonthValue(defaultMonth)!;
  const query = useQuery<OrderChangesResponse>({
    queryKey: ["finance-order-changes", period.year, period.month],
    queryFn: async () => (await financeApi.getOrderChanges(period)).data,
    refetchOnWindowFocus: true,
    refetchInterval: ORDER_CHANGES_POLL_MS,
  });

  // Miesiąc spoza listy (np. z adresu) musi być wybieralny w selekcie.
  const selectable = months.some((option) => option.value === month)
    ? months
    : [
        ...months,
        {
          value: month,
          year: period.year,
          month: period.month,
          label: query.data?.period.label ?? month,
        },
      ];

  function changeSubTab(next: OrderChangesSubTab) {
    setSubTab(next);
    writeParams(next, month, defaultMonth);
  }

  function changeMonth(next: string) {
    setMonth(next);
    writeParams(subTab, next, defaultMonth);
  }

  async function exportXlsx() {
    if (exporting) return;
    setExporting(true);
    try {
      const blob = await fetchAuthenticatedBlob(
        orderChangesExportPath(period.year, period.month),
      );
      downloadBlob(
        blob,
        `Zmiany_w_zamowieniach_${monthValue(period.year, period.month)}.xlsx`,
      );
    } catch {
      showToast("Nie udało się pobrać eksportu.", "error");
    } finally {
      setExporting(false);
    }
  }

  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: false,
  });

  // Dane już wczytane zostają na ekranie, gdy padnie odświeżenie w tle
  // (np. 503 w trakcie deployu) — awaria idzie wtedy jako pasek nad listą,
  // zamiast zastępować tabelę komunikatem.
  const staleAfterError = query.isError && query.data !== undefined;
  const body = staleAfterError ? (
    <div className="space-y-3">
      <p
        role="status"
        className="rounded-lg border border-destructive/20 bg-destructive-muted px-3 py-2 text-sm text-destructive-muted-foreground"
      >
        Nie udało się odświeżyć danych — pokazujemy ostatnio wczytany stan.{" "}
        <button
          type="button"
          onClick={() => query.refetch()}
          className="font-medium underline underline-offset-2"
        >
          Ponów
        </button>
      </p>
      <OrderChangesList
        data={query.data}
        subTab={subTab}
        onOpenGaps={() => changeSubTab("gaps")}
      />
    </div>
  ) : state === "loading" ? (
    <p className="py-10 text-center text-sm text-muted-foreground">
      Wczytywanie zmian w zamówieniach…
    </p>
  ) : state === "error" || state === "forbidden" || state === "not_found" ? (
    <QueryStateNotice
      state={state}
      description="Nie udało się wczytać zmian w zamówieniach."
      onRetry={() => query.refetch()}
    />
  ) : query.data ? (
    <OrderChangesList
      data={query.data}
      subTab={subTab}
      onOpenGaps={() => changeSubTab("gaps")}
    />
  ) : null;

  return (
    <OrderChangesPanel
      data={query.data ?? null}
      body={body}
      subTab={subTab}
      onSubTabChange={changeSubTab}
      month={month}
      months={selectable}
      onMonthChange={changeMonth}
      onExport={exportXlsx}
      exporting={exporting}
    />
  );
}
