"use client"

// Kafelki bez własnej karty: kalendarz na dziś, „Moi ludzie", notatka.
// Każdy pobiera dane sam — pulpit nie ma wspólnego zapytania, więc awaria
// jednego kafelka nie gasi pozostałych.

import Link from "next/link"
import { useMemo } from "react"
import { useQuery } from "@tanstack/react-query"

import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  nextDate,
  warsawDay,
  warsawMidnightIso,
} from "@/components/v2/dashboard/MyTasksDashboard"
import { WidgetErrorBlock } from "@/components/v2/dashboard/WidgetState"
import { calendarApi, type CalendarEventResponse } from "@/lib/api"
import { useMyPeopleSummary } from "@/lib/api/myPeople"
import type { TileConfig } from "@/lib/api/userDashboard"
import { summarySentences } from "@/lib/my-people-summary"
import { DASHBOARD_SECTION_POLL_MS } from "@/lib/polling"
import { useMyPeoplePanel } from "@/store/my-people"

const timeFormat = new Intl.DateTimeFormat("pl-PL", {
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/Warsaw",
})

export function CalendarTodayBody() {
  const day = warsawDay()
  const bounds = useMemo(() => {
    const nextMidnight = warsawMidnightIso(nextDate(day))
    return {
      start: warsawMidnightIso(day),
      end: new Date(new Date(nextMidnight).getTime() - 1).toISOString(),
    }
  }, [day])
  const query = useQuery({
    queryKey: ["dashboard", "calendar-today", day],
    queryFn: () =>
      calendarApi
        .listEvents({
          from_date: bounds.start,
          to_date: bounds.end,
          status: "scheduled",
          mine_only: true,
          limit: 50,
        })
        .then((response) => response.data as CalendarEventResponse[]),
    staleTime: 30_000,
    refetchInterval: DASHBOARD_SECTION_POLL_MS,
  })
  if (query.isPending) return <Skeleton className="h-full min-h-[48px] w-full" />
  if (query.isError) {
    return <WidgetErrorBlock error={query.error} onRetry={() => query.refetch()} />
  }
  const events = [...query.data].sort((a, b) => a.start_time.localeCompare(b.start_time))
  if (events.length === 0) {
    return <p className="text-sm text-muted-foreground">Dziś nic w kalendarzu.</p>
  }
  return (
    <ul className="flex flex-col gap-2">
      {events.map((event) => (
        <li key={event.id} className="flex gap-3 text-sm">
          <span className="w-11 shrink-0 font-mono text-muted-foreground">
            {event.all_day ? "cały" : timeFormat.format(new Date(event.start_time))}
          </span>
          <Link
            href={`/calendar?event=${event.id}`}
            className="min-w-0 border-l-2 border-primary pl-3 hover:underline"
          >
            <span className="block truncate font-medium text-foreground">{event.title}</span>
            {event.client_name || event.candidate_name ? (
              <span className="block truncate text-muted-foreground">
                {event.candidate_name ?? event.client_name}
              </span>
            ) : null}
          </Link>
        </li>
      ))}
    </ul>
  )
}

export function MyPeopleBody() {
  const query = useMyPeopleSummary()
  const openPanel = useMyPeoplePanel((s) => s.openPanel)
  if (query.isPending) return <Skeleton className="h-full min-h-[48px] w-full" />
  if (query.isError) {
    return <WidgetErrorBlock error={query.error} onRetry={() => query.refetch()} />
  }
  const sentences = summarySentences(query.data)
  return (
    <div className="flex h-full flex-col gap-2">
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-3xl font-semibold leading-none">
          {query.data.total}
        </span>
        <span className="text-xs text-muted-foreground">osób na Twojej liście</span>
      </div>
      {sentences.length > 0 ? (
        <ul className="space-y-1 text-sm text-foreground">
          {sentences.slice(0, 2).map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ul>
      ) : null}
      <Button variant="outline" size="sm" className="mt-auto self-start" onClick={openPanel}>
        Otwórz „Moi ludzie”
      </Button>
    </div>
  )
}

export function NoteBody({ config }: { config: TileConfig }) {
  const text = config.text?.trim()
  const links = config.links ?? []
  if (!text && links.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Pusta notatka — dodaj tekst albo linki w ustawieniach kafelka.
      </p>
    )
  }
  return (
    <div className="flex flex-col gap-2 text-sm">
      {text ? <p className="whitespace-pre-line text-foreground">{text}</p> : null}
      {links.length > 0 ? (
        <ul className="flex flex-col gap-1">
          {links.map((link) =>
            link.url.startsWith("/") ? (
              <li key={`${link.label}-${link.url}`}>
                <Link href={link.url} className="font-medium text-primary hover:underline">
                  {link.label}
                </Link>
              </li>
            ) : (
              <li key={`${link.label}-${link.url}`}>
                <a
                  href={link.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-medium text-primary hover:underline"
                >
                  {link.label}
                </a>
              </li>
            ),
          )}
        </ul>
      ) : null}
    </div>
  )
}
