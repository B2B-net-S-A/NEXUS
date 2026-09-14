"use client";

import { useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Loader2, RefreshCcw, TriangleAlert, Users } from "lucide-react";
import {
  recommendationsApi,
  type SeekingContractorsParams,
  type SeekingContractorsResponse,
} from "@/lib/api";
import { Alert } from "@/components/ui/alert";
import { ContractorMatchCard } from "./ContractorMatchCard";
import { RecommendationFiltersBar } from "./RecommendationFiltersBar";

export const SEEKING_PAGE_SIZE = 50;

const DEFAULT_FILTERS: SeekingContractorsParams = {
  horizon_days: 30,
  top_k: 5,
  threshold: 40,
  industry_blocklist: true,
  page_size: SEEKING_PAGE_SIZE,
};

/**
 * Następne okno = liczba już wczytanych wierszy (UAT B06). Backend porządkuje
 * pulę deterministycznie, więc okna nie nakładają się na siebie. Starszy
 * backend (bez `offset` w odpowiedzi) ignoruje przesunięcie i oddałby tę samą
 * pierwszą stronę w kółko — wtedy przycisku nie ma, jak do tej pory.
 */
export function nextSeekingOffset(
  lastPage: SeekingContractorsResponse,
  allPages: SeekingContractorsResponse[],
): number | undefined {
  if (!lastPage.truncated || lastPage.offset === undefined) return undefined;
  return allPages.reduce((n, page) => n + page.items.length, 0);
}

export function SeekingContractorsBoard() {
  const [filters, setFilters] = useState<SeekingContractorsParams>(DEFAULT_FILTERS);

  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ["seeking-contractors", filters],
    queryFn: async ({ pageParam }) => {
      const res = await recommendationsApi.seekingContractors({
        ...filters,
        offset: pageParam,
      });
      return res.data;
    },
    initialPageParam: 0,
    getNextPageParam: nextSeekingOffset,
    staleTime: 60_000,
  });

  // Do 09.2026 plansza kończyła się na pierwszych 50 osobach: „50 z 2890"
  // i żadnej drogi do reszty poza zgadywaniem filtrów. Kolejne okna doklejamy
  // do jednej listy; `total` i `degraded` czytamy ze WSZYSTKICH stron, bo
  // jedna padnięta odpowiedź dostawcy psuje wiarygodność całego kokpitu.
  const pages = data?.pages ?? [];
  const items = pages.flatMap((page) => page.items);
  const total = pages.length ? pages[pages.length - 1].total : 0;
  const horizonDays = pages[0]?.horizon_days;
  const degraded = pages.some((page) => page.meta?.degraded);
  const remaining = Math.max(0, total - items.length);

  return (
    <div>
      <RecommendationFiltersBar
        initial={filters}
        onApply={(newFilters) =>
          setFilters({ ...DEFAULT_FILTERS, ...newFilters })
        }
      />

      <div className="flex items-center justify-between mb-3">
        <div className="text-sm text-muted-foreground dark:text-muted-foreground">
          {isLoading
            ? "Wyszukuję dopasowania…"
            : data
              ? remaining > 0
                ? `${items.length} z ${total} konsultantów w horyzoncie ${horizonDays} dni`
                : `${total} konsultantów w horyzoncie ${horizonDays} dni`
              : ""}
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="text-xs text-primary hover:text-primary/80 flex items-center gap-1 disabled:opacity-50"
          data-testid="refresh-board"
        >
          {isFetching ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <RefreshCcw className="w-3 h-3" />
          )}
          Odśwież
        </button>
      </div>

      {isError && (
        <div className="rounded bg-destructive/10 border border-destructive/20 p-3 text-sm text-destructive mb-3">
          Nie udało się załadować listy:{" "}
          {error instanceof Error ? error.message : "nieznany błąd"}
        </div>
      )}

      {/*
        Awaria warstwy semantycznej NIE MOŻE renderować się jak pusty wynik.
        Backend mówi o tym w `meta.degraded`, ale do 09.2026 ten ekran w ogóle
        nie czytał `meta`, więc sygnał kończył się na granicy API: rekruter
        widział wiersze z pustymi dopasowaniami i żadnego wyjaśnienia, co czyta
        się jak „sprawdziliśmy i nie ma nic sensownego".

        Baner stoi NAD listą, bo `bulk_degraded` jest zbiorcze — jedna nieudana
        odpowiedź dostawcy psuje wiarygodność całego kokpitu, nie jednego
        wiersza, a który to wiersz, tego backend nie mówi.
      */}
      {!isLoading && degraded && (
        <Alert
          variant="error"
          icon={TriangleAlert}
          className="mb-3"
          data-testid="degraded-banner"
          title="Kokpit jest niepełny — wyszukiwanie nie doszło do skutku"
          description={
            <>
              Warstwa semantyczna była niedostępna przy liczeniu tej listy, więc
              u części konsultantów dopasowań nie policzyliśmy wcale. Pusty
              wiersz nie znaczy, że nic dla tej osoby nie ma — znaczy, że nie
              wiemy.{" "}
              <button
                type="button"
                onClick={() => refetch()}
                disabled={isFetching}
                className="font-medium underline underline-offset-2 disabled:opacity-50"
              >
                Spróbuj ponownie
              </button>
            </>
          }
        />
      )}

      {isLoading && (
        <div className="flex justify-center py-12">
          <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
        </div>
      )}

      {/*
        `!degraded` jest tu WARUNKIEM, nie ozdobą: „Brak konsultantów do
        ulokowania" przy padniętym dostawcy byłoby zdaniem nieprawdziwym,
        i to takim, po którym rekruter zamyka ekran i nie wraca.
      */}
      {!isLoading &&
        data &&
        items.length === 0 &&
        !degraded && (
          <div
            className="rounded-lg border border-dashed border-border dark:border-border p-12 text-center"
            data-testid="empty-state"
          >
            <Users className="w-12 h-12 mx-auto text-muted-foreground mb-3" />
            <h3 className="font-semibold text-foreground dark:text-muted-foreground mb-1">
              Brak konsultantów do ulokowania
            </h3>
            <p className="text-sm text-muted-foreground max-w-md mx-auto">
              Żaden kontrakt nie kończy się w wybranym horyzoncie i nikt nie ma
              statusu &ldquo;aktywnie szuka&rdquo; ani &ldquo;otwarty na
              oferty&rdquo;. Spróbuj zwiększyć horyzont lub poluzować filtry.
            </p>
          </div>
        )}

      {data && items.length > 0 && (
        <div
          className="grid grid-cols-1 lg:grid-cols-2 gap-4"
          data-testid="contractors-grid"
        >
          {items.map((row) => (
            <ContractorMatchCard key={row.candidate.id} row={row} />
          ))}
        </div>
      )}

      {hasNextPage && (
        <div className="mt-4 flex justify-center">
          <button
            type="button"
            onClick={() => fetchNextPage()}
            disabled={isFetchingNextPage}
            className="inline-flex items-center gap-2 rounded-lg border border-border px-4 py-2 text-sm font-medium text-foreground hover:bg-muted disabled:opacity-50"
            data-testid="load-more"
          >
            {isFetchingNextPage ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : null}
            Pokaż kolejnych {Math.min(SEEKING_PAGE_SIZE, remaining)}
          </button>
        </div>
      )}
    </div>
  );
}
