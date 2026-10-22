"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { Search } from "lucide-react";

import { apiErrorMessage } from "@/lib/api-error";
import {
  PREP_CAP_LABELS,
  PREP_FOLLOWUP_REASON_LABELS,
  PREP_GRADE_LABELS,
  PREP_LEVEL_LABELS,
  PREP_TOPIC_LABELS,
  cueIndexForQuote,
  formatCueTime,
  normalizeForQuote,
  type Prep,
  type PrepAnswer,
  type PrepAnswerGrade,
  type PrepFollowupReason,
  type PrepTopicResult,
  type PrepTranscript,
} from "@/lib/api/prepMeetings";
import { CRITERION_LABELS } from "@/lib/api/prepReviewConfig";
import { cn } from "@/lib/utils";

/**
 * Ocena prepu v2 (22.10.2026, makiety 1h38jS5LMc1673CENvUejR, plansza 3):
 * zakładki Ocena · Podsumowanie i follow-up · Transkrypt. Cytat w ocenie
 * przenosi do transkryptu i podświetla wypowiedź.
 */

const LEVEL_CLASS: Record<"weak" | "ok" | "good", string> = {
  weak: "bg-destructive/10 text-destructive",
  ok: "bg-muted text-foreground",
  good: "bg-success-muted text-success-muted-foreground",
};

export const GRADE_CLASS: Record<PrepAnswerGrade, string> = {
  strong: "bg-success-muted text-success-muted-foreground",
  general: "bg-warning-muted text-warning-muted-foreground",
  weak: "bg-destructive/10 text-destructive",
  missing: "bg-muted text-foreground",
  covered_in_prep1: "bg-muted text-muted-foreground",
};

const TOPIC_CLASS: Record<PrepTopicResult["status"], string> = {
  covered: "text-success-muted-foreground",
  partial: "text-warning-muted-foreground",
  missing: "text-destructive",
};

export const REASON_CLASS: Record<PrepFollowupReason, string> = {
  weak: "bg-destructive/10 text-destructive",
  missing: "bg-muted text-foreground",
  missing_topic: "bg-muted text-foreground",
  general: "bg-warning-muted text-warning-muted-foreground",
  unpracticed: "bg-warning-muted text-warning-muted-foreground",
};

function Chip({ className, children }: { className: string; children: React.ReactNode }) {
  return (
    <span className={cn("inline-flex shrink-0 rounded-md px-2 py-0.5 text-xs font-semibold", className)}>
      {children}
    </span>
  );
}

function QuoteButton({ quote, onQuote }: { quote: string; onQuote: (quote: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => onQuote(quote)}
      className="text-left text-xs italic text-primary hover:underline"
    >
      „{quote}”<span className="sr-only"> — pokaż w transkrypcie</span>
    </button>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{children}</h3>
  );
}

// ── Ocena ─────────────────────────────────────────────────────────────────────

export function ReviewScoreTab({ prep, onQuote }: { prep: Prep; onQuote: (quote: string) => void }) {
  const review = prep.review!;
  const c = review.criteria;
  const scores = c.scores ?? {};
  const weights = c.weights_used ?? {};
  const answers = c.answers ?? [];
  const topics = c.topics ?? [];
  const caps = (c.caps ?? []).map((cap) => PREP_CAP_LABELS[cap] ?? cap);
  const graded = answers.filter((a) => a.kind !== "followup");
  const followupAnswers = answers.filter((a) => a.kind === "followup");

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3 rounded-lg bg-muted/50 px-3 py-3">
        {review.level ? (
          <span className={cn("rounded-md px-3 py-1.5 text-base font-bold", LEVEL_CLASS[review.level])}>
            {PREP_LEVEL_LABELS[review.level]}
            {c.total != null ? ` · ${c.total}%` : ""}
          </span>
        ) : null}
        <div className="min-w-0 flex-1 text-sm text-foreground">
          {caps.length > 0 ? <>Najwyżej „OK”, bo: {caps.join(", ")}. </> : null}
          <Link href="/settings/prep-review" className="font-semibold text-primary hover:underline">
            Jak liczona jest ocena
          </Link>
          {review.config_version ? (
            <span className="text-muted-foreground"> · ustawienia w wersji {review.config_version}</span>
          ) : null}
        </div>
      </div>

      <section className="flex flex-col gap-1.5">
        <SectionTitle>Z czego wynik</SectionTitle>
        <ul className="divide-y divide-border rounded-lg border border-border text-sm">
          {Object.keys(scores).map((key) => {
            const value = scores[key];
            const weight = weights[key];
            return (
              <li key={key} className="flex items-center justify-between gap-3 px-3 py-2">
                <span className="min-w-0 text-foreground">
                  {CRITERION_LABELS[key as keyof typeof CRITERION_LABELS] ?? key}
                </span>
                <span className="shrink-0 tabular-nums text-muted-foreground">
                  {value == null ? (
                    key === "talk_share" ? "bez mówców — nie liczone" : "brak punktów — nie liczone"
                  ) : (
                    <>
                      <span className="font-semibold text-foreground">{value}%</span>
                      {weight != null ? ` · waga ${weight}%` : ""}
                    </>
                  )}
                </span>
              </li>
            );
          })}
        </ul>
      </section>

      {topics.length > 0 ? (
        <section className="flex flex-col gap-1.5">
          <SectionTitle>Tematy prowadzącego</SectionTitle>
          <ul className="divide-y divide-border rounded-lg border border-border">
            {topics.map((t) => (
              <li key={t.key} className="flex flex-col gap-0.5 px-3 py-2 text-sm">
                <div className="flex items-start justify-between gap-3">
                  <span className="text-foreground">
                    {t.label}
                    {t.required ? <span className="text-muted-foreground"> · obowiązkowy</span> : null}
                  </span>
                  <span className={cn("shrink-0 text-xs font-semibold", TOPIC_CLASS[t.status])}>
                    {PREP_TOPIC_LABELS[t.status]}
                    {t.unverified ? " (bez dowodu)" : ""}
                  </span>
                </div>
                {t.quote ? <QuoteButton quote={t.quote} onQuote={onQuote} /> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {graded.length > 0 ? (
        <AnswerList title="Odpowiedzi kandydata" answers={graded} onQuote={onQuote} />
      ) : null}
      {followupAnswers.length > 0 ? (
        <AnswerList title="Punkty z notatki po Prepie 1" answers={followupAnswers} onQuote={onQuote} />
      ) : null}

      {c.own_projects ? (
        <p className="text-xs text-muted-foreground">
          {c.own_projects.told
            ? "Kandydat sam opowiedział o swoich projektach."
            : "Kandydat nie opowiedział sam o swoich projektach."}
        </p>
      ) : null}
    </div>
  );
}

function AnswerList({
  title,
  answers,
  onQuote,
}: {
  title: string;
  answers: PrepAnswer[];
  onQuote: (quote: string) => void;
}) {
  return (
    <section className="flex flex-col gap-1.5">
      <SectionTitle>{title}</SectionTitle>
      <ul className="divide-y divide-border rounded-lg border border-border">
        {answers.map((a) => (
          <li key={a.key} className="flex flex-col gap-1 px-3 py-2 text-sm">
            <div className="flex items-start justify-between gap-3">
              <span className="min-w-0 text-foreground">
                {a.label}
                {a.kind === "question" ? <span className="text-muted-foreground"> · pytanie klienta</span> : null}
              </span>
              <Chip className={GRADE_CLASS[a.grade]}>
                {PREP_GRADE_LABELS[a.grade]}
                {a.unverified ? " (bez dowodu)" : ""}
              </Chip>
            </div>
            {a.quote ? <QuoteButton quote={a.quote} onQuote={onQuote} /> : null}
            {a.note && (a.grade === "weak" || a.grade === "general") ? (
              <p className="text-xs text-muted-foreground">Przećwicz: {a.note}</p>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

// ── Podsumowanie i follow-up ─────────────────────────────────────────────────

export function ReviewSummaryTab({ prep, onQuote }: { prep: Prep; onQuote: (quote: string) => void }) {
  const review = prep.review!;
  const c = review.criteria;
  const blocks: Array<[string, string, string[] | undefined]> = [
    ["Co poszło dobrze", "text-success-muted-foreground", c.went_well],
    ["Co poszło nie tak", "text-destructive", c.went_wrong],
    ["Co usprawnić — dla prowadzącego", "text-warning-muted-foreground", c.improve],
  ];
  return (
    <div className="flex flex-col gap-4 text-sm">
      {review.summary ? (
        <p className="rounded-lg bg-muted/50 px-3 py-3 leading-relaxed text-foreground">{review.summary}</p>
      ) : null}
      {blocks.map(([title, tone, lines]) =>
        lines && lines.length > 0 ? (
          <div key={title}>
            <div className={cn("font-semibold", tone)}>{title}</div>
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-foreground">
              {lines.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
        ) : null,
      )}

      {prep.prep_no === 1 ? <FollowupNote prep={prep} onQuote={onQuote} /> : <Prep2Comparison prep={prep} />}

      <p className="text-xs text-muted-foreground">
        To samo podsumowanie jest notatką „Prep {prep.prep_no} — podsumowanie z Teams” na profilu kandydata.
      </p>
    </div>
  );
}

/** Notatka rekrutera na Prep 2 — ten sam blok w karcie osoby (krok Prep 2). */
export function FollowupNote({
  prep,
  onQuote,
  compact = false,
}: {
  prep: Prep;
  onQuote?: (quote: string) => void;
  compact?: boolean;
}) {
  const items = prep.review?.criteria.followup ?? [];
  return (
    <div className="rounded-lg border border-primary/30 bg-primary/5 p-3">
      <div className="font-semibold text-foreground">Do powtórzenia na Prepie 2</div>
      {items.length === 0 ? (
        <p className="mt-1 text-sm text-muted-foreground">
          Nic — na Prepie 1 kandydat odpowiedział mocno na wszystko, a tematy obowiązkowe padły.
        </p>
      ) : (
        <ol className="mt-2 flex flex-col gap-2">
          {items.map((item, i) => (
            <li key={item.key} className="flex flex-col gap-0.5 text-sm">
              <div className="flex items-start gap-2">
                <span className="tabular-nums text-muted-foreground">{i + 1}.</span>
                <span className="min-w-0 flex-1 font-medium text-foreground">{item.label}</span>
                <Chip className={REASON_CLASS[item.reason]}>{PREP_FOLLOWUP_REASON_LABELS[item.reason]}</Chip>
              </div>
              {!compact && item.quote && onQuote ? (
                <div className="pl-5">
                  <QuoteButton quote={item.quote} onQuote={onQuote} />
                </div>
              ) : null}
              {item.note ? <p className="pl-5 text-xs text-muted-foreground">Przećwicz: {item.note}</p> : null}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function Prep2Comparison({ prep }: { prep: Prep }) {
  const rows = prep.review?.criteria.comparison ?? [];
  if (rows.length === 0) return null;
  const open = rows.filter((r) => r.after !== "strong");
  return (
    <div className="flex flex-col gap-2">
      <div className="font-semibold text-foreground">Punkty z Prepu 1 — co się poprawiło</div>
      <ul className="divide-y divide-border rounded-lg border border-border">
        {rows.map((r) => (
          <li key={r.key} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
            <span className="min-w-0 text-foreground">{r.label}</span>
            <span className="flex items-center gap-1.5">
              {r.before ? <Chip className={REASON_CLASS[r.before]}>{PREP_FOLLOWUP_REASON_LABELS[r.before]}</Chip> : null}
              <span aria-hidden>→</span>
              <span className="sr-only">teraz</span>
              <Chip className={GRADE_CLASS[r.after]}>{PREP_GRADE_LABELS[r.after]}</Chip>
            </span>
          </li>
        ))}
      </ul>
      <p
        className={cn(
          "rounded-lg px-3 py-2",
          open.length === 0 ? "bg-success-muted text-success-muted-foreground" : "bg-warning-muted text-warning-muted-foreground",
        )}
      >
        {open.length === 0
          ? "Na rozmowę u klienta nie zostało nic z Prepu 1."
          : `Na rozmowę u klienta zostało: ${open.map((r) => r.label).join(", ")}.`}
      </p>
    </div>
  );
}

// ── Transkrypt ───────────────────────────────────────────────────────────────

const ROLE_CLASS: Record<string, string> = {
  candidate: "text-primary",
  staff: "text-warning-muted-foreground",
  unknown: "text-muted-foreground",
};

export function ReviewTranscriptTab({
  transcript,
  isPending,
  error,
  focusQuote,
}: {
  transcript: PrepTranscript | undefined;
  isPending: boolean;
  error: unknown;
  focusQuote: string | null;
}) {
  const [query, setQuery] = useState("");
  const focusRef = useRef<HTMLLIElement | null>(null);
  const cues = useMemo(() => transcript?.cues ?? [], [transcript]);
  const focusIndex = useMemo(() => cueIndexForQuote(cues, focusQuote), [cues, focusQuote]);

  useEffect(() => {
    focusRef.current?.scrollIntoView?.({ block: "center" });
  }, [focusIndex]);

  if (isPending) return <p className="text-sm text-muted-foreground">Ładowanie transkryptu…</p>;
  if (error || !transcript) {
    return (
      <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
        {apiErrorMessage(error, "Nie udało się wczytać transkryptu.")}
      </p>
    );
  }
  if (cues.length === 0) {
    return (
      <pre className="max-h-[60dvh] overflow-y-auto whitespace-pre-wrap rounded-lg bg-muted/50 p-3 font-sans text-xs text-foreground">
        {transcript.text}
      </pre>
    );
  }

  const hasSpeakers = cues.some((c) => c.speaker);
  const candidate = transcript.speakers.filter((s) => s.role === "candidate");
  const needle = normalizeForQuote(query);
  const visible = cues
    .map((cue, index) => ({ cue, index }))
    .filter(({ cue }) => !needle || normalizeForQuote(`${cue.speaker ?? ""} ${cue.text}`).includes(needle));

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex min-h-10 w-0 min-w-[14rem] flex-1 items-center gap-2 rounded-md border border-border bg-card px-3">
          <Search className="h-4 w-4 text-muted-foreground" aria-hidden />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Szukaj w rozmowie"
            aria-label="Szukaj w rozmowie"
            className="w-0 flex-1 bg-transparent text-sm outline-none"
          />
        </label>
        {hasSpeakers && candidate.length > 0 ? (
          <span className="text-xs text-muted-foreground">
            Mówcy: {transcript.speakers.map((s) => s.name).join(", ")}
          </span>
        ) : null}
      </div>
      {!hasSpeakers ? (
        <p className="rounded-md bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground">
          Bez podziału na mówców — Teams go nie podał. Włącza to administrator w Teams (Meeting settings → speaker attribution).
        </p>
      ) : null}
      <ol className="max-h-[60dvh] divide-y divide-border overflow-y-auto rounded-lg border border-border">
        {visible.map(({ cue, index }) => (
          <li
            key={index}
            ref={index === focusIndex ? focusRef : undefined}
            className={cn("grid grid-cols-[3.5rem_minmax(0,1fr)] gap-3 px-3 py-2 text-sm", index === focusIndex && "bg-warning-muted")}
            data-focused={index === focusIndex ? "true" : undefined}
          >
            <span className="tabular-nums text-xs text-muted-foreground">{formatCueTime(cue.start)}</span>
            <div className="min-w-0">
              {cue.speaker ? (
                <div className={cn("text-xs font-semibold", ROLE_CLASS[cue.role ?? "unknown"])}>
                  {cue.speaker}
                  {cue.role === "candidate" ? " · kandydat" : ""}
                </div>
              ) : null}
              <div className="text-foreground">{cue.text}</div>
            </div>
          </li>
        ))}
      </ol>
      {visible.length === 0 ? <p className="text-sm text-muted-foreground">Nic nie pasuje do „{query}”.</p> : null}
    </div>
  );
}
