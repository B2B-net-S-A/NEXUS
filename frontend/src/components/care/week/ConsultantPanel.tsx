"use client";

import Link from "next/link";

import { DetailPanel, DetailSection } from "@/components/ds/DetailPanel";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useContractTimeline, type TimelineEvent } from "@/lib/api/care";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import { FrontOfficeSection } from "./FrontOfficeSection";
import { dayMonth } from "./week-format";

function EventRow({ event }: { event: TimelineEvent }) {
  return (
    <li className={cn("grid grid-cols-[3rem_minmax(0,1fr)] gap-2", event.future && "text-muted-foreground")}>
      <span className="tabular-nums text-xs leading-5 text-muted-foreground">{dayMonth(event.on)}</span>
      <span className="min-w-0">
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
    </li>
  );
}

/**
 * Panel boczny pozycji „Ten tydzień”: oś konsultanta (rekrutacja → start →
 * rozmowy → opinie → zamówienia → sygnały) i „Przekaż do front office”.
 * Bez stawek i danych o zdrowiu — serwer ich nie wysyła.
 */
export function ConsultantPanel({
  contractId,
  onClose,
  onTalk,
}: {
  contractId: number;
  onClose: () => void;
  onTalk: ((clientId: number) => void) | null;
}) {
  const query = useContractTimeline(contractId);
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: false,
  });
  const data = query.data;
  const past = data?.events.filter((event) => !event.future) ?? [];
  const ahead = data?.events.filter((event) => event.future) ?? [];
  const subtitle = data
    ? [
        data.contract.client_name,
        data.manager
          ? `menedżer: ${data.manager.name}${data.manager.position ? ` (${data.manager.position})` : ""}`
          : "menedżer u klienta: nie wskazano",
        data.contract.end_date ? `koniec ${dayMonth(data.contract.end_date)}` : null,
      ]
        .filter(Boolean)
        .join(" · ")
    : null;

  return (
    <DetailPanel
      title={data?.contract.candidate_name ?? "Konsultant"}
      badges={
        data?.signals.length ? (
          <Badge variant="warning" size="sm">
            do przepięcia
          </Badge>
        ) : null
      }
      subtitle={subtitle}
      onClose={onClose}
      closeLabel="Zamknij oś konsultanta"
      data-testid="care-consultant-panel"
      footer={
        <>
          {onTalk && data?.can_edit ? (
            <Button size="sm" onClick={() => onTalk(data.contract.client_id)}>
              Zapisz rozmowę
            </Button>
          ) : null}
          <Button size="sm" variant="ghost" asChild>
            <Link href={`/contracts/${contractId}?tab=care`}>Otwórz kontrakt</Link>
          </Button>
        </>
      }
    >
      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie osi…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" || !data ? (
        <QueryStateNotice
          state={state === "forbidden" || state === "not_found" ? state : "error"}
          onRetry={() => query.refetch()}
        />
      ) : (
        <>
          <DetailSection title="Oś konsultanta">
            {past.length ? (
              <ol className="space-y-1.5 text-sm" aria-label="Oś konsultanta">
                {past.map((event, index) => (
                  <EventRow key={`${event.kind}-${event.on}-${index}`} event={event} />
                ))}
              </ol>
            ) : (
              <p className="text-sm text-muted-foreground">Brak zdarzeń przed dzisiejszym dniem.</p>
            )}
          </DetailSection>
          {ahead.length ? (
            <DetailSection title="Przed nami">
              <ol className="space-y-1.5 text-sm" aria-label="Przed nami">
                {ahead.map((event, index) => (
                  <EventRow key={`${event.kind}-${event.on}-${index}`} event={event} />
                ))}
              </ol>
            </DetailSection>
          ) : null}
          {data.front_office_reasons.length ? <FrontOfficeSection contractId={contractId} /> : null}
          {!data.feedback_visible ? (
            <p className="text-xs text-muted-foreground">
              Opinie klienta widzą opiekun, Delivery Lead klienta, Head of Recruitment i administrator.
            </p>
          ) : null}
        </>
      )}
    </DetailPanel>
  );
}
