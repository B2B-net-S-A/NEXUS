"use client";

import { Download, RotateCcw, Search, SlidersHorizontal } from "lucide-react";

import {
  DEFAULT_ORDER_LIST_FILTERS,
  type OrderListFilters,
  type OrderSort,
} from "@/lib/client-order-list";

interface Props {
  search: string;
  onSearchChange: (value: string) => void;
  filters: OrderListFilters;
  onFiltersChange: (filters: OrderListFilters) => void;
  showMdSort?: boolean;
  showBudgetFilter?: boolean;
  resultCount: number;
  exporting: boolean;
  onExport: () => void;
}

function activeFilterCount(filters: OrderListFilters): number {
  return [
    filters.startFrom || filters.startTo,
    filters.endFrom || filters.endTo,
    filters.nearBudget,
    filters.endingSoon,
    filters.sort !== "created_desc",
  ].filter(Boolean).length;
}

export function OrderListControls({
  search,
  onSearchChange,
  filters,
  onFiltersChange,
  showMdSort = true,
  showBudgetFilter = true,
  resultCount,
  exporting,
  onExport,
}: Props) {
  const update = <K extends keyof OrderListFilters>(
    key: K,
    value: OrderListFilters[K],
  ) => onFiltersChange({ ...filters, [key]: value });
  const activeCount = activeFilterCount(filters);

  return (
    <section className="rounded-lg border border-border bg-card p-3">
      <div className="flex flex-col gap-2 sm:flex-row">
        <div className="relative min-w-0 flex-1">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <input
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="Szukaj po numerze zamówienia lub imieniu/nazwisku konsultanta…"
            aria-label="Szukaj zamówień"
            className="w-full rounded-md border border-border bg-background py-2 pl-9 pr-3 text-sm text-foreground outline-hidden placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
          />
        </div>
        <button
          type="button"
          onClick={onExport}
          disabled={exporting || resultCount === 0}
          className="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-md border border-border bg-background px-3 py-2 text-sm font-medium text-foreground hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Download className="h-4 w-4" aria-hidden="true" />
          {exporting ? "Przygotowuję…" : "Pobierz do Excela"}
        </button>
      </div>

      <details className="mt-3">
        <summary className="flex cursor-pointer list-none items-center gap-2 text-sm font-medium text-foreground">
          <SlidersHorizontal className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          Filtry i sortowanie
          {activeCount > 0 ? (
            <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs text-primary">
              {activeCount}
            </span>
          ) : null}
        </summary>

        <div className="mt-3 grid gap-3 border-t border-border pt-3 md:grid-cols-2 xl:grid-cols-4">
          <fieldset className="grid grid-cols-2 gap-2">
            <legend className="col-span-2 text-xs font-medium text-muted-foreground">
              Data rozpoczęcia
            </legend>
            <label className="text-xs text-muted-foreground">
              Od
              <input
                type="date"
                value={filters.startFrom}
                onChange={(event) => update("startFrom", event.target.value)}
                className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground"
              />
            </label>
            <label className="text-xs text-muted-foreground">
              Do
              <input
                type="date"
                value={filters.startTo}
                onChange={(event) => update("startTo", event.target.value)}
                className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground"
              />
            </label>
          </fieldset>

          <fieldset className="grid grid-cols-2 gap-2">
            <legend className="col-span-2 text-xs font-medium text-muted-foreground">
              Data zakończenia
            </legend>
            <label className="text-xs text-muted-foreground">
              Od
              <input
                type="date"
                value={filters.endFrom}
                onChange={(event) => update("endFrom", event.target.value)}
                className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground"
              />
            </label>
            <label className="text-xs text-muted-foreground">
              Do
              <input
                type="date"
                value={filters.endTo}
                onChange={(event) => update("endTo", event.target.value)}
                className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground"
              />
            </label>
          </fieldset>

          <label className="text-xs font-medium text-muted-foreground">
            Sortowanie
            <select
              value={filters.sort}
              onChange={(event) => update("sort", event.target.value as OrderSort)}
              className="mt-1 w-full rounded-md border border-border bg-background px-2 py-2 text-sm text-foreground"
            >
              <option value="created_desc">Data dodania — najnowsze</option>
              {showMdSort ? (
                <>
                  <option value="md_asc">Łączna liczba MD — rosnąco</option>
                  <option value="md_desc">Łączna liczba MD — malejąco</option>
                </>
              ) : null}
              <option value="cost_asc">Stawka kosztowa — rosnąco</option>
              <option value="cost_desc">Stawka kosztowa — malejąco</option>
              <option value="revenue_asc">Stawka przychodowa — rosnąco</option>
              <option value="revenue_desc">Stawka przychodowa — malejąco</option>
            </select>
          </label>

          <div className="flex flex-col gap-2 text-sm">
            {showBudgetFilter ? (
              <label className="flex items-start gap-2 text-foreground">
                <input
                  type="checkbox"
                  checked={filters.nearBudget}
                  onChange={(event) => update("nearBudget", event.target.checked)}
                  className="mt-0.5 h-4 w-4 rounded border-border text-primary focus:ring-ring"
                />
                Bliskie wyczerpania budżetu MD (≥80%)
              </label>
            ) : null}
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-2 text-foreground">
                <input
                  type="checkbox"
                  checked={filters.endingSoon}
                  onChange={(event) => update("endingSoon", event.target.checked)}
                  className="h-4 w-4 rounded border-border text-primary focus:ring-ring"
                />
                Kończące się w ciągu
              </label>
              <input
                type="number"
                min={0}
                step={1}
                value={filters.endingDays}
                disabled={!filters.endingSoon}
                onChange={(event) =>
                  update(
                    "endingDays",
                    Number.isFinite(event.currentTarget.valueAsNumber)
                      ? Math.max(0, event.currentTarget.valueAsNumber)
                      : 30,
                  )
                }
                aria-label="Liczba dni do zakończenia"
                className="w-20 rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground disabled:opacity-50"
              />
              <span className="text-muted-foreground">dni</span>
            </div>
          </div>
        </div>

        <div className="mt-3 flex items-center justify-between gap-3">
          <p className="text-xs text-muted-foreground">
            Widoczne wyniki: {resultCount}
          </p>
          <button
            type="button"
            onClick={() => onFiltersChange({ ...DEFAULT_ORDER_LIST_FILTERS })}
            disabled={activeCount === 0}
            className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
          >
            <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
            Wyczyść filtry
          </button>
        </div>
      </details>
    </section>
  );
}
