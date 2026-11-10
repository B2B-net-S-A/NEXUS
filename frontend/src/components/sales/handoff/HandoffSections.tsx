"use client";

import { useState } from "react";

import { TruncatedText } from "@/components/ds/TruncatedText";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Handoff, HandoffWeek } from "@/lib/api/sales-handoffs";
import { cn } from "@/lib/utils";

import { plural } from "../my-day";
import type { HandoffPanel } from "./HandoffCard";
import { bookerStatus, briefLine, handoffWhen, visibleWeeks, weekFunnel, weekLabel } from "./helpers";

const UNDATED_PREVIEW = 3;
const BOOKED_PREVIEW = 6;
const HEADER = "flex items-baseline justify-between gap-3 border-b border-border bg-muted/40 px-3 py-1";
const TITLE = "text-xs font-medium uppercase tracking-wide text-muted-foreground";

interface RowAction {
  label: string;
  primary: boolean;
  run: () => void;
}

type Open = (handoff: Handoff, panel: HandoffPanel) => void;

/** Co prowadzący ma teraz zrobić z przekazanym spotkaniem. */
function hostAction(handoff: Handoff, onOpen: Open): RowAction {
  switch (handoff.phase) {
    case "verdict":
      return { label: "Werdykt", primary: true, run: () => onOpen(handoff, "verdict") };
    case "confirm":
      return { label: "Potwierdź", primary: false, run: () => onOpen(handoff, null) };
    case "no_term":
      return { label: "Ustaw termin", primary: false, run: () => onOpen(handoff, "term") };
    default:
      return { label: "Otwórz", primary: false, run: () => onOpen(handoff, null) };
  }
}

interface RowProps {
  handoff: Handoff;
  viewer: "host" | "booker";
  active: boolean;
  action: RowAction | null;
  status?: string;
  onOpen: Open;
}

function HandoffRow({ handoff, viewer, active, action, status, onOpen }: RowProps) {
  return (
    <li className={cn("flex min-h-11 items-center gap-2 px-3 py-1", active && "bg-primary/5")}>
      <span className="w-28 shrink-0 text-xs tabular-nums text-muted-foreground">
        {handoffWhen(handoff.meeting_at)}
      </span>
      <button
        type="button"
        className="min-w-0 flex-1 text-left leading-tight"
        aria-current={active ? "true" : undefined}
        onClick={() => onOpen(handoff, null)}
      >
        <span className="block truncate text-sm font-medium text-foreground hover:underline">
          {handoff.company.name}
        </span>
        <TruncatedText className="block max-w-full text-xs text-muted-foreground">
          {briefLine(handoff, viewer)}
        </TruncatedText>
      </button>
      {handoff.clash && handoff.phase !== "done" && (
        <Badge variant="warning" size="sm" className="shrink-0">
          Kolizja
        </Badge>
      )}
      {handoff.confirmed_at && handoff.phase === "upcoming" && (
        <Badge variant="success" size="sm" className="shrink-0">
          Potwierdzone
        </Badge>
      )}
      {status && (
        <TruncatedText className="max-w-[13rem] shrink-0 text-xs text-muted-foreground">{status}</TruncatedText>
      )}
      {action && (
        <Button
          size="sm"
          variant={action.primary ? "primary" : "outline"}
          className="h-7 w-[104px] shrink-0 px-0"
          onClick={action.run}
        >
          {action.label}
        </Button>
      )}
    </li>
  );
}

interface SectionProps {
  rows: Handoff[];
  selectedId: number | null;
  canEdit: boolean;
  onOpen: Open;
}

/** „Przekazane do Ciebie”: umówione spotkania w kolejności terminów, osobno te bez terminu. */
export function HandedToMeSection({ rows, selectedId, canEdit, onOpen }: SectionProps) {
  const [allUndated, setAllUndated] = useState(false);
  if (rows.length === 0) return null;
  const dated = rows.filter((row) => row.meeting_at !== null);
  const undated = rows.filter((row) => row.meeting_at === null);
  const shown = allUndated ? undated : undated.slice(0, UNDATED_PREVIEW);
  const row = (handoff: Handoff) => (
    <HandoffRow
      key={handoff.opportunity.id}
      handoff={handoff}
      viewer="host"
      active={selectedId === handoff.opportunity.id}
      action={canEdit ? hostAction(handoff, onOpen) : null}
      onOpen={onOpen}
    />
  );
  return (
    <section data-testid="handed-to-me" data-tour="sales.handed-to-me">
      <header className={HEADER}>
        <h2 className={TITLE}>Przekazane do Ciebie</h2>
        <span className="text-xs text-muted-foreground">
          {dated.length} z terminem · {undated.length} bez terminu
        </span>
      </header>
      <ul className="divide-y divide-border border-b border-border">
        {dated.map(row)}
        {shown.map(row)}
        {undated.length > UNDATED_PREVIEW && (
          <li className="px-3 py-1.5 text-xs text-muted-foreground">
            {allUndated
              ? `Wszystkie spotkania bez terminu: ${undated.length}`
              : `Jeszcze ${plural(undated.length - UNDATED_PREVIEW, "spotkanie", "spotkania", "spotkań")} bez terminu`}
            {" · "}
            <button
              type="button"
              className="text-primary hover:underline"
              onClick={() => setAllUndated((value) => !value)}
            >
              {allUndated ? "Zwiń" : "Pokaż wszystkie"}
            </button>
          </li>
        )}
      </ul>
    </section>
  );
}

/** Liczby osoby, która umawia: tylko jej własne, bez celu i bez porównania z innymi. */
function Weeks({ weeks }: { weeks: HandoffWeek[] }) {
  const shown = visibleWeeks(weeks);
  if (shown.length === 0) return null;
  return (
    <p className="text-xs text-muted-foreground" data-testid="handoff-weeks">
      <span title="Umówione w tygodniu, a odbyte i zakwalifikowane w tygodniu werdyktu.">
        umówione → odbyte → zakwalifikowane:
      </span>{" "}
      {shown.map((week, index) => (
        <span key={week.week_start}>
          {index > 0 && " · "}
          {weekLabel(week, index)} <span className="font-medium tabular-nums text-foreground">{weekFunnel(week)}</span>
        </span>
      ))}
    </p>
  );
}

function bookerAction(handoff: Handoff, onOpen: Open, onRebook: (handoff: Handoff) => void): RowAction | null {
  if (handoff.verdict === "no_show" && handoff.status === "open") {
    return { label: "Umów ponownie", primary: true, run: () => onRebook(handoff) };
  }
  if (handoff.verdict === null && handoff.phase === "no_term") {
    return { label: "Ustaw termin", primary: false, run: () => onOpen(handoff, "term") };
  }
  return null;
}

interface BookedSectionProps extends SectionProps {
  weeks: HandoffWeek[];
  onRebook: (handoff: Handoff) => void;
}

/** „Umówione przez Ciebie”: co czeka na spotkanie i jaki werdykt dał prowadzący. */
export function BookedByMeSection({ rows, weeks, selectedId, canEdit, onOpen, onRebook }: BookedSectionProps) {
  const [all, setAll] = useState(false);
  if (rows.length === 0 && visibleWeeks(weeks).every((week) => week.booked + week.held === 0)) return null;
  const shown = all ? rows : rows.slice(0, BOOKED_PREVIEW);
  return (
    <section data-testid="booked-by-me">
      <header className={cn(HEADER, "flex-wrap")}>
        <h2 className={TITLE}>Umówione przez Ciebie</h2>
        <Weeks weeks={weeks} />
      </header>
      <ul className="divide-y divide-border border-b border-border">
        {shown.map((handoff) => (
          <HandoffRow
            key={handoff.opportunity.id}
            handoff={handoff}
            viewer="booker"
            active={selectedId === handoff.opportunity.id}
            action={canEdit ? bookerAction(handoff, onOpen, onRebook) : null}
            status={bookerStatus(handoff)}
            onOpen={onOpen}
          />
        ))}
        {rows.length > BOOKED_PREVIEW && (
          <li className="px-3 py-1.5 text-xs text-muted-foreground">
            {all ? `Wszystkie: ${rows.length}` : `Pokazano ${BOOKED_PREVIEW} z ${rows.length}`}
            {" · "}
            <button type="button" className="text-primary hover:underline" onClick={() => setAll((value) => !value)}>
              {all ? "Zwiń" : "Pokaż wszystkie"}
            </button>
          </li>
        )}
      </ul>
    </section>
  );
}
