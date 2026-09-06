"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, RefreshCcw, TriangleAlert, Users } from "lucide-react";
import { recommendationsApi, type SeekingContractorsParams } from "@/lib/api";
import { Alert } from "@/components/ui/alert";
import { ContractorMatchCard } from "./ContractorMatchCard";
import { RecommendationFiltersBar } from "./RecommendationFiltersBar";

const DEFAULT_FILTERS: SeekingContractorsParams = {
  horizon_days: 30,
  top_k: 5,
  threshold: 40,
  industry_blocklist: true,
  page_size: 50,
};

export function SeekingContractorsBoard() {
  const [filters, setFilters] =
    useState<SeekingContractorsParams>(DEFAULT_FILTERS);

  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["seeking-contractors", filters],
    queryFn: async () => {
      const res = await recommendationsApi.seekingContractors(filters);
      return res.data;
    },
    staleTime: 60_000,
  });

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
              ? data.truncated
                ? `${data.returned} z ${data.total} konsultantów w horyzoncie ${data.horizon_days} dni`
                : `${data.total} konsultantów w horyzoncie ${data.horizon_days} dni`
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
      {!isLoading && data?.meta?.degraded && (
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
        data.items.length === 0 &&
        !data.meta?.degraded && (
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

      {data && data.items.length > 0 && (
        <div
          className="grid grid-cols-1 lg:grid-cols-2 gap-4"
          data-testid="contractors-grid"
        >
          {data.items.map((row) => (
            <ContractorMatchCard key={row.candidate.id} row={row} />
          ))}
        </div>
      )}
    </div>
  );
}
