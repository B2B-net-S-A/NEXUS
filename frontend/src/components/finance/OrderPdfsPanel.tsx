"use client";

import type { ReactNode } from "react";
import { Building2, CalendarDays, Download, FileText, Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { OrderPdfClient, OrderPdfFile, OrderPdfMonth } from "@/lib/api/finance";
import {
  clientsLabel,
  filesLabel,
  orderPdfEntryTypeLabel,
  orderPdfKey,
  orderPdfMonthLabel,
  orderPdfPeriod,
  orderPdfStatusLabel,
} from "@/lib/finance-order-pdfs";
import { cn } from "@/lib/utils";

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
}

/**
 * Finanse → „Zamówienia PDF": miesiąc startu → klient → pliki do pobrania.
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
}: OrderPdfsPanelProps) {
  const selected = clients?.find((c) => c.client_id === clientId) ?? null;

  return (
    <section
      aria-label="Zamówienia PDF"
      className="grid gap-4 lg:grid-cols-[200px_280px_minmax(0,1fr)]"
    >
      <Column title="Miesiąc rozpoczęcia" icon={<CalendarDays className="h-4 w-4" />}>
        {monthsNotice ?? (
          months.length === 0 ? (
            <Empty>Brak zamówień z PDF-em w systemie.</Empty>
          ) : (
            <ul role="listbox" aria-label="Miesiąc rozpoczęcia" className="space-y-1">
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
          )
        )}
      </Column>

      <Column
        title={month ? `Klienci — ${orderPdfMonthLabel(month)}` : "Klienci"}
        icon={<Building2 className="h-4 w-4" />}
      >
        {clientsNotice ??
          (!month ? (
            <Empty>Wybierz miesiąc.</Empty>
          ) : !clients || clients.length === 0 ? (
            <Empty>W tym miesiącu nie zaczyna się żadne zamówienie z PDF-em.</Empty>
          ) : (
            <ul role="listbox" aria-label="Klienci" className="space-y-1">
              {clients.map((client) => (
                <li key={client.client_id}>
                  <PickButton
                    active={client.client_id === clientId}
                    onClick={() => onClientChange(client.client_id)}
                    title={client.client_name}
                    meta={filesLabel(client.files.length)}
                  />
                </li>
              ))}
            </ul>
          ))}
      </Column>

      <Column
        title={selected ? selected.client_name : "Pliki"}
        icon={<FileText className="h-4 w-4" />}
      >
        {clientsNotice ? null : !selected ? (
          <Empty>
            {clients && clients.length > 0
              ? "Wybierz klienta, aby zobaczyć PDF-y."
              : "Brak plików do pokazania."}
          </Empty>
        ) : (
          <ul aria-label={`Pliki — ${selected.client_name}`} className="space-y-2">
            {selected.files.map((file) => (
              <FileRow
                key={orderPdfKey(file)}
                file={file}
                downloading={downloadingKey === orderPdfKey(file)}
                onDownload={() => onDownload(file)}
              />
            ))}
          </ul>
        )}
      </Column>
    </section>
  );
}

function FileRow({
  file,
  downloading,
  onDownload,
}: {
  file: OrderPdfFile;
  downloading: boolean;
  onDownload: () => void;
}) {
  const status = orderPdfStatusLabel(file.status);
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-border bg-muted/30 px-3 py-2.5 sm:flex-row sm:items-start">
      <div className="min-w-0 flex-1 space-y-1">
        <p className="break-all text-sm font-semibold text-foreground">
          {file.download_name}
        </p>
        <p className="text-xs text-muted-foreground">
          {file.consultant_name ?? "Bez przypisanej osoby"} · {orderPdfPeriod(file)}
          {file.order_number ? ` · ${file.order_number}` : ""}
        </p>
        <div className="flex flex-wrap gap-1">
          <Badge variant={file.entry_type === "new" ? "soft" : "info"} size="sm">
            {orderPdfEntryTypeLabel(file.entry_type)}
          </Badge>
          {status ? (
            <Badge variant={file.status === "draft" ? "warning" : "outline"} size="sm">
              {status}
            </Badge>
          ) : null}
          {file.consultant_name ? null : (
            <Badge variant="neutral" size="sm">
              Nazwisko do uzupełnienia
            </Badge>
          )}
        </div>
        {file.original_name !== file.download_name ? (
          <p className="break-all text-[11px] text-muted-foreground">
            Oryginalna nazwa: {file.original_name}
          </p>
        ) : null}
      </div>
      <button
        type="button"
        onClick={onDownload}
        disabled={downloading}
        aria-label={`Pobierz ${file.download_name}`}
        className="inline-flex h-8 shrink-0 items-center gap-1.5 self-start rounded-md border border-border bg-background px-3 text-xs font-medium text-foreground hover:bg-accent disabled:opacity-60"
      >
        {downloading ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <Download className="h-3.5 w-3.5" />
        )}
        Pobierz
      </button>
    </li>
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
    <div className="min-w-0 rounded-xl border border-border bg-card p-3">
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
  meta: string;
}) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "w-full rounded-md px-2.5 py-2 text-left transition-colors",
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
