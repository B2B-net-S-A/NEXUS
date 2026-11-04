"use client";

/**
 * „Kandydaci do dodania” — trzecia linia nagłówka rekrutacji (14.10.2026,
 * K-D1, makieta https://claude.ai/artifact/DZWUbWtiQLrnzm81RwLvDP). Do tego dnia
 * osobny pasek z kaflami nad Tablicą (02.10.2026): przy 1280×720 razem
 * z nagłówkiem zajmował prawie pół ekranu.
 *
 * Cztery przyciski = cztery źródła kandydatów, każdy z liczbą; zdanie opisu
 * stoi w dymku i dla czytnika ekranu. Klik otwiera okno „Kandydaci do dodania”
 * na właściwej zakładce. „Dodaj” to menu: po nazwisku albo z pliku CV.
 *
 * Liczby są tanie: liczniki propozycji liczy serwer jednym zapytaniem
 * (`proposal-counts`), a skrzynka propozycji ładuje się dopiero w oknie.
 * Brak liczby to „—”, nigdy zero — zero znaczyłoby „nie ma nikogo”.
 */

import { Fragment, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, FileUp, Plus, UserPlus } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { JobTwinChip } from "@/components/v2/jobs/twins/JobTwinChip";
import { OpenSimilarTile } from "@/components/v2/jobs/twins/OpenSimilarTile";
import { fetchCandidateListPage } from "@/components/v2/pages/candidate-list-query";
import type { CandidateSourceTab } from "@/components/v2/recruitment/types";
import { useJobSearchSeed } from "@/components/v2/recruitment/useJobSearchSeed";
import { jobProposalsApi, jobProposalsKeys } from "@/lib/job-proposals-api";
import type { ManualSearchJob } from "@/lib/job-search-filters";
import { requirementLabel } from "@/lib/keyword-requirements";
import { useSimilarJobs } from "@/lib/similar-jobs-api";
import { similarPeopleTotal } from "@/lib/similar-reassign";
import { filtersToApiParams } from "@/lib/url-filters";

/** `number` = policzono, `"loading"` = w toku, `null` = nie wiadomo. */
export type SourceCount = number | "loading" | null;

export interface CandidateSourceTile {
  tab: CandidateSourceTab;
  count: SourceCount;
  description: string;
}

const TILE_TITLE: Record<CandidateSourceTab, string> = {
  similar: "Podobne rekrutacje",
  postings: "Nowi z ogłoszeń",
  base: "Propozycje z bazy",
  search: "Szukaj w bazie",
};

export interface CandidateSourcesStripViewProps {
  tiles: readonly CandidateSourceTile[];
  onOpen: (tab: CandidateSourceTab) => void;
  /** „Dodaj po nazwisku” / „z pliku CV” — brak = rola bez prawa dodawania. */
  onAddByName?: () => void;
  onAddFromCv?: () => void;
  /**
   * Kafel stojący zaraz po „Podobnych rekrutacjach” — „Otwarte podobne”
   * (bliźniaki, 0614). Własne zapytanie i okno, więc poza listą źródeł.
   */
  afterSimilar?: ReactNode;
}

/** Pozycja menu otwiera okno — po zamknięciu menu, nie w trakcie (fokus). */
function deferMenuAction(action: () => void) {
  window.setTimeout(action, 0);
}

/** Sam wygląd — bez zapytań (harness `/preview/job-detail`). */
export function CandidateSourcesStripView({
  tiles,
  onOpen,
  onAddByName,
  onAddFromCv,
  afterSimilar,
}: CandidateSourcesStripViewProps) {
  return (
    <section
      aria-label="Kandydaci do dodania"
      data-testid="candidate-sources-strip"
      data-help="jobs.board.sources"
      className="flex min-w-0 flex-wrap items-center gap-1.5"
    >
      {tiles.map((tile) => (
        <Fragment key={tile.tab}>
        <button
          type="button"
          onClick={() => onOpen(tile.tab)}
          data-testid={`source-tile-${tile.tab}`}
          data-tour={tile.tab === "search" ? "jobs.sources.search" : undefined}
          title={tile.description}
          className="inline-flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md border border-primary/25 bg-card px-2.5 text-[13px] font-semibold text-foreground transition-colors hover:border-primary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring pointer-coarse:min-h-9"
        >
          {TILE_TITLE[tile.tab]}
          <span
            className="font-bold tabular-nums"
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
          <span className="sr-only">— {tile.description}</span>
        </button>
        {tile.tab === "similar" ? afterSimilar : null}
        </Fragment>
      ))}
      {onAddByName || onAddFromCv ? (
        <DropdownMenu modal={false}>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              data-testid="sources-add"
              className="hit-area inline-flex h-7 shrink-0 items-center gap-1 whitespace-nowrap rounded-md px-1.5 text-[13px] font-semibold text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Plus className="h-3.5 w-3.5" aria-hidden="true" />
              Dodaj
              <ChevronDown className="h-3 w-3" aria-hidden="true" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-56">
            {onAddByName ? (
              <DropdownMenuItem
                onSelect={() => deferMenuAction(onAddByName)}
                data-testid="sources-add-by-name"
              >
                <UserPlus className="h-4 w-4" aria-hidden="true" />
                Dodaj po nazwisku
              </DropdownMenuItem>
            ) : null}
            {onAddFromCv ? (
              <DropdownMenuItem
                onSelect={() => deferMenuAction(onAddFromCv)}
                data-testid="sources-add-from-cv"
              >
                <FileUp className="h-4 w-4" aria-hidden="true" />
                Dodaj z pliku CV
              </DropdownMenuItem>
            ) : null}
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}
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
}

export function CandidateSourcesStrip({
  jobId,
  job,
  canSeeSimilar,
  onOpen,
  onAddByName,
  onAddFromCv,
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
  // Kafel mówi to samo co zakładka i „Szukaj ręcznie” (W1, audyt 06.10.2026):
  // obowiązkowe są tylko krytyczne, reszta słów tylko podnosi.
  const mandatory = seed.required.map((row) => row[0]).filter(Boolean).join(", ");

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
          ? mandatory
            ? `Obowiązkowe: ${mandatory} · reszta słów tylko podnosi`
            : `Po słowach z Championa: ${words} · nic nie jest obowiązkowe`
          : "W Championie nie ma jeszcze słów do wyszukiwania",
    },
  ];

  return (
    <CandidateSourcesStripView
      tiles={tiles}
      onOpen={onOpen}
      onAddByName={onAddByName}
      onAddFromCv={onAddFromCv}
      afterSimilar={
        <>
          <OpenSimilarTile jobId={jobId} enabled={canSeeSimilar} />
          {/* Bliźniak (0614) — w rzędzie tytułu łamał się przy 1280 px. */}
          {canSeeSimilar ? <JobTwinChip jobId={jobId} /> : null}
        </>
      }
    />
  );
}
