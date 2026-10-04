"use client"

// Kafelek „Dziś": pilne zadania cyklu rozmowy u klienta (telefon po rozmowie,
// zaległy debrief, brak prepu tuż przed rozmową) i dzisiejsza agenda — prepy,
// rozmowy u klienta, telefony. Dane z tego samego zapytania co ekran
// „Rozmowy u klienta” (`/api/interview-cycle`), więc liczby się zgadzają.

import Link from "next/link"

import { Skeleton } from "@/components/ui/skeleton"
import { warsawDay } from "@/components/v2/dashboard/MyTasksDashboard"
import { WidgetErrorBlock } from "@/components/v2/dashboard/WidgetState"
import { useInterviewCycle } from "@/lib/api/interviewCycle"
import {
  TODO_LABELS,
  candidateLabel,
  formatTime,
  pairContext,
  pairKey,
  type AgendaEntry,
  type AgendaKind,
  type CycleScope,
  type TodoEntry,
} from "@/lib/interview-cycle"
import { cn } from "@/lib/utils"
import { hasRole, useAuthStore } from "@/store/auth"

const MAX_TODOS = 4
const MAX_AGENDA = 6

/** Etykiety rodzaju wpisu na kafelku (krótsze niż na ekranie kalendarza). */
export const TODAY_KIND_LABELS: Record<AgendaKind, string> = {
  prep: "Prep 1",
  prep2: "Prep 2",
  interview: "Rozmowa u klienta",
  call: "Telefon po rozmowie",
  tentative: "Termin do potwierdzenia",
}

/** Dzień RRRR-MM-DD w strefie Europe/Warsaw (nie przeglądarki). */
function warsawDayOf(iso: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Warsaw",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(iso))
}

/** Zadanie na górę kafelka: pilne albo telefon/debrief po rozmowie. */
export function isUrgentTodo(todo: TodoEntry): boolean {
  return Boolean(todo.urgent) || todo.kind === "call_now" || todo.kind === "debrief_overdue"
}

/** Agenda z dzisiaj (Europe/Warsaw), po godzinie. */
export function todayAgenda(entries: readonly AgendaEntry[], today: string): AgendaEntry[] {
  return entries
    .filter((entry) => warsawDayOf(entry.start) === today)
    .sort((a, b) => new Date(a.start).getTime() - new Date(b.start).getTime())
}

function cycleHref(pair: { candidate_id: number; job_id: number }): string {
  return `/calendar?cycle=${pairKey(pair)}`
}

export function TodayCycleTile() {
  const user = useAuthStore((s) => s.user)
  const scope: CycleScope = hasRole(user, "delivery_lead") ? "jobs" : "mine"
  const query = useInterviewCycle(scope)
  const today = warsawDay()

  if (query.isPending) return <Skeleton className="h-full min-h-[48px] w-full" />
  if (query.isError) {
    return <WidgetErrorBlock error={query.error} onRetry={() => query.refetch()} />
  }

  const urgent = query.data.todos.filter(isUrgentTodo).slice(0, MAX_TODOS)
  const agenda = todayAgenda(query.data.agenda, today)
  const visibleAgenda = agenda.slice(0, MAX_AGENDA)

  if (urgent.length === 0 && agenda.length === 0) {
    return (
      <div className="flex flex-col gap-2 text-sm">
        <p className="text-muted-foreground">Na dziś nie ma rozmów ani prepów.</p>
        <Link href="/calendar" className="self-start font-medium text-primary hover:underline">
          Rozmowy u klienta →
        </Link>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col gap-3 text-sm">
      {urgent.length > 0 ? (
        <ul className="flex flex-col gap-1.5" aria-label="Pilne">
          {urgent.map((todo) => (
            <li key={`${todo.kind}-${pairKey(todo)}-${todo.event_id ?? todo.slot_request_id ?? ""}`}>
              <Link
                href={cycleHref(todo)}
                className="flex min-w-0 flex-col rounded-md border-l-2 border-destructive bg-destructive/5 px-2.5 py-1.5 hover:bg-destructive/10"
              >
                <span className="font-medium text-destructive">{TODO_LABELS[todo.kind]}</span>
                <span className="truncate text-foreground">
                  {candidateLabel(todo)}
                  <span className="text-muted-foreground"> · {pairContext(todo)}</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      ) : null}

      {agenda.length > 0 ? (
        <ul className="flex flex-col gap-2" aria-label="Dziś w kalendarzu">
          {visibleAgenda.map((entry) => (
            <li
              key={`${entry.kind}-${pairKey(entry)}-${entry.event_id ?? entry.slot_request_id ?? entry.start}`}
              className="flex gap-3"
            >
              <span className="w-11 shrink-0 font-mono text-muted-foreground">
                {formatTime(entry.start)}
              </span>
              <Link
                href={cycleHref(entry)}
                className={cn(
                  "min-w-0 border-l-2 pl-3 hover:underline",
                  entry.kind === "tentative" ? "border-warning" : "border-primary",
                  entry.done && "opacity-60",
                )}
              >
                <span className="block truncate font-medium text-foreground">
                  {TODAY_KIND_LABELS[entry.kind]} · {candidateLabel(entry)}
                </span>
                <span className="block truncate text-muted-foreground">
                  {pairContext(entry)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-muted-foreground">Dziś brak rozmów i prepów w kalendarzu.</p>
      )}

      <Link href="/calendar" className="mt-auto self-start font-medium text-primary hover:underline">
        {agenda.length > MAX_AGENDA
          ? `Pokaż w kalendarzu (jeszcze ${agenda.length - MAX_AGENDA}) →`
          : "Pokaż w kalendarzu →"}
      </Link>
    </div>
  )
}
