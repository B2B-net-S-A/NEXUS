"use client";

/**
 * Akademia — widok edycji (wariant C z makiet 24.09.2026): kafle lejka,
 * odłożeni przez Lunę do zatwierdzenia, sześć kolumn etapów i terminy
 * w biurze w tym tygodniu. Klik w kartę otwiera panel osoby z akcjami.
 */

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  EDITION_COLUMNS,
  STATUS_LABELS,
  awaitingLuna,
  byStatus,
  editionStats,
  freeSeats,
  lunaSkipped,
  sessionLabel,
  shortDate,
  taskOverdue,
} from "@/lib/academy-flow";
import type {
  AcademyApplication,
  AcademyProgram,
  AcademySessionRow,
  ActionBody,
} from "@/lib/api/academy";

import {
  ExperienceChip,
  PersonActions,
  ReasonsList,
  StatusLine,
  VerdictBadge,
  type ActFn,
  type DocumentsSupport,
} from "./AcademyShared";

const CARDS_PER_COLUMN = 30;

export function AcademyEditionView({
  program,
  apps,
  sessions,
  bookable,
  onAct,
  onBulk,
  busyIds,
  now,
  documents,
}: {
  program: AcademyProgram;
  apps: readonly AcademyApplication[];
  sessions: readonly AcademySessionRow[];
  bookable: readonly AcademySessionRow[];
  onAct: ActFn;
  onBulk: (ids: number[], body: ActionBody) => Promise<void>;
  busyIds: ReadonlySet<number>;
  now: Date;
  documents?: DocumentsSupport;
}) {
  const [openId, setOpenId] = React.useState<number | null>(null);
  const groups = React.useMemo(() => byStatus(apps), [apps]);
  const stats = React.useMemo(() => editionStats(apps), [apps]);
  const skipped = React.useMemo(() => lunaSkipped(apps), [apps]);
  const pendingLuna = awaitingLuna(apps);
  const open = apps.find((a) => a.id === openId) ?? null;
  const weekSessions = React.useMemo(() => {
    const end = now.getTime() + 7 * 24 * 3600 * 1000;
    return sessions.filter((s) => {
      const t = new Date(s.starts_at).getTime();
      return !s.cancelled && t >= now.getTime() - 12 * 3600 * 1000 && t <= end;
    });
  }, [sessions, now]);

  return (
    <div className="space-y-5">
      <dl className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Z ogłoszeń" value={stats.fromAds} hint={pendingLuna ? `${pendingLuna} czeka na Lunę` : undefined} />
        <Stat label="Do telefonu" value={stats.toCall} hint={stats.review ? `${stats.review} do decyzji` : undefined} />
        <Stat label="Umówieni w biurze" value={stats.scheduled} />
        <Stat label="Zadanie wydane" value={stats.tasks} />
        <Stat label="Zaliczyli / umowa" value={stats.passed} />
        <Stat label="Podpisali" value={stats.signed} hint={stats.excluded ? `${stats.excluded} wykluczonych` : undefined} />
      </dl>

      {skipped.length > 0 ? (
        <LunaSkippedBanner
          apps={skipped}
          maxYears={program.max_experience_years}
          onBulk={onBulk}
          onAct={onAct}
          busyIds={busyIds}
        />
      ) : null}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {EDITION_COLUMNS.map((status) => {
          const items = groups[status];
          return (
            <section
              key={status}
              aria-label={STATUS_LABELS[status]}
              className="flex min-w-0 flex-col gap-2 rounded-xl bg-muted/60 p-2"
            >
              <header className="flex items-center justify-between px-1 py-1 text-sm font-semibold">
                <span>{STATUS_LABELS[status]}</span>
                <Badge variant="outline">{items.length}</Badge>
              </header>
              {items.length === 0 ? (
                <p className="px-1 pb-2 text-xs text-muted-foreground">Nikogo na tym etapie.</p>
              ) : null}
              {items.slice(0, CARDS_PER_COLUMN).map((app) => (
                <button
                  key={app.id}
                  type="button"
                  onClick={() => setOpenId(app.id)}
                  className="flex flex-col items-start gap-1.5 rounded-lg border border-border bg-card px-3 py-2 text-left text-sm hover:border-primary/40 focus-visible:outline-2 focus-visible:outline-primary"
                >
                  <span className="font-medium">{app.full_name}</span>
                  <span className="flex flex-wrap gap-1">
                    <VerdictBadge app={app} />
                    <ExperienceChip app={app} />
                    {taskOverdue(app, now) ? <Badge variant="danger">po terminie</Badge> : null}
                  </span>
                  <StatusLine app={app} />
                </button>
              ))}
              {items.length > CARDS_PER_COLUMN ? (
                <p className="px-1 text-xs text-muted-foreground">
                  + {items.length - CARDS_PER_COLUMN} więcej
                </p>
              ) : null}
            </section>
          );
        })}
      </div>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold">Spotkania w biurze — najbliższe 7 dni</h2>
        {weekSessions.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Brak terminów w tym tygodniu. Dodaj rytm w zakładce „Spotkania”.
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            {weekSessions.map((s) => {
              const free = freeSeats(s);
              return (
                <div key={s.id} className="flex items-center justify-between rounded-lg border border-border bg-card px-4 py-3 text-sm">
                  <span className="font-medium">{sessionLabel(s.starts_at)}</span>
                  <Badge variant={free === 0 ? "danger" : free <= 2 ? "warning" : "success"}>
                    {s.taken}/{s.capacity}
                  </Badge>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <Sheet open={open !== null} onOpenChange={(o) => !o && setOpenId(null)}>
        <SheetContent side="right" size="md">
          {open ? (
            <PersonPanel
              app={open}
              bookable={bookable}
              onAct={onAct}
              busy={busyIds.has(open.id)}
              taskDueDays={program.task_due_days}
              documents={documents}
            />
          ) : null}
        </SheetContent>
      </Sheet>
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: number; hint?: string }) {
  return (
    <div className="rounded-lg border border-border bg-card px-4 py-3">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-2xl font-semibold tabular-nums">{value}</dd>
      {hint ? <dd className="text-xs text-muted-foreground">{hint}</dd> : null}
    </div>
  );
}

function LunaSkippedBanner({
  apps,
  maxYears,
  onBulk,
  onAct,
  busyIds,
}: {
  apps: readonly AcademyApplication[];
  maxYears: number;
  onBulk: (ids: number[], body: ActionBody) => Promise<void>;
  onAct: ActFn;
  busyIds: ReadonlySet<number>;
}) {
  const [expanded, setExpanded] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  return (
    <section className="rounded-xl border border-warning/30 bg-warning-muted/50 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold">Luna odłożyła {apps.length} os.</h2>
          <p className="text-xs text-muted-foreground">
            Doświadczenie ponad {maxYears} lat albo polski poniżej biegłego. Luna nikogo nie
            odrzuca — zatwierdź albo zadzwoń mimo to.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => setExpanded((v) => !v)}>
          {expanded ? "Zwiń" : "Pokaż listę"}
        </Button>
        <Button
          variant="destructive"
          size="sm"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await onBulk(
                apps.map((a) => a.id),
                { action: "reject" },
              );
            } finally {
              setBusy(false);
            }
          }}
        >
          Zatwierdź — wyklucz wszystkich ({apps.length})
        </Button>
      </div>
      {expanded ? (
        <ul className="mt-3 divide-y divide-border rounded-lg border border-border bg-card">
          {apps.map((app) => (
            <li key={app.id} className="flex flex-wrap items-start gap-3 px-3 py-2">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{app.full_name}</p>
                <ReasonsList app={app} />
              </div>
              <Button
                size="sm"
                variant="outline"
                disabled={busyIds.has(app.id)}
                onClick={() => void onAct(app, { action: "call" })}
              >
                Dzwonimy mimo to
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

export function PersonPanel({
  app,
  bookable,
  onAct,
  busy,
  taskDueDays,
  documents,
}: {
  app: AcademyApplication;
  bookable: readonly AcademySessionRow[];
  onAct: ActFn;
  busy?: boolean;
  taskDueDays: number;
  documents?: DocumentsSupport;
}) {
  return (
    <>
      <SheetHeader>
        <SheetTitle>{app.full_name}</SheetTitle>
        <SheetDescription>
          {STATUS_LABELS[app.status]} · zgłoszenie {shortDate(app.applied_at)}
          {app.source_job_title ? ` · ${app.source_job_title}` : ""}
        </SheetDescription>
      </SheetHeader>
      <SheetBody className="space-y-5">
        <div className="flex flex-wrap gap-2 text-sm">
          {app.phone ? (
            <a className="font-medium text-primary underline-offset-4 hover:underline" href={`tel:${app.phone}`}>
              {app.phone}
            </a>
          ) : (
            <span className="text-muted-foreground">brak telefonu</span>
          )}
          {app.email ? <span className="text-muted-foreground">· {app.email}</span> : null}
          <a
            className="text-primary underline-offset-4 hover:underline"
            href={`/candidates/${app.candidate_id}`}
          >
            Profil i CV
          </a>
        </div>
        <div className="flex flex-wrap gap-1">
          <VerdictBadge app={app} />
          <ExperienceChip app={app} />
          <StatusLine app={app} />
        </div>
        <ReasonsList app={app} />
        {app.closed_reason ? (
          <p className="rounded-md bg-muted px-3 py-2 text-sm">
            Powód: <span className="font-medium">{app.closed_reason}</span>
            {app.reapplied_at ? ` · aplikował ponownie ${shortDate(app.reapplied_at)}` : ""}
          </p>
        ) : null}
        <PersonActions
          key={`${app.id}-${app.status}`}
          app={app}
          sessions={bookable}
          onAct={onAct}
          busy={busy}
          taskDueDays={taskDueDays}
          documents={documents}
        />
        <NoteField app={app} onAct={onAct} />
      </SheetBody>
    </>
  );
}

function NoteField({ app, onAct }: { app: AcademyApplication; onAct: ActFn }) {
  const [value, setValue] = React.useState(app.note ?? "");
  const id = React.useId();
  const dirty = value !== (app.note ?? "");
  return (
    <div className="space-y-2">
      <label htmlFor={id} className="text-xs font-medium text-muted-foreground">
        Notatka
      </label>
      <textarea
        id={id}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        maxLength={2000}
        rows={3}
        className="w-full rounded-md border border-border bg-card px-3 py-2 text-sm"
      />
      {dirty ? (
        <Button size="sm" variant="outline" onClick={() => void onAct(app, { action: "note", note: value })}>
          Zapisz notatkę
        </Button>
      ) : null}
    </div>
  );
}
