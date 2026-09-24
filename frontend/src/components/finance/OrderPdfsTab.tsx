"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import {
  financeApi,
  orderPdfFilePath,
  orderPdfZipPath,
  type OrderPdfClient,
  type OrderPdfFile,
  type OrderPdfMonth,
  type OrderPdfsResponse,
} from "@/lib/api/finance";
import { apiErrorMessage } from "@/lib/api-error";
import {
  downloadAuthenticatedFile,
  downloadBlob,
  fetchAuthenticatedBlob,
  fetchAuthenticatedDownload,
} from "@/lib/authenticated-files";
import { monthValue, parseMonthValue } from "@/lib/finance-order-changes";
import { orderPdfKey, zipFallbackName } from "@/lib/finance-order-pdfs";
import { resolveViewState } from "@/lib/view-state";

import { OrderPdfsPanel, type ZipBusy } from "./OrderPdfsPanel";

async function loadPreviewPdf(ref: { kind: string; id: number }): Promise<Blob> {
  return fetchAuthenticatedBlob(
    orderPdfFilePath(ref as Pick<OrderPdfFile, "kind" | "id">, { preview: true }),
  );
}

/** Klucze w adresie — lustro listy czyszczonej w `app/finance/page.tsx`.
 *  Własne nazwy (nie `month`), bo „Zmiany w zamówieniach" mają domyślnie inny
 *  miesiąc i przełączenie zakładki nie może go przenosić. */
export const ORDER_PDFS_URL_KEYS = ["pdfMonth", "pdfClient"] as const;

function readParam(name: string): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get(name);
}

function writeParams(month: string | null, clientId: number | null) {
  const params = new URLSearchParams(window.location.search);
  if (month) params.set("pdfMonth", month);
  else params.delete("pdfMonth");
  if (clientId) params.set("pdfClient", String(clientId));
  else params.delete("pdfClient");
  const query = params.toString();
  window.history.replaceState(
    null,
    "",
    query ? `${window.location.pathname}?${query}` : window.location.pathname,
  );
}

/** Bieżący miesiąc, gdy ma pliki; inaczej najnowszy nie późniejszy niż bieżący;
 *  a gdy wszystkie są w przyszłości — najbliższy z nich. */
export function defaultOrderPdfMonth(
  months: OrderPdfMonth[],
  today: Date,
): string | null {
  if (months.length === 0) return null;
  const current = monthValue(today.getFullYear(), today.getMonth() + 1);
  const pastOrCurrent = months.find((m) => m.month <= current);
  return pastOrCurrent?.month ?? months[months.length - 1].month;
}

/**
 * Finanse → „Zamówienia PDF": PDF-y zamówień (nowe, przedłużenia, aneksy)
 * pogrupowane po miesiącu rozpoczęcia i kliencie.
 *
 * Wykaz liczy serwer przy każdym odczycie z bieżących zamówień, więc nowe
 * zamówienie z PDF-em jest tu od razu — bez ręcznej akcji.
 */
export function OrderPdfsTab() {
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [zipBusy, setZipBusy] = useState<ZipBusy>(null);
  const [pickedMonth, setPickedMonth] = useState<string | null>(() => {
    const parsed = parseMonthValue(readParam("pdfMonth"));
    return parsed ? monthValue(parsed.year, parsed.month) : null;
  });
  const [clientId, setClientId] = useState<number | null>(() => {
    const id = Number(readParam("pdfClient"));
    return Number.isInteger(id) && id > 0 ? id : null;
  });
  const [downloadingKey, setDownloadingKey] = useState<string | null>(null);

  const monthsQuery = useQuery({
    queryKey: ["finance-order-pdf-months"],
    queryFn: async () => (await financeApi.getOrderPdfMonths()).data.items,
    refetchOnWindowFocus: true,
  });
  const months = monthsQuery.data ?? [];
  const month = pickedMonth ?? defaultOrderPdfMonth(months, new Date());
  const period = parseMonthValue(month);

  const clientsQuery = useQuery<OrderPdfsResponse>({
    queryKey: ["finance-order-pdfs", period?.year, period?.month],
    queryFn: async () =>
      (await financeApi.getOrderPdfs({ year: period!.year, month: period!.month }))
        .data,
    enabled: period !== null,
    refetchOnWindowFocus: true,
  });

  // Miesiąc z adresu, którego nie ma na liście (np. po usunięciu pliku),
  // nadal da się przeglądać — pokazujemy go jako pozycję z zerem.
  const listed =
    month && !months.some((m) => m.month === month) && monthsQuery.isSuccess
      ? [...months, { month, clients: 0, files: 0 }].sort((a, b) =>
          b.month.localeCompare(a.month),
        )
      : months;

  function changeMonth(next: string) {
    setPickedMonth(next);
    setClientId(null);
    writeParams(next, null);
  }

  function changeClient(next: number) {
    setClientId(next);
    writeParams(month, next);
  }

  async function download(file: OrderPdfFile) {
    const key = orderPdfKey(file);
    if (downloadingKey) return;
    setDownloadingKey(key);
    try {
      await downloadAuthenticatedFile(orderPdfFilePath(file), file.download_name);
      refreshStatuses();
    } catch {
      showToast("Nie udało się pobrać pliku.", "error");
    } finally {
      setDownloadingKey(null);
    }
  }

  /** Status „Pobrane przez Ciebie" liczy serwer — po pobraniu czytamy go ponownie. */
  function refreshStatuses() {
    void queryClient.invalidateQueries({ queryKey: ["finance-order-pdfs"] });
  }

  async function downloadZip(
    busy: Exclude<ZipBusy, null>,
    options: { clientId?: number; files?: OrderPdfFile[] },
    clientName: string | null,
  ) {
    if (zipBusy || !period || !month) return;
    setZipBusy(busy);
    try {
      const { blob, filename } = await fetchAuthenticatedDownload(
        orderPdfZipPath(period.year, period.month, options),
      );
      downloadBlob(blob, filename ?? zipFallbackName(clientName, month));
      refreshStatuses();
    } catch (error) {
      showToast(apiErrorMessage(error, "Nie udało się pobrać archiwum ZIP."), "error");
    } finally {
      setZipBusy(null);
    }
  }

  const monthsState = resolveViewState({
    isLoading: monthsQuery.isLoading,
    isError: monthsQuery.isError,
    error: monthsQuery.error,
    isSuccess: monthsQuery.isSuccess,
    isEmpty: false,
  });
  const clientsState = resolveViewState({
    isLoading: period !== null && clientsQuery.isLoading,
    isError: clientsQuery.isError,
    error: clientsQuery.error,
    isSuccess: period === null ? true : clientsQuery.isSuccess,
    isEmpty: false,
  });

  const notice = (
    state: ReturnType<typeof resolveViewState>,
    retry: () => void,
  ) =>
    state === "loading" ? (
      <p className="py-6 text-center text-sm text-muted-foreground">Ładowanie…</p>
    ) : state === "error" || state === "forbidden" || state === "not_found" ? (
      <QueryStateNotice state={state} onRetry={retry} />
    ) : undefined;

  return (
    <OrderPdfsPanel
      months={listed}
      monthsNotice={notice(monthsState, () => void monthsQuery.refetch())}
      month={month}
      onMonthChange={changeMonth}
      clients={clientsQuery.data?.clients ?? null}
      // Lista klientów ma własny stan, niezależny od listy miesięcy (miesiąc
      // bywa z adresu). Wiązanie z `monthsState === "ready"` robiło z jej
      // błędu zdanie „w tym miesiącu nie zaczyna się żadne zamówienie”.
      clientsNotice={
        period !== null
          ? notice(clientsState, () => void clientsQuery.refetch())
          : undefined
      }
      clientId={clientId}
      onClientChange={changeClient}
      onDownload={download}
      downloadingKey={downloadingKey}
      onDownloadMonth={() => void downloadZip("month", {}, null)}
      onDownloadClient={(client: OrderPdfClient) =>
        void downloadZip(
          `client:${client.client_id}`,
          { clientId: client.client_id },
          client.client_name,
        )
      }
      onDownloadFiles={(client: OrderPdfClient, files: OrderPdfFile[]) => {
        if (files.length === 0) return;
        void downloadZip(
          "files",
          { clientId: client.client_id, files },
          client.client_name,
        );
      }}
      zipBusy={zipBusy}
      loadPdf={loadPreviewPdf}
    />
  );
}
