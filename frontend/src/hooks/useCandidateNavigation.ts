/**
 * Hook driving "next/previous candidate" navigation from a filtered search.
 *
 * Two modes:
 *
 * 1. `embedded` — parent (CandidatesListV2) already has the current page of
 *    results in memory. It passes them in as `pageItems` so we render
 *    instantly. We still fetch adjacent pages on demand when navigation
 *    crosses a page boundary.
 *
 * 2. `url` — the candidate profile is opened on its own page
 *    (`/candidates/[id]?nav=search&pos=N&...filters`). The hook decodes the
 *    filters from URL, fetches the page that contains `pos`, and resolves
 *    the candidate at that position.
 *
 * Navigation deliberately requests the light list payload — match stats,
 * active pipelines and last-activity joins are presentation data and are not
 * needed to resolve an adjacent candidate id.
 *
 * Keyboard: `K` = prev, `J` = next. Disabled while focus is in an
 * input/textarea/contenteditable.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import {
  type CandidateFilters,
  filtersToApiParams,
} from "@/lib/url-filters";
import { isInputActive } from "@/components/KeyboardShortcuts";

const DEFAULT_PAGE_SIZE = 20;

export interface CandidateLite {
  id: number;
  name?: string;
  lastname?: string;
}

interface CandidatesPage {
  items: CandidateLite[];
  total: number;
  page: number;
  page_size: number;
}

interface BaseOptions {
  /** Whether keyboard shortcuts and click handlers are enabled. */
  enabled: boolean;
  /** Filter state describing which list we're navigating. */
  filters: CandidateFilters;
  /** 1-based position within the filtered list. */
  position: number;
  /** Called with the new candidate id when user navigates. */
  onNavigate: (next: { candidateId: number; position: number }) => void;
}

interface EmbeddedOptions extends BaseOptions {
  mode: "embedded";
  /** Items already loaded by parent (current page). */
  pageItems: CandidateLite[];
  /** Total filtered count from parent. */
  total: number;
  /** Page number `pageItems` belongs to (1-based). */
  pageNumber: number;
  /** Page size (defaults to 20). */
  pageSize?: number;
}

interface UrlOptions extends BaseOptions {
  mode: "url";
}

type Options = EmbeddedOptions | UrlOptions;

export interface NavigationState {
  position: number;
  total: number;
  hasPrev: boolean;
  hasNext: boolean;
  isLoading: boolean;
  error: string | null;
  goPrev: () => void;
  goNext: () => void;
  retry: () => void;
}

const candidatesPageQueryKey = (filters: CandidateFilters, page: number) =>
  ["candidate-nav", filters, page] as const;

const positionToPage = (position: number, pageSize: number) =>
  Math.max(1, Math.floor((position - 1) / pageSize) + 1);

const positionWithinPage = (position: number, pageSize: number) =>
  ((position - 1) % pageSize + pageSize) % pageSize;

async function fetchCandidatesPage(
  filters: CandidateFilters,
  page: number,
  signal?: AbortSignal,
): Promise<CandidatesPage> {
  const params = filtersToApiParams(filters, page);
  const res = await api.get<CandidatesPage>("/api/candidates", {
    params,
    paramsSerializer: { indexes: null },
    signal,
  });
  return res.data;
}

export function useCandidateNavigation(opts: Options): NavigationState {
  const { enabled, filters, position, onNavigate } = opts;
  const pageSize =
    opts.mode === "embedded"
      ? opts.pageSize ?? DEFAULT_PAGE_SIZE
      : DEFAULT_PAGE_SIZE;

  // Track total locally so it stays correct after URL-mode fetch resolves.
  const [trackedTotal, setTrackedTotal] = useState<number | null>(
    opts.mode === "embedded" ? opts.total : null,
  );
  const [navigationError, setNavigationError] = useState<string | null>(null);

  const targetPage = positionToPage(position, pageSize);
  const parentPage = opts.mode === "embedded" ? opts.pageNumber : null;
  const parentItems = opts.mode === "embedded" ? opts.pageItems : null;

  // Fetch the page that contains `position` whenever we don't already have it
  // from the parent.
  const needsFetch =
    !enabled
      ? false
      : opts.mode === "url"
      ? true
      : targetPage !== parentPage;

  const pageQuery = useQuery({
    queryKey: candidatesPageQueryKey(filters, targetPage),
    queryFn: ({ signal }) => fetchCandidatesPage(filters, targetPage, signal),
    enabled: needsFetch,
    staleTime: 30_000,
  });

  useEffect(() => {
    if (pageQuery.data?.total !== undefined) {
      setTrackedTotal(pageQuery.data.total);
    }
  }, [pageQuery.data?.total]);

  // Effective items / total at the current position.
  const effectiveItems: CandidateLite[] = useMemo(() => {
    if (opts.mode === "embedded" && targetPage === parentPage && parentItems) {
      return parentItems;
    }
    return pageQuery.data?.items ?? [];
  }, [opts.mode, parentItems, parentPage, targetPage, pageQuery.data?.items]);

  const total =
    opts.mode === "embedded"
      ? opts.total
      : trackedTotal ?? pageQuery.data?.total ?? 0;

  const hasPrev = enabled && position > 1;
  const hasNext = enabled && total > 0 && position < total;
  const isLoading = pageQuery.isFetching;

  // Navigate by computing target position, locating its candidate id in the
  // appropriate page (current or to-be-fetched), and calling onNavigate. If
  // we don't yet have the target page in cache, we fetch it inline.
  const navigateTo = useCallback(
    async (nextPosition: number) => {
      if (nextPosition < 1 || (total > 0 && nextPosition > total)) return;
      const nextPage = positionToPage(nextPosition, pageSize);
      const idx = positionWithinPage(nextPosition, pageSize);

      // Same page as currently rendered → use what we have.
      if (nextPage === targetPage && effectiveItems[idx]) {
        onNavigate({ candidateId: effectiveItems[idx].id, position: nextPosition });
        return;
      }

      // Different page → fetch it (react-query will cache by queryKey).
      try {
        setNavigationError(null);
        const data = await fetchCandidatesPage(filters, nextPage);
        const target = data.items[idx];
        if (target) {
          setTrackedTotal(data.total);
          onNavigate({ candidateId: target.id, position: nextPosition });
        }
      } catch {
        setNavigationError("Nie udało się pobrać kolejnego kandydata");
      }
    },
    [effectiveItems, filters, onNavigate, pageSize, targetPage, total],
  );

  const goPrev = useCallback(() => {
    if (!hasPrev) return;
    void navigateTo(position - 1);
  }, [hasPrev, position, navigateTo]);

  const goNext = useCallback(() => {
    if (!hasNext) return;
    void navigateTo(position + 1);
  }, [hasNext, position, navigateTo]);

  // Keyboard shortcuts: K (previous) and J (next), mirroring list navigation.
  useEffect(() => {
    if (!enabled) return;
    const handler = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || e.shiftKey) return;
      if (isInputActive()) return;
      if (e.key.toLowerCase() === "k") {
        e.preventDefault();
        goPrev();
      } else if (e.key.toLowerCase() === "j") {
        e.preventDefault();
        goNext();
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [enabled, goPrev, goNext]);

  const retry = useCallback(() => {
    setNavigationError(null);
    void pageQuery.refetch();
  }, [pageQuery]);

  const queryError = pageQuery.error
    ? "Nie udało się pobrać listy kandydatów"
    : null;

  return {
    position,
    total,
    hasPrev,
    hasNext,
    isLoading,
    error: navigationError ?? queryError,
    goPrev,
    goNext,
    retry,
  };
}
