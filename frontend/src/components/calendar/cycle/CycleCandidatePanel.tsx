"use client";

import Link from "next/link";
import { ArrowUpRight, Video } from "lucide-react";

import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  AGENDA_LABELS,
  PREP_QUALITY_LABELS,
  TODO_ACTIONS,
  TODO_LABELS,
  actionForItem,
  actionForTodo,
  candidateLabel,
  countdownLabel,
  debriefAvailable,
  debriefAvailableFromLabel,
  formatDayLabel,
  formatSlot,
  formatTime,
  interviewStartFor,
  pairAgenda,
  pairContext,
  pairKey,
  prepQualityTone,
  type AgendaEntry,
  type CycleAction,
  type CycleItem,
  type CycleOverview,
  type TodoEntry,
} from "@/lib/interview-cycle";
import { cn } from "@/lib/utils";

import { ClientQuestions } from "./ClientQuestions";
import { CycleStepper } from "./CycleStepper";

const CHIP: Record<AgendaEntry["kind"], string> = {
  prep: "bg-primary/10 text-primary",
  prep2: "bg-primary/10 text-primary",
  interview: "bg-warning-muted text-warning-muted-foreground",
  call: "bg-success-muted text-success-muted-foreground",
  tentative: "bg-muted text-muted-foreground border border-dashed border-warning",
};

const QUALITY_CHIP: Record<ReturnType<typeof prepQualityTone>, string> = {
  done: "bg-success-muted text-success-muted-foreground",
  warn: "bg-warning-muted text-warning-muted-foreground",
  danger: "bg-destructive/10 text-destructive",
  muted: "bg-muted text-muted-foreground",
};

const TODO_URGENT = new Set<TodoEntry["kind"]>(["call_now", "debrief_overdue", "prep_weak"]);

/**
 * Panel kandydata otwierany z karty Tablicy (i z linku `?cycle=`): kroki
 * cyklu, zadania tej pary, jej prepy i rozmowy (Teams, ocena prepu,
 * szczegóły), terminy od klienta i pytania klienta. Zastąpił zakładkę
 * „Agenda” — nic, co w niej było, nie zniknęło.
 */
export function CycleCandidateSheet({
  item,
  data,
  now,
  canManageSlots,
  onAction,
  onClose,
}: {
  item: CycleItem | null;
  data: CycleOverview;
  now: Date;
  canManageSlots: boolean;
  onAction: (a: CycleAction) => void;
  onClose: () => void;
}) {
  return (
    <Sheet open={item != null} onOpenChange={(o) => !o && onClose()}>
      {item ? (
        <SheetContent side="right" size="md">
          <SheetHeader>
            <SheetTitle>{candidateLabel(item)}</SheetTitle>
            <SheetDescription className="sr-only">
              Kroki rozmowy u klienta, prepy i pytania klienta — {pairContext(item)}
            </SheetDescription>
          </SheetHeader>
          <SheetBody>
            <CandidateCycleCard
              item={item}
              data={data}
              now={now}
              canManageSlots={canManageSlots}
              onAction={onAction}
            />
          </SheetBody>
        </SheetContent>
      ) : null}
    </Sheet>
  );
}

export function CandidateCycleCard({
  item,
  data,
  now,
  canManageSlots,
  onAction,
}: {
  item: CycleItem;
  data: CycleOverview;
  now: Date;
  canManageSlots: boolean;
  onAction: (a: CycleAction) => void;
}) {
  const key = pairKey(item);
  const current = actionForItem(item, { canManageSlots });
  const req = item.slot_request;
  const todos = data.todos
    .filter((t) => pairKey(t) === key)
    .sort((a, b) => a.priority - b.priority);
  const events = pairAgenda(data.agenda, key, now);
  return (
    <div className="flex flex-col gap-5" data-testid="cycle-candidate-card" data-help="calendar.person">
      <div>
        <div className="text-sm text-muted-foreground">{pairContext(item)}</div>
        <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-sm font-medium">
          <Link
            href={`/jobs/${item.job_id}?candidate=${item.candidate_id}`}
            className="inline-flex items-center gap-0.5 text-primary hover:underline"
          >
            Rekrutacja <ArrowUpRight className="h-3.5 w-3.5" aria-hidden />
          </Link>
          <Link
            href={`/candidates/${item.candidate_id}`}
            className="inline-flex items-center gap-0.5 text-primary hover:underline"
          >
            Profil <ArrowUpRight className="h-3.5 w-3.5" aria-hidden />
          </Link>
        </div>
      </div>

      {todos.length > 0 ? (
        <ul className="flex flex-col gap-2" aria-label="Do zrobienia przy tym kandydacie">
          {todos.map((t) => {
            const action = actionForTodo(t, data.items);
            const allowed =
              action &&
              !((action.type === "add_slots" || action.type === "confirm") && !canManageSlots);
            const urgent = t.urgent || TODO_URGENT.has(t.kind);
            return (
              <li
                key={`${t.kind}-${t.event_id ?? t.slot_request_id ?? ""}`}
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2.5",
                  urgent ? "bg-destructive/10" : "bg-muted/60",
                )}
              >
                <div className="min-w-0 flex-1">
                  <div
                    className={cn(
                      "text-sm font-semibold",
                      urgent ? "text-destructive" : "text-foreground",
                    )}
                  >
                    {TODO_LABELS[t.kind]}
                  </div>
                  {t.due ? (
                    <div className="text-xs text-muted-foreground tabular-nums">
                      {t.kind === "call_now" ? countdownLabel(t.due, now) : `${formatDayLabel(t.due, now)} ${formatTime(t.due)}`}
                    </div>
                  ) : null}
                </div>
                {allowed && action ? (
                  <button
                    type="button"
                    onClick={() => onAction(action)}
                    className={cn(
                      "h-8 shrink-0 rounded-md px-3 text-xs font-semibold",
                      urgent
                        ? "bg-destructive text-destructive-foreground hover:bg-destructive/90"
                        : "border border-border bg-card hover:bg-muted",
                    )}
                  >
                    {TODO_ACTIONS[t.kind]}
                  </button>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}

      <CycleStepper
        steps={item.steps}
        action={
          current
            ? { stepKey: current.stepKey, label: current.label, onClick: () => onAction(current.action) }
            : null
        }
        onPrepReview={(eventId) => onAction({ type: "prep_review", pair: item, eventId })}
      />

      {events.length > 0 ? (
        <section aria-labelledby={`cycle-events-${key}`} className="flex flex-col gap-1">
          <h3
            id={`cycle-events-${key}`}
            className="text-xs font-semibold uppercase tracking-wide text-muted-foreground"
          >
            Prepy i rozmowy
          </h3>
          <ul className="divide-y divide-border rounded-lg border border-border">
            {events.map((e) => (
              <PairEventRow
                key={`${e.kind}-${e.event_id ?? e.slot_request_id}-${e.start}`}
                entry={e}
                interviewStart={
                  e.kind === "call" && e.event_id != null ? interviewStartFor(data, e.event_id) : undefined
                }
                now={now}
                onAction={onAction}
              />
            ))}
          </ul>
        </section>
      ) : null}

      {req && req.status !== "cancelled" && req.status !== "confirmed" ? (
        <div className="rounded-lg bg-muted/50 p-3 text-xs">
          <div className="mb-1 font-semibold text-foreground">Terminy od klienta</div>
          <ul className="space-y-0.5">
            {req.slots.map((s, i) => (
              <li key={s.start} className={cn(i === req.chosen_index && "font-semibold text-primary")}>
                {formatSlot(s)}
                {i === req.chosen_index ? " · wybrany" : ""}
              </li>
            ))}
          </ul>
          {req.note ? <p className="mt-1.5 text-muted-foreground">Notatka DL: {req.note}</p> : null}
        </div>
      ) : null}
      <ClientQuestions jobId={item.job_id} clientName={item.client_name} />
    </div>
  );
}

/** Jedno wydarzenie pary: prep, rozmowa, telefon po niej albo termin czekający na DL. */
function PairEventRow({
  entry,
  interviewStart,
  now,
  onAction,
}: {
  entry: AgendaEntry;
  /** Początek rozmowy, po której jest ten telefon — debrief dopiero od niego. */
  interviewStart?: string;
  now: Date;
  onAction: (a: CycleAction) => void;
}) {
  const past =
    entry.kind === "call"
      ? entry.done
      : new Date(entry.end ?? entry.start).getTime() < now.getTime();
  const range = entry.end ? `${formatTime(entry.start)}–${formatTime(entry.end)}` : formatTime(entry.start);
  return (
    <li className={cn("flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2.5", past && "opacity-60")}>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className={cn("rounded-md px-2 py-0.5 text-xs font-semibold", CHIP[entry.kind])}>
            {AGENDA_LABELS[entry.kind]}
          </span>
          {entry.prep_quality ? (
            <span
              className={cn(
                "rounded-md px-2 py-0.5 text-xs font-semibold",
                QUALITY_CHIP[prepQualityTone(entry.prep_quality)],
              )}
            >
              {PREP_QUALITY_LABELS[entry.prep_quality]}
            </span>
          ) : null}
        </div>
        <div className="mt-0.5 text-xs text-muted-foreground tabular-nums">
          {formatDayLabel(entry.start, now)} · {range}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {entry.online_meeting_url && !past ? (
          <a
            href={entry.online_meeting_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex h-8 items-center gap-1 rounded-md bg-primary/10 px-2.5 text-xs font-semibold text-primary hover:bg-primary/15"
          >
            <Video className="h-3.5 w-3.5" aria-hidden />
            Dołącz
          </a>
        ) : null}
        {entry.kind === "call" && !entry.done && entry.event_id != null ? (
          debriefAvailable(interviewStart, now) ? (
            <button
              type="button"
              onClick={() => onAction({ type: "debrief", pair: entry, eventId: entry.event_id as number })}
              className="h-8 rounded-md border border-border px-2.5 text-xs font-semibold hover:bg-muted"
            >
              Debrief
            </button>
          ) : (
            <>
              <span id={`debrief-hint-${entry.event_id}`} className="text-xs text-muted-foreground">
                {debriefAvailableFromLabel(interviewStart as string, now)}
              </span>
              <button
                type="button"
                disabled
                aria-describedby={`debrief-hint-${entry.event_id}`}
                className="h-8 cursor-not-allowed rounded-md border border-border px-2.5 text-xs font-semibold opacity-50"
              >
                Debrief
              </button>
            </>
          )
        ) : null}
        {entry.kind === "call" && entry.done ? (
          <span className="text-xs text-success-muted-foreground">debrief zapisany</span>
        ) : null}
        {entry.from_nexus && past && entry.event_id != null ? (
          <button
            type="button"
            onClick={() => onAction({ type: "prep_review", pair: entry, eventId: entry.event_id as number })}
            className="h-8 rounded-md border border-border px-2.5 text-xs font-semibold hover:bg-muted"
          >
            Ocena prepu
          </button>
        ) : null}
        {entry.kind !== "call" && entry.event_id != null ? (
          <button
            type="button"
            onClick={() => onAction({ type: "open_event", eventId: entry.event_id as number })}
            className="h-8 rounded-md px-2 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            Szczegóły
          </button>
        ) : null}
      </div>
    </li>
  );
}
