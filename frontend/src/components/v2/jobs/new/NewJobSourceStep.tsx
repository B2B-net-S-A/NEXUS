"use client";

/**
 * Krok 1 strony `/jobs/new`: klient i źródło danych (decyzje Artura 02.10.2026).
 *
 * Trzy sposoby wypełnienia formularza stoją obok siebie jako kafle — do 02.10
 * wgranie pliku i wpisanie ręczne były linkami w rogu pola tekstowego i nikt
 * nie wiedział, że są do wyboru. Klient jest wymagany we wszystkich trzech:
 * próba przejścia dalej bez niego pokazuje komunikat przy polu klienta, zamiast
 * zostawiać nieaktywny przycisk bez wyjaśnienia.
 */

import { useId, useRef, useState } from "react";
import { ClipboardPaste, FileUp, PencilLine, Sparkles, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { FileDropZone } from "@/components/ds/FileDropZone";
import {
  ClientSinglePicker,
  type ClientRef,
} from "@/components/clients/ClientSinglePicker";
import { FORM_SECTIONS, MIN_REQUEST_CHARS } from "@/lib/job-request-intake";
import { cn } from "@/lib/utils";

export type NewJobSource = "text" | "file" | "manual";

export const REQUEST_FILE_ACCEPT = ".docx,.pdf,.txt";
/** Lustro `MAX_FILE_BYTES` w `api/job_request_intake.py`. */
const REQUEST_FILE_MAX_BYTES = 10 * 1024 * 1024;

export const CLIENT_REQUIRED_TEXT =
  "Najpierw wybierz klienta. Bez niego nie przejdziesz dalej — od klienta zależą zasady CV, hiring manager i kategoria.";

const SOURCES: {
  value: NewJobSource;
  title: string;
  description: string;
  icon: typeof FileUp;
}[] = [
  {
    value: "text",
    title: "Wklej treść requestu",
    description: "Mail albo wiadomość od klienta. AI wypełni formularz, Ty sprawdzasz.",
    icon: ClipboardPaste,
  },
  {
    value: "file",
    title: "Wgraj plik",
    description:
      "Zapytanie klienta albo Profil Championa: .docx, .pdf, .txt. AI wypełni formularz.",
    icon: FileUp,
  },
  {
    value: "manual",
    title: "Wpisz ręcznie",
    description: "Bez AI. Pusty formularz, wszystko wpisujesz samodzielnie.",
    icon: PencilLine,
  },
];

const SECTION_HINT: Record<string, string> = {
  name: "jak napisał klient, razem z numerem",
  requirements: "słowa kluczowe, po których szukamy",
  terms: "budżet, tryb pracy, biuro, start",
  project: "dwa zdania dla rekrutera",
  questions: "dobra odpowiedź i odpowiedź, która odpada",
  team: "potwierdzasz kategorię; prowadzącego przydziela automat albo wskazujesz sam",
};

interface NewJobSourceStepProps {
  client: ClientRef | null;
  onClientChange: (client: ClientRef | null) => void;
  source: NewJobSource;
  onSourceChange: (source: NewJobSource) => void;
  text: string;
  onTextChange: (text: string) => void;
  file: File | null;
  onFileChange: (file: File | null) => void;
  reading: boolean;
  error: string | null;
  onRead: () => void;
  onManual: () => void;
}

export function NewJobSourceStep({
  client,
  onClientChange,
  source,
  onSourceChange,
  text,
  onTextChange,
  file,
  onFileChange,
  reading,
  error,
  onRead,
  onManual,
}: NewJobSourceStepProps) {
  const ids = { client: useId(), clientError: useId(), text: useId(), file: useId() };
  const clientRef = useRef<HTMLDivElement>(null);
  const tiles = useRef<Array<HTMLButtonElement | null>>([]);
  // Komunikat pojawia się dopiero po próbie przejścia dalej bez klienta.
  const [clientAsked, setClientAsked] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const clientMissing = client == null;
  const showClientError = clientMissing && clientAsked;

  const hasInput =
    source === "manual" ||
    (source === "file" ? file != null : text.trim().length >= MIN_REQUEST_CHARS);

  const proceed = () => {
    if (clientMissing) {
      setClientAsked(true);
      clientRef.current?.scrollIntoView?.({ block: "center", behavior: "smooth" });
      clientRef.current?.querySelector<HTMLElement>("button")?.focus();
      return;
    }
    if (source === "manual") onManual();
    else onRead();
  };

  const moveTile = (from: number, step: 1 | -1) => {
    const next = (from + step + SOURCES.length) % SOURCES.length;
    tiles.current[next]?.focus();
    onSourceChange(SOURCES[next].value);
  };

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-6 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <section className="flex flex-col gap-5 rounded-xl border border-border bg-card p-4 sm:p-6">
        <div ref={clientRef} className="flex flex-col gap-2">
          <span
            id={ids.client}
            className="inline-flex items-baseline gap-2 text-sm font-medium text-foreground"
          >
            Klient
            <span className="text-xs font-normal text-muted-foreground">wymagany</span>
          </span>
          <div
            role="group"
            aria-labelledby={ids.client}
            aria-describedby={showClientError ? ids.clientError : undefined}
            className={cn(
              "rounded-lg",
              showClientError && "ring-2 ring-warning ring-offset-2 ring-offset-card",
            )}
          >
            <ClientSinglePicker
              value={client}
              onChange={onClientChange}
              queryKey="clients-lookup-new-job"
              selectableOnly
              allowClear
              placeholder="Wybierz klienta…"
            />
          </div>
          {showClientError ? (
            <p
              id={ids.clientError}
              role="alert"
              className="rounded-lg border border-warning bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground"
            >
              {CLIENT_REQUIRED_TEXT}
            </p>
          ) : null}
        </div>

        <div className="flex flex-col gap-2">
          <div>
            <h2 id={`${ids.text}-source`} className="text-sm font-medium text-foreground">
              Skąd bierzemy dane?
            </h2>
            <p className="text-xs text-muted-foreground">
              Trzy sposoby, jeden formularz na końcu. Zawsze możesz zmienić zdanie.
            </p>
          </div>
          <div
            role="radiogroup"
            aria-labelledby={`${ids.text}-source`}
            className="grid gap-3 md:grid-cols-3"
          >
            {SOURCES.map((option, index) => {
              const checked = option.value === source;
              const Icon = option.icon;
              return (
                <button
                  key={option.value}
                  ref={(node) => {
                    tiles.current[index] = node;
                  }}
                  type="button"
                  role="radio"
                  aria-checked={checked}
                  tabIndex={checked ? 0 : -1}
                  disabled={reading}
                  onClick={() => onSourceChange(option.value)}
                  onKeyDown={(event) => {
                    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
                    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
                      event.preventDefault();
                      moveTile(index, 1);
                    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
                      event.preventDefault();
                      moveTile(index, -1);
                    }
                  }}
                  className={cn(
                    "flex min-w-0 flex-col items-start gap-2 rounded-xl border p-4 text-left transition-colors disabled:opacity-60",
                    checked
                      ? "border-primary bg-primary/5 ring-1 ring-primary"
                      : "border-border bg-card hover:border-primary/40 hover:bg-accent",
                  )}
                >
                  <span
                    className={cn(
                      "flex h-9 w-9 items-center justify-center rounded-lg",
                      checked ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
                    )}
                  >
                    <Icon className="h-4 w-4" aria-hidden />
                  </span>
                  <span className="text-sm font-semibold text-foreground">{option.title}</span>
                  <span className="text-xs leading-snug text-muted-foreground">
                    {option.description}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {source === "text" ? (
          <div className="flex flex-col gap-2">
            <label htmlFor={ids.text} className="text-sm font-medium text-foreground">
              Treść requestu
            </label>
            <Textarea
              id={ids.text}
              value={text}
              onChange={(e) => onTextChange(e.target.value)}
              rows={12}
              className="min-h-[240px] font-normal leading-relaxed"
              placeholder="Wklej treść maila od klienta — stanowisko, wymagania, stawka, tryb pracy…"
            />
          </div>
        ) : source === "file" ? (
          <div className="flex flex-col gap-2">
            <FileDropZone
              inputId={ids.file}
              file={file}
              onPick={(next) => {
                setFileError(null);
                onFileChange(next);
              }}
              accept={REQUEST_FILE_ACCEPT}
              maxBytes={REQUEST_FILE_MAX_BYTES}
              label="Plik z requestem"
              error={fileError}
              onError={setFileError}
              disabled={reading}
            />
            {file ? (
              <button
                type="button"
                className="inline-flex items-center gap-1 self-start text-xs font-medium text-muted-foreground hover:text-foreground"
                onClick={() => onFileChange(null)}
              >
                <X className="h-3.5 w-3.5" aria-hidden /> Usuń plik
              </button>
            ) : null}
          </div>
        ) : (
          <div className="rounded-lg bg-muted px-4 py-3 text-sm text-muted-foreground">
            <p className="font-medium text-foreground">Wpisujesz ręcznie</p>
            <p>
              Te same sześć sekcji, tylko puste. Podpowiedzi słów kluczowych i kategorii
              działają też bez AI.
            </p>
          </div>
        )}

        {error && (
          <div
            role="alert"
            className="rounded-lg border border-destructive/20 bg-destructive/10 px-3 py-2 text-sm text-destructive"
          >
            {error}
          </div>
        )}

        <div className="flex flex-wrap items-center justify-end gap-3">
          {!clientMissing && !hasInput ? (
            <span className="text-xs text-muted-foreground">
              {source === "file"
                ? "Wybierz plik z requestem."
                : `Wklej treść requestu (co najmniej ${MIN_REQUEST_CHARS} znaków).`}
            </span>
          ) : null}
          <Button
            type="button"
            onClick={proceed}
            // Bez klienta przycisk zostaje aktywny: kliknięcie mówi, czego brakuje.
            disabled={reading || (!clientMissing && !hasInput)}
            loading={reading}
          >
            {source !== "manual" && !reading && <Sparkles className="h-4 w-4" />}
            {reading
              ? "Czytam request…"
              : clientMissing
                ? "Najpierw wybierz klienta"
                : source === "manual"
                  ? "Przejdź do formularza"
                  : "Odczytaj i przejdź dalej"}
          </Button>
        </div>
      </section>

      <aside className="flex h-fit flex-col gap-3 rounded-xl border border-border bg-card p-4 sm:p-6">
        <h2 className="text-base font-semibold text-foreground">
          Co znajdzie się w formularzu
        </h2>
        <p className="text-sm text-muted-foreground">
          {source === "manual"
            ? "Sześć sekcji. Wypełniasz je po kolei; brakujące pola są zaznaczone na dole strony."
            : "Sześć sekcji. AI wypełnia tylko to, co jest w treści — braków nie zgaduje, tylko je zaznacza."}
        </p>
        <ol className="mt-1 flex flex-col gap-2.5">
          {FORM_SECTIONS.map((section, i) => (
            <li key={section.id} className="flex items-start gap-2.5 text-sm text-foreground">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-primary/10 text-xs font-semibold text-primary">
                {i + 1}
              </span>
              <span>
                <span className="font-medium">{section.label}</span>
                <span className="text-muted-foreground"> — {SECTION_HINT[section.id]}</span>
              </span>
            </li>
          ))}
        </ol>
      </aside>
    </div>
  );
}
