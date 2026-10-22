"use client";

import { useEffect, useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { apiErrorMessage } from "@/lib/api-error";
import {
  PREP_ITEM_LABELS,
  PREP_LEVEL_LABELS,
  formatTalkShare,
  isReviewV2,
  prepStatusLine,
  usePrep,
  usePrepTranscript,
  type Prep,
  type PrepItemStatus,
  type PrepReviewItem,
} from "@/lib/api/prepMeetings";
import { candidateLabel, pairContext, type PairInfo } from "@/lib/interview-cycle";
import { cn } from "@/lib/utils";

import { ReviewScoreTab, ReviewSummaryTab, ReviewTranscriptTab } from "./PrepReviewTabs";

const LEVEL_CLASS: Record<"weak" | "ok" | "good", string> = {
  weak: "bg-destructive/10 text-destructive",
  ok: "bg-muted text-foreground",
  good: "bg-success-muted text-success-muted-foreground",
};

const ITEM_CLASS: Record<PrepItemStatus, string> = {
  covered: "text-success-muted-foreground",
  covered_in_prep1: "text-muted-foreground",
  partial: "text-warning-muted-foreground",
  missing: "text-destructive",
};

export type PrepReviewTab = "score" | "summary" | "transcript";

/**
 * Ocena prepu z transkryptu Teams — zakładki Ocena · Podsumowanie
 * i follow-up · Transkrypt (v2, 22.10.2026). Wynik liczy serwer z ustawień
 * Ocena prepów; ocena jest podpowiedzią — nic nie blokuje ruchu kandydata.
 * Oceny sprzed v2 mają tylko punkty „omówione / nie było” (`PrepSummary`).
 */
export function PrepReviewDialog({
  open,
  onOpenChange,
  eventId,
  pair,
  initialTab = "score",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  eventId: number | null;
  pair: PairInfo | null;
  initialTab?: PrepReviewTab;
}) {
  const prep = usePrep(open ? eventId : null);
  const [tab, setTab] = useState<PrepReviewTab>(initialTab);
  const [focusQuote, setFocusQuote] = useState<string | null>(null);
  const transcript = usePrepTranscript(eventId, open && tab === "transcript");

  // Okno jest zamontowane na stałe — przy każdym otwarciu zaczyna od zakładki,
  // z której przyszło wejście („Transkrypt” w karcie osoby otwiera transkrypt).
  useEffect(() => {
    if (open) {
      setTab(initialTab);
      setFocusQuote(null);
    }
  }, [open, initialTab]);

  const data = prep.data;
  const v2 = isReviewV2(data?.review);
  const hasTranscript = data?.transcript_status === "fetched";
  const tabs: Array<[PrepReviewTab, string]> = [
    ["score", "Ocena"],
    ...(v2 ? ([["summary", "Podsumowanie i follow-up"]] as Array<[PrepReviewTab, string]>) : []),
    ...(hasTranscript ? ([["transcript", "Transkrypt"]] as Array<[PrepReviewTab, string]>) : []),
  ];
  const active = tabs.some(([id]) => id === tab) ? tab : "score";

  const showQuote = (quote: string) => {
    setFocusQuote(quote);
    setTab("transcript");
  };

  return (
    <AppModal
      open={open}
      onOpenChange={(o) => {
        if (!o) {
          setTab(initialTab);
          setFocusQuote(null);
        }
        onOpenChange(o);
      }}
      size="xl"
      title={data ? `Prep ${data.prep_no} — ocena` : "Ocena prepu"}
      description={pair ? `${candidateLabel(pair)} · ${pairContext(pair)}` : undefined}
    >
      {prep.isPending ? (
        <p className="text-sm text-muted-foreground">Ładowanie prepu…</p>
      ) : prep.isError || !data ? (
        <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {apiErrorMessage(prep.error, "Nie udało się wczytać prepu.")}
        </p>
      ) : (
        <div className="flex flex-col gap-4">
          <PrepFacts prep={data} />
          {tabs.length > 1 ? (
            <div role="tablist" aria-label="Ocena prepu" className="flex gap-1 border-b border-border">
              {tabs.map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={active === id}
                  onClick={() => setTab(id)}
                  className={cn(
                    "min-h-11 border-b-2 px-3 text-sm",
                    active === id
                      ? "border-primary font-semibold text-primary"
                      : "border-transparent text-muted-foreground hover:text-foreground",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          ) : null}
          {active === "score" ? (
            v2 ? (
              <ReviewScoreTab prep={data} onQuote={showQuote} />
            ) : (
              <PrepSummary prep={data} withFacts={false} />
            )
          ) : null}
          {active === "summary" && v2 ? <ReviewSummaryTab prep={data} onQuote={showQuote} /> : null}
          {active === "transcript" ? (
            <ReviewTranscriptTab
              transcript={transcript.data}
              isPending={transcript.isPending}
              error={transcript.isError ? transcript.error : null}
              focusQuote={focusQuote}
            />
          ) : null}
        </div>
      )}
    </AppModal>
  );
}

/** Kto prowadził, ile trwało, ile mówił kandydat — nad zakładkami. */
function PrepFacts({ prep }: { prep: Prep }) {
  const status = prepStatusLine(prep);
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        {prep.organizer ? <span>Prowadził(a): {prep.organizer.name}</span> : null}
        {prep.duration_seconds ? <span>· {Math.max(1, Math.round(prep.duration_seconds / 60))} min</span> : null}
        {prep.transcript_status === "fetched" ? <span>· kandydat mówił {formatTalkShare(prep.talk_share)}</span> : null}
        {prep.online_meeting_url ? (
          <a href={prep.online_meeting_url} target="_blank" rel="noreferrer" className="text-primary hover:underline">
            · Spotkanie w Teams ↗
          </a>
        ) : null}
      </div>
      {status ? <p className="rounded-md bg-muted/50 px-3 py-2 text-sm text-muted-foreground">{status}</p> : null}
    </div>
  );
}

/** Ocena sprzed v2: punkty „omówione / nie było”. `withFacts` = z linią faktów. */
export function PrepSummary({ prep, withFacts = true }: { prep: Prep; withFacts?: boolean }) {
  const review = prep.review;
  const status = prepStatusLine(prep);
  const items = review?.criteria.items ?? [];
  const must = items.filter((i) => i.kind === "must");
  const questions = items.filter((i) => i.kind === "question");
  const own = review?.criteria.own_projects;
  return (
    <div className="space-y-4" data-testid="prep-summary">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        {review?.status === "ok" && review.level ? (
          <span className={cn("rounded-md px-2 py-1 text-xs font-bold", LEVEL_CLASS[review.level])}>
            Ocena: {PREP_LEVEL_LABELS[review.level]}
          </span>
        ) : null}
        {withFacts && prep.organizer ? (
          <span className="text-xs text-muted-foreground">Prowadził(a): {prep.organizer.name}</span>
        ) : null}
        {withFacts && prep.duration_seconds ? (
          <span className="text-xs text-muted-foreground">
            · {Math.max(1, Math.round(prep.duration_seconds / 60))} min
          </span>
        ) : null}
        {withFacts && prep.transcript_status === "fetched" ? (
          <span className="text-xs text-muted-foreground">
            · kandydat mówił {formatTalkShare(prep.talk_share)}
          </span>
        ) : null}
      </div>
      {withFacts && status ? (
        <p className="rounded-md bg-muted/50 px-3 py-2 text-sm text-muted-foreground">{status}</p>
      ) : null}
      {review?.summary ? <p className="text-sm text-foreground">{review.summary}</p> : null}
      {must.length > 0 ? <ItemList title="Must-have rekrutacji" items={must} /> : null}
      {questions.length > 0 ? <ItemList title="Pytania tego klienta" items={questions} /> : null}
      {own ? (
        <p className="text-xs text-muted-foreground">
          {own.told
            ? `Kandydat sam opowiedział o swoich projektach: „${own.quote}”`
            : "Kandydat nie opowiedział sam o swoich projektach."}
        </p>
      ) : null}
      {review?.status === "ok" && review.remaining.length > 0 ? (
        <div className="rounded-lg border border-warning/40 bg-warning-muted/40 p-3 text-xs">
          <div className="mb-1 font-semibold text-foreground">
            {prep.prep_no === 1 ? "Na Prep 2 zostało" : "Nie omówiono"}
          </div>
          <ul className="list-disc space-y-0.5 pl-4">
            {review.remaining.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function ItemList({ title, items }: { title: string; items: PrepReviewItem[] }) {
  return (
    <div>
      <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </div>
      <ul className="divide-y divide-border rounded-lg border border-border">
        {items.map((item) => (
          <li key={item.key} className="px-3 py-2 text-sm">
            <div className="flex items-start justify-between gap-3">
              <span className="text-foreground">{item.label}</span>
              <span className={cn("shrink-0 text-xs font-semibold", ITEM_CLASS[item.status])}>
                {PREP_ITEM_LABELS[item.status]}
                {item.unverified ? " (bez dowodu)" : ""}
              </span>
            </div>
            {item.quote ? (
              <p className="mt-0.5 text-xs italic text-muted-foreground">„{item.quote}”</p>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
