"use client";

/**
 * Akademia — spotkania w biurze: terminy (stały rytm albo pojedynczy),
 * lista obecności, wydanie zadania obecnym, wynik zadania i umowa.
 * Ekran wspólny dla wariantów z makiet 24.09.2026.
 */

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  RHYTHM_DAYS,
  attendeesOf,
  freeSeats,
  sessionLabel,
  shortDate,
  toIsoDate,
} from "@/lib/academy-flow";
import type {
  AcademyApplication,
  AcademyProgram,
  AcademySessionRow,
  RhythmInput,
} from "@/lib/api/academy";

import {
  PersonActions,
  SessionsNotice,
  sessionsUnavailable,
  type ActFn,
  type DocumentsSupport,
  type SessionsLoadState,
} from "./AcademyShared";

export function AcademySessionsView({
  program,
  apps,
  sessions,
  bookable,
  onAct,
  onRhythm,
  onCreateSession,
  onCancelSession,
  busyIds,
  now,
  documents,
  sessionsState,
}: {
  program: AcademyProgram;
  apps: readonly AcademyApplication[];
  sessions: readonly AcademySessionRow[];
  bookable: readonly AcademySessionRow[];
  onAct: ActFn;
  onRhythm: (input: RhythmInput) => Promise<void>;
  onCreateSession: (startsAtIso: string, location: string | null) => Promise<void>;
  onCancelSession: (id: number) => Promise<void>;
  busyIds: ReadonlySet<number>;
  now: Date;
  documents?: DocumentsSupport;
  sessionsState?: SessionsLoadState | null;
}) {
  const visible = sessions.filter((s) => !s.cancelled);
  const defaultId =
    visible.find((s) => new Date(s.starts_at).getTime() >= now.getTime() - 6 * 3600 * 1000)?.id ??
    visible[visible.length - 1]?.id ??
    null;
  const [pickedId, setSelectedId] = React.useState<number | null>(null);
  // Terminy przychodzą asynchronicznie — bez wyboru pokazujemy najbliższy.
  const selectedId = pickedId ?? defaultId;
  const selected = visible.find((s) => s.id === selectedId) ?? null;
  const attendees = selected ? attendeesOf(apps, selected.id) : [];
  const toTask = attendees.filter((a) => a.status === "scheduled" && a.attended !== false);

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[22rem_minmax(0,1fr)]">
      <div className="space-y-4">
        <section className="space-y-2 rounded-xl border border-border bg-card p-4">
          <h2 className="text-sm font-semibold">Terminy</h2>
          {sessionsUnavailable(sessionsState) ? (
            <SessionsNotice state={sessionsState} />
          ) : visible.length === 0 ? (
            <p className="text-sm text-muted-foreground">Nie ma jeszcze terminów — dodaj rytm poniżej.</p>
          ) : (
            <ul className="space-y-1">
              {visible.map((s) => {
                const free = freeSeats(s);
                const past = new Date(s.starts_at).getTime() < now.getTime();
                return (
                  <li key={s.id} className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setSelectedId(s.id)}
                      aria-current={s.id === selectedId ? "true" : undefined}
                      className={`flex flex-1 items-center justify-between rounded-md px-3 py-2 text-left text-sm ${
                        s.id === selectedId ? "bg-primary/10 font-semibold" : "hover:bg-muted"
                      } ${past ? "text-muted-foreground" : ""}`}
                    >
                      <span>{sessionLabel(s.starts_at)}</span>
                      <Badge variant={free === 0 ? "danger" : free <= 2 ? "warning" : "success"}>
                        {s.taken}/{s.capacity}
                      </Badge>
                    </button>
                    {!past && s.people === 0 ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Odwołaj termin ${sessionLabel(s.starts_at)}`}
                        onClick={() => void onCancelSession(s.id)}
                      >
                        Odwołaj
                      </Button>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          )}
        </section>
        <RhythmForm program={program} onRhythm={onRhythm} />
        <SingleSessionForm onCreate={onCreateSession} />
      </div>

      <section className="min-w-0 space-y-3 rounded-xl border border-border bg-card p-4">
        {selected ? (
          <>
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="text-lg font-semibold">
                Spotkanie {sessionLabel(selected.starts_at)} — {attendees.length} os.
              </h2>
              {selected.location ? <span className="text-sm text-muted-foreground">{selected.location}</span> : null}
              {toTask.length > 1 ? (
                <Button
                  size="sm"
                  className="ml-auto"
                  onClick={async () => {
                    for (const app of toTask) await onAct(app, { action: "give_task" });
                  }}
                >
                  Wydaj zadanie wszystkim obecnym ({toTask.length})
                </Button>
              ) : null}
            </div>
            {attendees.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nikt nie jest zapisany na ten termin.</p>
            ) : (
              <ul className="divide-y divide-border">
                {attendees.map((app) => (
                  <li key={app.id} className="flex flex-col gap-2 py-3 lg:flex-row lg:items-start">
                    <div className="w-56 shrink-0">
                      <a
                        className="font-medium text-foreground underline-offset-4 hover:underline"
                        href={`/candidates/${app.candidate_id}`}
                      >
                        {app.full_name}
                      </a>
                      <p className="text-xs text-muted-foreground">
                        {app.phone ?? "brak telefonu"}
                        {app.status === "task_given" ? ` · oddaje do ${shortDate(app.task_due)}` : ""}
                        {app.attended === false ? " · nie przyszedł" : ""}
                      </p>
                    </div>
                    <div className="min-w-0 flex-1">
                      <PersonActions
                        key={`${app.id}-${app.status}`}
                        app={app}
                        sessions={bookable}
                        onAct={onAct}
                        busy={busyIds.has(app.id)}
                        taskDueDays={program.task_due_days}
                        documents={documents}
                      />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </>
        ) : (
          <p className="text-sm text-muted-foreground">Wybierz termin z listy.</p>
        )}
      </section>
    </div>
  );
}

function RhythmForm({
  program,
  onRhythm,
}: {
  program: AcademyProgram;
  onRhythm: (input: RhythmInput) => Promise<void>;
}) {
  const [days, setDays] = React.useState<number[]>([0, 2, 3]);
  const [time, setTime] = React.useState("10:00");
  const [weeks, setWeeks] = React.useState(2);
  const [location, setLocation] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const timeId = React.useId();
  const weeksId = React.useId();
  const locId = React.useId();
  return (
    <section className="space-y-3 rounded-xl border border-border bg-card p-4">
      <h2 className="text-sm font-semibold">Stały rytm spotkań</h2>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Dni tygodnia">
        {RHYTHM_DAYS.map((d) => {
          const on = days.includes(d.value);
          return (
            <button
              key={d.value}
              type="button"
              aria-pressed={on}
              onClick={() =>
                setDays((prev) => (on ? prev.filter((x) => x !== d.value) : [...prev, d.value]))
              }
              className={`h-9 min-w-11 rounded-md border px-2 text-sm ${
                on ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card hover:bg-muted"
              }`}
            >
              {d.label}
            </button>
          );
        })}
      </div>
      <div className="grid grid-cols-2 gap-2">
        <label htmlFor={timeId} className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
          Godzina
          <input
            id={timeId}
            type="time"
            value={time}
            onChange={(e) => setTime(e.target.value)}
            className="rounded-md border border-border bg-card px-2 py-2 text-sm text-foreground"
          />
        </label>
        <label htmlFor={weeksId} className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
          Na ile tygodni
          <select
            id={weeksId}
            value={weeks}
            onChange={(e) => setWeeks(Number(e.target.value))}
            className="rounded-md border border-border bg-card px-2 py-2 text-sm text-foreground"
          >
            {[1, 2, 3, 4, 6, 8].map((w) => (
              <option key={w} value={w}>
                {w}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label htmlFor={locId} className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
        Miejsce (opcjonalnie)
        <input
          id={locId}
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          placeholder="np. biuro, sala 2"
          className="rounded-md border border-border bg-card px-2 py-2 text-sm text-foreground"
        />
      </label>
      <Button
        size="sm"
        disabled={busy || days.length === 0}
        onClick={async () => {
          setBusy(true);
          try {
            await onRhythm({
              weekdays: days,
              time,
              weeks,
              location: location.trim() || null,
              capacity: program.session_capacity,
            });
          } finally {
            setBusy(false);
          }
        }}
      >
        Dodaj terminy (do {program.session_capacity} os. każdy)
      </Button>
    </section>
  );
}

function SingleSessionForm({
  onCreate,
}: {
  onCreate: (startsAtIso: string, location: string | null) => Promise<void>;
}) {
  const [date, setDate] = React.useState(toIsoDate(new Date()));
  const [time, setTime] = React.useState("10:00");
  const dateId = React.useId();
  const timeId = React.useId();
  return (
    <section className="space-y-3 rounded-xl border border-border bg-card p-4">
      <h2 className="text-sm font-semibold">Pojedynczy termin</h2>
      <div className="grid grid-cols-2 gap-2">
        <label htmlFor={dateId} className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
          Dzień
          <input
            id={dateId}
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="rounded-md border border-border bg-card px-2 py-2 text-sm text-foreground"
          />
        </label>
        <label htmlFor={timeId} className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
          Godzina
          <input
            id={timeId}
            type="time"
            value={time}
            onChange={(e) => setTime(e.target.value)}
            className="rounded-md border border-border bg-card px-2 py-2 text-sm text-foreground"
          />
        </label>
      </div>
      <Button
        size="sm"
        variant="outline"
        disabled={!date || !time}
        onClick={() => void onCreate(new Date(`${date}T${time}:00`).toISOString(), null)}
      >
        Dodaj termin
      </Button>
    </section>
  );
}
