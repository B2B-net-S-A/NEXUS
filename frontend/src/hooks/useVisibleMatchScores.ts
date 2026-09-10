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
}

interface Book {
  epoch: object;
  pending: Set<number>;
  requested: Set<number>;
}

const EMPTY_SCORES: Record<string, number> = {};
const EMPTY_BREAKDOWNS: Record<string, MatchBreakdown> = {};

/**
 * Canonical fit badges for the rows a recruiter actually sees.
 *
 * Rows report themselves with `onRowVisible(id)` when they enter the viewport;
 * ids seen within a short window go out in ONE request of at most
 * `MATCH_SCORES_MAX_CANDIDATES`, top of the screen first. Each row is asked
 * for once per result set. A new result set (or job) starts over: its
 * `epoch` changes, so scores of the previous rows never leak onto the next
 * ones and a late response for an old result set is dropped.
 *
 * A failed request leaves those rows without a badge and is not retried in a
 * loop — the column is decoration of a search that already rendered.
 */
export function useVisibleMatchScores(
  jobId: number | null | undefined,
  items: readonly { id: number }[] | null | undefined,
) {
  // A fresh identity per (job, result set) — compared by reference only.
  const epoch = useMemo(() => ({ jobId, items }), [jobId, items]);
  const order = useMemo(() => (items ?? []).map((item) => item.id), [items]);
  const [state, setState] = useState<ScoreState>(() => ({
    epoch,
    scores: EMPTY_SCORES,
    breakdowns: EMPTY_BREAKDOWNS,
  }));
  const book = useRef<Book>({ epoch, pending: new Set(), requested: new Set() });
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) clearTimeout(timer.current);
    },
    [],
  );

  const flush = useCallback(() => {
    timer.current = null;
    const current = book.current;
    if (jobId == null || current.epoch !== epoch) return;
    const batch = pickScoreRequestIds(order, current.pending, current.requested);
    if (batch.length === 0) return;
    for (const id of batch) {
      current.pending.delete(id);
      current.requested.add(id);
    }
    candidateSearchApi
      .matchScores(jobId, batch)
      .then((response) => {
        if (book.current.epoch !== epoch) return; // an earlier result set
        setState((prev) => {
          const base =
            prev.epoch === epoch
              ? prev
              : { epoch, scores: EMPTY_SCORES, breakdowns: EMPTY_BREAKDOWNS };
          return {
            epoch,
            scores: { ...base.scores, ...response.scores },
            breakdowns: { ...base.breakdowns, ...response.breakdowns },
          };
        });
      })
      .catch(() => {
        // Rows stay without a badge; nothing is retried in a loop.
      });
    // More rows came into view than one request may carry: next batch.
    if (current.pending.size > 0) timer.current = setTimeout(flush, 0);
  }, [epoch, jobId, order]);

  const onRowVisible = useCallback(
    (id: number) => {
      if (jobId == null) return;
      if (book.current.epoch !== epoch) {
        // First row of a new result set: forget the previous one, including
        // a flush it had scheduled (it would bail out on the old epoch and
        // strand this set's pending rows).
        if (timer.current !== null) clearTimeout(timer.current);
        timer.current = null;
        book.current = { epoch, pending: new Set(), requested: new Set() };
      }
      const current = book.current;
      if (current.requested.has(id) || current.pending.has(id)) return;
      current.pending.add(id);
      if (timer.current === null) timer.current = setTimeout(flush, BATCH_WINDOW_MS);
    },
    [epoch, jobId, flush],
  );

  const visible = state.epoch === epoch;
  return {
    scores: visible ? state.scores : EMPTY_SCORES,
    breakdowns: visible ? state.breakdowns : EMPTY_BREAKDOWNS,
    onRowVisible,
  };
}
