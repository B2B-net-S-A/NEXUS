"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { ClientSinglePicker, type ClientRef } from "@/components/clients/ClientSinglePicker";
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
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { resolveViewState } from "@/lib/view-state";

import {
  OrderChangesList,
  OrderChangesPanel,
  SUB_TAB_LABELS,
  subTabFromParam,
  type OrderChangesSubTab,
} from "./OrderChangesPanel";

/** Klucze filtrów w adresie — lustro listy czyszczonej w `app/finance/page.tsx`. */
export const ORDER_CHANGES_URL_KEYS = [
  "sub",
  "month",
  "q",
  "client",
  "clientName",
  "from",
  "to",
] as const;

function readParam(name: string): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get(name);
}

interface UrlState {
  sub: OrderChangesSubTab;
  month: string;
  q: string;
  client: ClientRef | null;
  from: string;
  to: string;
}

function writeParams(state: UrlState, defaultMonth: string) {
  const params = new URLSearchParams(window.location.search);
  const set = (key: string, value: string) =>
    value ? params.set(key, value) : params.delete(key);

  set("sub", state.sub === "changes" ? "" : state.sub);
  set("month", state.month === defaultMonth ? "" : state.month);
  set("q", state.q);
  set("client", state.client ? String(state.client.id) : "");
  // Nazwa jedzie obok id, żeby po odświeżeniu strony chip filtra nie mówił
  // „Klient: 18" — picker dociąga listę dopiero po otwarciu.
  set("clientName", state.client?.name ?? "");
  set("from", state.from);
  set("to", state.to);

  const query = params.toString();
  window.history.replaceState(
    null,
    "",
    query ? `${window.location.pathname}?${query}` : window.location.pathname,
  );
}

function readClientParam(): ClientRef | null {
  const id = Number(readParam("client"));
  if (!Number.isInteger(id) || id <= 0) return null;
  return { id, name: readParam("clientName") || `Klient #${id}` };
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
  const [search, setSearch] = useState(() => readParam("q") ?? "");
  const [client, setClient] = useState<ClientRef | null>(readClientParam);
  const [dateFrom, setDateFrom] = useState(() => readParam("from") ?? "");
  const [dateTo, setDateTo] = useState(() => readParam("to") ?? "");

  // Filtry liczy serwer (jedno źródło prawdy dla ekranu i eksportu), więc
  // wpisywanie musi być zdławione — jak w zakładce Wyniki.
  const debouncedSearch = useDebouncedValue(search, 300);

  const period = parseMonthValue(month) ?? parseMonthValue(defaultMonth)!;
  const filterParams = useMemo(
    () => ({
      q: debouncedSearch.trim() || undefined,
      client_id: client?.id,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
    }),
    [client?.id, dateFrom, dateTo, debouncedSearch],
  );
  // Odwrócony zakres serwer odrzuca 422 — nie pytamy o niego wcale, żeby
  // ekran nie migał komunikatem o błędzie w trakcie wpisywania drugiej daty.
  const rangeReversed = Boolean(dateFrom && dateTo && dateFrom > dateTo);
  const query = useQuery<OrderChangesResponse>({
    queryKey: ["finance-order-changes", period.year, period.month, filterParams],
    queryFn: async () =>
      (await financeApi.getOrderChanges({ ...period, ...filterParams })).data,
    enabled: !rangeReversed,
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

  const current: UrlState = {
    sub: subTab,
    month,
    q: search,
    client,
    from: dateFrom,
    to: dateTo,
  };

  /** Jedno wejście do stanu i adresu — inaczej każdy filtr miałby własną
   *  kopię zapisu URL-a i pierwszy zapomniany parametr znikałby po cichu. */
  function sync(patch: Partial<UrlState>) {
    if (patch.sub !== undefined) setSubTab(patch.sub);
    if (patch.month !== undefined) setMonth(patch.month);
    if (patch.q !== undefined) setSearch(patch.q);
    if (patch.client !== undefined) setClient(patch.client);
    if (patch.from !== undefined) setDateFrom(patch.from);
    if (patch.to !== undefined) setDateTo(patch.to);
    writeParams({ ...current, ...patch }, defaultMonth);
  }

  function changeSubTab(next: OrderChangesSubTab) {
    sync({ sub: next });
  }

  async function exportXlsx() {
    if (exporting) return;
    setExporting(true);
    try {
      // Te same filtry co zapytanie o ekran — plik nie może pokazywać czegoś
      // innego niż lista, na którą patrzy użytkownik.
      const blob = await fetchAuthenticatedBlob(
        orderChangesExportPath(period.year, period.month, {
          tab: subTab,
          ...filterParams,
        }),
      );
      const tabSlug = SUB_TAB_LABELS[subTab]
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(/ł/gi, "l")
        // Wielowyrazowa nazwa zakładki („Kończące się zamówienia") nie może
        // wpuścić spacji do nazwy pliku.
        .replace(/\s+/g, "_");
      downloadBlob(
        blob,
        `Zmiany_w_zamowieniach_${tabSlug}_${monthValue(period.year, period.month)}.xlsx`,
      );
    } catch {
      showToast("Nie udało się pobrać eksportu.", "error");
    } finally {
      setExporting(false);
    }
  }

  const filtersActive = Boolean(
    filterParams.q ||
      filterParams.client_id ||
      filterParams.date_from ||
      filterParams.date_to,
  );

  const filters = {
    search,
    onSearchChange: (value: string) => sync({ q: value }),
    dateFrom,
    onDateFromChange: (value: string) => sync({ from: value }),
    dateTo,
    onDateToChange: (value: string) => sync({ to: value }),
    clientPicker: (
      <ClientSinglePicker
        value={client}
        onChange={(next) => sync({ client: next })}
        queryKey="clients-lookup-order-changes"
        placeholder="Wszyscy klienci"
        allowClear
      />
    ),
    clientLabel: client?.name ?? null,
    onClearClient: () => sync({ client: null }),
    onClearDates: () => sync({ from: "", to: "" }),
    onClearAll: () => sync({ q: "", client: null, from: "", to: "" }),
  };

  const state = resolveViewState({
    isLoading: query.isLoading && !rangeReversed,
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
        filtersActive={filtersActive}
      />
    </div>
  ) : rangeReversed ? (
    <p
      role="status"
      className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground"
    >
      Data „od" jest późniejsza niż „do" — popraw zakres, żeby zobaczyć wyniki.
    </p>
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
      filtersActive={filtersActive}
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
      onMonthChange={(next) => sync({ month: next })}
      onExport={exportXlsx}
      exporting={exporting}
      filters={filters}
    />
  );
}
