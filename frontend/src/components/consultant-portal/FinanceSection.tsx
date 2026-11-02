"use client";

import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { FileText, Lock, Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import {
  PortalApiError,
  portalApi,
  portalKeys,
  usePortalQuery,
  type PortalDocument,
  type PortalMonth,
} from "@/lib/api/consultant-portal";

import { cleanCode, financeView, monthActionLabel, monthLabel } from "./portal-model";

function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

function VerifyCode({ hint, supportEmail }: { hint: string | null; supportEmail: string | null }) {
  const client = useQueryClient();
  const [sent, setSent] = useState(false);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      await portalApi.sendCode();
      setSent(true);
    } catch (failure) {
      setError(apiErrorMessage(failure, "Nie udało się wysłać kodu. Spróbuj ponownie za chwilę."));
    } finally {
      setBusy(false);
    }
  };
  const verify = async () => {
    setBusy(true);
    setError(null);
    try {
      await portalApi.verifyCode(code);
      await client.invalidateQueries({ queryKey: portalKeys.financeStatus });
    } catch (failure) {
      setError(apiErrorMessage(failure, "Nie udało się sprawdzić kodu. Spróbuj ponownie."));
      setCode("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-3 space-y-3 text-sm">
      <p className="text-muted-foreground">
        Faktury i raporty to dane finansowe, więc najpierw potwierdzimy, że to Ty.
        {sent && hint ? ` Wysłaliśmy kod SMS na numer kończący się na ${hint}.` : ""}
        {!sent && hint ? ` Wyślemy kod SMS na numer kończący się na ${hint}.` : ""}
      </p>
      {sent ? (
        <div className="flex gap-2">
          <Input
            aria-label="Kod SMS"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={12}
            className="max-w-40 tracking-widest"
            value={code}
            onChange={(event) => setCode(cleanCode(event.target.value))}
          />
          <Button disabled={busy || code.length !== 6} onClick={verify}>
            Potwierdź
          </Button>
        </div>
      ) : null}
      <Button variant={sent ? "outline" : "primary"} size="sm" disabled={busy} onClick={send}>
        {sent ? "Wyślij kod ponownie" : "Wyślij kod SMS"}
      </Button>
      {error ? (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      ) : null}
      <p className="text-xs text-muted-foreground">
        Numer się zmienił? {supportEmail ? `Napisz na ${supportEmail}` : "Załóż zgłoszenie"}. Numeru ani konta
        bankowego nie zmienisz sam w portalu.
      </p>
    </div>
  );
}

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

export function FinanceSection({ supportEmail }: { supportEmail: string | null }) {
  const status = usePortalQuery(portalKeys.financeStatus, portalApi.financeStatus);
  const view = financeView(status.data, { isError: status.isError });
  const months = usePortalQuery(portalKeys.finance, portalApi.financeOverview, view === "open");
  // Odblokowanie wygasa po 30 minutach: serwer mówi wtedy „sms_required”, a my pytamy znów o kod.
  const expired = months.error instanceof PortalApiError && months.error.code === "sms_required";

  return (
    <section className="rounded-xl border bg-card p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">Faktury i raporty</h2>
        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
          <Lock aria-hidden className="size-3" /> po potwierdzeniu kodem
        </span>
      </div>
      {view === "loading" ? <p className="mt-3 text-sm text-muted-foreground">Wczytujemy…</p> : null}
      {view === "error" ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {apiErrorMessage(status.error, "Nie udało się wczytać tej sekcji. Odśwież stronę.")}
        </p>
      ) : null}
      {view === "unavailable" ? <p className="mt-3 text-sm text-muted-foreground">{status.data?.message}</p> : null}
      {view === "verify" || expired ? (
        <VerifyCode hint={status.data?.phone_hint ?? null} supportEmail={supportEmail} />
      ) : null}
      {view === "open" && !expired ? (
        <>
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
        </>
      ) : null}
    </section>
  );
}
