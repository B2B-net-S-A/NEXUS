"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { candidateSearchApi } from "@/lib/candidate-search-api";
import type { MatchBreakdown } from "@/lib/match-breakdown";

/**
 * Mirror of `MATCH_SCORES_MAX_CANDIDATES` in
 * `backend/app/schemas/candidate_search.py`. Canonical fit is measured ON
 * DEMAND (query vector + exact vector provenance + scoring), so one request
 * covers what a recruiter can see at once — never the whole 50-row page.
 */
export const MATCH_SCORES_MAX_CANDIDATES = 20;

/** How long rows that scroll into view are gathered into one request. */
const BATCH_WINDOW_MS = 120;

/**
 * A 429 is retried on its own in this many ROUNDS, the delay doubling from
 * `RATE_LIMIT_RETRY_BASE_MS` (5, 10, 20, 40 s — past the server's one-minute
 * window). One round re-asks every row that got a 429 since the last round,
 * whichever request it came from. After the last round the row keeps its
 * "ponów" control.
 */
export const RATE_LIMIT_MAX_AUTO_RETRIES = 4;
export const RATE_LIMIT_RETRY_BASE_MS = 5_000;

/**
 * Why a row that was asked for has no score. Distinct from "not asked yet"
 * (no marker) and from "Ocena niepełna" (answered: no verified measurement).
 */
export type ScoreFailure =
  /** 403 — no access to canonical fit for this recruitment; not retried. */
  | "forbidden"
  /** 429, 5xx, network — "nie policzono", can be asked again. */
  | "retry";

function httpStatus(error: unknown): number | undefined {
  if (typeof error !== "object" || error === null || !("response" in error)) {
    return undefined;
  }
  const status = (error as { response?: { status?: unknown } }).response?.status;
  return typeof status === "number" ? status : undefined;
}

export function scoreFailureFor(error: unknown): ScoreFailure {
  return httpStatus(error) === 403 ? "forbidden" : "retry";
}

/** 429 from the scoring endpoints' rate limit — worth retrying on its own. */
export function isRateLimited(error: unknown): boolean {
  return httpStatus(error) === 429;
}

/**
 * Up to `max` ids that became visible and were not requested yet, in display
 * order — so the top of the screen is scored first.
 */
export function pickScoreRequestIds(
  displayOrder: readonly number[],
  pending: ReadonlySet<number>,
  requested: ReadonlySet<number>,
  max: number = MATCH_SCORES_MAX_CANDIDATES,
): number[] {
  const out: number[] = [];
  for (const id of displayOrder) {
    if (out.length >= max) break;
    if (pending.has(id) && !requested.has(id)) out.push(id);
  }
  return out;
}

interface ScoreState {
  epoch: object;
  scores: Record<string, number>;
  breakdowns: Record<string, MatchBreakdown>;
  failures: Record<string, ScoreFailure>;
}

/** Bookkeeping of one result set (one `epoch`). */
interface Book {
  epoch: object;
  /** Visible, waiting for the next request. */
  pending: Set<number>;
  /** Asked for (in flight or answered) under `profileKey`. */
  requested: Set<number>;
  /** Every row reported on screen — re-asked if the profile changes. */
  seen: Set<number>;
  /** Failed with "retry" — what the "ponów" control asks for again. */
  retryable: Set<number>;
  /** The server said 403 for this recruitment: stop asking. */
  forbidden: boolean;
  /** Weight profile the held scores were computed under (`profile_key`). */
  profileKey: string | null;
  controllers: Set<AbortController>;
  /** Rows whose last answer was a 429 — what the next retry round re-asks. */
  rateLimited: Set<number>;
  /** Automatic retry rounds since the last answer — the back-off exponent. */
  retryRounds: number;
  /** The ONE pending retry round of this result set. */
  retryTimer: ReturnType<typeof setTimeout> | null;
}

const EMPTY_SCORES: Record<string, number> = {};
const EMPTY_BREAKDOWNS: Record<string, MatchBreakdown> = {};
const EMPTY_FAILURES: Record<string, ScoreFailure> = {};

function newBook(epoch: object): Book {
  return {
    epoch,
    pending: new Set(),
    requested: new Set(),
    seen: new Set(),
    retryable: new Set(),
    forbidden: false,
    profileKey: null,
    controllers: new Set(),
    rateLimited: new Set(),
    retryRounds: 0,
    retryTimer: null,
  };
}

/** Cancel everything a superseded result set still has in flight. */
function retire(book: Book): void {
  for (const controller of book.controllers) controller.abort();
  book.controllers.clear();
  if (book.retryTimer !== null) clearTimeout(book.retryTimer);
  book.retryTimer = null;
}

function emptyState(epoch: object): ScoreState {
  return {
    epoch,
    scores: EMPTY_SCORES,
    breakdowns: EMPTY_BREAKDOWNS,
    failures: EMPTY_FAILURES,
  };
}

/**
 * Canonical fit badges for the rows a recruiter actually sees.
 *
 * Rows report themselves with `onRowVisible(id)` when they enter the viewport;
 * ids seen within a short window go out in ONE request of at most
 * `MATCH_SCORES_MAX_CANDIDATES`, top of the screen first. Each row is asked
 * for once per result set. A new result set (or job) starts over: its `epoch`
 * changes, requests still in flight for the previous one are aborted, and a
 * late answer for it is dropped.
 *
 * The cache is also keyed by the weight profile the server scored under
 * (`profile_key`): when it changes, the rows held under the old profile are
 * dropped and asked for again — two profiles never share one screen.
 *
 * A failure is never shown as "no score yet": a 403 marks the row
 * `forbidden` ("brak dostępu") and stops asking for this recruitment; any
 * other failure marks it `retry` ("nie policzono — ponów") until `retry()` —
 * and a 429 is retried on its own with a doubling delay.
 */
export function useVisibleMatchScores(
  jobId: number | null | undefined,
  items: readonly { id: number }[] | null | undefined,
) {
  // A fresh identity per (job, result set) — compared by reference only.
  const epoch = useMemo(() => ({ jobId, items }), [jobId, items]);
  const order = useMemo(() => (items ?? []).map((item) => item.id), [items]);
  const [state, setState] = useState<ScoreState>(() => emptyState(epoch));
  const book = useRef<Book>(newBook(epoch));
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Lets timers and answers of this render call the current closures.
  const flushRef = useRef<() => void>(() => {});

  const schedule = useCallback((delay: number) => {
    if (timer.current === null) {
      timer.current = setTimeout(() => flushRef.current(), delay);
    }
  }, []);

  const updateFailures = useCallback(
    (ids: readonly number[], failure: ScoreFailure | null) => {
      setState((prev) => {
        const base = prev.epoch === epoch ? prev : emptyState(epoch);
        const failures = { ...base.failures };
        for (const id of ids) {
          if (failure === null) delete failures[String(id)];
          else failures[String(id)] = failure;
        }
        return { ...base, failures };
      });
    },
    [epoch],
  );

  /** Put `ids` back in the queue of the CURRENT result set. */
  const requeue = useCallback(
    (current: Book, ids: readonly number[]) => {
      if (book.current !== current || current.forbidden || ids.length === 0) return;
      for (const id of ids) {
        current.retryable.delete(id);
        current.rateLimited.delete(id);
        current.requested.delete(id);
        current.pending.add(id);
      }
      updateFailures(ids, null);
      schedule(0);
    },
    [schedule, updateFailures],
  );

  const flush = useCallback(() => {
    timer.current = null;
    const current = book.current;
    if (jobId == null || current.epoch !== epoch || current.forbidden) return;
    const batch = pickScoreRequestIds(order, current.pending, current.requested);
    if (batch.length === 0) return;
    for (const id of batch) {
      current.pending.delete(id);
      current.requested.add(id);
    }
    const controller = new AbortController();
    current.controllers.add(controller);
    candidateSearchApi
      .matchScores(jobId, batch, { signal: controller.signal })
      .then((response) => {
        if (controller.signal.aborted || book.current !== current) return;
        current.retryRounds = 0;
        const key = response.profile_key ?? null;
        const switched =
          key !== null && current.profileKey !== null && key !== current.profileKey;
        if (key !== null) current.profileKey = key;
        if (switched) {
          // Answers sent under the previous profile are superseded, and the
          // rows it scored are asked for again under this one.
          for (const other of current.controllers) {
            if (other !== controller) other.abort();
          }
          const again = [...current.seen].filter((id) => !batch.includes(id));
          for (const id of again) {
            current.requested.delete(id);
            current.retryable.delete(id);
            current.rateLimited.delete(id);
            current.pending.add(id);
          }
          schedule(0);
        }
        for (const id of batch) {
          current.retryable.delete(id);
          current.rateLimited.delete(id);
        }
        setState((prev) => {
          const base = prev.epoch === epoch && !switched ? prev : emptyState(epoch);
          const failures = { ...base.failures };
          for (const id of batch) delete failures[String(id)];
          return {
            epoch,
            scores: { ...base.scores, ...response.scores },
            breakdowns: { ...base.breakdowns, ...response.breakdowns },
            failures,
          };
        });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || book.current !== current) return;
        const failure = scoreFailureFor(error);
        if (failure === "forbidden") {
          current.forbidden = true;
          current.pending.clear();
          updateFailures([...current.seen], "forbidden");
          return;
        }
        for (const id of batch) current.retryable.add(id);
        updateFailures(batch, "retry");
        if (!isRateLimited(error)) return;
        for (const id of batch) current.rateLimited.add(id);
        // ONE pending round per result set, re-asking EVERY row a 429 left
        // behind. A 429 while a round is pending joins that round — replacing
        // its timer (as each 429 did until 11.09) dropped the rows of the
        // earlier request: with two requests in flight rows 1–20 stayed on
        // "ponów" for good. The back-off advances once per round, not per
        // answer: two 429s of one round are one wait, not two doublings.
        if (current.retryTimer !== null) return;
        if (current.retryRounds >= RATE_LIMIT_MAX_AUTO_RETRIES) return;
        const delay = RATE_LIMIT_RETRY_BASE_MS * 2 ** current.retryRounds;
        current.retryRounds += 1;
        current.retryTimer = setTimeout(() => {
          current.retryTimer = null;
          const ids = [...current.rateLimited].filter((id) => current.retryable.has(id));
          current.rateLimited.clear();
          requeue(current, ids);
        }, delay);
      })
      .finally(() => {
        current.controllers.delete(controller);
      });
    // More rows came into view than one request may carry: next batch.
    if (current.pending.size > 0) schedule(0);
  }, [epoch, jobId, order, requeue, schedule, updateFailures]);

  useEffect(() => {
    flushRef.current = flush;
  }, [flush]);

  // A superseded result set (or unmount) cancels what it still has in flight.
  useEffect(
    () => () => {
      if (book.current.epoch === epoch) retire(book.current);
    },
    [epoch],
  );

  useEffect(
    () => () => {
      if (timer.current !== null) clearTimeout(timer.current);
      timer.current = null;
    },
    [],
  );

  const onRowVisible = useCallback(
    (id: number) => {
      if (jobId == null) return;
      if (book.current.epoch !== epoch) {
        // First row of a new result set: forget the previous one, including
        // a flush it had scheduled (it would bail out on the old epoch and
        // strand this set's pending rows).
        retire(book.current);
        if (timer.current !== null) clearTimeout(timer.current);
        timer.current = null;
        book.current = newBook(epoch);
      }
      const current = book.current;
      current.seen.add(id);
      if (current.forbidden) {
        updateFailures([id], "forbidden");
        return;
      }
      if (current.requested.has(id)) return;
      current.pending.add(id);
      schedule(BATCH_WINDOW_MS);
    },
    [epoch, jobId, schedule, updateFailures],
  );

  /** Ask again for every row that failed with "nie policzono — ponów". */
  const retry = useCallback(() => {
    const current = book.current;
    if (current.epoch !== epoch) return;
    if (current.retryTimer !== null) clearTimeout(current.retryTimer);
    current.retryTimer = null;
    requeue(current, [...current.retryable]);
  }, [epoch, requeue]);

  const visible = state.epoch === epoch;
  return {
    scores: visible ? state.scores : EMPTY_SCORES,
    breakdowns: visible ? state.breakdowns : EMPTY_BREAKDOWNS,
    failures: visible ? state.failures : EMPTY_FAILURES,
    onRowVisible,
    retry,
  };
}
