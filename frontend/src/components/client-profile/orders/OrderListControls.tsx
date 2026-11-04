"use client";

import type { ReactNode } from "react";
import { ChevronDown, Download, RotateCcw, Search, SlidersHorizontal } from "lucide-react";

import { Button } from "@/components/ui/button";

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
  /** Dodatkowe kontrolki w rzędzie wyszukiwarki (np. filtr typu zamówienia). */
  extraControls?: ReactNode;
  /** Drobny tekst na końcu rzędu (np. „14 pozycji na liście”). */
  trailing?: ReactNode;
}

/** „Pobierz do Excela” — stoi w rzędzie pigułek, obok „Nowe zamówienie”. */
export function OrderExportButton({
  exporting,
  disabled,
  onExport,
}: {
  exporting: boolean;
  disabled: boolean;
  onExport: () => void;
}) {
  return (
    <Button type="button" size="sm" variant="outline" onClick={onExport} disabled={exporting || disabled}>
      <Download className="h-4 w-4" aria-hidden="true" />
      {exporting ? "Przygotowuję…" : "Pobierz do Excela"}
    </Button>
  );
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
  extraControls = null,
  trailing = null,
}: Props) {
  const update = <K extends keyof OrderListFilters>(
    key: K,
    value: OrderListFilters[K],
  ) => onFiltersChange({ ...filters, [key]: value });
  const activeCount = activeFilterCount(filters);

  return (
    // Jeden rząd: wyszukiwarka, filtr typu, „Filtry i sortowanie”. Rozwinięte
    // filtry zajmują własny, pełny rząd pod spodem (`open:basis-full`).
    <section className="flex flex-wrap items-center gap-2" data-help="client.orders.search">
      <div className="relative min-w-0 flex-1 basis-64">
        <Search
          className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden="true"
        />
        <input
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="Szukaj po numerze zamówienia lub imieniu/nazwisku konsultanta…"
          aria-label="Szukaj zamówień"
          className="h-8 w-full rounded-md border border-border bg-card pl-9 pr-3 text-sm text-foreground outline-hidden placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring pointer-coarse:h-10"
        />
      </div>
      {extraControls}
      {trailing ? <div className="order-2 text-xs text-muted-foreground">{trailing}</div> : null}

      <details className="group/filters order-1 min-w-0 open:order-3 open:basis-full">
        <summary className="inline-flex h-8 cursor-pointer list-none items-center gap-1.5 rounded-md border border-border bg-card px-2.5 text-xs font-medium text-foreground hover:bg-muted pointer-coarse:h-10 [&::-webkit-details-marker]:hidden">
          <SlidersHorizontal className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          Filtry i sortowanie
          {activeCount > 0 ? (
            <span className="rounded-full bg-primary/10 px-1.5 text-[11px] font-semibold tabular-nums text-primary">
              {activeCount}
            </span>
          ) : null}
          <ChevronDown
            className="h-3.5 w-3.5 text-muted-foreground transition-transform group-open/filters:rotate-180"
            aria-hidden="true"
          />
        </summary>

        <div className="mt-2 rounded-lg border border-border bg-card p-3">
          <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-4">
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
                  className="mt-1 w-full min-w-0 rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground"
                />
              </label>
              <label className="text-xs text-muted-foreground">
                Do
                <input
                  type="date"
                  value={filters.startTo}
                  onChange={(event) => update("startTo", event.target.value)}
                  className="mt-1 w-full min-w-0 rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground"
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
                  className="mt-1 w-full min-w-0 rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground"
                />
              </label>
              <label className="text-xs text-muted-foreground">
                Do
                <input
                  type="date"
                  value={filters.endTo}
                  onChange={(event) => update("endTo", event.target.value)}
                  className="mt-1 w-full min-w-0 rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground"
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
                <option value="consultant_asc">Konsultant — A→Z</option>
                <option value="consultant_desc">Konsultant — Z→A</option>
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
                  Bliskie wyczerpania budżetu (≥80%)
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
            <p className="text-xs tabular-nums text-muted-foreground">
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
        </div>
      </details>
    </section>
  );
}
