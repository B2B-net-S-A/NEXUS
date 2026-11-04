"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useContractTimeline, type TimelineEvent } from "@/lib/api/care";
import { formatIsoDatePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import {
  HISTORY_FILTERS,
  eventDetailSeparator,
  historyCounts,
  historyEvents,
  type HistoryFilter,
} from "./card-format";

function EventRow({ event, action }: { event: TimelineEvent; action: ReactNode }) {
  return (
    <li
      className={cn(
        "grid grid-cols-[5.5rem_minmax(0,1fr)_auto] items-start gap-2 py-1.5",
        event.future && "text-muted-foreground",
      )}
    >
      <span className="text-xs leading-5 tabular-nums text-muted-foreground">
        {formatIsoDatePl(event.on)}
      </span>
      <span className="min-w-0 break-words text-sm">
        {event.link ? (
          <Link href={event.link} className={cn("hover:underline", !event.future && "text-foreground")}>
            {event.title}
          </Link>
        ) : (
          <span className={event.future ? undefined : "text-foreground"}>{event.title}</span>
        )}
        {event.detail ? (
          <span className="text-muted-foreground">
            {eventDetailSeparator(event.detail)}
            {event.detail}
          </span>
        ) : null}
      </span>
      {action ? <span className="shrink-0">{action}</span> : <span />}
    </li>
  );
}

interface CardHistoryProps {
  contractId: number;
  /** Akcja przy zdarzeniu (np. „Edytuj” starej karty technologicznej w zakładce kontraktu). */
  eventAction?: (event: TimelineEvent) => ReactNode;
}

/**
 * Jedna „Historia” karty konsultanta (zastępuje „Oś konsultanta” i „Oś
 * opieki”): rozmowy, sprawy, opinie, umowa i zamówienia z filtrami; to, co
 * przed nami (plan rozmowy), na górze tej samej listy. Dane z
 * `GET /contracts/{id}/timeline` — bez stawek i bez treści spraw.
 */
export function CardHistory({ contractId, eventAction }: CardHistoryProps) {
  const query = useContractTimeline(contractId);
  const [filter, setFilter] = useState<HistoryFilter>("all");
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });
  const events = query.data?.events ?? [];
  const counts = historyCounts(events);
  const { past, ahead } = historyEvents(events, filter);

  return (
    <section aria-label="Historia" className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">Historia</h3>
        <div role="group" aria-label="Filtr historii" className="flex flex-wrap gap-1">
          {HISTORY_FILTERS.map((item) => (
            <button
              key={item.value}
              type="button"
              aria-pressed={filter === item.value}
              onClick={() => setFilter(item.value)}
              className={cn(
                "rounded-full border px-2.5 py-0.5 text-xs transition-colors",
                filter === item.value
                  ? "border-primary bg-primary/10 text-foreground"
                  : "border-border text-muted-foreground hover:bg-muted",
              )}
            >
              {item.label}
              {query.isSuccess ? (
                <>
                  {" "}
                  <span className="tabular-nums text-muted-foreground">{counts[item.value]}</span>
                </>
              ) : null}
            </button>
          ))}
        </div>
      </div>
      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie historii…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice
          state={state}
          description={state === "error" ? "Nie udało się wczytać historii konsultanta." : undefined}
          onRetry={() => query.refetch()}
        />
      ) : (
        <>
          {ahead.length || past.length ? (
            <ol className="divide-y divide-border/60" aria-label="Historia konsultanta">
              {/* To, co przed nami (plan rozmowy „· za 2 dni”), stoi na górze listy — makieta P2. */}
              {ahead.map((event, index) => (
                <EventRow key={`ahead-${event.kind}-${event.on}-${index}`} event={event} action={null} />
              ))}
              {past.map((event, index) => (
                <EventRow
                  key={`${event.kind}-${event.on}-${index}`}
                  event={event}
                  action={eventAction ? eventAction(event) : null}
                />
              ))}
            </ol>
          ) : (
            <p className="text-sm text-muted-foreground">
              {filter === "all" ? "Nie ma jeszcze zdarzeń." : "Nic w tym filtrze."}
            </p>
          )}
          {query.data && !query.data.feedback_visible ? (
            <p className="text-xs text-muted-foreground">
              Opinie klienta widzą opiekun, Delivery Lead klienta, Head of Recruitment i administrator.
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}
