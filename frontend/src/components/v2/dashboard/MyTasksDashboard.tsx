"use client"

import Link from "next/link"
import { useEffect, useMemo, useState } from "react"
import {
  Bell,
  CalendarClock,
  CheckSquare2,
  ChevronDown,
  Clock3,
} from "lucide-react"
import { useQuery } from "@tanstack/react-query"

import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { Skeleton } from "@/components/ui/skeleton"
import {
  calendarApi,
  notificationsApi,
  type CalendarEventResponse,
  type NotificationResponse,
} from "@/lib/api"
import { cn } from "@/lib/utils"
import { useAuthStore } from "@/store/auth"

function warsawDay(): string {
  const parts = new Intl.DateTimeFormat("en", {
    timeZone: "Europe/Warsaw",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date())
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  return `${values.year}-${values.month}-${values.day}`
}

function nextDate(value: string): string {
  const [year, month, day] = value.split("-").map(Number)
  return new Date(Date.UTC(year, month - 1, day + 1, 12))
    .toISOString()
    .slice(0, 10)
}

function warsawMidnightIso(value: string): string {
  const utcGuess = new Date(`${value}T00:00:00Z`)
  const parts = new Intl.DateTimeFormat("en", {
    timeZone: "Europe/Warsaw",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(utcGuess)
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  const representedAsUtc = Date.UTC(
    Number(values.year),
    Number(values.month) - 1,
    Number(values.day),
    Number(values.hour),
    Number(values.minute),
    Number(values.second),
  )
  const offset = representedAsUtc - utcGuess.getTime()
  return new Date(utcGuess.getTime() - offset).toISOString()
}

function formatEventTime(event: CalendarEventResponse): string {
  if (event.all_day) return "Cały dzień"
  return new Intl.DateTimeFormat("pl-PL", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/Warsaw",
  }).format(new Date(event.start_time))
}

function TaskColumn({
  title,
  icon: Icon,
  count,
  children,
}: {
  title: string
  icon: typeof Bell
  count: number
  children: React.ReactNode
}) {
  return (
    <section className="min-w-0 p-4" aria-label={title}>
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Icon className="h-4 w-4 text-primary" />
          {title}
        </h3>
        <Badge variant="soft" size="sm">
          {count}
        </Badge>
      </div>
      <div className="mt-3">{children}</div>
    </section>
  )
}

function EventList({
  events,
  empty,
}: {
  events: CalendarEventResponse[]
  empty: string
}) {
  if (!events.length) {
    return <p className="py-5 text-center text-xs text-muted-foreground">{empty}</p>
  }
  return (
    <div className="space-y-1">
      {events.slice(0, 5).map((event) => (
        <Link
          key={event.id}
          href={`/calendar?event=${event.id}`}
          className="flex items-start gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-muted/60 focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
        >
          <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
            <Clock3 className="h-3.5 w-3.5" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium text-foreground">
              {event.title}
            </span>
            <span className="mt-0.5 block truncate text-xs text-muted-foreground">
              {formatEventTime(event)}
              {event.candidate_name ? ` · ${event.candidate_name}` : ""}
            </span>
          </span>
        </Link>
      ))}
      {events.length > 5 ? (
        <Link
          href="/calendar"
          className="block px-2 pt-2 text-xs font-medium text-primary hover:underline"
        >
          Pokaż wszystkie ({events.length})
        </Link>
      ) : null}
    </div>
  )
}

function NotificationList({
  notifications,
}: {
  notifications: NotificationResponse[]
}) {
  if (!notifications.length) {
    return (
      <p className="py-5 text-center text-xs text-muted-foreground">
        Brak nowych powiadomień
      </p>
    )
  }
  return (
    <div className="space-y-1">
      {notifications.slice(0, 5).map((notification) => {
        const content = (
          <>
            <span
              className={cn(
                "mt-1.5 h-2 w-2 shrink-0 rounded-full",
                notification.is_read ? "bg-muted-foreground/30" : "bg-primary",
              )}
            />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium text-foreground">
                {notification.title}
              </span>
              <span className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
                {notification.message}
              </span>
            </span>
          </>
        )
        const classes =
          "flex items-start gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-muted/60 focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
        return notification.link ? (
          <Link key={notification.id} href={notification.link} className={classes}>
            {content}
          </Link>
        ) : (
          <div key={notification.id} className={classes}>
            {content}
          </div>
        )
      })}
    </div>
  )
}

export function MyTasksDashboard() {
  const authUser = useAuthStore((state) => state.user)
  const scopeCacheKey = `${authUser?.id ?? "anonymous"}:${authUser?.authorization_version ?? "none"}`
  const [open, setOpen] = useState(true)
  const [day, setDay] = useState(warsawDay)

  useEffect(() => {
    const timer = window.setInterval(() => setDay(warsawDay()), 60_000)
    return () => window.clearInterval(timer)
  }, [])
  const bounds = useMemo(() => {
    const start = warsawMidnightIso(day)
    const nextMidnight = warsawMidnightIso(nextDate(day))
    return {
      start,
      end: new Date(new Date(nextMidnight).getTime() - 1).toISOString(),
    }
  }, [day])
  const calendarQuery = useQuery({
    queryKey: ["dashboard", "my-tasks", scopeCacheKey, "calendar", day],
    queryFn: () =>
      calendarApi
        .listEvents({
          from_date: bounds.start,
          to_date: bounds.end,
          status: "scheduled",
          mine_only: true,
          limit: 100,
        })
        .then((response) => response.data as CalendarEventResponse[]),
    staleTime: 30_000,
    refetchInterval: 60_000,
  })
  const notificationsQuery = useQuery({
    // The shell bell uses the same key and limit, so the dashboard reuses its
    // fresh response instead of polling the same feed a second time.
    queryKey: ["notifications", scopeCacheKey, 20],
    queryFn: () => notificationsApi.list(20).then((response) => response.data),
    staleTime: 15_000,
    refetchInterval: 30_000,
  })
  const deadlines =
    calendarQuery.data?.filter((event) => event.event_type === "deadline") ?? []
  const meetings =
    calendarQuery.data?.filter((event) => event.event_type !== "deadline") ?? []
  const notifications =
    notificationsQuery.data?.items.filter((notification) => !notification.is_read) ??
    []
  const unread = notificationsQuery.data?.unread_count ?? 0
  const total = deadlines.length + meetings.length + unread
  const loading = calendarQuery.isLoading || notificationsQuery.isLoading

  return (
    <section aria-labelledby="my-tasks-heading" data-testid="my-tasks-dashboard">
      <Collapsible open={open} onOpenChange={setOpen}>
        <Card className="overflow-hidden p-0">
          <CollapsibleTrigger asChild>
            <button
              type="button"
              className="flex w-full items-center justify-between gap-3 bg-card p-4 text-left transition-colors hover:bg-muted/40 focus:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
            >
              <span className="flex min-w-0 items-center gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <CheckSquare2 className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span
                    id="my-tasks-heading"
                    className="block text-base font-semibold text-foreground"
                  >
                    Moje zadania
                  </span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">
                    Deadline’y, spotkania i powiadomienia na dziś
                  </span>
                </span>
              </span>
              <span className="flex shrink-0 items-center gap-2">
                {!loading ? (
                  <Badge variant={total > 0 ? "soft" : "success"} size="sm">
                    {total > 0 ? `${total} do sprawdzenia` : "Spokojny dzień"}
                  </Badge>
                ) : null}
                <ChevronDown
                  className={cn(
                    "h-4 w-4 text-muted-foreground transition-transform",
                    open && "rotate-180",
                  )}
                />
              </span>
            </button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="border-t border-border">
              {loading ? (
                <div className="grid gap-3 p-4 md:grid-cols-3">
                  {Array.from({ length: 3 }).map((_, index) => (
                    <Skeleton key={index} className="h-36 w-full" />
                  ))}
                </div>
              ) : (
                <div className="grid divide-y divide-border md:grid-cols-3 md:divide-x md:divide-y-0">
                  <TaskColumn
                    title="Do zrobienia dziś"
                    icon={CheckSquare2}
                    count={deadlines.length}
                  >
                    {calendarQuery.isError ? (
                      <p className="py-5 text-center text-xs text-destructive">
                        Nie udało się pobrać deadline’ów.
                      </p>
                    ) : (
                      <EventList events={deadlines} empty="Brak deadline’ów na dziś" />
                    )}
                  </TaskColumn>
                  <TaskColumn
                    title="Spotkania"
                    icon={CalendarClock}
                    count={meetings.length}
                  >
                    {calendarQuery.isError ? (
                      <p className="py-5 text-center text-xs text-destructive">
                        Nie udało się pobrać spotkań.
                      </p>
                    ) : (
                      <EventList events={meetings} empty="Brak spotkań na dziś" />
                    )}
                  </TaskColumn>
                  <TaskColumn title="Powiadomienia" icon={Bell} count={unread}>
                    {notificationsQuery.isError ? (
                      <p className="py-5 text-center text-xs text-destructive">
                        Nie udało się pobrać powiadomień.
                      </p>
                    ) : (
                      <NotificationList notifications={notifications} />
                    )}
                  </TaskColumn>
                </div>
              )}
            </div>
          </CollapsibleContent>
        </Card>
      </Collapsible>
    </section>
  )
}
