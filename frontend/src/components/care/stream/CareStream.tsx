"use client";

// Lewa kolumna zakładki „Opieka i rozmowy” kontraktu (wariant A, 20.11.2026):
// jeden strumień rozmów i notatek z polem zapisu. Zastępuje „Historię” karty
// opieki, kartę „Opinie klienta” i „Notatki i rozmowy” — każde źródło ma
// własny odczyt, a awaria jednego to zdanie z ponowieniem, nie pusty strumień.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Handshake,
  MessageSquareText,
  Phone,
  StickyNote,
  UserRound,
  type LucideIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { contractsApi, type ContractTimelineItem } from "@/lib/api";
import { useContractCare, useContractTimeline } from "@/lib/api/care";
import { useContractFeedback } from "@/lib/api/client-people";
import { formatIsoDatePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";
import { isForbiddenError, isNotFoundError } from "@/lib/view-state";

import type { CareStreamActions } from "../card/ConsultantCard";
import { CareComposer } from "./CareComposer";
import {
  STREAM_FILTERS,
  buildCareStream,
  filterStream,
  isLongText,
  streamCounts,
  visibleFilters,
  type StreamFilter,
  type StreamItem,
  type StreamKind,
} from "./care-stream";

const KIND_ICON: Record<StreamKind, LucideIcon> = {
  note: StickyNote,
  call: Phone,
  consultant: UserRound,
  project: MessageSquareText,
  client: Handshake,
  care: Activity,
};

interface CareStreamProps {
  contractId: number;
  /** Moduł opieki włączony — rozmowy, karty technologiczne i zmiany w opiece. */
  careOpen: boolean;
  /** Akcje karty opieki (okno rozmowy, okno opinii); `null` — karta się wczytuje albo jej nie ma. */
  care: CareStreamActions | null;
  /** Notatka przy kontrakcie: edycja kontraktów w zakresie klienta (ta sama bramka co serwer). */
  canAddNote: boolean;
  /** Opinie klienta widzi krąg D11 (opiekun, DL, HoR, admin). */
  canReadFeedback: boolean;
  /** „Edytuj” przy starej karcie technologicznej (zapisujący opiekę). */
  onEditTechCard?: (target: { id: number; on: string }) => void;
}

/** Brak dostępu do źródła to nie awaria strumienia — o opiece mówi prawa kolumna. */
function failed(query: { isError: boolean; error: unknown }): boolean {
  return query.isError && !isForbiddenError(query.error) && !isNotFoundError(query.error);
}

function SourceError({ text, onRetry }: { text: string; onRetry: () => void }) {
  return (
    <p role="alert" className="flex flex-wrap items-center gap-x-2 py-1.5 text-[13px] text-destructive">
      <span>{text}</span>
      <Button type="button" size="sm" variant="ghost" className="h-7 px-2" onClick={onRetry}>
        Spróbuj ponownie
      </Button>
    </p>
  );
}

function StreamRow({
  item,
  expanded,
  onToggle,
  onEditTechCard,
}: {
  item: StreamItem;
  expanded: boolean;
  onToggle: () => void;
  onEditTechCard?: (target: { id: number; on: string }) => void;
}) {
  const Icon = KIND_ICON[item.kind];
  const long = isLongText(item.body);
  if (item.quiet) {
    return (
      <li className="grid grid-cols-[28px_minmax(0,1fr)_auto] items-start gap-3 py-2 text-muted-foreground">
        <span className="inline-flex size-7 items-center justify-center">
          <Icon aria-hidden className="size-3.5" />
        </span>
        <p className="min-w-0 pt-1 text-[12.5px] leading-5">
          {item.title}
          {item.facts.length ? <span> · {item.facts.join(" · ")}</span> : null}
        </p>
        <span className="pt-1 text-[12px] tabular-nums">{formatIsoDatePl(item.day)}</span>
      </li>
    );
  }
  return (
    <li className="grid grid-cols-[28px_minmax(0,1fr)_auto] gap-3 py-3">
      <span className="inline-flex size-7 items-center justify-center rounded-full bg-muted text-muted-foreground">
        <Icon aria-hidden className="size-3.5" />
      </span>
      <div className="min-w-0">
        <p className="text-[13px] font-medium leading-5 text-foreground">{item.title}</p>
        {item.body ? (
          <p
            className={cn(
              "mt-0.5 whitespace-pre-line break-words text-[13px] leading-5 text-foreground/85",
              long && !expanded && "line-clamp-3",
            )}
          >
            {item.body}
          </p>
        ) : null}
        {long ? (
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={expanded}
            className="hit-area mt-0.5 text-[12px] font-medium text-primary hover:underline"
          >
            {expanded ? "Zwiń" : "Rozwiń"}
          </button>
        ) : null}
        {item.facts.length || item.author ? (
          <p className="mt-0.5 text-[12px] text-muted-foreground">
            {[...item.facts, item.author].filter(Boolean).join(" · ")}
          </p>
        ) : null}
      </div>
      <div className="flex flex-col items-end gap-1">
        <span className="pt-0.5 text-[12px] tabular-nums text-muted-foreground">{formatIsoDatePl(item.day)}</span>
        {item.techCard && onEditTechCard ? (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 px-2 text-xs"
            onClick={() => onEditTechCard(item.techCard!)}
          >
            Edytuj
          </Button>
        ) : null}
      </div>
    </li>
  );
}

export function CareStream({
  contractId,
  careOpen,
  care,
  canAddNote,
  canReadFeedback,
  onEditTechCard,
}: CareStreamProps) {
  const notes = useQuery({
    queryKey: ["contract-notes-timeline", contractId],
    queryFn: async () => (await contractsApi.notesTimeline(contractId)).data as ContractTimelineItem[],
    enabled: Number.isFinite(contractId) && contractId > 0,
  });
  const careDetail = useContractCare(contractId, careOpen);
  const timeline = useContractTimeline(contractId, careOpen);
  const feedback = useContractFeedback(contractId, careOpen && canReadFeedback);
  const [filter, setFilter] = useState<StreamFilter>("all");
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());

  const items = buildCareStream({
    notes: notes.data,
    conversations: careDetail.data?.conversations,
    techCards: careDetail.data?.tech_cards,
    feedback: feedback.data?.items,
    timeline: timeline.data?.events,
  });
  const counts = streamCounts(items);
  const filters = visibleFilters(counts);
  const active = filters.includes(filter) ? filter : "all";
  const shown = filterStream(items, active);
  const sources = [notes, ...(careOpen ? [careDetail, timeline] : []), ...(careOpen && canReadFeedback ? [feedback] : [])];
  const loading = sources.some((query) => query.isLoading);
  const anyFailed = sources.some(failed);
  const allDone = sources.every((query) => query.isSuccess || (query.isError && !failed(query)));

  const toggle = (key: string) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <section
      aria-label="Rozmowy i notatki"
      data-tour="contract.care.stream"
      className="rounded-xl border border-border bg-card p-4 shadow-xs"
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-[13.5px] font-semibold text-foreground">
          Rozmowy i notatki
          {allDone && items.length ? (
            <span className="ml-2 text-[12px] font-normal tabular-nums text-muted-foreground">{items.length}</span>
          ) : null}
        </h2>
        {filters.length ? (
          <div role="group" aria-label="Filtr strumienia" className="flex flex-wrap gap-1">
            {STREAM_FILTERS.filter((item) => filters.includes(item.value)).map((item) => (
              <button
                key={item.value}
                type="button"
                aria-pressed={active === item.value}
                onClick={() => setFilter(item.value)}
                className={cn(
                  "hit-area rounded-full border px-2.5 py-0.5 text-[12px] transition-colors",
                  active === item.value
                    ? "border-primary bg-primary/10 text-foreground"
                    : "border-border text-muted-foreground hover:bg-muted",
                )}
              >
                {item.label} <span className="tabular-nums text-muted-foreground">{counts[item.value]}</span>
              </button>
            ))}
          </div>
        ) : null}
      </div>

      <CareComposer contractId={contractId} canAddNote={canAddNote} care={care} />

      <div className="mt-2">
        {failed(notes) ? (
          <SourceError text="Nie udało się wczytać notatek kontraktu." onRetry={() => void notes.refetch()} />
        ) : null}
        {careOpen && failed(careDetail) ? (
          <SourceError text="Nie udało się wczytać rozmów z konsultantem." onRetry={() => void careDetail.refetch()} />
        ) : null}
        {careOpen && failed(timeline) ? (
          <SourceError text="Nie udało się wczytać zmian w opiece." onRetry={() => void timeline.refetch()} />
        ) : null}
        {careOpen && canReadFeedback && failed(feedback) ? (
          <SourceError text="Nie udało się wczytać opinii klienta." onRetry={() => void feedback.refetch()} />
        ) : null}

        {loading && !items.length ? (
          <p className="py-3 text-[13px] text-muted-foreground">Wczytywanie rozmów i notatek…</p>
        ) : shown.length ? (
          <ol className="divide-y divide-border/60" aria-label="Strumień rozmów i notatek">
            {shown.map((item) => (
              <StreamRow
                key={item.key}
                item={item}
                expanded={expanded.has(item.key)}
                onToggle={() => toggle(item.key)}
                onEditTechCard={onEditTechCard}
              />
            ))}
          </ol>
        ) : allDone && !anyFailed ? (
          <p className="py-3 text-[13px] text-muted-foreground">
            Przy tym kontrakcie nie ma jeszcze rozmów ani notatek.
            {canAddNote || care?.canTalk ? "" : " Notatkę przy kontrakcie dodaje osoba z edycją kontraktów."}
          </p>
        ) : null}

        {careOpen && !canReadFeedback ? (
          <p className="pt-2 text-[12px] text-muted-foreground">
            Opinie klienta widzą opiekun, Delivery Lead klienta, Head of Recruitment i administrator.
          </p>
        ) : null}
      </div>
    </section>
  );
}
