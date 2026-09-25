"use client";

import { useQuery } from "@tanstack/react-query";

import { RequirementRowsField } from "@/components/v2/candidates/RequirementRowsField";
import { candidatesApi } from "@/lib/api";
import { cleanRows, describeKeywordSearch } from "@/lib/keyword-requirements";
import { DEFAULT_FILTERS, filtersToApiParams } from "@/lib/url-filters";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { cn } from "@/lib/utils";

/** „1 osoba”, „3 osoby”, „12 osób” — polska odmiana liczebnika. */
export function peopleCountLabel(n: number): string {
  const lastTwo = n % 100;
  const last = n % 10;
  const shown = n.toLocaleString("pl-PL");
  if (n === 1) return "1 osoba";
  if (last >= 2 && last <= 4 && !(lastTwo >= 12 && lastTwo <= 14)) return `${shown} osoby`;
  return `${shown} osób`;
}

/**
 * Ile osób w bazie spełnia wymagania — ten sam silnik i te same statusy co
 * „Szukaj ręcznie” (lista kandydatów, aktywni i pasywni), więc liczba
 * zgadza się z tym, co rekruter zobaczy po otwarciu wyszukiwania.
 */
function useRequirementsCount(rows: string[][], exclude: string[], enabled: boolean) {
  const key = useDebouncedValue(JSON.stringify({ rows, exclude }), 500);
  const settled = JSON.parse(key) as { rows: string[][]; exclude: string[] };
  return useQuery({
    queryKey: ["search-requirements-count", key],
    enabled: enabled && settled.rows.length > 0,
    staleTime: 60_000,
    queryFn: async () => {
      const params = filtersToApiParams(
        {
          ...DEFAULT_FILTERS,
          status: ["active", "passive"],
          qAny: settled.rows,
          qNone: settled.exclude,
        },
        1,
        { page_size: 1 },
      );
      const { data } = await candidatesApi.list(params);
      return typeof data?.total === "number" ? (data.total as number) : null;
    },
  });
}

export interface SearchRequirementsEditorProps {
  rows: string[][];
  exclude: string[];
  onChange: (next: { rows: string[][]; exclude: string[] }) => void;
  /** Wymagane i puste (bramka „Przekaż do searchu”). */
  invalid?: boolean;
  /** Harness `/preview/*` — bez zapytań. */
  countEnabled?: boolean;
  /** Bez prawa edycji: samo zdanie z wymaganiami, bez pól. */
  readOnly?: boolean;
  className?: string;
}

/**
 * Wymagania do wyszukiwania w bazie (sekcja 2 Championa, decyzje Artura
 * 25.09.2026): wiersz = wymaganie, słowa w wierszu = warianty. Rekruter
 * dostaje je jako start „Szukaj ręcznie”; automaty ich nie czytają.
 */
export function SearchRequirementsEditor({
  rows,
  exclude,
  onChange,
  invalid = false,
  countEnabled = true,
  readOnly = false,
  className,
}: SearchRequirementsEditorProps) {
  const clean = cleanRows(rows);
  const count = useRequirementsCount(clean, exclude, countEnabled && !readOnly);
  const sentence = describeKeywordSearch({ rows, exclude, scopeLabel: null });
  if (readOnly) {
    return (
      <p className={cn("text-sm text-foreground", className)}>
        {clean.length === 0 ? "Brak wymagań do wyszukiwania." : sentence}
      </p>
    );
  }
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <RequirementRowsField
        rows={rows}
        onRowsChange={(next) => onChange({ rows: next, exclude })}
        exclude={exclude}
        onExcludeChange={(next) => onChange({ rows, exclude: next })}
        suggest={{}}
        invalid={invalid}
      />
      <div
        className="flex flex-wrap items-baseline gap-x-2 gap-y-1 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2 text-sm"
        aria-live="polite"
      >
        {clean.length > 0 && countEnabled && (
          <span className="font-semibold tabular-nums text-primary">
            {count.isSuccess && count.data != null
              ? `~${peopleCountLabel(count.data)} w bazie`
              : count.isError
                ? "Nie udało się policzyć osób w bazie."
                : "Liczę osoby w bazie…"}
          </span>
        )}
        <span className="text-foreground">
          {clean.length === 0
            ? invalid
              ? "Dodaj co najmniej jedno wymaganie — bez niego rekrutacja nie trafi do searchu."
              : "Rekruter zacznie „Szukaj ręcznie” od tych wymagań."
            : sentence}
        </span>
      </div>
    </div>
  );
}
