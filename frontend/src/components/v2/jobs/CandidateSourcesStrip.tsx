"use client";

/**
 * Pasek „Kandydaci do dodania” nad Tablicą rekrutacji (02.10.2026, makieta B:
 * https://claude.ai/artifact/ASHNaTXA9omvTH393cQjCv).
 *
 * Cztery kafle = cztery źródła kandydatów, każdy z liczbą i jednym zdaniem.
 * Klik otwiera okno „Kandydaci do dodania” na właściwej zakładce. Zastąpił
 * blok propozycji w kolumnie „Nowi” („Propozycje z bazy · N”, pasek przepięć,
 * „Znajdź w bazie (AI)”) i przycisk „Dodaj kandydatów” w nagłówku.
 *
 * Liczby są tanie: liczniki propozycji liczy serwer jednym zapytaniem
 * (`proposal-counts`), a skrzynka propozycji ładuje się dopiero w oknie.
 * Brak liczby to „—”, nigdy zero — zero znaczyłoby „nie ma nikogo”.
 */

import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Database, Inbox, Link2, Search, UserPlus, type LucideIcon } from "lucide-react";

import { fetchCandidateListPage } from "@/components/v2/pages/candidate-list-query";
import type { CandidateSourceTab } from "@/components/v2/recruitment/types";
import { useJobSearchSeed } from "@/components/v2/recruitment/useJobSearchSeed";
import { jobProposalsApi, jobProposalsKeys } from "@/lib/job-proposals-api";
import type { ManualSearchJob } from "@/lib/job-search-filters";
import { requirementLabel } from "@/lib/keyword-requirements";
import { useSimilarJobs } from "@/lib/similar-jobs-api";
import { similarPeopleTotal } from "@/lib/similar-reassign";
import { filtersToApiParams } from "@/lib/url-filters";
import { cn } from "@/lib/utils";

/** `number` = policzono, `"loading"` = w toku, `null` = nie wiadomo. */
export type SourceCount = number | "loading" | null;

export interface CandidateSourceTile {
  tab: CandidateSourceTab;
  count: SourceCount;
  description: string;
}

const TILE_META: Record<CandidateSourceTab, { title: string; icon: LucideIcon; action: string }> = {
  similar: { title: "Podobne rekrutacje", icon: Link2, action: "Pokaż" },
  postings: { title: "Nowi z ogłoszeń", icon: Inbox, action: "Pokaż" },
  base: { title: "Propozycje z bazy", icon: Database, action: "Przejrzyj" },
  search: { title: "Szukaj w bazie", icon: Search, action: "Otwórz" },
};

export interface CandidateSourcesStripViewProps {
  tiles: readonly CandidateSourceTile[];
  onOpen: (tab: CandidateSourceTab) => void;
  /** „Dodaj po nazwisku” / „z pliku CV” — brak = rola bez prawa dodawania. */
  onAddByName?: () => void;
  onAddFromCv?: () => void;
  /** Miejsce na przełącznik widoku tablicy (rzadko widoczny). */
  trailing?: ReactNode;
}

/** Sam wygląd — bez zapytań (harness `/preview/job-detail`). */
export function CandidateSourcesStripView({
  tiles,
  onOpen,
  onAddByName,
  onAddFromCv,
  trailing,
}: CandidateSourcesStripViewProps) {
  return (
    <section
      aria-label="Kandydaci do dodania"
      data-testid="candidate-sources-strip"
      data-help="jobs.board.sources"
      className="@container space-y-2 rounded-lg bg-primary/5 px-3 py-2.5"
    >
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <h2 className="text-[11px] font-semibold uppercase tracking-eyebrow text-muted-foreground">
          Kandydaci do dodania
        </h2>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {onAddByName ? (
            <button
              type="button"
              onClick={onAddByName}
              data-testid="sources-add-by-name"
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-primary hover:underline"
            >
              <UserPlus className="h-3.5 w-3.5" aria-hidden="true" />
              Dodaj po nazwisku
            </button>
          ) : null}
          {onAddFromCv ? (
            <button
              type="button"
              onClick={onAddFromCv}
              data-testid="sources-add-from-cv"
              className="text-xs font-semibold text-primary hover:underline"
            >
              albo z pliku CV
            </button>
          ) : null}
          {trailing}
        </div>
      </div>
      {/* Układ po szerokości PASKA, nie okna: menu, szyna kart i dok zabierają
          miejsce. Na laptopie (pasek < 1024 px) kafel to jedna linia: nazwa
          i liczba, bez ikony i słowa „Pokaż” (cały kafel jest przyciskiem,
          opis w podpowiedzi) — przy 1280×720 nazwa łamała się na trzy wiersze
          (04.10.2026). */}
      <div className="grid grid-cols-1 gap-2 @lg:grid-cols-2 @3xl:grid-cols-4">
        {tiles.map((tile) => {
          const meta = TILE_META[tile.tab];
          const Icon = meta.icon;
          return (
            <button
              key={tile.tab}
              type="button"
              onClick={() => onOpen(tile.tab)}
              data-testid={`source-tile-${tile.tab}`}
              title={tile.description}
              className={cn(
                "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-2.5 rounded-lg border border-primary/25 bg-card px-3 py-1.5 text-left transition-colors @5xl:min-h-[68px] @5xl:grid-cols-[2rem_minmax(0,1fr)_auto] @5xl:items-start @5xl:py-2",
                "hover:border-primary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              )}
            >
              <span
                aria-hidden="true"
                className="hidden h-8 w-8 items-center justify-center rounded-md bg-primary/10 text-primary @5xl:flex"
              >
                <Icon className="h-4 w-4" />
              </span>
              <span className="min-w-0">
                <span className="block truncate text-[13px] font-semibold leading-tight text-foreground @5xl:whitespace-normal">
                  {meta.title}
                </span>
                <span className="mt-0.5 line-clamp-2 hidden text-xs leading-snug text-muted-foreground @5xl:block">
                  {tile.description}
                </span>
              </span>
              <span className="flex items-baseline gap-2 text-right @5xl:block">
                <span
                  className="block text-lg font-bold leading-tight tabular-nums text-foreground"
                  data-testid={`source-tile-${tile.tab}-count`}
                >
                  {tile.count === "loading" ? (
                    <span className="text-muted-foreground" aria-label="liczę">
                      …
                    </span>
                  ) : tile.count === null ? (
                    <span className="text-muted-foreground" aria-label="nie policzono">
                      —
                    </span>
                  ) : (
                    tile.count
                  )}
                </span>
                <span className="hidden text-xs font-semibold text-primary @5xl:block">{meta.action}</span>
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

/** „1 wysłana”, „3 wysłane”, „5 wysłanych” — ta sama odmiana dla „pozostała”. */
function counted(n: number, one: string, few: string, many: string): string {
  if (n === 1) return `1 ${one}`;
  const last = n % 10;
  const lastTwo = n % 100;
  return last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14) ? `${n} ${few}` : `${n} ${many}`;
}

/** Opis kafla „Podobne rekrutacje” — eksport dla testu. */
export function similarTileDescription(total: { sent: number; other: number } | null): string {
  if (!total) return "Osoby z podobnych rekrutacji — najpierw wysłane do klienta";
  const sent = `${counted(total.sent, "wysłana", "wysłane", "wysłanych")} do klienta`;
  return total.other > 0
    ? `${sent}, ${counted(total.other, "pozostała", "pozostałe", "pozostałych")} z tych rekrutacji`
    : `${sent} w podobnych rekrutacjach`;
}

export interface CandidateSourcesStripProps {
  jobId: number;
  /** Rekrutacja — słowa z Championa do kafla „Szukaj w bazie”. */
  job: ManualSearchJob;
  /** `GET /similar` to RecruiterPlus — bez tego kafel nie pyta (403). */
  canSeeSimilar: boolean;
  onOpen: (tab: CandidateSourceTab) => void;
  onAddByName?: () => void;
  onAddFromCv?: () => void;
  trailing?: ReactNode;
}

export function CandidateSourcesStrip({
  jobId,
  job,
  canSeeSimilar,
  onOpen,
  onAddByName,
  onAddFromCv,
  trailing,
}: CandidateSourcesStripProps) {
  const similar = useSimilarJobs(jobId, canSeeSimilar);
  const counts = useQuery({
    queryKey: jobProposalsKeys.counts(jobId),
    queryFn: ({ signal }) => jobProposalsApi.counts(jobId, signal),
    staleTime: 30_000,
    retry: false,
  });
  // Liczby z okna (wszystkie źródła), gdy było otwarte — tylko odczyt cache'u.
  const visibleSplit = useQuery<{ postings: number; base: number } | null>({
    queryKey: jobProposalsKeys.visibleSplit(jobId),
    queryFn: () => null,
    enabled: false,
  });
  const seed = useJobSearchSeed(jobId, job, true);
  const filtersKey = seed.filters ? JSON.stringify(seed.filters) : "";
  const searchCount = useQuery({
    queryKey: ["job-search-base-count", jobId, filtersKey],
    enabled: seed.ready && seed.hasRows && seed.filters != null,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
    retry: false,
    queryFn: async ({ signal }) => {
      const data = await fetchCandidateListPage<{ total?: unknown }>(
        // Jawne „najnowsi”: liczba nie zależy od kolejności, a domyślne
        // „Dopasowanie” kazałoby serwerowi układać całą listę przy każdym
        // wejściu na rekrutację.
        filtersToApiParams({ ...seed.filters!, sort: "newest", sortExplicit: true }, 1, {
          page_size: 1,
        }),
        signal,
      );
      return typeof data?.total === "number" ? data.total : null;
    },
  });

  const similarTotal = similarPeopleTotal(similar.data);
  const proposalCount = (pick: "postings_recent" | "base"): SourceCount => {
    const fromWindow = visibleSplit.data?.[pick === "base" ? "base" : "postings"];
    if (typeof fromWindow === "number") return fromWindow;
    return counts.isSuccess ? counts.data[pick] : counts.isError ? null : "loading";
  };
  const screenedOut = counts.data?.screened_out ?? 0;
  const words = [...seed.required, ...seed.preferred].slice(0, 2).map(requirementLabel).join(", ");

  const tiles: CandidateSourceTile[] = [
    {
      tab: "similar",
      count: !canSeeSimilar
        ? null
        : similarTotal
          ? similarTotal.total
          : similar.isError || similar.isSuccess
            ? null
            : "loading",
      description: similarTileDescription(similarTotal),
    },
    {
      tab: "postings",
      count: proposalCount("postings_recent"),
      description:
        screenedOut > 0
          ? `Z ostatnich 7 dni, pasują do tej rekrutacji · ${screenedOut} odłożonych przez AI`
          : "Z ostatnich 7 dni, pasują do tej rekrutacji",
    },
    {
      tab: "base",
      count: proposalCount("base"),
      description: "Wybrane przez nocny przegląd bazy",
    },
    {
      tab: "search",
      count: !seed.ready
        ? "loading"
        : !seed.hasRows
          ? null
          : searchCount.isSuccess
            ? searchCount.data
            : searchCount.isError
              ? null
              : "loading",
      description: !seed.ready
        ? "Po słowach z Championa"
        : seed.hasRows
          ? `Po słowach z Championa: ${words}`
          : "W Championie nie ma jeszcze słów do wyszukiwania",
    },
  ];

  return (
    <CandidateSourcesStripView
      tiles={tiles}
      onOpen={onOpen}
      onAddByName={onAddByName}
      onAddFromCv={onAddFromCv}
      trailing={trailing}
    />
  );
}
