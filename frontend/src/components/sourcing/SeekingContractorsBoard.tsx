"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, RefreshCcw, Users } from "lucide-react";
import {
  recommendationsApi,
  type SeekingContractorsParams,
} from "@/lib/api";
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
  const [filters, setFilters] = useState<SeekingContractorsParams>(DEFAULT_FILTERS);

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
        <div className="text-sm text-gray-600 dark:text-gray-400">
          {isLoading
            ? "Wyszukuję dopasowania…"
            : data
              ? `${data.total} konsultantów w horyzoncie ${data.horizon_days} dni`
              : ""}
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-1 disabled:opacity-50"
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
        <div className="rounded bg-red-50 border border-red-200 p-3 text-sm text-red-700 mb-3">
          Nie udało się załadować listy:{" "}
          {error instanceof Error ? error.message : "nieznany błąd"}
        </div>
      )}

      {isLoading && (
        <div className="flex justify-center py-12">
          <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
        </div>
      )}

      {!isLoading && data && data.items.length === 0 && (
        <div
          className="rounded-lg border border-dashed border-gray-300 dark:border-gray-700 p-12 text-center"
          data-testid="empty-state"
        >
          <Users className="w-12 h-12 mx-auto text-gray-400 mb-3" />
          <h3 className="font-semibold text-gray-700 dark:text-gray-300 mb-1">
            Brak konsultantów do ulokowania
          </h3>
          <p className="text-sm text-gray-500 max-w-md mx-auto">
            Żaden kontrakt nie kończy się w wybranym horyzoncie i nikt nie ma
            statusu &ldquo;aktywnie szuka&rdquo; ani &ldquo;otwarty na oferty&rdquo;.
            Spróbuj zwiększyć horyzont lub poluzować filtry.
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
