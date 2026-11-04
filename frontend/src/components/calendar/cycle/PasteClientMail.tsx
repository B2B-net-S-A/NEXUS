"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ClipboardPaste, Loader2 } from "lucide-react";

import { apiErrorMessage } from "@/lib/api-error";
import { interviewCycleApi } from "@/lib/api/interviewCycle";
import { readSummary, type SlotsFromMail } from "@/lib/interview-slot-mail";
import { warsawToday } from "@/lib/warsaw-date";
import { cn } from "@/lib/utils";

const INPUT =
  "w-full rounded-md border border-border bg-card px-3 py-2 text-sm focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring";

/**
 * „Wklej maila od klienta” (20.10.2026): tekst idzie do odczytu i znika —
 * w formularzu zostają terminy do sprawdzenia. Wspólne dla okna „Terminy od
 * klienta” i „Kiedy rozmowa u klienta?” przy ruchu karty.
 */
export function PasteClientMail({
  onRead,
  idPrefix,
}: {
  /** Wołane tylko przy `status: "ok"` — formularz podmienia terminy. */
  onRead: (result: SlotsFromMail) => void;
  idPrefix: string;
}) {
  const [text, setText] = useState("");
  const [mailDate, setMailDate] = useState(() => warsawToday());
  const [summary, setSummary] = useState<{ ok: boolean; text: string } | null>(null);
  const [collapsed, setCollapsed] = useState(false);

  const read = useMutation({
    mutationFn: () =>
      interviewCycleApi.readSlotsFromMail({ text: text.trim(), mail_date: mailDate || null }),
    onSuccess: (result) => {
      setSummary({ ok: result.status === "ok", text: readSummary(result) });
      if (result.status === "ok") {
        onRead(result);
        setText("");
        setCollapsed(true);
      }
    },
    onError: (err) =>
      setSummary({ ok: false, text: apiErrorMessage(err, "Nie udało się odczytać terminów — wpisz je ręcznie.") }),
  });

  if (collapsed) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-muted/50 px-3 py-2 text-xs">
        <span role="status" className="text-muted-foreground">
          {summary?.text}
        </span>
        <button
          type="button"
          onClick={() => {
            setCollapsed(false);
            setSummary(null);
          }}
          className="font-semibold text-primary hover:underline"
        >
          Wklej inny mail
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-2 rounded-lg border border-dashed border-border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label htmlFor={`${idPrefix}-mail`} className="text-xs font-semibold text-muted-foreground">
          Wklej maila od klienta — NEXUS wypisze terminy
        </label>
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          Mail z dnia
          <input
            type="date"
            value={mailDate}
            max={warsawToday()}
            onChange={(e) => setMailDate(e.target.value)}
            className="h-7 rounded-md border border-border bg-card px-2 text-xs"
          />
        </label>
      </div>
      <textarea
        id={`${idPrefix}-mail`}
        rows={4}
        maxLength={8000}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="np. „Pasuje nam czwartek o 10:00 albo 14:30, piątek między 9 a 12…”"
        className={cn(INPUT, "resize-y")}
      />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-muted-foreground">Treść maila nie zostaje w NEXUSIE.</span>
        <button
          type="button"
          onClick={() => {
            setSummary(null);
            read.mutate();
          }}
          disabled={!text.trim() || read.isPending}
          className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-card px-3 text-xs font-semibold hover:bg-muted disabled:opacity-50"
        >
          {read.isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
          ) : (
            <ClipboardPaste className="h-3.5 w-3.5" aria-hidden="true" />
          )}
          {read.isPending ? "Czytam…" : "Odczytaj terminy"}
        </button>
      </div>
      {summary && !summary.ok ? (
        <p role="alert" className="rounded-md bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground">
          {summary.text}
        </p>
      ) : null}
    </div>
  );
}
