"use client";

import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import {
  ClientSinglePicker,
  type ClientRef,
} from "@/components/clients/ClientSinglePicker";
import { useToast } from "@/components/Toast";
import {
  financeApi,
  orderChangesExportPath,
  orderPdfFilePath,
  type InvoiceLine,
  type OrderChangesResponse,
  type OrderPdfRef,
} from "@/lib/api/finance";
import { apiErrorMessage } from "@/lib/api-error";
import {
  downloadAuthenticatedFile,
  downloadBlob,
  fetchAuthenticatedBlob,
} from "@/lib/authenticated-files";
import {
  boardItems,
  cardItemsAllTabs,
  statusCounts,
  withCheck,
  withInvoiceLines,
  type BoardItem,
  type StatusFilter,
} from "@/lib/finance-order-board";
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
  type OrderChangesBoardState,
  type OrderChangesSubTab,
} from "./OrderChangesPanel";
import { pdfKey } from "./OrderChangeRow";

/** Klucz zapytania o badge „do zrobienia" przy zakładce w menu Finansów. */
export const ORDER_CHANGES_SUMMARY_KEY = [
  "finance-order-changes-summary",
] as const;

/** Klucze filtrów w adresie — lustro listy czyszczonej w `app/finance/page.tsx`. */
export const ORDER_CHANGES_URL_KEYS = [
  "sub",
  "month",
  "q",
  "client",
  "clientName",
  "from",
  "to",
  "status",
  "tile",
] as const;

const STATUS_VALUES: readonly StatusFilter[] = ["todo", "done", "all"];

function statusFromParam(value: string | null): StatusFilter {
  return (STATUS_VALUES as readonly string[]).includes(value ?? "")
    ? (value as StatusFilter)
    : "todo";
}

async function loadPreviewPdf(ref: {
  kind: string;
  id: number;
}): Promise<Blob> {
  return fetchAuthenticatedBlob(
    orderPdfFilePath(ref as Pick<OrderPdfRef, "kind" | "id">, {
      preview: true,
    }),
  );
}

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
  status: StatusFilter;
  tile: string | null;
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
  set("status", state.status === "todo" ? "" : state.status);
  set("tile", state.tile ?? "");

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
export function OrderChangesTab({
  onOpenInPdfs,
}: {
  /** „Otwórz w Zamówienia PDF" — przełącza widok Finansów na miesiąc i klienta pliku. */
  onOpenInPdfs?: (pdf: OrderPdfRef) => void;
} = {}) {
  const { showToast } = useToast();
  const queryClient = useQueryClient();
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
  const [status, setStatus] = useState<StatusFilter>(() =>
    statusFromParam(readParam("status")),
  );
  const [tile, setTile] = useState<string | null>(() => readParam("tile"));
  const [previewCard, setPreviewCard] = useState<string | null>(null);
  const [pendingKeys, setPendingKeys] = useState<ReadonlySet<string>>(
    () => new Set(),
  );
  const [downloadingPdf, setDownloadingPdf] = useState<string | null>(null);

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
  const queryKey = [
    "finance-order-changes",
    period.year,
    period.month,
    filterParams,
  ] as const;
  const query = useQuery<OrderChangesResponse>({
    queryKey,
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
    status,
    tile,
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
    if (patch.status !== undefined) setStatus(patch.status);
    if (patch.tile !== undefined) setTile(patch.tile);
    writeParams({ ...current, ...patch }, defaultMonth);
  }

  function changeSubTab(next: OrderChangesSubTab) {
    setPreviewCard(null);
    sync({ sub: next });
  }

  // Karta w panelu → historia zamówienia (wszystkie miesiące). Linia
  // zamówienia zbiorczego dostaje też zmiany CAŁEJ grupy.
  const previewRef = useMemo(() => {
    if (!previewCard || !query.data) return null;
    const [first] = cardItemsAllTabs(query.data, previewCard);
    if (!first) return null;
    return { order_id: first.orderId, order_group_id: first.orderGroupId };
  }, [previewCard, query.data]);
  const historyQuery = useQuery({
    queryKey: [
      "finance-order-history",
      previewRef?.order_id ?? null,
      previewRef?.order_group_id ?? null,
    ],
    queryFn: async () =>
      (await financeApi.getOrderHistory(previewRef!)).data.items,
    enabled: previewRef !== null,
  });

  async function toggle(item: BoardItem, done: boolean) {
    if (pendingKeys.has(item.key)) return;
    setPendingKeys((keys) => new Set(keys).add(item.key));
    try {
      const { data } = await financeApi.setOrderChangeCheck({
        year: period.year,
        month: period.month,
        item_key: item.key,
        done,
      });
      // Liczniki klienta, pasek postępu i filtr statusu liczą się z tych
      // danych — odświeżają się od razu, bez czekania na ponowny odczyt.
      queryClient.setQueryData<OrderChangesResponse>(queryKey, (previous) =>
        previous ? withCheck(previous, item.key, data.done) : previous,
      );
    } catch (error) {
      showToast(
        apiErrorMessage(error, "Nie udało się zapisać „Zrobione”."),
        "error",
      );
    } finally {
      setPendingKeys((keys) => {
        const next = new Set(keys);
        next.delete(item.key);
        return next;
      });
      void queryClient.invalidateQueries({
        queryKey: ["finance-order-changes"],
      });
      void queryClient.invalidateQueries({
        queryKey: ORDER_CHANGES_SUMMARY_KEY,
      });
      void queryClient.invalidateQueries({
        queryKey: ["finance-order-history"],
      });
      void queryClient.invalidateQueries({ queryKey: ["finance-order-pdfs"] });
    }
  }

  async function saveInvoiceLine(
    item: BoardItem,
    line: InvoiceLine,
    text: string,
  ): Promise<boolean> {
    if (item.orderId == null) return false;
    try {
      const { data } = await financeApi.updateInvoiceLine(item.orderId, {
        index: line.index,
        text,
      });
      // Karta pokazuje od razu zapisany tekst — bez czekania na odczyt.
      queryClient.setQueryData<OrderChangesResponse>(queryKey, (previous) =>
        previous
          ? withInvoiceLines(previous, data.order_id, data.lines)
          : previous,
      );
      showToast("Zapisano pozycję faktury.", "success");
      return true;
    } catch (error) {
      showToast(
        apiErrorMessage(error, "Nie udało się zapisać pozycji faktury."),
        "error",
      );
      return false;
    } finally {
      void queryClient.invalidateQueries({
        queryKey: ["finance-order-changes"],
      });
    }
  }

  async function downloadPdf(pdf: OrderPdfRef) {
    if (downloadingPdf) return;
    setDownloadingPdf(pdfKey(pdf));
    try {
      await downloadAuthenticatedFile(orderPdfFilePath(pdf), pdf.download_name);
      void queryClient.invalidateQueries({ queryKey: ["finance-order-pdfs"] });
    } catch {
      showToast("Nie udało się pobrać pliku.", "error");
    } finally {
      setDownloadingPdf(null);
    }
  }

  const data = query.data;
  const counts = useMemo(
    () => (data ? statusCounts(boardItems(data, subTab)) : null),
    [data, subTab],
  );

  const board: OrderChangesBoardState = {
    status,
    selectedClient: tile,
    onSelectClient: (next) => {
      setPreviewCard(null);
      sync({ tile: next });
    },
    onToggle: toggle,
    onSaveInvoiceLine: saveInvoiceLine,
    pendingKeys,
    onDownloadPdf: downloadPdf,
    downloadingPdf,
    previewCard,
    onPreviewCard: setPreviewCard,
    preview: {
      itemsForCard: (cardKey) => (data ? cardItemsAllTabs(data, cardKey) : []),
      history: {
        items: historyQuery.data ?? null,
        loading: historyQuery.isLoading,
        failed: historyQuery.isError,
      },
      loadPdf: loadPreviewPdf,
      onOpenInPdfs: (pdf) => onOpenInPdfs?.(pdf),
    },
  };

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
        // Wielowyrazowa nazwa zakładki („Zamówienia bez kontynuacji") nie może
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
        board={board}
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
      board={board}
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
      onMonthChange={(next) => {
        setPreviewCard(null);
        sync({ month: next });
      }}
      onExport={exportXlsx}
      exporting={exporting}
      filters={filters}
      status={status}
      onStatusChange={(next) => sync({ status: next })}
      statusCounts={counts}
    />
  );
}
