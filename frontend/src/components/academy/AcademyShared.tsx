"use client";

/**
 * Akademia — wspólne klocki widoków: werdykt Luny, powody, wybór powodu
 * wykluczenia i przyciski akcji zależne od etapu. Wyłącznie prezentacja —
 * akcje przychodzą w `onAct` (kontener woła API, harness zmienia stan lokalnie).
 */

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  REJECT_REASONS,
  VERDICT_LABELS,
  cohortLabel,
  freeSeats,
  nextCohort,
  sessionLabel,
  shortDate,
  toIsoDate,
} from "@/lib/academy-flow";
import type {
  AcademyApplication,
  AcademySessionRow,
  ActionBody,
  CohortDates,
  DocumentsBody,
} from "@/lib/api/academy";

import { AcademyDocumentsDialog } from "./AcademyDocumentsDialog";

export type ActFn = (app: AcademyApplication, body: ActionBody) => Promise<boolean>;

/**
 * Stan zapytania o terminy w biurze. Wczytywanie i błąd NIE mogą wyglądać jak
 * „nie ma terminów” — dzwoniący dodałby wtedy rytm drugi raz.
 */
export interface SessionsLoadState {
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}

/** Komunikat zamiast listy terminów; `null`, gdy terminy są wczytane. */
export function SessionsNotice({ state }: { state?: SessionsLoadState | null }) {
  if (!state) return null;
  if (state.error) {
    return (
      <div role="alert" className="flex flex-wrap items-center gap-2 text-sm text-danger">
        <span>Nie udało się wczytać terminów w biurze: {state.error}</span>
        <Button size="sm" variant="outline" onClick={state.onRetry}>
          Ponów
        </Button>
      </div>
    );
  }
  if (state.loading) {
    return <p className="text-sm text-muted-foreground">Wczytuję terminy…</p>;
  }
  return null;
}

/** Czy terminy są niedostępne (wczytywanie albo błąd). */
export function sessionsUnavailable(state?: SessionsLoadState | null): boolean {
  return !!state && (state.loading || !!state.error);
}

/** Generowanie kompletu dokumentów uczestnika (umowa, regulamin…). */
export interface DocumentsSupport {
  cohort: CohortDates | null | undefined;
  defaultHandoverName: string;
  onDownload: (app: AcademyApplication, body: DocumentsBody) => Promise<boolean>;
}

export function VerdictBadge({ app }: { app: AcademyApplication }) {
  if (app.status !== "new" && app.status !== "to_call") return null;
  if (app.screening_verdict === null) {
    return <Badge variant="outline">Luna czyta CV…</Badge>;
  }
  const variant =
    app.screening_verdict === "call"
      ? "success"
      : app.screening_verdict === "review"
        ? "warning"
        : "danger";
  return <Badge variant={variant}>{VERDICT_LABELS[app.screening_verdict]}</Badge>;
}

export function ExperienceChip({ app }: { app: AcademyApplication }) {
  const years = app.experience_years;
  if (years === null || years === undefined) return null;
  const label = Number.isInteger(years) ? String(years) : String(years).replace(".", ",");
  const basis = app.screening_facts?.experience_basis;
  const suffix =
    basis === "after_studies"
      ? " po studiach"
      : app.screening_facts?.still_studying
        ? ", studiuje"
        : "";
  return (
    <Badge variant="outline">
      {label} l. pracy{suffix}
    </Badge>
  );
}

export function ReasonsList({ app }: { app: AcademyApplication }) {
  if (!app.screening_reasons?.length) return null;
  return (
    <ul className="space-y-1 text-sm">
      {app.screening_reasons.map((reason, i) => (
        <li key={`${reason.code}-${i}`} className="text-muted-foreground">
          <span className="text-foreground">{reason.text}</span>
          {reason.quote ? (
            <span className="ml-1 italic">„{reason.quote}”</span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

/** Wybór powodu wykluczenia — zapisywany na stałe, więc zawsze jawny. */
export function RejectPicker({
  onConfirm,
  onCancel,
  busy,
  confirmLabel = "Wyklucz na stałe",
}: {
  onConfirm: (reason: string) => void;
  onCancel: () => void;
  busy?: boolean;
  confirmLabel?: string;
}) {
  const [reason, setReason] = React.useState("");
  const id = React.useId();
  return (
    <div className="space-y-3 rounded-lg border border-destructive/30 bg-destructive-muted/40 p-3">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Gotowe powody">
        {REJECT_REASONS.map((preset) => (
          <button
            key={preset}
            type="button"
            onClick={() => setReason(preset)}
            className={`rounded-full border px-3 py-1 text-xs ${
              reason === preset
                ? "border-destructive bg-destructive text-destructive-foreground"
                : "border-border bg-card text-foreground hover:bg-muted"
            }`}
          >
            {preset}
          </button>
        ))}
      </div>
      <label htmlFor={id} className="block text-xs font-medium text-muted-foreground">
        Powód (zostanie zapamiętany — ta osoba nie wróci w kolejnych edycjach)
      </label>
      <input
        id={id}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        className="w-full rounded-md border border-border bg-card px-3 py-2 text-sm"
        placeholder="np. szuka pracy zdalnej"
        maxLength={500}
      />
      <div className="flex gap-2">
        <Button
          variant="destructive"
          size="sm"
          disabled={!reason.trim() || busy}
          onClick={() => onConfirm(reason.trim())}
        >
          {confirmLabel}
        </Button>
        <Button variant="ghost" size="sm" onClick={onCancel}>
          Anuluj
        </Button>
      </div>
    </div>
  );
}

export function SessionSelect({
  sessions,
  value,
  onChange,
  currentId,
  label = "Termin spotkania",
}: {
  sessions: readonly AcademySessionRow[];
  value: number | null;
  onChange: (id: number | null) => void;
  currentId?: number | null;
  label?: string;
}) {
  const id = React.useId();
  return (
    <label htmlFor={id} className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
      {label}
      <select
        id={id}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
        className="rounded-md border border-border bg-card px-2 py-2 text-sm text-foreground"
      >
        <option value="">Wybierz termin…</option>
        {sessions.map((s) => {
          const free = freeSeats(s);
          const full = free === 0 && s.id !== currentId;
          return (
            <option key={s.id} value={s.id} disabled={full}>
              {sessionLabel(s.starts_at)} — {full ? "pełny" : `${free} wolne`}
            </option>
          );
        })}
      </select>
    </label>
  );
}

/** Przyciski akcji dla etapu osoby (panel osoby, widok spotkań). */
export function PersonActions({
  app,
  sessions,
  onAct,
  busy,
  taskDueDays = 5,
  documents,
}: {
  app: AcademyApplication;
  sessions: readonly AcademySessionRow[];
  onAct: ActFn;
  busy?: boolean;
  taskDueDays?: number;
  documents?: DocumentsSupport;
}) {
  const [rejecting, setRejecting] = React.useState(false);
  const [docsOpen, setDocsOpen] = React.useState(false);
  const [sessionId, setSessionId] = React.useState<number | null>(app.session_id);
  const [cohort, setCohort] = React.useState(
    app.cohort_month ?? toIsoDate(nextCohort(new Date())),
  );
  const run = (body: ActionBody) => void onAct(app, body);

  // Edycja inna niż najbliższa: daty liczy serwer z miesiąca edycji osoby.
  const cohortForDocs =
    documents && (!app.cohort_month || app.cohort_month === documents.cohort?.month)
      ? documents.cohort
      : null;
  const documentsButton = documents ? (
    <>
      <Button variant="outline" size="sm" disabled={busy} onClick={() => setDocsOpen(true)}>
        Dokumenty uczestnika…
      </Button>
      {docsOpen ? (
        <AcademyDocumentsDialog
          app={app}
          open={docsOpen}
          onOpenChange={setDocsOpen}
          cohort={cohortForDocs}
          defaultHandoverName={documents.defaultHandoverName}
          onDownload={documents.onDownload}
          onMarkSent={() => run({ action: "contract_sent" })}
        />
      ) : null}
    </>
  ) : null;

  if (rejecting) {
    return (
      <RejectPicker
        busy={busy}
        onCancel={() => setRejecting(false)}
        onConfirm={(reason) => {
          setRejecting(false);
          run({
            action: app.status === "task_given" ? "task_failed" : "reject",
            reason,
          });
        }}
      />
    );
  }

  const withdraw = (
    <Button
      variant="ghost"
      size="sm"
      disabled={busy}
      onClick={() => run({ action: "withdraw", reason: "Zrezygnował sam" })}
    >
      Zrezygnował sam
    </Button>
  );
  const reject = (
    <Button variant="outline" size="sm" disabled={busy} onClick={() => setRejecting(true)}>
      Wyklucz…
    </Button>
  );

  switch (app.status) {
    case "new":
      return (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" disabled={busy} onClick={() => run({ action: "call" })}>
            Dzwonimy
          </Button>
          {reject}
        </div>
      );
    case "to_call":
    case "scheduled":
      return (
        <div className="space-y-3">
          <div className="flex flex-wrap items-end gap-2">
            <SessionSelect
              sessions={sessions}
              value={sessionId}
              onChange={setSessionId}
              currentId={app.session_id}
            />
            <Button
              size="sm"
              disabled={busy || sessionId === null || sessionId === app.session_id}
              onClick={() => run({ action: "schedule", session_id: sessionId })}
            >
              {app.status === "scheduled" ? "Przenieś" : "Umów"}
            </Button>
          </div>
          <div className="flex flex-wrap gap-2">
            {app.status === "to_call" ? (
              <Button
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() => run({ action: "no_answer" })}
              >
                Nie odebrał ({app.call_attempts})
              </Button>
            ) : (
              <>
                <Button size="sm" disabled={busy} onClick={() => run({ action: "give_task" })}>
                  Przyszedł — wydaj zadanie ({taskDueDays} dni)
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={busy}
                  onClick={() => run({ action: "absent" })}
                >
                  Nie przyszedł
                </Button>
              </>
            )}
            {reject}
            {withdraw}
          </div>
        </div>
      );
    case "task_given":
      return (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" disabled={busy} onClick={() => run({ action: "task_passed" })}>
            Zaliczył zadanie
          </Button>
          <Button variant="outline" size="sm" disabled={busy} onClick={() => setRejecting(true)}>
            Nie zaliczył…
          </Button>
          {withdraw}
        </div>
      );
    case "task_passed":
    case "contract_sent":
      return (
        <div className="flex flex-wrap items-end gap-2">
          {documentsButton}
          {app.status === "task_passed" ? (
            <Button
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={() => run({ action: "contract_sent" })}
            >
              Umowa wysłana
            </Button>
          ) : null}
          <CohortInput value={cohort} onChange={setCohort} />
          <Button
            size="sm"
            disabled={busy}
            onClick={() => run({ action: "signed", cohort_month: cohort })}
          >
            Podpisał — edycja {cohortLabel(cohort)}
          </Button>
          {withdraw}
        </div>
      );
    case "signed":
      return (
        <div className="flex flex-wrap items-end gap-2">
          {documentsButton}
          <CohortInput value={cohort} onChange={setCohort} />
          <Button
            variant="outline"
            size="sm"
            disabled={busy || cohort === app.cohort_month}
            onClick={() => run({ action: "move_cohort", cohort_month: cohort })}
          >
            Zmień edycję
          </Button>
        </div>
      );
    case "rejected":
    case "withdrew":
      return (
        <Button variant="outline" size="sm" disabled={busy} onClick={() => run({ action: "restore" })}>
          Przywróć do telefonów
        </Button>
      );
    default:
      return null;
  }
}

function CohortInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const id = React.useId();
  const months = React.useMemo(() => {
    const now = new Date();
    return [0, 1, 2, 3].map((i) =>
      toIsoDate(new Date(now.getFullYear(), now.getMonth() + i, 1)),
    );
  }, []);
  return (
    <label htmlFor={id} className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
      Edycja
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-border bg-card px-2 py-2 text-sm text-foreground"
      >
        {(months.includes(value) ? months : [value, ...months]).map((m) => (
          <option key={m} value={m}>
            {cohortLabel(m)}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Jedna linia stanu osoby pod nazwiskiem (etap-zależna). */
export function StatusLine({ app }: { app: AcademyApplication }) {
  const parts: string[] = [];
  switch (app.status) {
    case "to_call":
      if (app.call_attempts) parts.push(`nie odebrał ×${app.call_attempts}`);
      break;
    case "scheduled":
      parts.push(sessionLabel(app.session_starts_at));
      if (app.attended === false) parts.push("nie przyszedł");
      break;
    case "task_given":
      parts.push(`oddaje do ${shortDate(app.task_due)}`);
      break;
    case "contract_sent":
      parts.push(`umowa wysłana ${shortDate(app.contract_sent_at)}`);
      break;
    case "signed":
      parts.push(`edycja ${cohortLabel(app.cohort_month)}`);
      break;
    default:
      break;
  }
  return parts.length ? <span className="text-xs text-muted-foreground">{parts.join(" · ")}</span> : null;
}
