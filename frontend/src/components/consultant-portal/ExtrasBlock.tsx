"use client";

// Dodatki do faktury w wierszu miesiąca panelu konsultanta (13.11.2026):
// stan zgłoszonych dodatków (polecenie, weryfikacja, szkolenie, delegacja)
// i zgłoszenie delegacji z dokumentami. Delegacja czeka na Finanse; po
// zatwierdzeniu wchodzi do danych do faktury.
import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Paperclip } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import { portalApi, portalKeys, type PortalExtra } from "@/lib/api/consultant-portal";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<PortalExtra["status"], string> = {
  pending: "text-warning-muted-foreground",
  approved: "text-success-muted-foreground",
  rejected: "text-destructive",
};

/** „Kraków 3–4.11” → poprawny wpis; kwota z przecinkiem jak w fakturze. */
export function travelFormValid(amount: string, description: string, files: number): boolean {
  const value = Number(amount.trim().replace(/\s/g, "").replace(",", "."));
  return Number.isFinite(value) && value > 0 && description.trim().length >= 3 && files > 0 && files <= 5;
}

function pln(value: string): string {
  return `${Number(value).toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} zł`;
}

export function ExtrasBlock({ year, month, extras }: { year: number; month: number; extras: PortalExtra[] }) {
  const client = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    const form = new FormData();
    form.set("year", String(year));
    form.set("month", String(month));
    form.set("amount", amount.trim());
    form.set("description", description.trim());
    files.forEach((file) => form.append("files", file));
    try {
      await portalApi.addTravel(form);
      setMessage("Delegacja zgłoszona. Finanse sprawdzą dokumenty i dadzą znać.");
      setOpen(false);
      setAmount("");
      setDescription("");
      setFiles([]);
      await client.invalidateQueries({ queryKey: portalKeys.finance });
    } catch (failure) {
      setError(apiErrorMessage(failure, "Nie udało się zgłosić delegacji. Spróbuj ponownie."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-2 space-y-1.5 text-xs">
      {extras.length > 0 ? (
        <div className="rounded-lg bg-muted/50 p-3">
          <p className="text-sm font-medium">Dodatki do faktury</p>
          <ul className="mt-1 space-y-1">
            {extras.map((extra) => (
              <li key={extra.id} className="flex flex-wrap items-baseline justify-between gap-x-2">
                <span className="min-w-0">
                  {extra.kind_label}
                  {extra.description !== extra.kind_label ? <span className="text-muted-foreground"> · {extra.description}</span> : null}
                  {extra.reason ? <span className="block text-destructive">Powód: {extra.reason}</span> : null}
                </span>
                <span className="shrink-0 tabular-nums">
                  {pln(extra.amount)} · <span className={cn("font-medium", STATUS_TONE[extra.status])}>{extra.status_label}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {open ? (
        <div className="grid max-w-xl gap-2 rounded-lg border p-3">
          <p className="text-sm font-medium">Zgłoś delegację</p>
          <p className="text-muted-foreground">
            Dołącz fakturę za hotel, paragony albo bilety. Po zatwierdzeniu przez Finanse koszt pojawi się w danych do faktury.
          </p>
          <div className="flex flex-wrap gap-2">
            <label className="grid gap-0.5">
              <span className="text-muted-foreground">Kwota netto (zł)</span>
              <Input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} className="h-9 w-32 tabular-nums" />
            </label>
            <label className="grid min-w-48 flex-1 gap-0.5">
              <span className="text-muted-foreground">Dokąd i kiedy</span>
              <Input value={description} maxLength={300} onChange={(e) => setDescription(e.target.value)} className="h-9" />
            </label>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input
              ref={input}
              type="file"
              hidden
              multiple
              aria-label="Dokumenty delegacji"
              accept=".pdf,.jpg,.jpeg,.png,.docx"
              onChange={(event) => setFiles(Array.from(event.target.files ?? []).slice(0, 5))}
            />
            <Button size="sm" variant="outline" onClick={() => input.current?.click()}>
              <Paperclip aria-hidden className="size-3.5" /> Dołącz dokumenty
            </Button>
            <span className="text-muted-foreground">
              {files.length === 0 ? "Bez dokumentów" : files.map((f) => f.name).join(", ")}
            </span>
          </div>
          <div className="flex gap-1.5">
            <Button size="sm" disabled={busy || !travelFormValid(amount, description, files.length)} onClick={submit}>
              Wyślij do Finansów
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
              Anuluj
            </Button>
          </div>
        </div>
      ) : (
        <button type="button" className="text-primary underline-offset-2 hover:underline" onClick={() => setOpen(true)}>
          Zgłoś delegację z dokumentami
        </button>
      )}
      {message ? <p className="text-muted-foreground">{message}</p> : null}
      {error ? (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}
