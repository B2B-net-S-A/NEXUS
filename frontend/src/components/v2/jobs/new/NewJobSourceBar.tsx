"use client";

/**
 * Pasek nad formularzem `/jobs/new`: klient i „Wypełnij z: Wklej treść | Wgraj
 * plik | Inna rekrutacja” (decyzja D2, 10.10.2026).
 *
 * Do tej daty strona miała dwa kroki: najpierw klient i jeden z trzech kafli
 * źródła, potem formularz. Każdy kafel dawał inny ekran (ręczny — pusty
 * przerywany prostokąt na 40% szerokości), a zmiana źródła kasowała wpisane
 * pola. Teraz formularz stoi na stronie zawsze, a źródło to akcja, z której
 * można skorzystać w dowolnej chwili i dowolną liczbę razy — odczyt wypełnia
 * tylko puste pola (`lib/job-intake-fill.ts`).
 *
 * Klient jest wymagany przy każdym źródle: kliknięcie akcji bez klienta
 * pokazuje komunikat przy polu klienta zamiast otwierać panel.
 */

import { useEffect, useId, useRef, useState, type ReactNode, type RefObject } from "react";
import { ClipboardPaste, Copy, FileUp, Sparkles, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { FileDropZone } from "@/components/ds/FileDropZone";
import {
  ClientSinglePicker,
  type ClientRef,
} from "@/components/clients/ClientSinglePicker";
import { MIN_REQUEST_CHARS } from "@/lib/job-request-intake";
import { cn } from "@/lib/utils";

/** Źródło, z którego formularz był wypełniany ostatnio (zapis formularza). */
export type NewJobSource = "text" | "file" | "manual";

/** Otwarty panel pod paskiem. */
export type NewJobSourcePanel = "text" | "file" | "template";

export const REQUEST_FILE_ACCEPT = ".docx,.pdf,.txt";
/** Lustro `MAX_FILE_BYTES` w `api/job_request_intake.py`. */
const REQUEST_FILE_MAX_BYTES = 10 * 1024 * 1024;

export const CLIENT_REQUIRED_TEXT =
  "Najpierw wybierz klienta. Od klienta zależą zasady CV, hiring manager i kategoria — bez niego nie odczytamy requestu ani nie utworzymy rekrutacji.";

/** `id` pola klienta — cel linku „klient” ze stopki strony. */
export const CLIENT_FIELD_ANCHOR = "new-job-client";

const ACTIONS: { value: NewJobSourcePanel; label: string; icon: typeof FileUp }[] = [
  { value: "text", label: "Wklej treść", icon: ClipboardPaste },
  { value: "file", label: "Wgraj plik", icon: FileUp },
  { value: "template", label: "Inna rekrutacja", icon: Copy },
];

interface NewJobSourceBarProps {
  client: ClientRef | null;
  onClientChange: (client: ClientRef | null) => void;
  /** Ktoś próbował użyć źródła albo utworzyć rekrutację bez klienta. */
  clientAsked: boolean;
  /** Próba bez klienta — strona pokazuje komunikat i ustawia fokus na polu. */
  onClientRequired: () => void;
  clientRef: RefObject<HTMLDivElement | null>;
  /** Cały pasek — strona przenosi tu fokus po „Cofnij wypełnienie”. */
  barRef?: RefObject<HTMLElement | null>;
  panel: NewJobSourcePanel | null;
  onPanelChange: (panel: NewJobSourcePanel | null) => void;
  /** Treść wpisana w panelu, jeszcze nieodczytana. */
  text: string;
  onTextChange: (text: string) => void;
  file: File | null;
  onFileChange: (file: File | null) => void;
  reading: boolean;
  error: string | null;
  onRead: (kind: "text" | "file") => void;
  /** Lista rekrutacji-szablonów (`TemplateJobPicker`) — renderuje ją strona. */
  templatePicker: ReactNode;
  disabled?: boolean;
}

export function NewJobSourceBar({
  client,
  onClientChange,
  clientAsked,
  onClientRequired,
  clientRef,
  barRef,
  panel,
  onPanelChange,
  text,
  onTextChange,
  file,
  onFileChange,
  reading,
  error,
  onRead,
  templatePicker,
  disabled = false,
}: NewJobSourceBarProps) {
  const ids = {
    client: useId(),
    clientError: useId(),
    group: useId(),
    panel: useId(),
    text: useId(),
    file: useId(),
  };
  const [fileError, setFileError] = useState<string | null>(null);
  const clientMissing = client == null;
  const showClientError = clientMissing && clientAsked;
  // Bez klienta panel się nie otwiera — także gdy klient zniknął po otwarciu.
  const open = clientMissing ? null : panel;
  const textReady = text.trim().length >= MIN_REQUEST_CHARS;

  // Panel znika razem z przyciskiem, który go zamknął („Zamknij”, „Odczytaj”,
  // wybór rekrutacji-szablonu). Bez tego fokus klawiatury spadał na początek
  // strony; wraca na przycisk źródła, o ile ktoś nie przeniósł go sam.
  const actionRefs = useRef<Partial<Record<NewJobSourcePanel, HTMLButtonElement | null>>>({});
  const lastOpenRef = useRef<NewJobSourcePanel | null>(open);
  useEffect(() => {
    const closed = lastOpenRef.current;
    lastOpenRef.current = open;
    if (open != null || closed == null) return;
    const active = document.activeElement;
    if (active && active !== document.body && active.isConnected) return;
    actionRefs.current[closed]?.focus();
  }, [open]);

  const toggle = (next: NewJobSourcePanel) => {
    if (clientMissing) {
      onClientRequired();
      return;
    }
    onPanelChange(panel === next ? null : next);
  };

  return (
    <section
      ref={barRef}
      tabIndex={-1}
      aria-label="Klient i źródło danych"
      className="flex flex-col gap-3 rounded-xl border border-border bg-card p-3 outline-none focus-visible:ring-2 focus-visible:ring-ring sm:p-4"
    >
      {/* Jeden rząd na laptopie: formularz ma zaczynać się wysoko na stronie. */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:gap-6">
        <div
          ref={clientRef}
          id={CLIENT_FIELD_ANCHOR}
          className="flex min-w-0 scroll-mt-28 items-center gap-2 lg:w-80 lg:shrink-0"
        >
          <span id={ids.client} className="shrink-0 text-sm font-medium text-foreground">
            Klient
          </span>
          <div
            role="group"
            aria-labelledby={ids.client}
            aria-describedby={showClientError ? ids.clientError : undefined}
            className={cn(
              // Długa nazwa klienta ma się uciąć w przycisku, a nie rozepchnąć
              // pasek — bez `min-w-0` przycisk nie kurczy się poniżej tekstu.
              "min-w-0 flex-1 rounded-lg [&_button:first-of-type]:min-w-0",
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
              // Odczyt wraca po kilkudziesięciu sekundach: zmiana klienta w tym
              // czasie wstawiłaby dane (i hiring managera) innego klienta.
              disabled={reading}
            />
          </div>
        </div>

        <div
          role="group"
          aria-labelledby={ids.group}
          className="flex min-w-0 flex-wrap items-center gap-2"
        >
          <span id={ids.group} className="text-sm text-muted-foreground">
            Wypełnij z:
          </span>
          {ACTIONS.map((action) => {
            const pressed = open === action.value;
            const Icon = action.icon;
            return (
              <Button
                key={action.value}
                ref={(node) => {
                  actionRefs.current[action.value] = node;
                }}
                type="button"
                size="sm"
                variant={pressed ? "primary" : "outline"}
                aria-pressed={pressed}
                aria-expanded={pressed}
                aria-controls={pressed ? ids.panel : undefined}
                disabled={disabled || reading}
                onClick={() => toggle(action.value)}
              >
                <Icon className="h-3.5 w-3.5" aria-hidden /> {action.label}
              </Button>
            );
          })}
          {/* Dopisek dopiero na szerokim ekranie — na laptopie pasek ma zostać jednym rzędem. */}
          <span className="hidden text-xs text-muted-foreground 2xl:inline">
            albo wpisz ręcznie — odczyt wypełnia tylko puste pola.
          </span>
        </div>
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

      {open ? (
        <div
          id={ids.panel}
          data-testid="new-job-source-panel"
          className="flex flex-col gap-3 border-t border-border pt-3"
        >
          {open === "text" ? (
            <div className="flex flex-col gap-2">
              <label htmlFor={ids.text} className="text-sm font-medium text-foreground">
                Treść requestu
              </label>
              <Textarea
                id={ids.text}
                value={text}
                onChange={(e) => onTextChange(e.target.value)}
                rows={6}
                disabled={reading}
                className="min-h-[9rem] font-normal leading-relaxed"
                placeholder="Wklej treść maila od klienta — stanowisko, wymagania, stawka, tryb pracy…"
              />
            </div>
          ) : open === "file" ? (
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
                hint="Zapytanie klienta albo Profil Championa: .docx, .pdf, .txt, do 10 MB."
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
            templatePicker
          )}

          {error ? (
            <div
              role="alert"
              className="rounded-lg border border-destructive/20 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              {error}
            </div>
          ) : null}

          <div className="flex flex-wrap items-center justify-end gap-3">
            {open === "text" && !textReady ? (
              <span className="text-xs text-muted-foreground">
                Wklej treść requestu (co najmniej {MIN_REQUEST_CHARS} znaków).
              </span>
            ) : null}
            {open === "file" && !file ? (
              <span className="text-xs text-muted-foreground">Wybierz plik z requestem.</span>
            ) : null}
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={reading}
              onClick={() => onPanelChange(null)}
            >
              Zamknij
            </Button>
            {open !== "template" ? (
              <Button
                type="button"
                size="sm"
                onClick={() => onRead(open)}
                disabled={reading || disabled || (open === "file" ? !file : !textReady)}
                loading={reading}
              >
                {!reading && <Sparkles className="h-3.5 w-3.5" aria-hidden />}
                {reading ? "Czytam request…" : "Odczytaj"}
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
