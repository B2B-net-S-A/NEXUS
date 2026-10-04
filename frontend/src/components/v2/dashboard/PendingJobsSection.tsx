"use client";

/**
 * „Rekrutacje do dokończenia albo zamknięcia” na pulpicie (Rekrutacja bez
 * szkiców). Od tej zmiany rekrutacja nie bywa szkicem: `/jobs/new` zakłada,
 * przekazuje i publikuje w jednym kroku, a niedokończona praca to formularz
 * zapisany na koncie. Zostają dwie zaległości sprzed zmiany:
 *  - stare szkice — system zamknie je sam od dnia `autoclose_on` (nic nie
 *    jest kasowane, rekrutację da się otworzyć ponownie),
 *  - rekrutacje opublikowane, których nikt nie przekazał do searchu.
 *
 * Wiersze przychodzą z `GET /api/board-tasks` (`pending_jobs`,
 * `unfinished_forms`): Delivery Lead widzi swoje, Head of Recruitment i admin
 * — wszystkie. Lista nie liczy się do „Czeka na Ciebie” — wzór
 * `NewJobLeadsSection`: obok zadań stoi w panelu, a gdy nic nie czeka — sama,
 * we własnej ramce.
 */

import Link from "next/link";
import { Fragment, useState } from "react";

import { Button } from "@/components/ui/button";
import type { PendingJobRow, PendingJobs, UnfinishedJobForm } from "@/lib/api/boardTasks";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";
import { warsawDateOf, warsawToday } from "@/lib/warsaw-date";

export const PENDING_JOBS_TITLE = "Rekrutacje do dokończenia albo zamknięcia";
export const UNFINISHED_FORMS_TITLE = "Niedokończone formularze nowej rekrutacji";

/** Tyle rekrutacji widać, zanim trzeba kliknąć „Pokaż wszystkie”. */
export const PENDING_JOBS_ROWS = 6;

/** Tyle braków wypisujemy w wierszu; reszta jako „i N więcej” (pełna lista w dymku). */
const MISSING_SHOWN = 3;

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

/** „RRRR-MM-DD” → „DD.MM” bez przeliczania strefy (sama data z serwera). */
export function shortDay(day: string): string | null {
  const match = DATE_ONLY.exec(day.trim());
  return match ? `${match[3]}.${match[2]}` : null;
}

function dayNumber(day: string): number {
  return Date.parse(`${day}T00:00:00Z`) / 86_400_000;
}

/** Dni kalendarzowe (Europe/Warsaw) od `from` do `to`; `null` = data nieczytelna. */
export function daysBetween(from: string | null | undefined, to: string): number | null {
  const start = warsawDateOf(from);
  if (!start) return null;
  return Math.round(dayNumber(to) - dayNumber(start));
}

/** „Szkic od 12 dni · zamknięcie za 3 dni” / „W pracy bez przekazania”. */
export function pendingJobState(
  row: PendingJobRow,
  autocloseOn: string | null,
  now: Date = new Date(),
): string {
  if (row.kind === "published_not_handed_off") return "W pracy bez przekazania";
  const today = warsawToday(now);
  const age = daysBetween(row.created_at, today);
  const parts: string[] = [];
  if (age === null || age <= 0) parts.push("Szkic od dziś");
  else if (age === 1) parts.push("Szkic od wczoraj");
  else parts.push(`Szkic od ${age} dni`);
  if (autocloseOn && DATE_ONLY.test(autocloseOn)) {
    const left = Math.round(dayNumber(autocloseOn) - dayNumber(today));
    if (left <= 0) parts.push("zamknięcie dziś");
    else if (left === 1) parts.push("zamknięcie jutro");
    else parts.push(`zamknięcie za ${left} dni`);
  }
  return parts.join(" · ");
}

/** „brakuje: budżet · tryb pracy · i 2 więcej”; pusta lista = `null`. */
export function missingSummary(missing: string[]): string | null {
  const items = missing.map((item) => item.trim()).filter(Boolean);
  if (items.length === 0) return null;
  const shown = items.slice(0, MISSING_SHOWN);
  const rest = items.length - shown.length;
  return `brakuje: ${shown.join(" · ")}${rest > 0 ? ` · i ${rest} więcej` : ""}`;
}

export function pendingJobLinks(jobId: number) {
  return {
    // Strona rekrutacji otwiera okno publikacji (`JobReopenDialog`).
    finish: `/jobs/${jobId}?reopen=1`,
    // Stare wejście do zamknięcia (`win=order&wintab=close`) otwiera okno
    // „Zamknij rekrutację”, gdy osoba ma do tego prawo.
    close: `/jobs/${jobId}?win=order&wintab=close`,
    fill: `/jobs/${jobId}?tab=champion&mode=edit`,
  };
}

function formsLine(forms: UnfinishedJobForm[]): string {
  const count = countPl(
    forms.length,
    "niedokończony formularz",
    "niedokończone formularze",
    "niedokończonych formularzy",
  );
  return `Masz ${count} nowej rekrutacji`;
}

function formLabel(form: UnfinishedJobForm): string {
  const label = form.label.trim() || "Bez nazwy";
  return form.client_name ? `${label} · ${form.client_name}` : label;
}

export interface PendingJobsSectionProps {
  pending: PendingJobs | null | undefined;
  forms: UnfinishedJobForm[] | null | undefined;
  /** Panel „Czeka na Ciebie” nie ma nic do zrobienia — sekcja stoi sama. */
  standalone?: boolean;
}

/** Czy sekcja ma co pokazać — panel decyduje po tym, czy w ogóle się renderuje. */
export function hasPendingJobsContent(
  pending: PendingJobs | null | undefined,
  forms: UnfinishedJobForm[] | null | undefined,
): boolean {
  return (pending?.items.length ?? 0) > 0 || (forms?.length ?? 0) > 0;
}

export function PendingJobsSection({ pending, forms, standalone = false }: PendingJobsSectionProps) {
  const [expanded, setExpanded] = useState(false);
  const rows = pending?.items ?? [];
  const unfinished = forms ?? [];
  if (rows.length === 0 && unfinished.length === 0) return null;

  const autocloseOn = pending?.autoclose_on ?? null;
  const autocloseDay = autocloseOn ? shortDay(autocloseOn) : null;
  const hasDrafts = rows.some((row) => row.kind === "legacy_draft");
  const shown = expanded ? rows : rows.slice(0, PENDING_JOBS_ROWS);
  const title = rows.length > 0 ? PENDING_JOBS_TITLE : UNFINISHED_FORMS_TITLE;

  const section = (
    <section
      aria-label={title}
      className={cn("@container/pending min-w-0", !standalone && "lg:col-span-3")}
    >
      {rows.length > 0 ? (
        <>
          <header className="mb-1">
            {/* Liczba w nawiasie, bez plakietki zadania — lista nie liczy się
                do „Czeka na Ciebie”. */}
            <h3 className="text-sm font-semibold">
              {PENDING_JOBS_TITLE} <span className="tabular-nums">({rows.length})</span>
            </h3>
          </header>
          {autocloseDay && hasDrafts ? (
            <p className="mb-2 text-xs font-medium text-warning" data-testid="pending-autoclose">
              Od {autocloseDay} system zamknie szkice, których nikt nie dokończył. Dane zostają,
              rekrutację da się otworzyć ponownie.
            </p>
          ) : null}
          <ul className="divide-y divide-border rounded-lg border border-border">
            {shown.map((row) => {
              const links = pendingJobLinks(row.job_id);
              const missing = missingSummary(row.missing);
              return (
                <li
                  key={row.job_id}
                  // Opis i przyciski obok siebie dopiero od 640 px sekcji.
                  className="grid gap-x-4 gap-y-1.5 px-3 py-2.5 @min-[640px]/pending:grid-cols-[minmax(0,1fr)_auto] @min-[640px]/pending:items-center"
                >
                  <div className="min-w-0">
                    <p className="min-w-0 truncate text-sm">
                      <Link
                        href={`/jobs/${row.job_id}`}
                        title={row.title}
                        className="font-medium hover:underline"
                      >
                        {row.title}
                      </Link>
                      {row.client_name ? (
                        <span className="text-muted-foreground"> · {row.client_name}</span>
                      ) : null}
                    </p>
                    <p className="text-xs text-muted-foreground" data-testid="pending-job-meta">
                      <span
                        className={cn(row.kind === "legacy_draft" && "font-medium text-foreground")}
                      >
                        {pendingJobState(row, autocloseOn)}
                      </span>
                      {missing ? (
                        <Fragment>
                          <span aria-hidden> · </span>
                          <span title={row.missing.join("\n")}>{missing}</span>
                        </Fragment>
                      ) : null}
                      {row.delivery_lead_name ? (
                        <Fragment>
                          <span aria-hidden> · </span>
                          <span>DL: {row.delivery_lead_name}</span>
                        </Fragment>
                      ) : null}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5 @min-[640px]/pending:justify-end">
                    <Button asChild size="sm">
                      <Link href={links.finish} aria-label={`Dokończ: ${row.title}`}>
                        Dokończ
                      </Link>
                    </Button>
                    <Button asChild size="sm" variant="outline">
                      <Link href={links.fill} aria-label={`Uzupełnij: ${row.title}`}>
                        Uzupełnij
                      </Link>
                    </Button>
                    <Button asChild size="sm" variant="quiet">
                      <Link href={links.close} aria-label={`Zamknij: ${row.title}`}>
                        Zamknij
                      </Link>
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
          {rows.length > PENDING_JOBS_ROWS && (
            <button
              type="button"
              onClick={() => setExpanded((value) => !value)}
              aria-expanded={expanded}
              className="mt-1.5 text-xs font-medium text-primary hover:underline"
            >
              {expanded ? "Zwiń" : `Pokaż wszystkie (${rows.length})`}
            </button>
          )}
        </>
      ) : null}
      {unfinished.length > 0 ? (
        <div className={cn("text-xs", rows.length > 0 && "mt-2")} data-testid="unfinished-forms">
          <Link href="/jobs/new" className="font-medium text-primary hover:underline">
            {formsLine(unfinished)}
          </Link>
          {unfinished.length <= 3 ? (
            <span className="text-muted-foreground">
              {": "}
              {unfinished.map(formLabel).join(", ")}
            </span>
          ) : null}
        </div>
      ) : null}
    </section>
  );

  return standalone ? (
    <div className="rounded-xl border border-border bg-card p-4">{section}</div>
  ) : (
    section
  );
}
