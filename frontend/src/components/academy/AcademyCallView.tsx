"use client";

/**
 * Akademia — tryb dzwonienia (wariant B z makiet 24.09.2026): jedna osoba
 * naraz. Rekruter pyta o warunki z ogłoszenia, zapisuje na termin w biurze
 * i przechodzi dalej. Skróty: T — umów, N — nie pasuje, O — nie odebrał,
 * ↓/↑ — następna/poprzednia osoba (wyłączone, gdy kursor jest w polu).
 */

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { callQueue, freeSeats, sessionLabel, shortDate } from "@/lib/academy-flow";
import type {
  AcademyApplication,
  AcademyProgram,
  AcademySessionRow,
} from "@/lib/api/academy";

import {
  ExperienceChip,
  ReasonsList,
  RejectPicker,
  SessionsNotice,
  VerdictBadge,
  sessionsUnavailable,
  type ActFn,
  type SessionsLoadState,
} from "./AcademyShared";

type Answer = "yes" | "no" | null;

export function AcademyCallView({
  program,
  apps,
  bookable,
  onAct,
  busyIds,
  sessionsState,
}: {
  program: AcademyProgram;
  apps: readonly AcademyApplication[];
  bookable: readonly AcademySessionRow[];
  onAct: ActFn;
  busyIds: ReadonlySet<number>;
  sessionsState?: SessionsLoadState | null;
}) {
  const queue = React.useMemo(() => callQueue(apps), [apps]);
  const [currentId, setCurrentId] = React.useState<number | null>(null);
  const current = queue.find((a) => a.id === currentId) ?? queue[0] ?? null;
  const index = current ? queue.indexOf(current) : -1;

  const [answers, setAnswers] = React.useState<Answer[]>([]);
  const [sessionId, setSessionId] = React.useState<number | null>(null);
  const [rejecting, setRejecting] = React.useState(false);

  // Nowa osoba = czyste odpowiedzi; domyślny termin = pierwszy z wolnym miejscem.
  const firstFree = bookable.find((s) => freeSeats(s) > 0)?.id ?? null;
  React.useEffect(() => {
    setAnswers(program.conditions.map(() => null));
    setRejecting(false);
    setSessionId(firstFree);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.id, program.conditions.length]);

  const conditionsOk =
    program.conditions.length === 0 || answers.every((a) => a === "yes");
  const anyNo = answers.some((a) => a === "no");
  const busy = current ? busyIds.has(current.id) : false;
  const done = apps.filter((a) => a.status === "scheduled").length;

  const goNext = React.useCallback(() => {
    if (index >= 0 && index + 1 < queue.length) setCurrentId(queue[index + 1].id);
  }, [index, queue]);

  const schedule = React.useCallback(async () => {
    if (!current || sessionId === null || !conditionsOk) return;
    const nextId = queue[index + 1]?.id ?? null;
    const ok = await onAct(current, { action: "schedule", session_id: sessionId });
    if (ok) setCurrentId(nextId);
  }, [current, sessionId, conditionsOk, onAct, queue, index]);

  const noAnswer = React.useCallback(async () => {
    if (!current) return;
    const nextId = queue[index + 1]?.id ?? null;
    const ok = await onAct(current, { action: "no_answer" });
    if (ok) setCurrentId(nextId);
  }, [current, onAct, queue, index]);

  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        !current ||
        busy ||
        event.metaKey ||
        event.ctrlKey ||
        event.altKey ||
        target?.closest("input, textarea, select, [contenteditable='true'], [role='dialog']")
      ) {
        return;
      }
      const key = event.key.toLowerCase();
      if (key === "t") {
        event.preventDefault();
        void schedule();
      } else if (key === "n") {
        event.preventDefault();
        setRejecting(true);
      } else if (key === "o") {
        event.preventDefault();
        void noAnswer();
      } else if (event.key === "ArrowDown") {
        event.preventDefault();
        goNext();
      } else if (event.key === "ArrowUp" && index > 0) {
        event.preventDefault();
        setCurrentId(queue[index - 1].id);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [current, busy, schedule, noAnswer, goNext, index, queue]);

  if (!current) {
    return (
      <div className="rounded-xl border border-border bg-card p-10 text-center">
        <p className="text-base font-medium">Kolejka telefonów jest pusta.</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Nowe zgłoszenia z ogłoszeń pojawią się tu po posortowaniu przez Lunę.
        </p>
      </div>
    );
  }

  const selected = bookable.find((s) => s.id === sessionId) ?? null;

  return (
    <div className="flex flex-col gap-4 lg:flex-row">
      <aside className="w-full shrink-0 space-y-3 rounded-xl border border-border bg-card p-4 lg:w-72">
        <div>
          <h2 className="text-sm font-semibold">Kolejka telefonów</h2>
          <p className="text-xs text-muted-foreground">
            {queue.length} do telefonu · {done} umówionych
          </p>
        </div>
        <ol className="max-h-36 space-y-1 overflow-y-auto lg:max-h-[60vh]" aria-label="Kolejka">
          {queue.map((app) => (
            <li key={app.id}>
              <button
                type="button"
                onClick={() => setCurrentId(app.id)}
                aria-current={app.id === current.id ? "true" : undefined}
                className={`flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm ${
                  app.id === current.id ? "bg-primary/10 font-semibold text-foreground" : "hover:bg-muted"
                }`}
              >
                <span className="min-w-0 flex-1 truncate">{app.full_name}</span>
                {app.screening_verdict === "review" ? <Badge variant="warning" size="sm">decyzja</Badge> : null}
                {app.call_attempts ? <Badge variant="outline" size="sm">×{app.call_attempts}</Badge> : null}
              </button>
            </li>
          ))}
        </ol>
        <p className="text-xs text-muted-foreground">
          Skróty: T — umów · N — nie pasuje · O — nie odebrał · ↓ — następna osoba
        </p>
      </aside>

      <section className="min-w-0 flex-1 space-y-4">
        <div className="flex flex-wrap items-start gap-4 rounded-xl border border-border bg-card p-5">
          <div className="min-w-0 flex-1 space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-2xl font-semibold">{current.full_name}</h2>
              <VerdictBadge app={current} />
            </div>
            <p className="text-sm text-muted-foreground">
              Zgłoszenie {shortDate(current.applied_at)}
              {current.source_job_title ? ` · ${current.source_job_title}` : ""}
              {current.city ? ` · ${current.city}` : ""}
            </p>
            <div className="flex flex-wrap gap-1">
              <ExperienceChip app={current} />
            </div>
            <ReasonsList app={current} />
          </div>
          <div className="flex flex-col items-end gap-2">
            {current.phone ? (
              <a
                href={`tel:${current.phone}`}
                className="text-2xl font-medium tabular-nums text-primary underline-offset-4 hover:underline"
              >
                {current.phone}
              </a>
            ) : (
              <span className="text-sm text-muted-foreground">Brak telefonu w profilu</span>
            )}
            <div className="flex gap-2">
              <Button asChild variant="outline" size="sm">
                <a href={`/candidates/${current.candidate_id}`} target="_blank" rel="noreferrer">
                  Pokaż CV
                </a>
              </Button>
              <Button variant="outline" size="sm" disabled={busy} onClick={() => void noAnswer()}>
                Nie odebrał
              </Button>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <section className="space-y-3 rounded-xl border border-border bg-card p-5">
            <h3 className="text-base font-semibold">1. Warunki z ogłoszenia</h3>
            {program.conditions.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Program nie ma pytań na telefon — dodaj je w Ustawieniach.
              </p>
            ) : (
              program.conditions.map((question, i) => (
                <fieldset key={question} className="flex items-center gap-3 rounded-lg border border-border px-4 py-3">
                  <legend className="sr-only">{question}</legend>
                  <span className="min-w-0 flex-1 text-sm">{question}</span>
                  {(["yes", "no"] as const).map((value) => (
                    <Button
                      key={value}
                      size="sm"
                      variant={answers[i] === value ? (value === "yes" ? "primary" : "destructive") : "outline"}
                      aria-pressed={answers[i] === value}
                      onClick={() =>
                        setAnswers((prev) => prev.map((a, j) => (j === i ? value : a)))
                      }
                    >
                      {value === "yes" ? "Tak" : "Nie"}
                    </Button>
                  ))}
                </fieldset>
              ))
            )}
          </section>
          <section className="space-y-3 rounded-xl border border-border bg-card p-5">
            <h3 className="text-base font-semibold">2. Termin spotkania w biurze</h3>
            {sessionsUnavailable(sessionsState) ? (
              <SessionsNotice state={sessionsState} />
            ) : bookable.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Nie ma przyszłych terminów — dodaj rytm w zakładce „Spotkania”.
              </p>
            ) : (
              <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Termin">
                {bookable.slice(0, 8).map((s) => {
                  const free = freeSeats(s);
                  const on = s.id === sessionId;
                  return (
                    <button
                      key={s.id}
                      type="button"
                      role="radio"
                      aria-checked={on}
                      disabled={free === 0}
                      onClick={() => setSessionId(s.id)}
                      className={`flex min-w-36 flex-col items-start rounded-lg border px-3 py-2 text-left text-sm disabled:opacity-50 ${
                        on ? "border-2 border-primary bg-primary/10" : "border-border bg-card hover:bg-muted"
                      }`}
                    >
                      <span className="font-semibold">{sessionLabel(s.starts_at)}</span>
                      <span className="text-xs text-muted-foreground">
                        {free === 0 ? "pełny" : `${free} wolne miejsca`}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </section>
        </div>

        {rejecting ? (
          <RejectPicker
            busy={busy}
            onCancel={() => setRejecting(false)}
            onConfirm={async (reason) => {
              const nextId = queue[index + 1]?.id ?? null;
              const ok = await onAct(current, { action: "reject", reason });
              if (ok) setCurrentId(nextId);
            }}
          />
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <Button
              size="lg"
              disabled={busy || !conditionsOk || selected === null}
              onClick={() => void schedule()}
            >
              {selected ? `Umów na ${sessionLabel(selected.starts_at)} i dalej →` : "Wybierz termin"}
            </Button>
            <Button size="lg" variant="outline" disabled={busy} onClick={() => setRejecting(true)}>
              Nie pasuje — wyklucz na stałe
            </Button>
            {anyNo ? (
              <span className="text-sm text-muted-foreground">
                Któryś warunek nie pasuje — zapisz powód przyciskiem obok.
              </span>
            ) : !conditionsOk ? (
              <span className="text-sm text-muted-foreground">Odpowiedz na pytania, żeby umówić.</span>
            ) : null}
          </div>
        )}
      </section>
    </div>
  );
}
