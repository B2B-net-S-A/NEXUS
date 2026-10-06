"use client";

/**
 * Karta z notatki rekrutera (0421, decyzje D1–D5 z 06.10.2026) — części okna
 * „Karta rekomendacji”:
 *
 * - `NoteSourceTiles` — „Wgraj notatkę” / „Wklej tekst” / „Wpisz ręcznie”,
 * - `NoteSourceInput` — plik albo tekst + „Odczytaj notatkę”,
 * - `RecommendationCardNoteReview` — „obecnie → propozycja” z zaznaczeniem.
 *
 * Wszystkie są prezentacyjne (harness `/preview/recommendation-card?state=import`
 * renderuje je bez zapytań); stan i zapytania trzyma `RecommendationCardDialog`.
 */

import { useRef } from "react";
import {
  AlertTriangle,
  ClipboardPaste,
  FileUp,
  Loader2,
  PencilLine,
} from "lucide-react";

import { FileDropZone } from "@/components/ds/FileDropZone";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Textarea } from "@/components/ui/textarea";
import type { NoteProposal } from "@/lib/api/recommendationCards";
import {
  type NoteReviewState,
  answerOrigin,
  rateChangeWarning,
} from "@/lib/recommendation-card-note";
import { cn } from "@/lib/utils";

export type NoteSource = "file" | "text" | "manual";

export const NOTE_FILE_ACCEPT = ".docx,.pdf,.txt";
export const NOTE_FILE_MAX_BYTES = 5 * 1024 * 1024;

const SOURCES = [
  {
    value: "file" as const,
    title: "Wgraj notatkę",
    description: "Word, PDF albo TXT — do 5 MB",
    icon: FileUp,
  },
  {
    value: "text" as const,
    title: "Wklej tekst",
    description: "Notatka z Teams, maila albo telefonu",
    icon: ClipboardPaste,
  },
  {
    value: "manual" as const,
    title: "Wpisz ręcznie",
    description: "Pola karty jak dotychczas",
    icon: PencilLine,
  },
];

export function NoteSourceTiles({
  value,
  onChange,
  disabled,
}: {
  value: NoteSource;
  onChange: (source: NoteSource) => void;
  disabled?: boolean;
}) {
  const tiles = useRef<(HTMLButtonElement | null)[]>([]);
  const move = (from: number, step: 1 | -1) => {
    const next = (from + step + SOURCES.length) % SOURCES.length;
    tiles.current[next]?.focus();
    onChange(SOURCES[next].value);
  };
  return (
    <div
      role="radiogroup"
      aria-label="Jak wypełnić kartę"
      className="grid gap-2 @lg:grid-cols-3"
    >
      {SOURCES.map((option, index) => {
        const checked = option.value === value;
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
            disabled={disabled}
            onClick={() => onChange(option.value)}
            onKeyDown={(event) => {
              if (
                event.altKey ||
                event.ctrlKey ||
                event.metaKey ||
                event.shiftKey
              )
                return;
              if (event.key === "ArrowRight" || event.key === "ArrowDown") {
                event.preventDefault();
                move(index, 1);
              } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
                event.preventDefault();
                move(index, -1);
              }
            }}
            className={cn(
              "flex min-w-0 items-start gap-2.5 rounded-lg border p-3 text-left transition-colors disabled:opacity-60",
              checked
                ? "border-primary bg-primary/5 ring-1 ring-primary"
                : "border-border bg-card hover:border-primary/40 hover:bg-accent",
            )}
          >
            <span
              className={cn(
                "flex size-8 shrink-0 items-center justify-center rounded-md",
                checked
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground",
              )}
            >
              <Icon className="size-4" aria-hidden />
            </span>
            <span className="min-w-0">
              <span className="block text-sm font-semibold text-foreground">
                {option.title}
              </span>
              <span className="block text-xs leading-snug text-muted-foreground">
                {option.description}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

export function NoteSourceInput({
  source,
  file,
  onFileChange,
  text,
  onTextChange,
  fileError,
  onFileError,
  reading,
  blockedReason,
  onRead,
}: {
  source: "file" | "text";
  file: File | null;
  onFileChange: (file: File | null) => void;
  text: string;
  onTextChange: (text: string) => void;
  fileError: string | null;
  onFileError: (message: string | null) => void;
  reading: boolean;
  /** Powód, dla którego odczyt jest zablokowany (niezapisane zmiany). */
  blockedReason?: string | null;
  onRead: () => void;
}) {
  const ready = source === "file" ? file != null : text.trim().length >= 30;
  return (
    <div className="space-y-3">
      {source === "file" ? (
        <FileDropZone
          inputId="card-note-file"
          file={file}
          onPick={(next) => {
            onFileError(null);
            onFileChange(next);
          }}
          accept={NOTE_FILE_ACCEPT}
          maxBytes={NOTE_FILE_MAX_BYTES}
          label="Notatka z rozmowy"
          hint="Przeciągnij plik albo wybierz z dysku. Pliku nie zapisujemy — tylko jego tekst trafi do historii kandydata."
          error={fileError}
          onError={onFileError}
          disabled={reading}
        />
      ) : (
        <div className="space-y-1">
          <label
            htmlFor="card-note-text"
            className="text-xs font-medium text-foreground"
          >
            Notatka z rozmowy
          </label>
          <Textarea
            id="card-note-text"
            rows={8}
            value={text}
            disabled={reading}
            placeholder="Wklej notatkę — może być hasłami: stawka, dostępność, tryb pracy, odpowiedzi na pytania…"
            onChange={(event) => onTextChange(event.target.value)}
          />
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        NEXUS wypełni tylko te pola i odpowiedzi, które znajdzie w notatce.
        Przed zapisem zobaczysz każdą zmianę. Narodowość odczytujemy wyłącznie
        ze wzoru działu — nie wysyłamy jej do AI.
      </p>
      {blockedReason ? (
        <p
          role="status"
          className="rounded-md bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground"
        >
          {blockedReason}
        </p>
      ) : null}
      <Button
        type="button"
        onClick={onRead}
        disabled={!ready || reading || Boolean(blockedReason)}
      >
        {reading ? (
          <Loader2 className="size-3.5 animate-spin" aria-hidden />
        ) : null}
        {reading ? "Czytam notatkę…" : "Odczytaj notatkę"}
      </Button>
    </div>
  );
}

const ORIGIN_LABEL: Record<"note_ai" | "note_rule", string> = {
  note_ai: "AI",
  note_rule: "wzór działu",
};

export function RecommendationCardNoteReview({
  proposal,
  state,
  onChange,
  sourceLabel,
}: {
  proposal: NoteProposal;
  state: NoteReviewState;
  onChange: (state: NoteReviewState) => void;
  /** Nazwa pliku albo „wklejony tekst”. */
  sourceLabel: string;
}) {
  const toggleField = (key: string, checked: boolean) =>
    onChange({ ...state, fields: { ...state.fields, [key]: checked } });
  const setAnswer = (
    qid: string,
    patch: Partial<NoteReviewState["answers"][string]>,
  ) =>
    onChange({
      ...state,
      answers: { ...state.answers, [qid]: { ...state.answers[qid], ...patch } },
    });
  const nothing = !proposal.fields.length && !proposal.answers.length;
  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">
        Z {sourceLabel}: {proposal.fields.length} pól i{" "}
        {proposal.answers.length} odpowiedzi. Zaznacz, co trafi do karty.
      </p>
      {proposal.message ? (
        <p
          role="status"
          className="rounded-md bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground"
        >
          {proposal.message}
        </p>
      ) : null}

      {proposal.fields.length ? (
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[34rem] border-collapse text-xs">
            <caption className="sr-only">Pola karty z notatki</caption>
            <thead>
              <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                <th scope="col" className="w-8 py-2 pr-2">
                  <span className="sr-only">Przyjmij</span>
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  Pole
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  Obecnie
                </th>
                <th scope="col" className="py-2 font-medium">
                  Propozycja z notatki
                </th>
              </tr>
            </thead>
            <tbody>
              {proposal.fields.map((field) => {
                const id = `note-field-${field.key}`;
                return (
                  <tr
                    key={field.key}
                    className="border-b border-border align-top last:border-0"
                  >
                    <td className="py-2.5 pr-2">
                      <Checkbox
                        id={id}
                        checked={Boolean(state.fields[field.key])}
                        onCheckedChange={(value) =>
                          toggleField(field.key, value === true)
                        }
                      />
                    </td>
                    <td className="py-2.5 pr-3 font-medium text-foreground">
                      <label htmlFor={id}>{field.label}</label>
                    </td>
                    <td className="py-2.5 pr-3 text-muted-foreground">
                      {field.current ?? "—"}
                    </td>
                    <td className="py-2.5">
                      <span className="whitespace-pre-line font-medium text-foreground">
                        {field.proposed}
                      </span>{" "}
                      <span
                        className={cn(
                          "ml-1 inline-flex rounded-full px-1.5 py-px text-[10.5px] font-semibold",
                          !field.changed
                            ? "bg-muted text-muted-foreground"
                            : field.current
                              ? "bg-warning-muted text-warning-muted-foreground"
                              : "bg-primary/10 text-primary",
                        )}
                      >
                        {!field.changed
                          ? "bez zmian"
                          : field.current
                            ? "zmiana"
                            : ORIGIN_LABEL[field.origin]}
                      </span>
                      {field.quote ? (
                        <span className="mt-1 block font-mono text-[11px] text-muted-foreground">
                          „{field.quote}”
                        </span>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}

      {rateChangeWarning(proposal, state) ? (
        <p
          role="status"
          className="flex gap-2 rounded-md bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground"
        >
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span>
            <strong className="font-semibold">Zmiana stawki.</strong> Kandydat
            jest już na etapie od „Zweryfikowany”, więc nowa stawka otworzy
            sprawę „zmiana stawki” — Delivery Lead dostanie powiadomienie, tak
            jak przy ręcznej zmianie.
          </span>
        </p>
      ) : null}

      {proposal.answers.length ? (
        <section
          aria-label="Odpowiedzi na pytania z Profilu Championa"
          className="space-y-2"
        >
          <h3 className="text-xs font-semibold text-foreground">
            Odpowiedzi na pytania z Profilu Championa
          </h3>
          {proposal.answers.map((answer) => {
            const choice = state.answers[answer.question_id];
            const id = `note-answer-${answer.question_id}`;
            const phrased =
              choice != null &&
              answerOrigin(choice.response, answer.sentence) === "phrased";
            return (
              <div
                key={answer.question_id}
                className="space-y-2 rounded-md border border-border p-3 text-xs"
              >
                <div className="flex items-start gap-2">
                  <Checkbox
                    id={`${id}-pick`}
                    checked={Boolean(choice?.selected)}
                    onCheckedChange={(value) =>
                      setAnswer(answer.question_id, {
                        selected: value === true,
                      })
                    }
                  />
                  <label
                    htmlFor={`${id}-pick`}
                    className="min-w-0 flex-1 font-medium text-foreground"
                  >
                    {answer.number}. {answer.question}
                  </label>
                  <span className="shrink-0 rounded-full bg-primary/10 px-1.5 py-px text-[10.5px] font-semibold text-primary">
                    {phrased ? "zdanie z haseł" : "z notatki"}
                  </span>
                </div>
                {answer.current ? (
                  <p className="text-muted-foreground">
                    Obecnie w arkuszu: {answer.current}
                  </p>
                ) : null}
                <p className="rounded bg-muted/60 px-2 py-1.5 font-mono text-[11px] text-foreground">
                  {answer.keywords}
                </p>
                {answer.problem ? (
                  <p
                    role="status"
                    className="text-[11px] text-warning-muted-foreground"
                  >
                    Luna dopisała coś, czego nie ma w notatce („{answer.problem}
                    ”) — zdania nie wstawiamy. Zostaw hasła albo popraw
                    odpowiedź.
                  </p>
                ) : null}
                <label htmlFor={id} className="sr-only">
                  Odpowiedź do arkusza — pytanie {answer.number}
                </label>
                <Textarea
                  id={id}
                  rows={3}
                  value={choice?.response ?? ""}
                  onChange={(event) =>
                    setAnswer(answer.question_id, {
                      response: event.target.value,
                    })
                  }
                />
                {answer.sentence ? (
                  <div className="flex flex-wrap gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant={phrased ? "primary" : "outline"}
                      onClick={() =>
                        setAnswer(answer.question_id, {
                          response: answer.sentence ?? "",
                        })
                      }
                    >
                      Zdanie
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant={phrased ? "outline" : "primary"}
                      onClick={() =>
                        setAnswer(answer.question_id, {
                          response: answer.keywords,
                        })
                      }
                    >
                      Hasła
                    </Button>
                  </div>
                ) : null}
              </div>
            );
          })}
        </section>
      ) : null}

      {nothing ? null : (
        <p className="text-[11px] text-muted-foreground">
          Tekst notatki trafi do historii kandydata. Pola przyjęte z notatki
          mają plakietkę — Delivery Lead zobaczy, skąd pochodzą.
        </p>
      )}
    </div>
  );
}
