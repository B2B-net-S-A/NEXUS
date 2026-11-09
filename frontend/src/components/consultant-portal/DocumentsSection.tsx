"use client";

import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { FileText, Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  portalApi,
  portalKeys,
  usePortalQuery,
  type PortalDocument,
  type PortalMonth,
} from "@/lib/api/consultant-portal";

import { monthActionLabel, monthLabel, saveBlob } from "./portal-model";

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
              accept=".pdf,.docx,.jpg,.jpeg,.png"
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
      {message ? <p className="mt-1 text-xs text-muted-foreground">{message}</p> : null}
      {error ? (
        <p role="alert" className="mt-1 text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </li>
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
