"use client";

/**
 * Zakładka „Szukaj w bazie” okna „Kandydaci do dodania” (02.10.2026).
 *
 * Zastępuje „Znajdź w bazie (AI)”: wyszukiwanie rusza samo, po SŁOWACH, które
 * Delivery Lead wpisał w sekcji 2 Championa („Wymagania do wyszukiwania”) —
 * ten sam silnik i te same filtry startowe co pełne „Szukaj ręcznie”. Zdania
 * z must-have („Minimum 5 lat doświadczenia…”), sekcja 4 Championa i język
 * nie są kryterium: stoją w linii „Rekruter sprawdza w rozmowie” (wariant A,
 * 13.10.2026). Każda linia mówi, co robi z listą: wycina, podnosi albo nic.
 *
 * Lista jest krótka (strony po 20, „Pokaż więcej”) i ma ten sam podgląd osoby
 * co pozostałe zakładki. Zmiana słów i filtrów = zakładka „Szukaj ręcznie”
 * tego samego okna (14.10.2026 — zaznaczenia zostają).
 *
 * 14.10.2026: „+ Dodaj” w wierszu, dodana osoba zostaje na liście z „Cofnij”
 * (usunięcie z rekrutacji), a pod faktami chipy powodu z rozbicia dopasowania.
 */

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useInfiniteQuery, useQueries, useQueryClient } from "@tanstack/react-query";
import { UserPlus } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FieldSnippets, type FieldSnippet } from "@/components/v2/MatchSnippet";
import type { SourceTabSlots } from "@/components/v2/jobs/SimilarJobsPanel";
import { fetchCandidateListPage } from "@/components/v2/pages/candidate-list-query";
import { getCurrentTitle, type CandidateLite } from "@/components/v2/pages/candidate-list-helpers";
import { candidatesApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { formatReasonCounts, summarizeBulkResult } from "@/lib/bulk-result-summary";
import { candidateSearchApi, proposalsBulkApi } from "@/lib/candidate-search-api";
import { jobProposalsKeys, talkCheckLabel, type TalkCheck } from "@/lib/job-proposals-api";
import { requirementLabel } from "@/lib/keyword-requirements";
import { yearsLabel } from "@/lib/proposal-facts";
import type { EmploymentMarker } from "@/lib/employment-marker";
import type { MatchBreakdown } from "@/lib/match-breakdown";
import { formatHourlyRate } from "@/lib/proposals-merge";
import { filtersToApiParams } from "@/lib/url-filters";

import { PersonPreview } from "./PersonPreview";
import { PickList, ScoreBadge, type PickRow } from "./pick-list";
import { breakdownReasonChips, withKeptRows } from "./reason-chips";
import type { JobSearchSeed } from "./useJobSearchSeed";

export const SEARCH_BASE_PAGE = 20;

/** Wiersz dodany w tym oknie: miejsce na liście i wynik z chwili dodania. */
interface KeptRow {
  value: SearchCandidate;
  index: number;
  score: number | null;
  breakdown: MatchBreakdown | null;
}

interface SearchCandidate extends CandidateLite {
  id: number;
  city?: string | null;
  location?: string | null;
  expected_rate_hourly?: number | string | null;
  expected_rate_currency?: string | null;
  match_snippets?: FieldSnippet[] | null;
  /** `GET /api/candidates` niesie znacznik „Pracuje u nas” przy każdej osobie. */
  employment_marker?: EmploymentMarker | null;
}

interface SearchPage {
  items: SearchCandidate[];
  total: number;
  page: number;
  page_size: number;
}

type WordTone = "required" | "must" | "nice" | "not" | "place" | "talk";

const WORD_CLASS: Record<WordTone, string> = {
  required: "rounded bg-primary/10 px-1.5 py-0.5 text-xs font-semibold text-primary",
  must: "rounded border border-primary/30 px-1.5 py-0.5 text-xs font-medium text-primary",
  nice: "rounded border border-dashed border-border px-1.5 py-0.5 text-xs text-foreground",
  not: "rounded bg-destructive-muted px-1.5 py-0.5 text-xs font-semibold text-destructive-muted-foreground",
  place: "rounded border border-border bg-card px-1.5 py-0.5 text-xs text-foreground",
  talk: "rounded-full border border-border bg-card px-2 py-0.5 text-xs text-foreground",
};

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
  /** Czego nie szukamy, tylko pytamy w rozmowie — z `GET …/proposal-counts`. */
  talkChecks: readonly TalkCheck[];
  /** Awaria odczytu tej listy — nie udaje „nie ma o co pytać”. */
  talkChecksError?: string | null;
  /** Must-have zdaniem (`not_searchable_must`) — chip „? … — zapytaj” w wierszu. */
  askLabels?: readonly string[];
  /** Osoby już dodane w tym oknie (harness) — wiersz w stanie „Dodano · Cofnij”. */
  initialAddedIds?: readonly number[];
  readOnly?: boolean;
  canOpenProfile: boolean;
  /** Zakładka „Szukaj ręcznie” (zmiana słów i filtrów). */
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
    talkChecks,
    talkChecksError = null,
    askLabels = [],
    initialAddedIds,
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
  // 14.10.2026: osoba dodana w tym oknie zostaje na liście („Dodano do
  // „Nowych” · rezerwacja 12 h · Cofnij”), także gdy odświeżenie wyników już
  // jej nie zwraca — `kept` pamięta wiersz i jego miejsce.
  const [addedIds, setAddedIds] = useState<ReadonlySet<number>>(() => new Set(initialAddedIds ?? []));
  const [kept, setKept] = useState<ReadonlyMap<number, KeptRow>>(() => new Map());
  const [rowAdding, setRowAdding] = useState<ReadonlySet<number>>(() => new Set());
  const [undoing, setUndoing] = useState<ReadonlySet<number>>(() => new Set());
  // U4 (audyt 06.10.2026): osoba, która już jest w rekrutacji, do odświeżenia
  // listy mówi „Dodano” i nie da się jej kliknąć drugi raz.
  const [inJobIds, setInJobIds] = useState<ReadonlySet<number>>(() => new Set());
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
  const liveItems = useMemo(() => pages.flatMap((page) => page.items ?? []), [pages]);
  const items = useMemo(() => withKeptRows(liveItems, kept, (c) => c.id), [liveItems, kept]);
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
  // Rozbicie dopasowania (`matching_must` / `gap_must`) — chipy powodu.
  const breakdowns = new Map<number, MatchBreakdown>();
  for (const query of scoreQueries) {
    for (const [id, value] of Object.entries(query.data?.scores ?? {})) {
      if (typeof value === "number") scores.set(Number(id), value);
    }
    for (const [id, value] of Object.entries(query.data?.breakdowns ?? {})) {
      if (value) breakdowns.set(Number(id), value);
    }
  }
  const scoresPending = scoreQueries.some((q) => q.isPending && q.fetchStatus !== "idle");

  const rows: PickRow[] = items.map((c) => ({
    candidateId: c.id,
    fullName: fullName(c),
    // Dodanego odświeżenie już nie zwraca — wynik z chwili dodania.
    fitScore: scores.get(c.id) ?? kept.get(c.id)?.score ?? null,
    rateLabel: null,
    availabilityLabel: null,
    note: null,
    facts:
      [getCurrentTitle(c), yearsLabel(c.years_it_experience), c.city?.trim() || null, rateLabel(c)]
        .filter(Boolean)
        .join(" · ") || null,
    sourceLabel: null,
    employment: c.employment_marker ?? null,
    warnings: inJobIds.has(c.id) && !addedIds.has(c.id)
      ? [{ key: "added", label: "Dodano do „Nowych”", blocking: true }]
      : [],
    chips: breakdownReasonChips(breakdowns.get(c.id) ?? kept.get(c.id)?.breakdown, askLabels),
    addState: undoing.has(c.id)
      ? "undoing"
      : addedIds.has(c.id)
        ? "added"
        : rowAdding.has(c.id)
          ? "adding"
          : null,
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
  /** Jedna droga dla „+ Dodaj” w wierszu i „Dodaj N do Nowych” w stopce. */
  const addIds = async (ids: readonly number[], perRow: boolean) => {
    if (readOnly || ids.length === 0) return;
    // Miejsce wiersza na liście — dodana osoba zostaje tam z „Cofnij”.
    const snapshot = new Map<number, KeptRow>();
    for (const id of ids) {
      const index = items.findIndex((c) => c.id === id);
      if (index < 0) continue;
      snapshot.set(id, {
        value: items[index],
        index,
        score: scores.get(id) ?? null,
        breakdown: breakdowns.get(id) ?? null,
      });
    }
    if (perRow) setRowAdding((prev) => new Set([...prev, ...ids]));
    else setAdding(true);
    try {
      const result = await proposalsBulkApi.addInChunks(jobId, {
        candidate_ids: [...ids],
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
      // Z zaznaczenia schodzą dodani ORAZ osoby, które już są w rekrutacji.
      const gone = new Set<number>(result.added);
      const inJob = result.skipped
        .filter((row) => row.reason === "already_in_job")
        .map((row) => row.candidate_id);
      inJob.forEach((id) => gone.add(id));
      setAddedIds((prev) => new Set([...prev, ...result.added]));
      setKept((prev) => {
        const next = new Map(prev);
        for (const id of result.added) {
          const row = snapshot.get(id);
          if (row) next.set(id, row);
        }
        return next;
      });
      setInJobIds((prev) => new Set([...prev, ...inJob]));
      setSelected((prev) => new Set([...prev].filter((id) => !gone.has(id))));
      void queryClient.invalidateQueries({ queryKey: ["job-search-base", jobId] });
      void queryClient.invalidateQueries({ queryKey: ["candidates-v2"] });
      void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
      void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
      void queryClient.invalidateQueries({ queryKey: ["pipeline-scores"] });
      void queryClient.invalidateQueries({ queryKey: jobProposalsKeys.all(jobId) });
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się dodać kandydatów do rekrutacji."));
    } finally {
      if (perRow) setRowAdding((prev) => new Set([...prev].filter((id) => !ids.includes(id))));
      else setAdding(false);
    }
  };
  const addSelected = () => addIds([...selected], false);

  /**
   * „Cofnij”: usunięcie osoby z rekrutacji. Wiersz wraca do zwykłego stanu po
   * odświeżeniu wyników (osoba spoza rekrutacji znów jest w wynikach).
   */
  const undoAdd = async (candidateId: number) => {
    if (readOnly) return;
    setUndoing((prev) => new Set([...prev, candidateId]));
    try {
      await candidatesApi.removeFromRecruitment(candidateId, jobId);
      await Promise.allSettled([
        queryClient.invalidateQueries({ queryKey: ["job-search-base", jobId] }),
        queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] }),
        queryClient.invalidateQueries({ queryKey: ["kanban", jobId] }),
        queryClient.invalidateQueries({ queryKey: jobProposalsKeys.all(jobId) }),
      ]);
      void queryClient.invalidateQueries({ queryKey: ["pipeline-scores"] });
      void queryClient.invalidateQueries({ queryKey: ["candidates-v2"] });
      setAddedIds((prev) => new Set([...prev].filter((id) => id !== candidateId)));
      setKept((prev) => {
        const next = new Map(prev);
        next.delete(candidateId);
        return next;
      });
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się cofnąć dodania."));
    } finally {
      setUndoing((prev) => new Set([...prev].filter((id) => id !== candidateId)));
    }
  };

  // Wariant A (13.10.2026): każda linia mówi, co robi z listą — wycina,
  // podnosi w kolejności albo nic (sprawdza rekruter w rozmowie).
  const line = (key: string, label: string, hint: string | null, content: ReactNode) => (
    <li key={key} className="flex flex-col gap-1 sm:flex-row sm:gap-3">
      <div className="shrink-0 sm:w-40">
        <p className="text-xs font-medium text-foreground">{label}</p>
        {hint ? <p className="text-[11px] leading-snug text-muted-foreground">{hint}</p> : null}
      </div>
      <div className="min-w-0 flex-1 space-y-1">{content}</div>
    </li>
  );
  const wordRows = (rows: readonly (readonly string[])[], tone: WordTone) =>
    rows.map((row, r) => (
      <div key={r} className="flex flex-wrap items-center gap-1.5">
        {row.map((word, index) => (
          <span key={`${word}-${index}`} className="inline-flex items-center gap-1.5">
            {index > 0 ? <span className="text-xs text-muted-foreground">lub</span> : null}
            <span className={WORD_CLASS[tone]}>{word}</span>
          </span>
        ))}
      </div>
    ));
  const nice = seed.preferred.slice(seed.must.length);
  const cities = seed.filters?.locationPreferred ?? [];

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
            <p className="text-xs text-muted-foreground" data-testid="search-base-source">
              {seed.sourceNote}
            </p>
            <ul className="space-y-2.5" aria-label="Wymagania do wyszukiwania">
              {seed.required.length > 0
                ? line(
                    "required",
                    "Wymagane (krytyczne)",
                    "bez tego słowa osoba nie pojawi się na liście",
                    wordRows(seed.required, "required"),
                  )
                : null}
              {seed.must.length > 0
                ? line(
                    "must",
                    "Musi mieć (Delivery Lead)",
                    "podnosi w kolejności, nie wycina",
                    wordRows(seed.must, "must"),
                  )
                : null}
              {nice.length > 0 ? line("nice", "Mile widziane", null, wordRows(nice, "nice")) : null}
              {seed.exclude.length > 0
                ? line("exclude", "Wyklucz", null, wordRows([seed.exclude], "not"))
                : null}
              {cities.length > 0
                ? line(
                    "location",
                    "Lokalizacja kandydata",
                    "miasto w profilu kandydata, nie słowo w CV · podnosi w kolejności",
                    <div className="flex flex-wrap items-center gap-1.5">
                      {cities.map((city) => (
                        <span key={city} className={WORD_CLASS.place}>
                          📍 {city}
                        </span>
                      ))}
                    </div>,
                  )
                : null}
              {talkChecksError
                ? line(
                    "talk",
                    "Rekruter sprawdza w rozmowie",
                    null,
                    <p role="alert" className="text-xs text-muted-foreground">
                      Nie wczytano listy do rozmowy: {talkChecksError}
                    </p>,
                  )
                : talkChecks.length > 0
                  ? line(
                      "talk",
                      "Rekruter sprawdza w rozmowie",
                      "tego nie szukamy — zapytaj w rozmowie",
                      <ul className="flex flex-wrap gap-1.5" aria-label="Rekruter sprawdza w rozmowie">
                        {talkChecks.map((check) => (
                          <li key={`${check.kind}-${check.label}`} className={WORD_CLASS.talk}>
                            {talkCheckLabel(check)}
                          </li>
                        ))}
                      </ul>,
                    )
                  : null}
            </ul>
            <p className="text-xs text-muted-foreground" data-testid="search-base-summary">
              {list.isError
                ? "Nie udało się wyszukać."
                : total === null
                  ? "Szukam w CV, profilu i notatkach…"
                  : seed.required.length > 0
                    ? `Szukamy w CV, profilu i notatkach: ${seed.required.map(requirementLabel).join(" i ")}. Znaleziono osób: ${total}, od najlepiej dopasowanych.`
                    : `Nic nie jest obowiązkowe — osób: ${total}, od najlepiej dopasowanych.`}
            </p>
          </section>

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
                onAdd={(row) => void addIds([row.candidateId], true)}
                onUndo={(row) => void undoAdd(row.candidateId)}
              />
              {list.hasNextPage ? (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => void list.fetchNextPage()}
                  loading={list.isFetchingNextPage}
                >
                  Pokaż więcej ({liveItems.length} z {total})
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
      talkChecks={talkChecks}
      selection={{
        checked: selected.has(previewItem.id) && !addedIds.has(previewItem.id),
        disabled: readOnly || addedIds.has(previewItem.id),
        onToggle: () => toggle(previewItem.id),
        label: addedIds.has(previewItem.id) ? "Dodano do „Nowych”" : "Dodaj tę osobę do „Nowych”",
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
