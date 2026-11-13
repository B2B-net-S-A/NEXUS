"use client";

import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, Copy, FileText, Minus, Upload, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  portalApi,
  portalKeys,
  usePortalQuery,
  type PortalDocument,
  type PortalMonth,
  type PortalMonthSettlement,
  type PortalSettlementInvoice,
} from "@/lib/api/consultant-portal";
import { cn } from "@/lib/utils";

import { ExtrasBlock } from "./ExtrasBlock";
import { formatDay, monthActionLabel, monthLabel, saveBlob } from "./portal-model";

function MonthRow({ row }: { row: PortalMonth }) {
  const client = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const action = monthActionLabel(row);
  const kind = row.action === "send_invoice" ? "invoice" : "report";

  const upload = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    const form = new FormData();
    form.set("kind", kind);
    form.set("year", String(row.year));
    form.set("month", String(row.month));
    form.set("file", file);
    try {
      const answer = await portalApi.upload(form);
      setMessage(answer.duplicate ? "Ten plik już mamy." : "Dokument przyjęty. Damy znać po sprawdzeniu.");
      await client.invalidateQueries({ queryKey: portalKeys.finance });
    } catch (failure) {
      setError(apiErrorMessage(failure, "Nie udało się wysłać dokumentu. Spróbuj ponownie."));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };
  const download = async (document_: PortalDocument) => {
    setError(null);
    try {
      saveBlob(await portalApi.downloadDocument(document_.id), document_.file_name ?? "dokument");
    } catch (failure) {
      setError(apiErrorMessage(failure, "Nie udało się pobrać dokumentu."));
    }
  };

  return (
    <li className="py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="min-w-0">
          <span className="block font-medium">{monthLabel(row.year, row.month)}</span>
          <span className="block text-xs text-muted-foreground">
            {row.report_label} · {row.invoice_label}
          </span>
        </span>
        {action ? (
          <>
            <input
              ref={input}
              type="file"
              hidden
              aria-label={action}
              accept=".pdf,.xlsx,.msg,.eml,.docx,.jpg,.jpeg,.png"
              onChange={(event) => upload(event.target.files?.[0])}
            />
            <Button size="sm" disabled={busy} onClick={() => input.current?.click()}>
              <Upload aria-hidden className="size-3.5" /> {action}
            </Button>
          </>
        ) : null}
      </div>
      {row.documents.length > 0 ? (
        <ul className="mt-2 space-y-1">
          {row.documents.map((document_) => (
            <li key={document_.id} className="text-xs">
              <button
                type="button"
                className="inline-flex max-w-full items-center gap-1 text-primary underline-offset-2 hover:underline"
                onClick={() => download(document_)}
              >
                <FileText aria-hidden className="size-3 shrink-0" />
                <span className="truncate">{document_.file_name ?? "Dokument"}</span>
              </button>
              {document_.reject_reason ? (
                <span className="block text-destructive">Do poprawy: {document_.reject_reason}</span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {row.settlement ? <SettlementBlock settlement={row.settlement} /> : null}
      {row.extras ? <ExtrasBlock year={row.year} month={row.month} extras={row.extras} /> : null}
      {message ? <p className="mt-1 text-xs text-muted-foreground">{message}</p> : null}
      {error ? (
        <p role="alert" className="mt-1 text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </li>
  );
}

const CHECK_ICON = {
  ok: <Check aria-hidden className="size-3" />,
  warn: <AlertTriangle aria-hidden className="size-3" />,
  fail: <X aria-hidden className="size-3" />,
  none: <Minus aria-hidden className="size-3" />,
} as const;

const CHECK_TONE = {
  ok: "bg-success-muted text-success-muted-foreground",
  warn: "bg-warning-muted text-warning-muted-foreground",
  fail: "bg-destructive-muted text-destructive-muted-foreground",
  none: "bg-muted text-muted-foreground",
} as const;

const CHECK_LABEL = { ok: "Zgodne", warn: "Uwaga", fail: "Do poprawy", none: "Sprawdza człowiek" } as const;

function md(value: string | null): string {
  return value == null ? "–" : Number(value).toLocaleString("pl-PL", { maximumFractionDigits: 3 });
}

function pln(value: string | null): string {
  if (value == null) return "–";
  return `${Number(value).toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} zł`;
}

function plainAmount(value: string | null): string {
  return value == null ? "" : Number(value).toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Pole do przepisania w programie do faktur: wartość i przycisk „Kopiuj”. */
function CopyFact({ label, value, copy }: { label: string; value: string; copy?: string }) {
  const [copied, setCopied] = useState(false);
  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(copy ?? value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="flex min-w-0 items-start justify-between gap-2">
        <span className="min-w-0 break-words tabular-nums">{value}</span>
        <button
          type="button"
          onClick={onCopy}
          className="inline-flex shrink-0 items-center gap-1 rounded px-1 text-primary hover:underline"
          aria-label={`Kopiuj: ${label}`}
        >
          {copied ? <Check aria-hidden className="size-3" /> : <Copy aria-hidden className="size-3" />}
          {copied ? "Skopiowane" : "Kopiuj"}
        </button>
      </dd>
    </>
  );
}

/** Zatwierdzony dodatek: osobna pozycja faktury (opis i netto do skopiowania). */
function ExtraItem({ description, net }: { description: string; net: string }) {
  return (
    <>
      <CopyFact label="Pozycja" value={description} />
      <CopyFact label="Netto pozycji" value={pln(net)} copy={plainAmount(net)} />
    </>
  );
}

/** Po przyjęciu RCP: dane do faktury do skopiowania (E3.2), a gdy faktura już
 * jest w KSeF — jej stan i termin zapłaty (E4). */
function InvoiceData({ invoice }: { invoice: PortalSettlementInvoice }) {
  if (invoice.ksef) {
    const differs = invoice.ksef.state === "differs";
    const waiting = invoice.ksef.state === "extra_pending";
    return (
      <dl className="grid max-w-xl grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 rounded-md bg-card p-2">
        <dt className="text-muted-foreground">Faktura</dt>
        <dd className="break-words">{invoice.ksef.invoice_number ?? invoice.ksef.ksef_number}</dd>
        <dt className="text-muted-foreground">Kwota netto</dt>
        <dd className={cn("tabular-nums", differs && "font-semibold text-destructive")}>{pln(invoice.ksef.net_amount)}</dd>
        {differs ? (
          <>
            <dt className="text-muted-foreground">Z rozliczenia</dt>
            <dd className="font-semibold tabular-nums">{pln(invoice.amount_net)}</dd>
          </>
        ) : null}
        {waiting ? (
          <>
            <dt className="text-muted-foreground">Dodatek</dt>
            <dd>czeka na zatwierdzenie Finansów</dd>
          </>
        ) : null}
        {invoice.ksef.due_date && !differs ? (
          <>
            <dt className="text-muted-foreground">Płatność do</dt>
            <dd className="tabular-nums">{formatDay(invoice.ksef.due_date)}</dd>
          </>
        ) : null}
      </dl>
    );
  }
  return (
    <div className="max-w-xl space-y-1 rounded-md bg-card p-2">
      <p className="font-medium">Dane do faktury</p>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1">
        {invoice.buyer ? (
          <>
            <CopyFact label="Nabywca" value={invoice.buyer.name} />
            <CopyFact label="NIP" value={invoice.buyer.nip} />
            <CopyFact label="Adres" value={invoice.buyer.address} />
          </>
        ) : null}
        {invoice.item ? (
          <>
            <CopyFact label="Pozycja" value={invoice.item.description} />
            <CopyFact label="Ilość" value={invoice.item.quantity} />
            {invoice.extra_items?.length ? (
              <CopyFact label="Netto pozycji" value={pln(invoice.item.net)} copy={plainAmount(invoice.item.net)} />
            ) : null}
          </>
        ) : null}
        {(invoice.extra_items ?? []).map((extra, index) => (
          <ExtraItem key={`${extra.description}-${index}`} description={extra.description} net={extra.net} />
        ))}
        <CopyFact label="Kwota netto" value={pln(invoice.amount_net)} copy={plainAmount(invoice.amount_net)} />
        <CopyFact label="Data sprzedaży" value={formatDay(invoice.sale_date)} />
        <dt className="text-muted-foreground">Termin płatności</dt>
        <dd>{invoice.payment_days} dni od nadania numeru KSeF</dd>
      </dl>
    </div>
  );
}

/** Stan RCP, wynik sprawdzenia, MD i dane do faktury (E3, styl A: bez kroków miesiąca). */
export function SettlementBlock({ settlement }: { settlement: PortalMonthSettlement }) {
  return (
    <div className="mt-2 space-y-2 rounded-lg bg-muted/50 p-3 text-xs">
      <p className="text-sm font-medium">{settlement.label}</p>
      {settlement.fix_reason ? <p className="text-destructive">Co poprawić: {settlement.fix_reason}</p> : null}
      {settlement.checks.length > 0 ? (
        <ul className="space-y-1">
          {settlement.checks.map((check) => (
            <li key={check.title} className="flex items-start gap-2">
              <span
                role="img"
                aria-label={CHECK_LABEL[check.state]}
                className={cn("mt-px flex size-4 shrink-0 items-center justify-center rounded-full", CHECK_TONE[check.state])}
              >
                {CHECK_ICON[check.state]}
              </span>
              <span>{check.title}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {settlement.md_regular != null ? (
        <p className="text-muted-foreground">
          {md(settlement.md_regular)} MD
          {settlement.md_extra ? ` i ${md(settlement.md_extra)} MD pracy dodatkowej` : ""}
          {settlement.md_remaining_after != null ? ` · na zamówieniu zostanie ${md(settlement.md_remaining_after)} MD` : ""}
        </p>
      ) : null}
      {settlement.invoice ? <InvoiceData invoice={settlement.invoice} /> : null}
    </div>
  );
}

export function DocumentsSection() {
  const months = usePortalQuery(portalKeys.finance, portalApi.financeOverview);
  return (
    <section className="rounded-xl border bg-card p-4">
      <h2 className="text-sm font-semibold">Faktury i raporty</h2>
      {months.isLoading ? <p className="mt-3 text-sm text-muted-foreground">Wczytujemy…</p> : null}
      {months.isError ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {apiErrorMessage(months.error, "Nie udało się wczytać dokumentów. Odśwież stronę.")}
        </p>
      ) : null}
      {months.isSuccess ? (
        <ul className="mt-2 divide-y text-sm">
          {months.data.months.map((row) => (
            <MonthRow key={`${row.year}-${row.month}`} row={row} />
          ))}
        </ul>
      ) : null}
    </section>
  );
}
