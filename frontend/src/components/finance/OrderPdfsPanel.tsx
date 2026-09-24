"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Building2,
  CalendarDays,
  Download,
  Eye,
  FileText,
  FolderArchive,
  Loader2,
  X,
} from "lucide-react";

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
  orderPdfStatusLabel,
} from "@/lib/finance-order-pdfs";
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

const TYPE_VARIANT: Record<OrderPdfEntryType, "success" | "info" | "soft"> = {
  new: "success",
  extension: "info",
  amendment: "soft",
};

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
      className="grid gap-4 lg:grid-cols-[220px_280px_minmax(0,1fr)]"
    >
      <Column
        title="Miesiąc rozpoczęcia"
        icon={<CalendarDays className="h-4 w-4" />}
      >
        {monthsNotice ??
          (months.length === 0 ? (
            <Empty>Brak zamówień z PDF-em w systemie.</Empty>
          ) : (
            <>
              <ul
                role="listbox"
                aria-label="Miesiąc rozpoczęcia"
                className="max-h-64 space-y-1 overflow-y-auto lg:max-h-none lg:overflow-visible"
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
                className="mt-3 inline-flex h-9 w-full items-center justify-center gap-1.5 rounded-md border border-border bg-background px-3 text-sm font-medium text-foreground hover:bg-muted disabled:opacity-50"
              >
                {zipBusy === "month" ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <Download className="h-4 w-4" aria-hidden />
                )}
                Pobierz cały miesiąc
              </button>
            </>
          ))}
      </Column>

      <Column
        title={month ? `Klienci — ${orderPdfMonthLabel(month)}` : "Klienci"}
        icon={<Building2 className="h-4 w-4" />}
      >
        {clientsNotice ??
          (!month ? (
            <Empty>Wybierz miesiąc.</Empty>
          ) : !clients || clients.length === 0 ? (
            <Empty>
              W tym miesiącu nie zaczyna się żadne zamówienie z PDF-em.
            </Empty>
          ) : (
            <ul role="listbox" aria-label="Klienci" className="max-h-64 space-y-1 overflow-y-auto lg:max-h-none lg:overflow-visible">
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
                        "inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border transition-colors disabled:opacity-50",
                        client.client_id === clientId
                          ? "border-primary bg-primary text-primary-foreground"
                          : "border-border bg-background text-foreground hover:bg-muted",
                      )}
                    >
                      {busy ? (
                        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                      ) : (
                        <Download className="h-4 w-4" aria-hidden />
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          ))}
      </Column>

      <div className="min-w-0 rounded-xl border border-border bg-card p-3 sm:p-4">
        {clientsNotice ? null : !selected ? (
          <>
            <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-foreground">
              <FileText className="h-4 w-4 text-muted-foreground" aria-hidden />
              Pliki
            </h2>
            <Empty>
              {clients && clients.length > 0
                ? "Wybierz klienta, aby zobaczyć PDF-y."
                : "Brak plików do pokazania."}
            </Empty>
          </>
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
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-semibold text-foreground">
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
        <div className="flex flex-wrap items-center gap-2">
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
                  "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                  active
                    ? "border-foreground bg-foreground text-background"
                    : "border-border bg-background text-foreground hover:bg-muted",
                )}
              >
                {option.label} · {typeCount(option.value)}
              </button>
            );
          })}
        </div>
        <label className="ml-auto inline-flex cursor-pointer items-center gap-2 text-sm text-foreground">
          <Checkbox
            checked={onlyNew}
            onCheckedChange={(value) => setOnlyNew(value === true)}
            aria-label="Tylko niepobrane"
          />
          Tylko niepobrane
        </label>
      </div>

      {visible.length === 0 ? (
        <Empty>
          {onlyNew
            ? "Wszystkie pliki tego klienta są już pobrane przez Ciebie."
            : "Brak plików tego typu."}
        </Empty>
      ) : (
        <div className="overflow-x-auto">
          <div
            role="table"
            aria-label={`Pliki — ${client.client_name}`}
            className="min-w-[680px] space-y-2"
          >
            <div
              role="row"
              className={cn(
                FILE_GRID,
                "px-3 text-xs font-semibold uppercase tracking-[0.06em] text-muted-foreground",
              )}
            >
              <span role="columnheader">
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
              <span role="columnheader">Zamówienie</span>
              <span role="columnheader">Typ</span>
              <span role="columnheader">Okres</span>
              <span role="columnheader">Status</span>
              <span role="columnheader" className="sr-only">
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

      <p className="flex flex-wrap items-center gap-2 rounded-lg bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
        <FolderArchive className="h-4 w-4" aria-hidden />
        Pliki w ZIP-ie: Klient_NrZam_Nazwisko_Typ_DataOd-DataDo.pdf (bez
        polskich znaków i spacji)
      </p>
    </div>
  );
}

/** Kolumny: zaznaczenie · zamówienie · typ · okres · status · akcje. */
const FILE_GRID =
  "grid grid-cols-[28px_minmax(0,2.4fr)_minmax(0,1fr)_minmax(0,1.2fr)_minmax(0,1.3fr)_76px] items-center gap-3";

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
        "rounded-lg border px-3 py-2.5 text-sm",
        checked ? "border-primary/40 bg-primary/5" : "border-border bg-card",
      )}
    >
      <span role="cell">
        <Checkbox
          checked={checked}
          onCheckedChange={(value) => onCheck(value === true)}
          aria-label={`Zaznacz: ${heading}`}
        />
      </span>
      <span role="cell" className="min-w-0">
        <span className="block font-semibold text-foreground">{heading}</span>
        <span className="block break-all text-xs text-muted-foreground">
          {file.download_name}
        </span>
        {file.consultant_name ? null : (
          <Badge variant="neutral" size="sm" className="mt-1">
            Nazwisko do uzupełnienia
          </Badge>
        )}
      </span>
      <span role="cell" className="flex flex-col items-start gap-1">
        <Badge size="sm" variant={TYPE_VARIANT[file.entry_type]}>
          {orderPdfEntryTypeLabel(file.entry_type)}
        </Badge>
        {file.status === "draft" ? (
          <Badge size="sm" variant="warning">
            {orderPdfStatusLabel(file.status)}
          </Badge>
        ) : null}
      </span>
      <span role="cell" className="text-xs text-foreground">
        {orderPdfPeriod(file)}
      </span>
      <span role="cell" className="text-xs">
        <span
          className={
            file.downloaded_at
              ? "text-success-muted-foreground"
              : "font-medium text-primary"
          }
        >
          {downloadStatusLabel(file)}
        </span>
        {file.pending_change ? (
          <span className="block font-medium text-primary">
            zmiana do rozliczenia
          </span>
        ) : null}
      </span>
      <span role="cell" className="flex justify-end gap-1.5">
        <button
          type="button"
          onClick={onPreview}
          aria-label={`Podgląd: ${file.download_name}`}
          title="Podgląd"
          className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border bg-background text-foreground hover:bg-muted"
        >
          <Eye className="h-3.5 w-3.5" aria-hidden />
        </button>
        <button
          type="button"
          onClick={onDownload}
          disabled={downloading}
          aria-label={`Pobierz ${file.download_name}`}
          title="Pobierz"
          className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border bg-background text-foreground hover:bg-muted disabled:opacity-60"
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-2 sm:p-4"
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
        "inline-flex h-9 items-center gap-1.5 rounded-md px-3 text-sm font-medium transition-colors disabled:opacity-50",
        primary
          ? "bg-primary font-semibold text-primary-foreground hover:bg-primary/90"
          : "border border-border bg-background text-foreground hover:bg-muted",
      )}
    >
      {busy ? (
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      ) : primary ? (
        <Download className="h-4 w-4" aria-hidden />
      ) : null}
      {children}
    </button>
  );
}

function Column({
  title,
  icon,
  children,
}: {
  title: string;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="h-fit min-w-0 rounded-xl border border-border bg-card p-3">
      <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-foreground">
        <span className="text-muted-foreground">{icon}</span>
        <span className="truncate">{title}</span>
      </h2>
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
        "w-full min-w-0 flex-1 rounded-md px-2.5 py-2 text-left transition-colors",
        active
          ? "bg-primary/10 text-primary"
          : "text-foreground hover:bg-muted",
      )}
    >
      <span className="block truncate text-sm font-medium">{title}</span>
      <span className="block text-xs text-muted-foreground">{meta}</span>
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
