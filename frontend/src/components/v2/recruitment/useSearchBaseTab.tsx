"use client";

/**
 * Zakładka „Szukaj w bazie” okna „Kandydaci do dodania” (02.10.2026).
 *
 * Zastępuje „Znajdź w bazie (AI)”: wyszukiwanie rusza samo, po SŁOWACH, które
 * Delivery Lead wpisał w sekcji 2 Championa („Wymagania do wyszukiwania”) —
 * ten sam silnik i te same filtry startowe co pełne „Szukaj ręcznie”. Zdania
 * z must-have („Minimum 5 lat doświadczenia…”) nie są kryterium: stoją osobno
 * jako rzeczy do sprawdzenia w rozmowie.
 *
 * Lista jest krótka (strony po 20, „Pokaż więcej”) i ma ten sam podgląd osoby
 * co pozostałe zakładki. Zmiana słów i filtrów = pełne „Szukaj ręcznie”.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery, useQueries, useQueryClient } from "@tanstack/react-query";
import { UserPlus } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FieldSnippets, type FieldSnippet } from "@/components/v2/MatchSnippet";
import type { SourceTabSlots } from "@/components/v2/jobs/SimilarJobsPanel";
import { fetchCandidateListPage } from "@/components/v2/pages/candidate-list-query";
import { getCurrentTitle, type CandidateLite } from "@/components/v2/pages/candidate-list-helpers";
import { apiErrorMessage } from "@/lib/api-error";
import { formatReasonCounts, summarizeBulkResult } from "@/lib/bulk-result-summary";
import { candidateSearchApi, proposalsBulkApi } from "@/lib/candidate-search-api";
import { jobProposalsKeys } from "@/lib/job-proposals-api";
import { requirementLabel } from "@/lib/keyword-requirements";
import { yearsLabel } from "@/lib/proposal-facts";
import { formatHourlyRate } from "@/lib/proposals-merge";
import { filtersToApiParams } from "@/lib/url-filters";

import { PersonPreview } from "./PersonPreview";
import { PickList, ScoreBadge, type PickRow } from "./pick-list";
import type { JobSearchSeed } from "./useJobSearchSeed";

export const SEARCH_BASE_PAGE = 20;

interface SearchCandidate extends CandidateLite {
  id: number;
  city?: string | null;
  location?: string | null;
  expected_rate_hourly?: number | string | null;
  expected_rate_currency?: string | null;
  match_snippets?: FieldSnippet[] | null;
}

interface SearchPage {
  items: SearchCandidate[];
  total: number;
  page: number;
  page_size: number;
}

/** Klucz listy wyników — także kafel czyta stąd liczbę osób. */
export const searchBaseKey = (jobId: number, filtersKey: string) =>
  ["job-search-base", jobId, filtersKey] as const;

function fullName(c: SearchCandidate): string {
  return `${c.name ?? ""} ${c.lastname ?? ""}`.trim() || `Kandydat #${c.id}`;
}

function rateLabel(c: SearchCandidate): string | null {
  if (c.expected_rate_currency && c.expected_rate_currency !== "PLN") return null;
  const value = typeof c.expected_rate_hourly === "string" ? Number(c.expected_rate_hourly) : c.expected_rate_hourly;
  return formatHourlyRate(value ?? null);
}

export interface SearchBaseTabOptions {
  enabled: boolean;
  seed: JobSearchSeed;
  /** Must-have, po których nie szukamy (zdania) — z `GET …/proposal-counts`. */
  notSearchable: readonly string[];
  readOnly?: boolean;
  canOpenProfile: boolean;
  /** Pełne „Szukaj ręcznie” (zmiana słów i filtrów). */
  onOpenManualSearch: () => void;
  /** Sekcja 2 Championa — tam Delivery Lead wpisuje słowa. */
  onOpenChampionSearch?: () => void;
}

export interface SearchBaseTab extends SourceTabSlots {
  /** Liczba wyników; `null` = jeszcze nie wiadomo albo brak słów w Championie. */
  total: number | null;
}

export function useSearchBaseTab(
  jobId: number,
  {
    enabled,
    seed,
    notSearchable,
    readOnly = false,
    canOpenProfile,
    onOpenManualSearch,
    onOpenChampionSearch,
  }: SearchBaseTabOptions,
): SearchBaseTab {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [selected, setSelected] = useState<ReadonlySet<number>>(() => new Set());
  const [previewId, setPreviewId] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const previewTrigger = useRef<HTMLElement | null>(null);

  const filtersKey = seed.filters ? JSON.stringify(seed.filters) : "";
  // Bez wierszy w Championie nie ma po czym szukać — cała baza pod nagłówkiem
  // „wyniki wyszukiwania” byłaby obietnicą bez pokrycia.
  const canSearch = enabled && seed.ready && seed.hasRows && seed.filters != null;
  const list = useInfiniteQuery({
    queryKey: searchBaseKey(jobId, filtersKey),
    enabled: canSearch,
    initialPageParam: 1,
    queryFn: ({ pageParam, signal }) =>
      fetchCandidateListPage<SearchPage>(
        filtersToApiParams(seed.filters!, pageParam, { page_size: SEARCH_BASE_PAGE }),
        signal,
      ),
    getNextPageParam: (last, pages) =>
      pages.length * SEARCH_BASE_PAGE < (last?.total ?? 0) ? pages.length + 1 : undefined,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
  const pages = useMemo(() => list.data?.pages ?? [], [list.data]);
  const items = useMemo(() => pages.flatMap((page) => page.items ?? []), [pages]);
  const total = list.isSuccess ? (pages[0]?.total ?? 0) : null;

  // Dopasowanie do TEJ rekrutacji — jedno zapytanie na stronę wyników (≤ 20
  // osób, limit trasy). Błąd albo brak pomiaru = „nie policzono”, nigdy 0.
  const scoreQueries = useQueries({
    queries: pages.map((page) => {
      const ids = (page.items ?? []).map((c) => c.id);
      return {
        queryKey: ["job-search-base-scores", jobId, ids.join(",")],
        queryFn: ({ signal }: { signal: AbortSignal }) =>
          candidateSearchApi.matchScores(jobId, ids, { signal }),
        enabled: canSearch && ids.length > 0,
        staleTime: 5 * 60_000,
        retry: false,
      };
    }),
  });
  const scores = new Map<number, number>();
  for (const query of scoreQueries) {
    for (const [id, value] of Object.entries(query.data?.scores ?? {})) {
      if (typeof value === "number") scores.set(Number(id), value);
    }
  }
  const scoresPending = scoreQueries.some((q) => q.isPending && q.fetchStatus !== "idle");

  const rows: PickRow[] = items.map((c) => ({
    candidateId: c.id,
    fullName: fullName(c),
    fitScore: scores.get(c.id) ?? null,
    rateLabel: null,
    availabilityLabel: null,
    note: null,
    facts:
      [getCurrentTitle(c), yearsLabel(c.years_it_experience), c.city?.trim() || null, rateLabel(c)]
        .filter(Boolean)
        .join(" · ") || null,
    sourceLabel: null,
    warnings: [],
    extra: c.match_snippets?.length ? (
      <FieldSnippets snippets={c.match_snippets} className="mt-0.5" />
    ) : undefined,
  }));

  const previewIndex = previewId == null ? -1 : items.findIndex((c) => c.id === previewId);
  const previewItem = previewIndex >= 0 ? items[previewIndex] : null;
  // Osoba dodana do rekrutacji znika z wyników — jej karta też.
  useEffect(() => {
    if (previewId != null && list.isSuccess && previewIndex < 0) setPreviewId(null);
  }, [previewId, previewIndex, list.isSuccess]);

  const closePreview = () => {
    setPreviewId(null);
    const trigger = previewTrigger.current;
    if (trigger?.isConnected) trigger.focus();
  };
  const toggle = (candidateId: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(candidateId)) next.delete(candidateId);
      else next.add(candidateId);
      return next;
    });

  const count = selected.size;
  const addSelected = async () => {
    if (readOnly || count === 0) return;
    setAdding(true);
    try {
      const result = await proposalsBulkApi.add(jobId, {
        candidate_ids: [...selected],
        initial_stage_legacy: "new",
        source: "manual_search",
      });
      const summary = summarizeBulkResult(result);
      const parts = [
        result.total_added > 0 ? `Dodano do Nowych: ${result.total_added}.` : "Nikogo nie dodano.",
      ];
      if (summary.skipped.length > 0) parts.push(`Pominięto: ${formatReasonCounts(summary.skipped)}.`);
      if (summary.warnings.length > 0) parts.push(`Uwaga: ${formatReasonCounts(summary.warnings)}.`);
      if (result.total_added > 0) showSuccess(parts.join(" "));
      else showError(parts.join(" "));
      setSelected((prev) => {
        const next = new Set(prev);
        for (const id of result.added) next.delete(id);
        return next;
      });
      void queryClient.invalidateQueries({ queryKey: ["job-search-base", jobId] });
      void queryClient.invalidateQueries({ queryKey: ["candidates-v2"] });
      void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
      void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
      void queryClient.invalidateQueries({ queryKey: ["pipeline-scores"] });
      void queryClient.invalidateQueries({ queryKey: jobProposalsKeys.all(jobId) });
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się dodać kandydatów do rekrutacji."));
    } finally {
      setAdding(false);
    }
  };

  const wordRow = (label: string, row: readonly string[], tone: "must" | "nice" | "not", key: string) => (
    <li key={key} className="flex flex-wrap items-center gap-1.5">
      <span className="w-24 shrink-0 text-xs text-muted-foreground">{label}</span>
      {row.map((word, index) => (
        <span key={`${word}-${index}`} className="inline-flex items-center gap-1.5">
          {index > 0 ? <span className="text-xs text-muted-foreground">lub</span> : null}
          <span
            className={
              tone === "must"
                ? "rounded bg-primary/10 px-1.5 py-0.5 text-xs font-semibold text-primary"
                : tone === "nice"
                  ? "rounded border border-dashed border-border px-1.5 py-0.5 text-xs text-foreground"
                  : "rounded bg-destructive-muted px-1.5 py-0.5 text-xs font-semibold text-destructive-muted-foreground"
            }
          >
            {word}
          </span>
        </span>
      ))}
    </li>
  );

  const body = (
    <div className="space-y-3">
      {!seed.ready ? (
        <p role="status" className="text-sm text-muted-foreground">
          Wczytuję słowa do wyszukiwania…
        </p>
      ) : !seed.hasRows ? (
        <div className="space-y-2 rounded-md border border-dashed border-border p-3" data-testid="search-base-empty">
          <p className="text-sm">
            W Championie nie ma jeszcze słów do wyszukiwania. Wpisuje je Delivery Lead w sekcji
            „Wymagania do wyszukiwania w bazie”.
          </p>
          <div className="flex flex-wrap gap-2">
            {onOpenChampionSearch ? (
              <Button size="sm" variant="outline" onClick={onOpenChampionSearch}>
                Otwórz Championa
              </Button>
            ) : null}
            <Button size="sm" variant="outline" onClick={onOpenManualSearch}>
              Szukaj ręcznie
            </Button>
          </div>
        </div>
      ) : (
        <>
          <section
            aria-label="Słowa do wyszukiwania"
            className="space-y-2 rounded-md bg-muted/50 p-3"
          >
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Słowa z Championa
              </p>
              <button
                type="button"
                onClick={onOpenManualSearch}
                className="text-xs font-semibold text-primary hover:underline"
              >
                Zmień słowa i filtry
              </button>
            </div>
            <ul className="space-y-1.5" aria-label="Wymagania do wyszukiwania">
              {seed.required.map((row, i) => wordRow("Musi mieć", row, "must", `must-${i}`))}
              {seed.preferred.map((row, i) => wordRow("Mile widziane", row, "nice", `nice-${i}`))}
              {seed.exclude.length > 0 ? wordRow("Wyklucz", seed.exclude, "not", "exclude") : null}
            </ul>
            <p className="text-xs text-muted-foreground" data-testid="search-base-summary">
              {list.isError
                ? "Nie udało się wyszukać."
                : total === null
                  ? "Szukam w CV, profilu i notatkach…"
                  : seed.required.length > 0
                    ? `Szukamy w CV, profilu i notatkach: ${seed.required.map(requirementLabel).join(" i ")}. Znaleziono osób: ${total}, od najlepiej dopasowanych.`
                    : `Żaden wiersz nie jest technologią, więc nic nie jest obowiązkowe — osób: ${total}, od najlepiej dopasowanych.`}
            </p>
          </section>

          {notSearchable.length > 0 ? (
            <section
              aria-label="Po tym nie szukamy"
              className="space-y-1 rounded-md border border-dashed border-border p-3"
            >
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Po tym nie szukamy · sprawdzisz w rozmowie
              </p>
              <ul className="space-y-0.5">
                {notSearchable.map((label) => (
                  <li key={label} className="text-sm">
                    {label}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {list.isError ? (
            <p role="alert" className="text-sm text-destructive">
              {apiErrorMessage(list.error, "Nie udało się wyszukać w bazie.")}{" "}
              <button type="button" className="underline" onClick={() => void list.refetch()}>
                Ponów
              </button>
            </p>
          ) : !list.isSuccess ? (
            <p role="status" className="text-sm text-muted-foreground">
              Szukam…
            </p>
          ) : (
            <>
              <PickList
                label="Wyniki wyszukiwania"
                rows={rows}
                selected={selected}
                onToggle={(row) => toggle(row.candidateId)}
                readOnly={readOnly}
                emptyText="Nikt spoza tej rekrutacji nie pasuje do tych słów. Zmień słowa w Championie albo poszukaj ręcznie."
                renderScore={(row) =>
                  row.fitScore != null || !scoresPending ? (
                    <ScoreBadge score={row.fitScore} />
                  ) : (
                    <span className="shrink-0 text-xs text-muted-foreground" role="status">
                      liczę…
                    </span>
                  )
                }
                activeId={previewItem?.id ?? null}
                onPreview={(row, trigger) => {
                  previewTrigger.current = trigger;
                  setPreviewId(row.candidateId);
                }}
                onClosePreview={closePreview}
              />
              {list.hasNextPage ? (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => void list.fetchNextPage()}
                  loading={list.isFetchingNextPage}
                >
                  Pokaż więcej ({items.length} z {total})
                </Button>
              ) : null}
            </>
          )}
        </>
      )}
    </div>
  );

  const footer = (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="text-xs text-muted-foreground" aria-live="polite">
        {readOnly
          ? "Masz tu tylko podgląd — dodawać może zespół rekrutacji."
          : count > 0
            ? `${count} zaznaczonych trafi do »Nowych«, zarezerwowanych dla Ciebie na 12 h.`
            : "Zaznacz osoby — trafią do »Nowych«, zarezerwowane dla Ciebie na 12 h."}
      </p>
      {readOnly ? null : (
        <Button
          onClick={addSelected}
          disabled={count === 0 || adding}
          loading={adding}
          data-testid="search-base-submit"
        >
          <UserPlus className="h-4 w-4" aria-hidden="true" />
          Dodaj {count} do Nowych
        </Button>
      )}
    </div>
  );

  const sidePane = previewItem ? (
    <PersonPreview
      key={previewItem.id}
      jobId={jobId}
      candidateId={previewItem.id}
      name={fullName(previewItem)}
      source={{
        title: "Skąd ta osoba",
        line: "Wyszukiwanie w bazie po słowach z Championa.",
      }}
      extra={
        previewItem.match_snippets?.length
          ? {
              title: "Trafienia słów",
              content: <FieldSnippets snippets={previewItem.match_snippets} />,
            }
          : null
      }
      position={{ index: previewIndex, total: items.length }}
      onPrev={() => setPreviewId(items[previewIndex - 1]?.id ?? previewItem.id)}
      onNext={() => setPreviewId(items[previewIndex + 1]?.id ?? previewItem.id)}
      onClose={closePreview}
      canOpenProfile={canOpenProfile}
      selection={{
        checked: selected.has(previewItem.id),
        disabled: readOnly,
        onToggle: () => toggle(previewItem.id),
        label: "Dodaj tę osobę do „Nowych”",
      }}
    />
  ) : undefined;

  return {
    toolbar: null,
    body,
    footer,
    sidePane,
    total: seed.hasRows ? total : null,
    onEscapeKeyDown: (event) => {
      if (!previewItem) return;
      event.preventDefault();
      closePreview();
    },
  };
}
