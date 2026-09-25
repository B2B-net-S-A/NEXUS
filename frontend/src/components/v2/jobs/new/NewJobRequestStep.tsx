"use client";

import { useId, useRef } from "react";
import { FileText, Sparkles, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  ClientSinglePicker,
  type ClientRef,
} from "@/components/clients/ClientSinglePicker";
import { MIN_REQUEST_CHARS } from "@/lib/job-request-intake";

const WHAT_AI_READS = [
  "Rola",
  "Must-have i mile widziane",
  "Wymagania do wyszukiwania w bazie",
  "Budżet PLN/h",
  "Tryb pracy, dni w biurze, miasto",
  "O projekcie (2 zdania)",
  "Pytania screeningowe (min. 2)",
];

export const REQUEST_FILE_ACCEPT = ".docx,.pdf,.txt";

interface NewJobRequestStepProps {
  client: ClientRef | null;
  onClientChange: (client: ClientRef | null) => void;
  text: string;
  onTextChange: (text: string) => void;
  file: File | null;
  onFileChange: (file: File | null) => void;
  reading: boolean;
  error: string | null;
  onRead: () => void;
  onSkipAi: () => void;
}

/** Krok 1 strony `/jobs/new`: klient + request (tekst albo plik). */
export function NewJobRequestStep({
  client,
  onClientChange,
  text,
  onTextChange,
  file,
  onFileChange,
  reading,
  error,
  onRead,
  onSkipAi,
}: NewJobRequestStepProps) {
  const textId = useId();
  const fileRef = useRef<HTMLInputElement>(null);
  const hasInput = file != null || text.trim().length >= MIN_REQUEST_CHARS;
  const canRead = client != null && hasInput && !reading;

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <section className="flex flex-col gap-5 rounded-xl border border-border bg-card p-4 sm:p-6">
        <div className="flex flex-col gap-2">
          <span className="text-sm font-medium text-foreground">Klient</span>
          <ClientSinglePicker
            value={client}
            onChange={onClientChange}
            queryKey="clients-lookup-new-job"
            allowClear
            placeholder="Wybierz klienta…"
          />
        </div>

        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <label
              htmlFor={textId}
              className="text-sm font-medium text-foreground"
            >
              Request od klienta
            </label>
            <span className="text-xs text-muted-foreground">
              lub{" "}
              <button
                type="button"
                className="font-medium text-primary underline-offset-2 hover:underline"
                onClick={() => fileRef.current?.click()}
              >
                wgraj plik
              </button>{" "}
              (.docx, .pdf, .txt)
            </span>
            <input
              ref={fileRef}
              type="file"
              accept={REQUEST_FILE_ACCEPT}
              className="hidden"
              aria-label="Plik z requestem"
              onChange={(e) => {
                onFileChange(e.target.files?.[0] ?? null);
                e.target.value = "";
              }}
            />
          </div>
          {file ? (
            <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-muted/40 px-4 py-3 text-sm">
              <span className="flex min-w-0 items-center gap-2">
                <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span className="truncate">{file.name}</span>
              </span>
              <button
                type="button"
                aria-label="Usuń plik"
                className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                onClick={() => onFileChange(null)}
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          ) : (
            <Textarea
              id={textId}
              value={text}
              onChange={(e) => onTextChange(e.target.value)}
              rows={16}
              className="min-h-[320px] font-normal leading-relaxed"
              placeholder="Wklej treść maila od klienta — stanowisko, wymagania, stawka, tryb pracy…"
            />
          )}
        </div>

        {error && (
          <div
            role="alert"
            className="rounded-lg border border-destructive/20 bg-destructive/10 px-3 py-2 text-sm text-destructive"
          >
            {error}
          </div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-3">
          <button
            type="button"
            className="text-sm text-muted-foreground underline-offset-2 hover:text-foreground hover:underline disabled:opacity-50"
            onClick={onSkipAi}
            disabled={client == null || reading}
          >
            Wypełnij ręcznie, bez AI
          </button>
          <Button
            type="button"
            onClick={onRead}
            disabled={!canRead}
            loading={reading}
          >
            {!reading && <Sparkles className="h-4 w-4" />}
            {reading ? "Czytam request…" : "Odczytaj request"}
          </Button>
        </div>
        {client == null && (
          <p className="-mt-2 text-right text-xs text-muted-foreground">
            Najpierw wybierz klienta.
          </p>
        )}
      </section>

      <aside className="flex h-fit flex-col gap-3 rounded-xl border border-border bg-card p-4 sm:p-6">
        <h2 className="text-base font-semibold text-foreground">
          Co AI wyciągnie z requestu
        </h2>
        <p className="text-sm text-muted-foreground">
          To minimum, żeby rekrutacja od razu trafiła do searchu. Wszystko
          sprawdzisz i poprawisz w następnym kroku — AI nie zgaduje brakujących
          danych, tylko je zaznacza.
        </p>
        <ol className="mt-1 flex flex-col gap-2.5">
          {WHAT_AI_READS.map((label, i) => (
            <li
              key={label}
              className="flex items-center gap-2.5 text-sm text-foreground"
            >
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-primary/10 text-xs font-semibold text-primary">
                {i + 1}
              </span>
              {label}
            </li>
          ))}
        </ol>
      </aside>
    </div>
  );
}
