"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { apiErrorMessage } from "@/lib/api-error";
import {
  PREP_ITEM_LABELS,
  PREP_LEVEL_LABELS,
  formatTalkShare,
  prepStatusLine,
  usePrep,
  usePrepTranscript,
  type Prep,
  type PrepItemStatus,
  type PrepReviewItem,
} from "@/lib/api/prepMeetings";
import { candidateLabel, pairContext, type PairInfo } from "@/lib/interview-cycle";
import { cn } from "@/lib/utils";

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

/**
 * Ocena prepu z transkryptu Teams. Poziom liczy serwer z punktów i udziału
 * kandydata w rozmowie; każdy punkt „omówione” ma cytat z rozmowy. Ocena jest
 * podpowiedzią dla prowadzącego — nic nie blokuje ruchu kandydata.
 */
export function PrepReviewDialog({
  open,
  onOpenChange,
  eventId,
  pair,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  eventId: number | null;
  pair: PairInfo | null;
}) {
  const prep = usePrep(open ? eventId : null);
  const [showTranscript, setShowTranscript] = useState(false);
  const transcript = usePrepTranscript(eventId, open && showTranscript);

  return (
    <AppModal
      open={open}
      onOpenChange={(o) => {
        if (!o) setShowTranscript(false);
        onOpenChange(o);
      }}
      size="lg"
      title={prep.data ? `Prep ${prep.data.prep_no} — ocena` : "Ocena prepu"}
      description={pair ? `${candidateLabel(pair)} · ${pairContext(pair)}` : undefined}
    >
      {prep.isPending ? (
        <p className="text-sm text-muted-foreground">Ładowanie prepu…</p>
      ) : prep.isError || !prep.data ? (
        <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {apiErrorMessage(prep.error, "Nie udało się wczytać prepu.")}
        </p>
      ) : (
        <div className="space-y-4">
          <PrepSummary prep={prep.data} />
          {prep.data.transcript_status === "fetched" ? (
            <div>
              <button
                type="button"
                onClick={() => setShowTranscript((v) => !v)}
                aria-expanded={showTranscript}
                className="text-xs font-semibold text-primary hover:underline"
              >
                {showTranscript ? "Ukryj transkrypt" : "Pokaż pełny transkrypt"}
              </button>
              {showTranscript ? (
                transcript.isPending ? (
                  <p className="mt-2 text-xs text-muted-foreground">Ładowanie transkryptu…</p>
                ) : transcript.isError || !transcript.data ? (
                  <p role="alert" className="mt-2 text-xs text-destructive">
                    {apiErrorMessage(transcript.error, "Nie udało się wczytać transkryptu.")}
                  </p>
                ) : (
                  <pre className="mt-2 max-h-80 overflow-y-auto whitespace-pre-wrap rounded-lg bg-muted/50 p-3 font-sans text-xs text-foreground">
                    {transcript.data.text}
                  </pre>
                )
              ) : null}
            </div>
          ) : null}
        </div>
      )}
    </AppModal>
  );
}

export function PrepSummary({ prep }: { prep: Prep }) {
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
        {prep.organizer ? (
          <span className="text-xs text-muted-foreground">Prowadził(a): {prep.organizer.name}</span>
        ) : null}
        {prep.duration_seconds ? (
          <span className="text-xs text-muted-foreground">
            · {Math.max(1, Math.round(prep.duration_seconds / 60))} min
          </span>
        ) : null}
        {prep.transcript_status === "fetched" ? (
          <span className="text-xs text-muted-foreground">
            · kandydat mówił {formatTalkShare(prep.talk_share)}
          </span>
        ) : null}
      </div>
      {status ? (
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
