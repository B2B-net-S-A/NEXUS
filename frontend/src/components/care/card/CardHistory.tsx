"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useContractTimeline, type TimelineEvent } from "@/lib/api/care";
import { formatIsoDatePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import { HISTORY_FILTERS, historyCounts, historyEvents, type HistoryFilter } from "./card-format";

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
      <span className="min-w-0 text-sm">
        {event.link ? (
          <Link href={event.link} className="hover:underline">
            {event.title}
          </Link>
        ) : (
          event.title
        )}
        {event.detail ? (
          <span className="block break-words text-xs text-muted-foreground">{event.detail}</span>
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
 * opieki”): rozmowy, sprawy, opinie, umowa i zamówienia z filtrami. Dane z
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
          {ahead.length ? (
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Przed nami
              </p>
              <ol className="divide-y divide-border/60" aria-label="Przed nami">
                {ahead.map((event, index) => (
                  <EventRow key={`${event.kind}-${event.on}-${index}`} event={event} action={null} />
                ))}
              </ol>
            </div>
          ) : null}
          {past.length ? (
            <ol className="divide-y divide-border/60" aria-label="Historia konsultanta">
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
