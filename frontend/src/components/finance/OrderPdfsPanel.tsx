"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Download, Eye, FolderArchive, Loader2, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import type {
  OrderPdfClient,
  OrderPdfEntryType,
  OrderPdfFile,
  OrderPdfMonth,
} from "@/lib/api/finance";
import {
  clientsLabel,
  downloadStatusLabel,
  filesLabel,
  newFilesCount,
  newFilesLabel,
  orderPdfEntryTypeLabel,
  orderPdfKey,
  orderPdfMonthLabel,
  orderPdfPeriod,
  orderPdfPeriodInvalid,
  orderPdfStatusLabel,
} from "@/lib/finance-order-pdfs";
import { CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { OrderPdfViewer, type OrderPdfLoader } from "./OrderPdfViewer";

/** Który ZIP właśnie się buduje: miesiąc, klient albo wybrane pliki. */
export type ZipBusy = "month" | `client:${number}` | "files" | null;

export interface OrderPdfsPanelProps {
  months: OrderPdfMonth[];
  /** Zastępuje listę miesięcy (ładowanie / błąd). */
  monthsNotice?: ReactNode;
  month: string | null;
  onMonthChange: (month: string) => void;
  clients: OrderPdfClient[] | null;
  /** Zastępuje listę klientów (ładowanie / błąd). */
  clientsNotice?: ReactNode;
  clientId: number | null;
  onClientChange: (clientId: number) => void;
  onDownload: (file: OrderPdfFile) => void;
  downloadingKey: string | null;
  /** ZIP całego miesiąca (podfolder na klienta). */
  onDownloadMonth: () => void;
  /** ZIP wszystkich plików klienta z miesiąca. */
  onDownloadClient: (client: OrderPdfClient) => void;
  /** ZIP wskazanych plików klienta („Pobierz zaznaczone", „Pobierz nowe"). */
  onDownloadFiles: (client: OrderPdfClient, files: OrderPdfFile[]) => void;
  zipBusy: ZipBusy;
  /** Źródło bajtów podglądu (harness podaje plik statyczny). */
  loadPdf: OrderPdfLoader;
}

type TypeFilter = "all" | OrderPdfEntryType;

const TYPE_FILTERS: { value: TypeFilter; label: string }[] = [
  { value: "all", label: "Wszystkie" },
  { value: "new", label: "Nowe zamówienia" },
  { value: "extension", label: "Przedłużenia" },
  { value: "amendment", label: "Aneksy" },
];

/**
 * Finanse → „Zamówienia PDF": miesiąc startu → klient → pliki do pobrania,
 * pojedynczo albo ZIP-em (klient, miesiąc, zaznaczone, nowe).
 *
 * Czysta prezentacja — zapytania robi `OrderPdfsTab`, a ten sam komponent
 * renderuje publiczny harness `/preview/finance-order-pdfs` bez żadnego
 * zapytania.
 */
export function OrderPdfsPanel({
  months,
  monthsNotice,
  month,
  onMonthChange,
  clients,
  clientsNotice,
  clientId,
  onClientChange,
  onDownload,
  downloadingKey,
  onDownloadMonth,
  onDownloadClient,
  onDownloadFiles,
  zipBusy,
  loadPdf,
}: OrderPdfsPanelProps) {
  const selected = clients?.find((c) => c.client_id === clientId) ?? null;
  const monthFiles = months.find((item) => item.month === month)?.files ?? 0;
  const [previewFile, setPreviewFile] = useState<OrderPdfFile | null>(null);

  useEffect(() => {
    if (!previewFile) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPreviewFile(null);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [previewFile]);

  return (
    <section
      aria-label="Zamówienia PDF"
      className="grid gap-3.5 lg:grid-cols-[210px_260px_minmax(0,1fr)] lg:items-start"
    >
      <Column title="Miesiąc rozpoczęcia">
        {monthsNotice ??
          (months.length === 0 ? (
            <Empty>Brak zamówień z PDF-em w systemie.</Empty>
          ) : (
            <>
              <ul
                role="listbox"
                aria-label="Miesiąc rozpoczęcia"
                className="max-h-64 space-y-0.5 overflow-y-auto lg:max-h-none lg:overflow-visible"
              >
                {months.map((item) => (
                  <li key={item.month}>
                    <PickButton
                      active={item.month === month}
                      onClick={() => onMonthChange(item.month)}
                      title={orderPdfMonthLabel(item.month)}
                      meta={`${clientsLabel(item.clients)} · ${filesLabel(item.files)}`}
                    />
                  </li>
                ))}
              </ul>
              <button
                type="button"
                onClick={onDownloadMonth}
                disabled={!month || monthFiles === 0 || zipBusy !== null}
                className="mx-1 mb-1 mt-2 inline-flex h-8 w-[calc(100%-0.5rem)] items-center justify-center gap-1.5 rounded-md border border-border bg-background px-3 text-xs font-medium text-foreground hover:bg-muted disabled:opacity-50 pointer-coarse:min-h-10"
              >
                {zipBusy === "month" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                ) : (
                  <Download className="h-3.5 w-3.5" aria-hidden />
                )}
                Pobierz cały miesiąc
              </button>
            </>
          ))}
      </Column>

      <Column
        title={month ? `Klienci — ${orderPdfMonthLabel(month)}` : "Klienci"}
      >
        {clientsNotice ??
          (!month ? (
            <Empty>Wybierz miesiąc.</Empty>
          ) : !clients || clients.length === 0 ? (
            <Empty>
              W tym miesiącu nie zaczyna się żadne zamówienie z PDF-em.
            </Empty>
          ) : (
            <ul role="listbox" aria-label="Klienci" className="max-h-64 space-y-0.5 overflow-y-auto lg:max-h-none lg:overflow-visible">
              {clients.map((client) => {
                const fresh = newFilesCount(client.files);
                const busy = zipBusy === `client:${client.client_id}`;
                return (
                  <li
                    key={client.client_id}
                    className="flex items-center gap-1"
                  >
                    <PickButton
                      active={client.client_id === clientId}
                      onClick={() => onClientChange(client.client_id)}
                      title={client.client_name}
                      meta={
                        <>
                          {filesLabel(client.files.length)} ·{" "}
                          {fresh > 0 ? (
                            <span className="font-medium text-primary">
                              {newFilesLabel(fresh)}
                            </span>
                          ) : (
                            "pobrane"
                          )}
                        </>
                      }
                    />
                    <button
                      type="button"
                      onClick={() => onDownloadClient(client)}
                      disabled={zipBusy !== null}
                      aria-label={`Pobierz wszystkie pliki klienta: ${client.client_name}`}
                      title="Pobierz wszystkie pliki klienta (ZIP)"
                      className={cn(
                        "mr-1 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md border transition-colors disabled:opacity-50 pointer-coarse:min-h-10 pointer-coarse:min-w-10",
                        client.client_id === clientId
                          ? "border-primary bg-primary text-primary-foreground"
                          : "border-border bg-background text-foreground hover:bg-muted",
                      )}
                    >
                      {busy ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                      ) : (
                        <Download className="h-3.5 w-3.5" aria-hidden />
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          ))}
      </Column>

      <div className="min-w-0">
        {clientsNotice ? null : !selected ? (
          <div className="rounded-[10px] border border-border bg-card p-1.5">
            <h2 className={cn("px-2.5 pb-1 pt-2", CALM_HEAD)}>Pliki</h2>
            <div className="p-1.5">
              <Empty>
                {clients && clients.length > 0
                  ? "Wybierz klienta, aby zobaczyć PDF-y."
                  : "Brak plików do pokazania."}
              </Empty>
            </div>
          </div>
        ) : (
          <ClientFiles
            key={`${month}:${selected.client_id}`}
            client={selected}
            month={month}
            onDownload={onDownload}
            downloadingKey={downloadingKey}
            onDownloadClient={onDownloadClient}
            onDownloadFiles={onDownloadFiles}
            zipBusy={zipBusy}
            onPreview={setPreviewFile}
          />
        )}
      </div>

      {previewFile ? (
        <PreviewDialog
          file={previewFile}
          loadPdf={loadPdf}
          onClose={() => setPreviewFile(null)}
          onDownload={() => onDownload(previewFile)}
          downloading={downloadingKey === orderPdfKey(previewFile)}
        />
      ) : null}
    </section>
  );
}

function ClientFiles({
  client,
  month,
  onDownload,
  downloadingKey,
  onDownloadClient,
  onDownloadFiles,
  zipBusy,
  onPreview,
}: {
  client: OrderPdfClient;
  month: string | null;
  onDownload: (file: OrderPdfFile) => void;
  downloadingKey: string | null;
  onDownloadClient: (client: OrderPdfClient) => void;
  onDownloadFiles: (client: OrderPdfClient, files: OrderPdfFile[]) => void;
  zipBusy: ZipBusy;
  onPreview: (file: OrderPdfFile) => void;
}) {
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [onlyNew, setOnlyNew] = useState(false);
  const [checked, setChecked] = useState<ReadonlySet<string>>(() => new Set());

  const fresh = useMemo(
    () => client.files.filter((file) => !file.downloaded_at),
    [client.files],
  );
  const visible = useMemo(
    () =>
      client.files.filter(
        (file) =>
          (typeFilter === "all" || file.entry_type === typeFilter) &&
          (!onlyNew || !file.downloaded_at),
      ),
    [client.files, onlyNew, typeFilter],
  );
  const selectedFiles = client.files.filter((file) =>
    checked.has(orderPdfKey(file)),
  );
  const allVisibleChecked =
    visible.length > 0 &&
    visible.every((file) => checked.has(orderPdfKey(file)));
  const someVisibleChecked = visible.some((file) =>
    checked.has(orderPdfKey(file)),
  );
  const typeCount = (value: TypeFilter) =>
    value === "all"
      ? client.files.length
      : client.files.filter((file) => file.entry_type === value).length;

  function toggle(file: OrderPdfFile, value: boolean) {
    setChecked((current) => {
      const next = new Set(current);
      if (value) next.add(orderPdfKey(file));
      else next.delete(orderPdfKey(file));
      return next;
    });
  }

  function toggleAll(value: boolean) {
    setChecked((current) => {
      const next = new Set(current);
      visible.forEach((file) =>
        value ? next.add(orderPdfKey(file)) : next.delete(orderPdfKey(file)),
      );
      return next;
    });
  }

  const busy = zipBusy !== null;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-foreground">
            {client.client_name}
            {month ? ` — ${orderPdfMonthLabel(month)}` : ""}
          </h2>
          <p className="text-xs text-muted-foreground">
            {filesLabel(client.files.length)} · {fresh.length} niepobranych
            przez Ciebie
            {selectedFiles.length > 0
              ? ` · ${selectedFiles.length} zaznaczone`
              : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <ZipButton
            onClick={() => onDownloadFiles(client, selectedFiles)}
            disabled={busy || selectedFiles.length === 0}
            busy={zipBusy === "files" && selectedFiles.length > 0}
          >
            Pobierz zaznaczone ({selectedFiles.length})
          </ZipButton>
          <ZipButton
            onClick={() => onDownloadFiles(client, fresh)}
            disabled={busy || fresh.length === 0}
          >
            Pobierz nowe ({fresh.length})
          </ZipButton>
          <ZipButton
            primary
            onClick={() => onDownloadClient(client)}
            disabled={busy}
            busy={zipBusy === `client:${client.client_id}`}
          >
            Pobierz wszystkie (ZIP)
          </ZipButton>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div
          role="radiogroup"
          aria-label="Typ pliku"
          className="flex flex-wrap gap-1.5"
        >
          {TYPE_FILTERS.map((option) => {
            const active = option.value === typeFilter;
            return (
              <button
                key={option.value}
                type="button"
                role="radio"
                aria-checked={active}
                onClick={() => setTypeFilter(option.value)}
                className={cn(
                  "inline-flex h-7 items-center whitespace-nowrap rounded-full border px-2.5 text-xs font-medium tabular-nums transition-colors pointer-coarse:min-h-10",
                  active
                    ? "border-foreground bg-foreground text-background"
                    : "border-border bg-card text-muted-foreground hover:text-foreground",
                )}
              >
                {option.label} · {typeCount(option.value)}
              </button>
            );
          })}
        </div>
        <label className="ml-auto inline-flex cursor-pointer items-center gap-2 text-xs font-medium text-foreground">
          <Checkbox
            checked={onlyNew}
            onCheckedChange={(value) => setOnlyNew(value === true)}
            aria-label="Tylko niepobrane"
          />
          Tylko niepobrane
        </label>
      </div>

      {/* Jedna karta-tabela: nagłówek, wiersze oddzielone linią i stopka
          (makieta 02.10.2026) — zamiast osobnej ramki na każdy plik. */}
      <div className="rounded-[10px] border border-border bg-card">
        {visible.length === 0 ? (
          <div className="p-3">
            <Empty>
              {onlyNew
                ? "Wszystkie pliki tego klienta są już pobrane przez Ciebie."
                : "Brak plików tego typu."}
            </Empty>
          </div>
        ) : (
          <div className="relative overflow-x-auto">
            <div
              role="table"
              aria-label={`Pliki — ${client.client_name}`}
              className="min-w-[720px]"
            >
              <div
                role="row"
                className={cn(
                  FILE_GRID,
                  "min-h-[34px] rounded-t-[10px] border-b border-border bg-background px-3.5",
                  CALM_HEAD,
                )}
              >
                <span role="columnheader" className="flex">
                  <Checkbox
                    checked={
                      allVisibleChecked
                        ? true
                        : someVisibleChecked
                          ? "indeterminate"
                          : false
                    }
                    onCheckedChange={(value) => toggleAll(value === true)}
                    aria-label="Zaznacz wszystkie"
                  />
                </span>
                <span role="columnheader">Zamówienie · osoba</span>
                <span role="columnheader">Typ</span>
                <span role="columnheader">Okres</span>
                <span role="columnheader">Status</span>
                <span role="columnheader" className="text-right">
                  Akcje
                </span>
              </div>
              {visible.map((file) => (
                <FileRow
                  key={orderPdfKey(file)}
                  file={file}
                  checked={checked.has(orderPdfKey(file))}
                  onCheck={(value) => toggle(file, value)}
                  downloading={downloadingKey === orderPdfKey(file)}
                  onDownload={() => onDownload(file)}
                  onPreview={() => onPreview(file)}
                />
              ))}
            </div>
          </div>
        )}
        <p className="flex flex-wrap items-center gap-2 border-t border-border px-3.5 py-2 text-xs text-muted-foreground">
          <FolderArchive className="h-3.5 w-3.5 shrink-0" aria-hidden />
          Pliki w ZIP-ie: Klient_NrZam_Nazwisko_Typ_DataOd-DataDo.pdf (bez
          polskich znaków i spacji)
        </p>
      </div>
    </div>
  );
}

/** Kolumny: zaznaczenie · zamówienie · typ · okres · status · akcje. */
const FILE_GRID =
  "grid grid-cols-[20px_minmax(0,2.2fr)_minmax(0,1fr)_minmax(0,1.3fr)_minmax(0,1.4fr)_124px] items-center gap-3";

function fileHeading(file: OrderPdfFile): string {
  const number = file.order_number
    ? `Zam. ${file.order_number}`
    : orderPdfEntryTypeLabel(file.entry_type);
  return `${number} · ${file.consultant_name ?? "Bez przypisanej osoby"}`;
}

function FileRow({
  file,
  checked,
  onCheck,
  downloading,
  onDownload,
  onPreview,
}: {
  file: OrderPdfFile;
  checked: boolean;
  onCheck: (value: boolean) => void;
  downloading: boolean;
  onDownload: () => void;
  onPreview: () => void;
}) {
  const heading = fileHeading(file);
  return (
    <div
      role="row"
      className={cn(
        FILE_GRID,
        CALM_ROW,
        "min-h-[50px] px-3.5 py-1.5 text-[13px] last:border-b-0",
        checked && "bg-primary/5",
      )}
    >
      <span role="cell" className="flex">
        <Checkbox
          checked={checked}
          onCheckedChange={(value) => onCheck(value === true)}
          aria-label={`Zaznacz: ${heading}`}
        />
      </span>
      <span role="cell" className="min-w-0">
        <span className="block font-semibold text-foreground">{heading}</span>
        <span className={cn(CALM_SUBLINE, "break-all")}>
          {file.download_name}
        </span>
        {file.consultant_name ? null : (
          <Badge variant="neutral" size="sm" className="mt-1">
            Nazwisko do uzupełnienia
          </Badge>
        )}
      </span>
      <span role="cell" className="flex flex-col items-start gap-1">
        <span>{orderPdfEntryTypeLabel(file.entry_type)}</span>
        {file.status === "draft" ? (
          <Badge size="sm" variant="warning">
            {orderPdfStatusLabel(file.status)}
          </Badge>
        ) : null}
      </span>
      <span
        role="cell"
        className={cn(
          "tabular-nums",
          orderPdfPeriodInvalid(file)
            ? "text-xs font-medium text-warning-muted-foreground"
            : "text-foreground",
        )}
      >
        {orderPdfPeriod(file)}
      </span>
      <span role="cell" className="flex flex-col items-start gap-1 text-xs">
        <span
          className={
            file.downloaded_at
              ? "text-muted-foreground"
              : "font-semibold text-primary"
          }
        >
          {downloadStatusLabel(file)}
        </span>
        {file.pending_change ? (
          <Badge size="sm" variant="warning">
            zmiana do rozliczenia
          </Badge>
        ) : null}
      </span>
      <span role="cell" className="flex justify-end gap-1.5">
        <button
          type="button"
          onClick={onPreview}
          aria-label={`Podgląd: ${file.download_name}`}
          title="Podgląd"
          className="inline-flex h-7 items-center gap-1.5 rounded-md border border-border bg-background px-2.5 text-xs font-medium text-foreground hover:bg-muted pointer-coarse:min-h-10"
        >
          <Eye className="h-3.5 w-3.5" aria-hidden />
          Podgląd
        </button>
        <button
          type="button"
          onClick={onDownload}
          disabled={downloading}
          aria-label={`Pobierz ${file.download_name}`}
          title="Pobierz"
          className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-border bg-background text-foreground hover:bg-muted disabled:opacity-60 pointer-coarse:min-h-10 pointer-coarse:min-w-10"
        >
          {downloading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : (
            <Download className="h-3.5 w-3.5" aria-hidden />
          )}
        </button>
      </span>
    </div>
  );
}

function PreviewDialog({
  file,
  loadPdf,
  onClose,
  onDownload,
  downloading,
}: {
  file: OrderPdfFile;
  loadPdf: OrderPdfLoader;
  onClose: () => void;
  onDownload: () => void;
  downloading: boolean;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 p-2 sm:p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Podgląd: ${file.download_name}`}
        onClick={(event) => event.stopPropagation()}
        className="flex h-[85dvh] w-full max-w-3xl flex-col gap-3 rounded-xl border border-border bg-card p-4 shadow-xl"
      >
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-foreground">
              {fileHeading(file)}
            </p>
            <p className="break-all text-xs text-muted-foreground">
              {file.download_name}
            </p>
          </div>
          <button
            type="button"
            onClick={onDownload}
            disabled={downloading}
            className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
          >
            {downloading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
            ) : (
              <Download className="h-3.5 w-3.5" aria-hidden />
            )}
            Pobierz
          </button>
          <button
            type="button"
            onClick={onClose}
            aria-label="Zamknij podgląd (Esc)"
            className="inline-flex h-8 w-8 items-center justify-center rounded-md bg-muted text-muted-foreground hover:text-foreground"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </div>
        <div className="min-h-0 flex-1">
          <OrderPdfViewer file={file} loadPdf={loadPdf} />
        </div>
      </div>
    </div>
  );
}

function ZipButton({
  children,
  onClick,
  disabled,
  busy = false,
  primary = false,
}: {
  children: ReactNode;
  onClick: () => void;
  disabled: boolean;
  busy?: boolean;
  primary?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-xs font-medium transition-colors disabled:opacity-50 pointer-coarse:min-h-10",
        primary
          ? "bg-primary font-semibold text-primary-foreground hover:bg-primary/90"
          : "border border-border bg-background text-foreground hover:bg-muted",
      )}
    >
      {busy ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
      ) : primary ? (
        <Download className="h-3.5 w-3.5" aria-hidden />
      ) : null}
      {children}
    </button>
  );
}

function Column({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="min-w-0 rounded-[10px] border border-border bg-card p-1.5">
      <h2 className={cn("truncate px-2.5 pb-1 pt-2", CALM_HEAD)}>{title}</h2>
      {children}
    </div>
  );
}

function PickButton({
  active,
  onClick,
  title,
  meta,
}: {
  active: boolean;
  onClick: () => void;
  title: string;
  meta: ReactNode;
}) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "w-full min-w-0 flex-1 rounded-lg px-2.5 py-2 text-left transition-colors",
        active
          ? "bg-primary/10 text-primary"
          : "text-foreground hover:bg-muted/60",
      )}
    >
      <span className="block truncate text-[13px] font-semibold">{title}</span>
      <span className="block text-[11.5px] leading-4 text-muted-foreground">
        {meta}
      </span>
    </button>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
      {children}
    </p>
  );
}
