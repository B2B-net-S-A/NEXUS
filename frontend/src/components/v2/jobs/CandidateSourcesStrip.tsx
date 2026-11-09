"use client";

/**
 * Od audytu U3 (08.11.2026) w jednym rzędzie: kafle „Nowi z ogłoszeń”, „Moi
 * ludzie”, „Aplikacje”; reszta źródeł w menu „Szukaj ▾”, bez wielkich liczb.
 *
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

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, FileUp, Plus, Search, UserPlus } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { JobTwinChip } from "@/components/v2/jobs/twins/JobTwinChip";
import { JobApplicantsTile } from "@/components/v2/jobs/JobApplicantsTile";
import { MyPeopleTile } from "@/components/v2/jobs/MyPeopleTile";
import { OpenSimilarTile } from "@/components/v2/jobs/twins/OpenSimilarTile";
import type { CandidateSourceTab } from "@/components/v2/recruitment/types";
import { useJobSearchSeed } from "@/components/v2/recruitment/useJobSearchSeed";
import { jobProposalsApi, jobProposalsKeys } from "@/lib/job-proposals-api";
import type { ManualSearchJob } from "@/lib/job-search-filters";
import { requirementLabel } from "@/lib/keyword-requirements";
import { useSimilarJobs } from "@/lib/similar-jobs-api";
import { similarPeopleTotal } from "@/lib/similar-reassign";

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
  /** Kafel po źródłach — „Aplikacje” (wszyscy aplikujący, 07.11.2026). */
  afterTiles?: ReactNode;
  /**
   * „Kto już to robił” (09.11.2026) — wyszukiwanie po obowiązkach z Championa
   * (`docs/claude/kandydaci-wyszukiwanie/kto-juz-to-robil-wyszukiwanie-po-celu.md`).
   */
  dutyHref?: string;
}

/** Pozycja menu otwiera okno — po zamknięciu menu, nie w trakcie (fokus). */
function deferMenuAction(action: () => void) {
  window.setTimeout(action, 0);
}

function SourceCountText({ tab, count }: { tab: CandidateSourceTab; count: SourceCount }) {
  return (
    <span className="font-bold tabular-nums" data-testid={`source-tile-${tab}-count`}>
      {count === "loading" ? (
        <span className="text-muted-foreground" aria-label="liczę">
          …
        </span>
      ) : count === null ? (
        <span className="text-muted-foreground" aria-label="nie policzono">
          —
        </span>
      ) : (
        count
      )}
    </span>
  );
}

/**
 * Menu „Szukaj ▾” (audyt U3, 08.11.2026): liczby typu 2080 i 6823 nie były do
 * decyzji, a zajmowały rząd i zawijały pasek na drugą linię przy 1280 px.
 * Popover, nie `DropdownMenu`, bo kafle „Otwarte podobne” i „Bliźniak” mają
 * w środku własne okienka, a menu zamknęłoby się razem z nimi.
 */
function SourcesSearchMenu({
  tiles,
  onOpen,
  extras,
  dutyHref,
}: {
  tiles: readonly CandidateSourceTile[];
  onOpen: (tab: CandidateSourceTab) => void;
  extras?: ReactNode;
  dutyHref?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          data-testid="sources-search-menu"
          data-tour="jobs.sources.search"
          title="Podobne rekrutacje, propozycje z bazy i wyszukiwanie w bazie"
          className="inline-flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md border border-primary/25 bg-card px-2.5 text-[13px] font-semibold text-foreground transition-colors hover:border-primary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring pointer-coarse:min-h-9"
        >
          <Search className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
          Szukaj
          <ChevronDown className="h-3 w-3" aria-hidden="true" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72 p-1.5" data-testid="sources-search-menu-content">
        <ul>
          {tiles.map((tile) => (
            <li key={tile.tab}>
              <button
                type="button"
                data-testid={`source-tile-${tile.tab}`}
                onClick={() => {
                  setOpen(false);
                  deferMenuAction(() => onOpen(tile.tab));
                }}
                className="block w-full rounded-md px-2 py-1.5 text-left hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="block text-[13px] font-semibold text-foreground">{TILE_TITLE[tile.tab]}</span>
                <span className="block text-xs leading-snug text-muted-foreground">{tile.description}</span>
              </button>
            </li>
          ))}
          {dutyHref ? (
            <li>
              <Link
                href={dutyHref}
                onClick={() => setOpen(false)}
                data-testid="source-tile-duties"
                data-tour="jobs.sources.duties"
                className="block w-full rounded-md px-2 py-1.5 text-left hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="flex items-center gap-1.5 text-[13px] font-semibold text-foreground">
                  Kto już to robił
                  <span className="rounded bg-primary/10 px-1 text-[10px] font-semibold uppercase text-primary">nowe</span>
                </span>
                <span className="block text-xs leading-snug text-muted-foreground">
                  Po obowiązkach z Championa — AI czyta CV i pokazuje cytat, także gdy CV nazywa to inaczej
                </span>
              </Link>
            </li>
          ) : null}
        </ul>
        {extras ? <div className="mt-1 flex flex-wrap items-center gap-1.5 border-t border-border px-1 pt-1.5">{extras}</div> : null}
      </PopoverContent>
    </Popover>
  );
}

/** Sam wygląd — bez zapytań (harness `/preview/job-detail`). */
export function CandidateSourcesStripView({
  tiles,
  onOpen,
  onAddByName,
  onAddFromCv,
  afterSimilar,
  afterTiles,
  dutyHref,
}: CandidateSourcesStripViewProps) {
  const postings = tiles.find((tile) => tile.tab === "postings");
  const searched = tiles.filter((tile) => tile.tab !== "postings");
  return (
    <section
      aria-label="Kandydaci do dodania"
      data-testid="candidate-sources-strip"
      data-help="jobs.board.sources"
      className="flex min-w-0 flex-wrap items-center gap-1.5"
    >
      {postings ? (
        <button
          type="button"
          onClick={() => onOpen(postings.tab)}
          data-testid={`source-tile-${postings.tab}`}
          title={postings.description}
          className="inline-flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md border border-primary/25 bg-card px-2.5 text-[13px] font-semibold text-foreground transition-colors hover:border-primary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring pointer-coarse:min-h-9"
        >
          {TILE_TITLE[postings.tab]}
          <SourceCountText tab={postings.tab} count={postings.count} />
          <span className="sr-only">— {postings.description}</span>
        </button>
      ) : null}
      {afterTiles}
      <SourcesSearchMenu tiles={searched} onOpen={onOpen} extras={afterSimilar} dutyHref={dutyHref} />
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
  const similarTotal = similarPeopleTotal(similar.data);
  const postingsCount = (): SourceCount => {
    const fromWindow = visibleSplit.data?.postings;
    if (typeof fromWindow === "number") return fromWindow;
    return counts.isSuccess ? counts.data.postings_recent : counts.isError ? null : "loading";
  };
  const screenedOut = counts.data?.screened_out ?? 0;
  const words = [...seed.required, ...seed.preferred].slice(0, 2).map(requirementLabel).join(", ");
  // Kafel mówi to samo co zakładka i „Szukaj ręcznie” (W1, audyt 06.10.2026):
  // obowiązkowe są tylko krytyczne, reszta słów tylko podnosi.
  const mandatory = seed.required.map((row) => row[0]).filter(Boolean).join(", ");

  const tiles: CandidateSourceTile[] = [
    {
      tab: "similar",
      count: null,
      description: similarTileDescription(similarTotal),
    },
    {
      tab: "postings",
      count: postingsCount(),
      description:
        screenedOut > 0
          ? `Z ostatnich 7 dni, pasują do tej rekrutacji · ${screenedOut} odłożonych przez AI`
          : "Z ostatnich 7 dni, pasują do tej rekrutacji",
    },
    {
      tab: "base",
      count: null,
      description: "Wybrane przez nocny przegląd bazy",
    },
    {
      tab: "search",
      count: null,
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
      dutyHref={`/candidates?mode=goal&job=${jobId}`}
      afterTiles={
        <>
          <MyPeopleTile />
          <JobApplicantsTile jobId={jobId} />
        </>
      }
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
