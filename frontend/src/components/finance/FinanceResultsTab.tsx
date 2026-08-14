"use client";

import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Banknote, Search, TrendingUp, Wallet } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatCard, StatCardGrid } from "@/components/ds/StatCard";
import { useToast } from "@/components/Toast";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import {
  financeApi,
  type FinanceEditableField,
  type FinancePeriod,
  type FinanceResultsResponse,
} from "@/lib/api/finance";
import { FinanceImportPanel } from "@/components/finance/FinanceImportPanel";
import {
  FinanceResultsTable,
  formatMoney,
} from "@/components/finance/FinanceResultsTable";

export function FinanceResultsTab() {
  const { showToast } = useToast();
  const queryClient = useQueryClient();

  const [selected, setSelected] = useState<{ year: number; month: number } | null>(
    null,
  );
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search, 300);
  const searching = debouncedSearch.trim().length > 0;
  const [sort, setSort] = useState("row_number");
  const [direction, setDirection] = useState<"asc" | "desc">("asc");

  const periodsQuery = useQuery<FinancePeriod[]>({
    queryKey: ["finance-periods"],
    queryFn: async () => (await financeApi.listPeriods()).data,
  });

  const periods = useMemo(() => periodsQuery.data ?? [], [periodsQuery.data]);
  // Domyślnie najnowszy dostępny miesiąc (lista przychodzi posortowana malejąco).
  const active = selected ?? (periods[0] ? { year: periods[0].year, month: periods[0].month } : null);

  const resultsQuery = useQuery<FinanceResultsResponse>({
    queryKey: [
      "finance-results",
      active?.year,
      active?.month,
      debouncedSearch,
      sort,
      direction,
    ],
    queryFn: async () =>
      (
        await financeApi.getResults({
          year: active!.year,
          month: active!.month,
          q: debouncedSearch.trim() || undefined,
          sort,
          direction,
        })
      ).data,
    enabled: active != null,
  });

  function refreshAll() {
    queryClient.invalidateQueries({ queryKey: ["finance-periods"] });
    queryClient.invalidateQueries({ queryKey: ["finance-results"] });
    queryClient.invalidateQueries({ queryKey: ["finance-imports"] });
  }

  async function handleEdit(
    rowId: number,
    field: FinanceEditableField,
    value: number | null,
  ) {
    await financeApi.updateRow(rowId, { [field]: value });
    queryClient.invalidateQueries({ queryKey: ["finance-results"] });
  }

  function toggleSort(key: string) {
    if (sort === key) {
      setDirection((d) => (d === "desc" ? "asc" : "desc"));
    } else {
      setSort(key);
      setDirection("desc");
    }
  }

  const totals = resultsQuery.data?.totals;

  return (
    <div className="space-y-4">
      <FinanceImportPanel
        onImported={(result) => {
          setSelected({ year: result.year, month: result.month });
          refreshAll();
        }}
      />

      {periodsQuery.isError ? (
        <QueryStateNotice
          state="error"
          description="Nie udało się wczytać listy miesięcy."
          onRetry={() => periodsQuery.refetch()}
        />
      ) : periods.length === 0 && !periodsQuery.isLoading ? (
        <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
          Nie zaimportowano jeszcze żadnego miesiąca. Wgraj plik Excel powyżej.
        </div>
      ) : (
        <>
          <StatCardGrid>
            <StatCard
              label="KOSZT"
              icon={Wallet}
              value={formatMoney(totals?.cost ?? null)}
              sub="Suma wynagrodzeń kontraktorów"
            />
            <StatCard
              label="PRZYCHÓD"
              icon={Banknote}
              value={formatMoney(totals?.revenue ?? null)}
              sub="Suma wystawionych faktur"
            />
            <StatCard
              label="MARŻA"
              icon={TrendingUp}
              value={formatMoney(totals?.margin ?? null)}
              sub={
                totals?.avg_margin_pct != null
                  ? `Śr. marża: ${totals.avg_margin_pct.toLocaleString("pl-PL", {
                      maximumFractionDigits: 1,
                    })}%`
                  : undefined
              }
            />
          </StatCardGrid>

          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="relative min-w-[16rem] flex-1">
              <Search
                className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden
              />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Szukaj po kandydacie, kliencie…"
                aria-label="Szukaj wyników"
                className="w-full rounded-lg border border-border bg-background py-2 pl-9 pr-3 text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
              />
            </div>

            {/* JEDEN selektor sterujący kaflami i tabelą; lista zawiera
                wyłącznie miesiące, które mają import. */}
            <select
              aria-label="Miesiąc"
              value={active ? `${active.year}-${active.month}` : ""}
              onChange={(e) => {
                const [y, m] = e.target.value.split("-").map(Number);
                setSelected({ year: y, month: m });
              }}
              className="rounded-md border border-border bg-background px-3 py-2 text-sm font-medium"
            >
              {periods.map((p) => (
                <option key={p.run_id} value={`${p.year}-${p.month}`}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>

          {resultsQuery.isError ? (
            <QueryStateNotice
              state="error"
              description="Nie udało się wczytać wyników za wybrany miesiąc."
              onRetry={() => resultsQuery.refetch()}
            />
          ) : resultsQuery.isLoading ? (
            <div className="py-10 text-center text-sm text-muted-foreground">
              Ładowanie wyników…
            </div>
          ) : (
            <>
              {(resultsQuery.data?.needs_completion_count ?? 0) > 0 && (
                <p className="text-xs text-muted-foreground">
                  Kliknij dwukrotnie komórkę, aby ją edytować. Pola oznaczone jako{" "}
                  <span className="rounded bg-destructive/10 px-1 text-destructive">
                    brak danych
                  </span>{" "}
                  wymagają uzupełnienia po imporcie (
                  {resultsQuery.data?.needs_completion_count}{" "}
                  {resultsQuery.data?.needs_completion_count === 1
                    ? "wiersz"
                    : "wierszy"}
                  ).
                </p>
              )}
              <FinanceResultsTable
                rows={resultsQuery.data?.rows ?? []}
                sort={sort}
                direction={direction}
                onSort={toggleSort}
                onEdit={handleEdit}
                onError={(msg) => showToast(msg, "error")}
                searching={searching}
              />
            </>
          )}
        </>
      )}
    </div>
  );
}
