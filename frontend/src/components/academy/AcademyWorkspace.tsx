"use client";

/**
 * Akademia — ekran jednego programu (prezentacja). Zakładki: Edycja (C),
 * Dzwonienie (B), Spotkania, Wykluczeni, Ustawienia. Dane i akcje przychodzą
 * w propsach: kontener (`AcademyScreen`) woła API, harness `/preview/academy`
 * zmienia stan lokalnie.
 */

import * as React from "react";

import { TabbedNav } from "@/components/ds/TabbedNav";
import { PageHeader } from "@/components/ds/PageHeader";
import { Button } from "@/components/ui/button";
import {
  bookableSessions,
  callQueue,
  cohortLabel,
  nextCohort,
  shortDate,
  toIsoDate,
  truncatedListNote,
} from "@/lib/academy-flow";
import type {
  AcademyApplication,
  AcademyCounts,
  AcademyProgramDetail,
  AcademySessionRow,
  ActionBody,
  DocumentsBody,
  JobOption,
  ProgramInput,
  RhythmInput,
} from "@/lib/api/academy";

import { AcademyCallView } from "./AcademyCallView";
import { AcademyEditionView } from "./AcademyEditionView";
import { AcademyExcludedView } from "./AcademyExcludedView";
import { AcademySessionsView } from "./AcademySessionsView";
import { AcademySettingsView } from "./AcademySettingsView";
import type { ActFn, SessionsLoadState } from "./AcademyShared";

export type AcademyView = "edition" | "calls" | "sessions" | "excluded" | "settings";

export const ACADEMY_VIEWS: readonly AcademyView[] = [
  "edition",
  "calls",
  "sessions",
  "excluded",
  "settings",
];

export interface AcademyHandlers {
  act: ActFn;
  bulk: (ids: number[], body: ActionBody) => Promise<void>;
  sync: () => Promise<void>;
  rhythm: (input: RhythmInput) => Promise<void>;
  createSession: (startsAtIso: string, location: string | null) => Promise<void>;
  cancelSession: (id: number) => Promise<void>;
  saveProgram: (patch: Partial<ProgramInput>) => Promise<void>;
  addSource: (jobId: number, since: string | null) => Promise<void>;
  removeSource: (jobId: number) => Promise<void>;
  searchJobs: (q: string) => Promise<JobOption[]>;
  downloadDocuments: (app: AcademyApplication, body: DocumentsBody) => Promise<boolean>;
}

export function AcademyWorkspace({
  program,
  apps,
  sessions,
  view,
  onViewChange,
  handlers,
  busyIds,
  syncing,
  now = new Date(),
  currentUserName = "",
  counts,
  total,
  sessionsState,
}: {
  program: AcademyProgramDetail;
  apps: readonly AcademyApplication[];
  sessions: readonly AcademySessionRow[];
  view: AcademyView;
  onViewChange: (view: AcademyView) => void;
  handlers: AcademyHandlers;
  busyIds: ReadonlySet<number>;
  syncing: boolean;
  now?: Date;
  currentUserName?: string;
  /** Liczniki z serwera (lista zgłoszeń ma limit). */
  counts?: AcademyCounts | null;
  /** Wszystkich zgłoszeń pasujących do listy — gdy więcej niż `apps`, lista jest przycięta. */
  total?: number | null;
  /** Stan zapytania o terminy — wczytywanie/błąd to nie „brak terminów”. */
  sessionsState?: SessionsLoadState | null;
}) {
  const bookable = React.useMemo(() => bookableSessions(sessions, now), [sessions, now]);
  const documents = {
    cohort: program.next_cohort,
    defaultHandoverName: currentUserName,
    onDownload: handlers.downloadDocuments,
  };
  const cohortRange = program.next_cohort
    ? ` (${shortDate(program.next_cohort.start)}–${shortDate(program.next_cohort.end)})`
    : "";
  const queueSize = callQueue(apps).length;
  const excluded =
    typeof counts?.rejected === "number"
      ? counts.rejected
      : apps.filter((a) => a.status === "rejected").length;
  const listNote = truncatedListNote(apps.length, total);
  const upcoming = sessions.filter(
    (s) => !s.cancelled && new Date(s.starts_at).getTime() > now.getTime(),
  ).length;

  const tabs = [
    { value: "edition", label: "Edycja" },
    { value: "calls", label: "Dzwonienie", count: queueSize },
    { value: "sessions", label: "Spotkania", count: upcoming },
    { value: "excluded", label: "Wykluczeni", count: excluded },
    { value: "settings", label: "Ustawienia" },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        breadcrumb={[{ label: "Akademia", href: "/academy" }, { label: program.name }]}
        title={program.name}
        description={`Najbliższa edycja: ${cohortLabel(
          program.next_cohort?.month ?? toIsoDate(nextCohort(now)),
        )}${cohortRange} · ${
          program.sources.length
        } ogłosz. · ${program.is_active ? "nabór aktywny" : "nabór wstrzymany"}`}
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" disabled={syncing} onClick={() => void handlers.sync()}>
              {syncing ? "Pobieram…" : "Pobierz zgłoszenia teraz"}
            </Button>
            <Button onClick={() => onViewChange("calls")} disabled={queueSize === 0}>
              Tryb dzwonienia ({queueSize})
            </Button>
          </div>
        }
      />
      <TabbedNav
        tabs={tabs}
        value={view}
        onValueChange={(v) => onViewChange(v as AcademyView)}
        ariaLabel="Widoki akademii"
      />
      {listNote && view !== "settings" ? (
        <p className="rounded-lg border border-border bg-muted/60 px-4 py-2 text-xs text-muted-foreground">
          {listNote}
        </p>
      ) : null}
      {program.sources.length === 0 && view !== "settings" ? (
        <div className="rounded-lg border border-warning/30 bg-warning-muted/50 px-4 py-3 text-sm">
          Nie podpięto jeszcze ogłoszeń — nikt nie wpadnie do naboru.{" "}
          <button
            type="button"
            className="font-medium text-primary underline-offset-4 hover:underline"
            onClick={() => onViewChange("settings")}
          >
            Podepnij ogłoszenia w Ustawieniach
          </button>
        </div>
      ) : null}

      {view === "edition" ? (
        <AcademyEditionView
          program={program}
          apps={apps}
          sessions={sessions}
          bookable={bookable}
          onAct={handlers.act}
          onBulk={handlers.bulk}
          busyIds={busyIds}
          now={now}
          documents={documents}
          counts={counts}
          sessionsState={sessionsState}
        />
      ) : null}
      {view === "calls" ? (
        <AcademyCallView
          program={program}
          apps={apps}
          bookable={bookable}
          onAct={handlers.act}
          busyIds={busyIds}
          sessionsState={sessionsState}
        />
      ) : null}
      {view === "sessions" ? (
        <AcademySessionsView
          program={program}
          apps={apps}
          sessions={sessions}
          bookable={bookable}
          onAct={handlers.act}
          onRhythm={handlers.rhythm}
          onCreateSession={handlers.createSession}
          onCancelSession={handlers.cancelSession}
          busyIds={busyIds}
          now={now}
          documents={documents}
          sessionsState={sessionsState}
        />
      ) : null}
      {view === "excluded" ? (
        <AcademyExcludedView apps={apps} onAct={handlers.act} busyIds={busyIds} />
      ) : null}
      {view === "settings" ? (
        <AcademySettingsView
          key={program.id}
          program={program}
          onSave={handlers.saveProgram}
          onAddSource={handlers.addSource}
          onRemoveSource={handlers.removeSource}
          searchJobs={handlers.searchJobs}
        />
      ) : null}
    </div>
  );
}
