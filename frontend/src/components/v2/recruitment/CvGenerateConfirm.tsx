"use client";

/**
 * Trzy potwierdzenia przed generacją CV w karcie „CV do klienta” (21.10.2026).
 *
 * Zgłoszenie zespołu: CV powstawało samo po ruchu na „Zweryfikowany”, zanim
 * rekruter dopisał, czego nie obejmowały pytania, i z pliku wybranego przez
 * system. Teraz rekruter widzi i potwierdza: plik CV, odpowiedzi ze screeningu
 * i dodatkowe notatki do CV — w dowolnej kolejności. Reguły w
 * `lib/cv-generate-confirm.ts`, stan trzyma `CvGeneratePanel`.
 */

import { useId, useState, type ReactNode } from "react";
import Link from "next/link";
import { Check } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { screeningQuestionLabel } from "@/components/v2/screening/ScreeningAnswersList";
import { useScreeningFormState } from "@/lib/api/screeningForm";
import type { CvAiSourceCount, CvAiSourceFile } from "@/lib/cv-ai-sources";
import {
  cvFileDetail,
  type CvConfirmations,
  type CvConfirmStep,
} from "@/lib/cv-generate-confirm";
import { screeningFormHref, screeningSummaryRows } from "@/lib/screening-summary";
import { cn } from "@/lib/utils";

const ANSWERS_PREVIEW = 4;

export interface CvGenerateConfirmProps {
  candidateId: number;
  jobId: number;
  /** Pliki do wyboru (`cvFileChoices`, a przy awarii źródeł — lista generatora). */
  files: readonly CvAiSourceFile[];
  /** Liczba odpowiedzi; `null` = nie udało się sprawdzić (awaria `…/ai-sources`). */
  answers: CvAiSourceCount | null;
  existingNotes: number;
  fileId: number | null;
  onFileChange: (documentId: number) => void;
  noteDraft: string;
  onNoteDraftChange: (value: string) => void;
  confirmed: CvConfirmations;
  onConfirm: (next: CvConfirmations) => void;
  left: readonly CvConfirmStep[];
  disabled?: boolean;
}

export function CvGenerateConfirm({
  candidateId,
  jobId,
  files,
  answers,
  existingNotes,
  fileId,
  onFileChange,
  noteDraft,
  onNoteDraftChange,
  confirmed,
  onConfirm,
  left,
  disabled = false,
}: CvGenerateConfirmProps) {
  const chosen = files.find((file) => file.document_id === fileId) ?? null;
  const fileDone = !left.includes("file");
  const answersDone = !left.includes("answers");
  const notesDone = !left.includes("notes");

  return (
    <div className="space-y-2" data-testid="cv-generate-confirm">
      <p className="text-xs text-muted-foreground">
        Sprawdź, z czego powstanie CV. Kolejność dowolna — „Generuj” odblokuje się po trzech potwierdzeniach.
      </p>

      <ConfirmStep
        number={1}
        title={fileDone && chosen ? `Plik CV: ${chosen.filename ?? "plik CV"}` : "Plik CV"}
        done={fileDone}
        summary={chosen ? cvFileDetail(chosen) : null}
        onReopen={() => onConfirm({ ...confirmed, file: null })}
        reopenLabel="Zmień plik"
        disabled={disabled}
        testId="cv-confirm-file"
      >
        {files.length === 0 ? (
          <p className="text-xs text-warning-muted-foreground">
            Osoba nie ma w profilu pliku PDF, DOC ani DOCX — wgraj CV w sekcji „CV”.
          </p>
        ) : (
          <fieldset className="space-y-1.5">
            <legend className="sr-only">Plik CV do generacji</legend>
            {files.map((file) => (
              <label
                key={file.document_id}
                className={cn(
                  "flex cursor-pointer items-start gap-2 rounded-lg border px-2.5 py-2 text-xs",
                  file.document_id === fileId ? "border-primary bg-primary/5" : "border-border bg-card",
                )}
              >
                <input
                  type="radio"
                  name={`cv-file-${jobId}-${candidateId}`}
                  className="mt-0.5 accent-primary"
                  checked={file.document_id === fileId}
                  onChange={() => onFileChange(file.document_id)}
                  disabled={disabled}
                />
                <span className="min-w-0">
                  <span className="block font-medium text-foreground [overflow-wrap:anywhere]">
                    {file.filename ?? "plik CV"}
                  </span>
                  <span className="block text-muted-foreground">{cvFileDetail(file)}</span>
                </span>
              </label>
            ))}
          </fieldset>
        )}
        <Button
          size="sm"
          onClick={() => onConfirm({ ...confirmed, file: fileId })}
          disabled={disabled || fileId == null}
        >
          Potwierdź plik
        </Button>
      </ConfirmStep>

      <ConfirmStep
        number={2}
        title={answersDone && answers ? `Odpowiedzi ze screeningu: ${answers.count}` : "Odpowiedzi ze screeningu"}
        done={answersDone}
        summary={
          answers == null
            ? "nie udało się sprawdzić, ile ich jest"
            : answers.excluded > 0
              ? `Przeczące pytaniu (${answers.excluded}) nie trafią do CV jako fakt`
              : answers.count === 0
                ? "brak odpowiedzi"
                : null
        }
        onReopen={() => onConfirm({ ...confirmed, answers: false })}
        reopenLabel="Zmień odpowiedzi"
        disabled={disabled}
        testId="cv-confirm-answers"
      >
        <AnswersPreview candidateId={candidateId} jobId={jobId} count={answers?.count ?? null} />
        <div className="flex flex-wrap gap-1.5">
          <Button size="sm" onClick={() => onConfirm({ ...confirmed, answers: true })} disabled={disabled}>
            {answers?.count === 0 ? "Potwierdź bez odpowiedzi" : "Potwierdź odpowiedzi"}
          </Button>
          <Button size="sm" variant="outline" asChild>
            <Link href={screeningFormHref(jobId, candidateId)}>Popraw w formularzu</Link>
          </Button>
        </div>
      </ConfirmStep>

      <NotesStep
        done={notesDone}
        noteDraft={noteDraft}
        onNoteDraftChange={onNoteDraftChange}
        existingNotes={existingNotes}
        onConfirm={() => onConfirm({ ...confirmed, notes: noteDraft.trim() })}
        onReopen={() => onConfirm({ ...confirmed, notes: null })}
        disabled={disabled}
      />
    </div>
  );
}

function ConfirmStep({
  number,
  title,
  done,
  summary,
  onReopen,
  reopenLabel,
  disabled,
  testId,
  children,
}: {
  number: number;
  title: string;
  done: boolean;
  summary: string | null;
  onReopen: () => void;
  reopenLabel: string;
  disabled: boolean;
  testId: string;
  children: ReactNode;
}) {
  return (
    <section
      aria-label={title}
      data-testid={testId}
      data-done={done ? "true" : "false"}
      className={cn("space-y-2 rounded-lg border p-2.5", done ? "border-border bg-card" : "border-primary/40 bg-card")}
    >
      <div className="flex items-start gap-2">
        <StepMark number={number} done={done} />
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold text-foreground [overflow-wrap:anywhere]">{title}</p>
          {summary ? <p className="text-[11px] text-muted-foreground">{summary}</p> : null}
        </div>
        {done ? (
          <button
            type="button"
            className="text-xs font-medium text-primary hover:underline disabled:opacity-60"
            onClick={onReopen}
            disabled={disabled}
            aria-label={reopenLabel}
          >
            Zmień
          </button>
        ) : null}
      </div>
      {done ? null : children}
    </section>
  );
}

function StepMark({ number, done }: { number: number; done: boolean }) {
  return done ? (
    <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-success text-success-foreground">
      <Check className="size-3" aria-hidden />
      <span className="sr-only">potwierdzone</span>
    </span>
  ) : (
    <span className="flex size-5 shrink-0 items-center justify-center rounded-full border-2 border-primary text-[11px] font-bold text-primary">
      {number}
    </span>
  );
}

/** „Ile lat z Javą?” zostaje bez dwukropka, „Dostępność” dostaje go. */
function questionWithColon(label: string): string {
  return /[?:.!]$/.test(label.trim()) ? label : `${label}:`;
}

/** Pierwsze odpowiedzi z formularza screeningu — treść, którą przeczyta model. */
function AnswersPreview({ candidateId, jobId, count }: { candidateId: number; jobId: number; count: number | null }) {
  const query = useScreeningFormState(candidateId, jobId, count !== 0);
  const [all, setAll] = useState(false);
  if (count === 0) {
    return <p className="text-xs text-muted-foreground">Formularz screeningu nie ma odpowiedzi na pytania.</p>;
  }
  if (query.isPending) return <p className="text-xs text-muted-foreground">Wczytuję odpowiedzi…</p>;
  if (query.isError) {
    // Awaria nie udaje braku odpowiedzi — liczba z serwera zostaje.
    return (
      <p role="alert" className="text-xs text-destructive-muted-foreground">
        Nie udało się wczytać odpowiedzi.{" "}
        <button type="button" className="font-medium underline" onClick={() => void query.refetch()}>
          Ponów
        </button>
      </p>
    );
  }
  const rows = screeningSummaryRows(query.data).filter((row) => (row.response ?? "").trim());
  const shown = all ? rows : rows.slice(0, ANSWERS_PREVIEW);
  return (
    <div className="space-y-1 rounded-md bg-muted/60 p-2 text-xs">
      <ul className="space-y-1">
        {shown.map((row, index) => (
          <li key={row.question_id} className="[overflow-wrap:anywhere]">
            <span className="text-muted-foreground">{questionWithColon(screeningQuestionLabel(row, index))}</span>{" "}
            <span className="text-foreground">{row.response}</span>
          </li>
        ))}
      </ul>
      {rows.length > ANSWERS_PREVIEW ? (
        <button
          type="button"
          aria-expanded={all}
          className="font-medium text-primary hover:underline"
          onClick={() => setAll((open) => !open)}
        >
          {all ? "Zwiń" : `+ ${rows.length - ANSWERS_PREVIEW} więcej`}
        </button>
      ) : null}
    </div>
  );
}

function NotesStep({
  done,
  noteDraft,
  onNoteDraftChange,
  existingNotes,
  onConfirm,
  onReopen,
  disabled,
}: {
  done: boolean;
  noteDraft: string;
  onNoteDraftChange: (value: string) => void;
  existingNotes: number;
  onConfirm: () => void;
  onReopen: () => void;
  disabled: boolean;
}) {
  const id = useId();
  const text = noteDraft.trim();
  return (
    <section
      aria-label="Dodatkowe notatki do CV"
      data-testid="cv-confirm-notes"
      data-done={done ? "true" : "false"}
      className={cn("space-y-2 rounded-lg border p-2.5", done ? "border-border bg-card" : "border-primary/40 bg-card")}
    >
      <div className="flex items-start gap-2">
        <StepMark number={3} done={done} />
        <div className="min-w-0 flex-1">
          <label htmlFor={id} className="text-xs font-semibold text-foreground">
            Dodatkowe notatki do CV
          </label>
          {done ? (
            <p className="text-[11px] text-muted-foreground [overflow-wrap:anywhere]">
              {text ? `„${text.length > 80 ? `${text.slice(0, 80)}…` : text}”` : "nic do dodania"}
            </p>
          ) : null}
        </div>
        {done ? (
          <button
            type="button"
            className="text-xs font-medium text-primary hover:underline disabled:opacity-60"
            onClick={onReopen}
            disabled={disabled}
            aria-label="Edytuj notatki"
          >
            Edytuj
          </button>
        ) : null}
      </div>
      {done ? null : (
        <>
          <Textarea
            id={id}
            rows={3}
            value={noteDraft}
            onChange={(event) => onNoteDraftChange(event.target.value)}
            placeholder="To, o co nie było pytania, np. „prowadził migrację Jenkinsa do GitHub Actions”"
            disabled={disabled}
          />
          <p className="text-[11px] text-muted-foreground">
            Zapiszemy ją jako notatkę w tej rekrutacji przed generacją.
            {existingNotes > 0 ? ` Notatki, które już są w rekrutacji (${existingNotes}), AI też przeczyta.` : ""}
          </p>
          <Button size="sm" variant={text ? "primary" : "outline"} onClick={onConfirm} disabled={disabled}>
            {text ? "Potwierdź notatki" : "Nie mam nic do dodania"}
          </Button>
        </>
      )}
    </section>
  );
}
