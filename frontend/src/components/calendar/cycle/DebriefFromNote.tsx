"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Loader2, Sparkles } from "lucide-react";

import { apiErrorMessage } from "@/lib/api-error";
import { interviewCycleApi } from "@/lib/api/interviewCycle";
import { debriefFillSummary, type DebriefFromText } from "@/lib/debrief-from-text";
import { cn } from "@/lib/utils";

/**
 * „Co mówił kandydat” (20.10.2026, PR 4 uproszczenia cyklu rozmowy): jedno
 * pole na notatkę z telefonu po rozmowie u klienta. „Rozpisz” wypełnia
 * pytania klienta, ofertę, stawkę i komentarz poniżej — rekruter sprawdza
 * i zapisuje zwykły debrief. Bez tego okno działa jak dotąd.
 */
export function DebriefFromNote({
  onApply,
}: {
  /** Wołane tylko przy `status: "ok"` z wynikiem i treścią notatki. */
  onApply: (result: DebriefFromText, note: string) => void;
}) {
  const [note, setNote] = useState("");
  const [summary, setSummary] = useState<{ ok: boolean; text: string } | null>(null);

  const read = useMutation({
    mutationFn: () => interviewCycleApi.debriefFromText(note.trim()),
    onSuccess: (result) => {
      setSummary({ ok: result.status === "ok", text: debriefFillSummary(result) });
      if (result.status === "ok") onApply(result, note);
    },
    onError: (err) =>
      setSummary({ ok: false, text: apiErrorMessage(err, "Nie udało się rozpisać notatki — uzupełnij pola ręcznie.") }),
  });

  return (
    <div className="space-y-2 rounded-lg border border-dashed border-border p-3">
      <label htmlFor="debrief-note" className="block text-sm font-semibold">
        Co mówił kandydat?
      </label>
      <p className="text-xs text-muted-foreground">
        Wklej albo pisz w trakcie telefonu — NEXUS rozpisze pytania klienta, ofertę i stawkę na pola niżej.
      </p>
      <textarea
        id="debrief-note"
        rows={4}
        maxLength={8000}
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="np. „pytali o Kafkę i migrację na Javę 21, przyjmie jeśli zdalnie 4 dni, stawka bez zmian”"
        className="w-full resize-y rounded-md border border-border bg-card px-3 py-2 text-sm focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
      />
      <div className="flex flex-wrap items-center justify-between gap-2">
        {summary ? (
          <p
            role={summary.ok ? "status" : "alert"}
            className={cn("text-xs", summary.ok ? "text-muted-foreground" : "text-warning-muted-foreground")}
          >
            {summary.text}
          </p>
        ) : (
          <span />
        )}
        <button
          type="button"
          onClick={() => {
            setSummary(null);
            read.mutate();
          }}
          disabled={!note.trim() || read.isPending}
          className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-card px-3 text-xs font-semibold hover:bg-muted disabled:opacity-50"
        >
          {read.isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
          ) : (
            <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
          )}
          {read.isPending ? "Rozpisuję…" : "Rozpisz na pola"}
        </button>
      </div>
    </div>
  );
}
