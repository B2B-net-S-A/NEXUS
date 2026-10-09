"use client";

/**
 * Pasek filtrów nad listami „Nowe rekrutacje — kto prowadzi” i „Propozycje
 * automatu do akceptacji” (09.10.2026): klient, kategoria, Delivery Lead,
 * osoba, priorytet. Reguły są w `lib/new-job-leads-filters.ts`; tu jest stan
 * (z pamięcią w przeglądarce dla konta) i pola wyboru.
 */

import { useEffect, useMemo, useState } from "react";

import { competenceShortLabel } from "@/components/v2/CompetenceCategoryBadge";
import {
  EMPTY_LEAD_FILTERS,
  filterLeads,
  hasLeadFilters,
  leadFilterOptions,
  liveLeadFilters,
  readStoredLeadFilters,
  writeStoredLeadFilters,
  type LeadFilterList,
  type LeadFilterOptions,
  type LeadFilterRow,
  type LeadFilters,
} from "@/lib/new-job-leads-filters";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";

type FilterKey = keyof LeadFilters;

export interface LeadFiltersState<T> {
  /** Filtry, które mają o co się zaczepić na dzisiejszej liście. */
  filters: LeadFilters;
  filtered: T[];
  filtering: boolean;
  options: LeadFilterOptions;
  /** Pola do pokazania; pusta lista = bez paska. */
  keys: FilterKey[];
  choose: (next: LeadFilters) => void;
}

const FIELD_ORDER: FilterKey[] = ["client", "cat", "dl", "who", "prio"];

/**
 * Stan filtrów jednej listy. Pasek stoi dopiero, gdy lista ma więcej niż
 * `showAbove` wierszy (krótką widać w całości) albo gdy filtr już działa —
 * ustawiony filtr musi dać się zobaczyć i zdjąć.
 */
export function useLeadFilters<T extends LeadFilterRow>(
  rows: readonly T[],
  list: LeadFilterList,
  showAbove: number,
): LeadFiltersState<T> {
  const userId = useAuthStore((state) => state.user?.id);
  const [chosen, setChosen] = useState<LeadFilters>(EMPTY_LEAD_FILTERS);
  // Zapamiętany wybór wczytujemy po zamontowaniu: konto bywa znane dopiero
  // po odtworzeniu sesji, a pamięci przeglądarki nie ma przy renderze serwera.
  useEffect(() => {
    setChosen(readStoredLeadFilters(userId, list));
  }, [userId, list]);
  // W polu kategorii ta sama krótka nazwa co na plakietce w wierszu.
  const options = useMemo(
    () =>
      leadFilterOptions(rows, (row) =>
        row.category_name ? (competenceShortLabel(row.category_slug) ?? row.category_name) : null,
      ),
    [rows],
  );
  const filters = useMemo(() => liveLeadFilters(chosen, options), [chosen, options]);
  const filtered = useMemo(() => filterLeads(rows, filters), [rows, filters]);
  const filtering = hasLeadFilters(filters);
  // Pole z jedną pozycją niczego nie zawęża — chyba że właśnie filtruje.
  const keys =
    rows.length > showAbove || filtering
      ? FIELD_ORDER.filter((key) => options[key].length > 1 || filters[key])
      : [];
  const choose = (next: LeadFilters) => {
    setChosen(next);
    writeStoredLeadFilters(userId, next, list);
  };
  return { filters, filtered, filtering, options, keys, choose };
}

export interface LeadFiltersBarProps<T> {
  state: LeadFiltersState<T>;
  /** Nazwa grupy dla czytnika ekranu. */
  label?: string;
  /** Pole osoby: prowadzący na liście rekrutacji, proponowana osoba w propozycjach. */
  who?: { label: string; all: string };
}

export function LeadFiltersBar<T>({
  state,
  label = "Filtry listy",
  who = { label: "Prowadzący", all: "Prowadzący: wszyscy" },
}: LeadFiltersBarProps<T>) {
  if (state.keys.length === 0) return null;
  const fields: Record<FilterKey, { label: string; all: string }> = {
    client: { label: "Klient", all: "Klient: wszyscy" },
    cat: { label: "Kategoria", all: "Kategoria: wszystkie" },
    dl: { label: "Delivery Lead", all: "Delivery Lead: wszyscy" },
    who,
    prio: { label: "Priorytet", all: "Priorytet: każdy" },
  };

  return (
    // Wąska sekcja (telefon): pola w dwóch kolumnach; od 520 px — w rzędzie.
    <div className="@container/filters mb-2">
      <div
        role="group"
        aria-label={label}
        className="grid grid-cols-2 items-center gap-2 @min-[520px]/filters:flex @min-[520px]/filters:flex-wrap"
      >
        {state.keys.map((key) => {
          const value = state.filters[key];
          return (
            <select
              key={key}
              aria-label={fields[key].label}
              value={value}
              onChange={(event) => state.choose({ ...state.filters, [key]: event.target.value })}
              className={cn(
                "h-8 w-full min-w-0 rounded-md border bg-background px-2 text-xs focus:outline-none focus:ring-2 focus:ring-ring @min-[520px]/filters:w-auto @min-[520px]/filters:max-w-[200px]",
                value
                  ? "border-primary font-medium text-foreground"
                  : "border-input text-muted-foreground",
              )}
            >
              <option value="">{fields[key].all}</option>
              {state.options[key].map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          );
        })}
        {state.filtering ? (
          <button
            type="button"
            onClick={() => state.choose(EMPTY_LEAD_FILTERS)}
            className="text-xs font-medium text-primary hover:underline"
          >
            Wyczyść filtry
          </button>
        ) : null}
      </div>
    </div>
  );
}
