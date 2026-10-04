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
import { safeExternalHref, safeInternalPath } from "@/lib/safe-href"
import type { TileConfig } from "@/lib/api/userDashboard"
import { pluralPl } from "@/lib/plural-pl"
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
  // 04.10.2026: kafelek pokazuje nowe dopasowania do rekrutacji (to, co da się
  // od razu dodać), a nie liczbę czekających — tę liczy panel „Moi ludzie”.
  const { new_matches: newMatches, jobs_with_matches: jobsWithMatches } = query.data
  const matches = (query.data.latest_matches ?? []).slice(0, 5)
  return (
    <div className="flex h-full flex-col gap-2 text-sm">
      {newMatches > 0 && matches.length > 0 ? (
        <>
          <p className="font-medium text-foreground">
            {newMatches} {pluralPl(newMatches, "nowe dopasowanie", "nowe dopasowania", "nowych dopasowań")}{" "}
            w {jobsWithMatches} {pluralPl(jobsWithMatches, "rekrutacji", "rekrutacjach", "rekrutacjach")}
          </p>
          <ul className="flex flex-col gap-1.5">
            {matches.map((match) => (
              <li
                key={`${match.job_id}-${match.candidate_id}`}
                className="flex items-center gap-2"
              >
                <span className="min-w-0 flex-1 truncate">
                  <span className="text-foreground">{match.full_name}</span>
                  <span className="text-muted-foreground"> → {match.job_title}</span>
                </span>
                {match.score !== null ? (
                  <span
                    className="shrink-0 font-mono text-xs font-semibold tabular-nums text-foreground"
                    title="Dopasowanie"
                  >
                    {Math.round(match.score)}
                  </span>
                ) : null}
                <Link
                  href={`/jobs/${match.job_id}?people=1`}
                  className="shrink-0 text-xs font-medium text-primary hover:underline"
                  aria-label={`Dodaj: ${match.full_name} do rekrutacji ${match.job_title}`}
                >
                  Dodaj
                </Link>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="text-muted-foreground">
          Brak nowych dopasowań — dzwonek da znać, gdy pojawi się rekrutacja dla Twoich ludzi.
        </p>
      )}
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
          {links.map((link) => {
            // Runda 8 (R8-N10-5): `/\evil.com` przeglądarka czyta jak
            // `//evil.com` — ścieżka wewnętrzna tylko przez `safeInternalPath`,
            // zewnętrzny wyłącznie https; resztę pokazujemy jako tekst.
            const internal = safeInternalPath(link.url)
            const external =
              internal === null && link.url.startsWith("https://")
                ? safeExternalHref(link.url)
                : null
            return (
              <li key={`${link.label}-${link.url}`}>
                {internal ? (
                  <Link href={internal} className="font-medium text-primary hover:underline">
                    {link.label}
                  </Link>
                ) : external ? (
                  <a
                    href={external}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-medium text-primary hover:underline"
                  >
                    {link.label}
                  </a>
                ) : (
                  <span className="text-muted-foreground">{link.label}</span>
                )}
              </li>
            )
          })}
        </ul>
      ) : null}
    </div>
  )
}
