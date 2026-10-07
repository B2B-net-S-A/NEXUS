"use client";

import { useQuery } from "@tanstack/react-query";

import { RequirementRowsField } from "@/components/v2/candidates/RequirementRowsField";
import { fetchCandidateListPage } from "@/components/v2/pages/candidate-list-query";
import { cleanRows, describeKeywordSearch } from "@/lib/keyword-requirements";
import type { CriticalResolution } from "@/lib/critical-skills";
import { mandatorySourceNote, splitByCritical } from "@/lib/job-search-filters";
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

/** Zdanie pod wierszami: ile osób spełnia wiersze obowiązkowe i co z resztą. */
export function requirementsCountLabel(data: {
  total: number | null;
  preferredRows: number;
  requiredRows: number;
}): string | null {
  if (data.total == null) return null;
  if (data.preferredRows === 0) return `~${peopleCountLabel(data.total)} w bazie`;
  const n = data.preferredRows;
  const few = n % 10 >= 2 && n % 10 <= 4 && !(n % 100 >= 12 && n % 100 <= 14);
  const rest =
    n === 1
      ? "1 wiersz tylko podnosi w kolejności"
      : few
        ? `${n} wiersze tylko podnoszą w kolejności`
        : `${n} wierszy tylko podnosi w kolejności`;
  if (data.requiredRows === 0) return `Cała baza (~${peopleCountLabel(data.total)}); ${rest}`;
  return `~${peopleCountLabel(data.total)} ma umiejętności krytyczne; ${rest}`;
}

/**
 * Ile osób w bazie spełnia wymagania — ten sam silnik i te same statusy co
 * „Szukaj ręcznie” (lista kandydatów, aktywni i pasywni), więc liczba
 * zgadza się z tym, co rekruter zobaczy po otwarciu wyszukiwania. Zapytanie
 * idzie funkcją listy: tablice lecą jako powtórzony parametr, a forma
 * `status[]=` byłaby dla serwera innym polem i liczba objęłaby całą bazę.
 *
 * Obowiązkowe są wyłącznie umiejętności krytyczne z serwera — ta sama reguła
 * co „Szukaj w bazie” i „Szukaj ręcznie” (`splitByCritical` / `jobSearchPlan`,
 * `critical_resolution.search_rows`; audyt 06.10.2026). Pozostałe wiersze
 * tylko podnoszą w kolejności; klasyfikacja „technologia / nie” już o tym
 * nie decyduje.
 */
function useRequirementsCount(
  required: string[][],
  preferredRows: number,
  exclude: string[],
  enabled: boolean,
) {
  const key = useDebouncedValue(JSON.stringify({ required, preferredRows, exclude }), 500);
  const settled = JSON.parse(key) as {
    required: string[][];
    preferredRows: number;
    exclude: string[];
  };
  return useQuery({
    queryKey: ["search-requirements-count", key],
    enabled: enabled && settled.required.length + settled.preferredRows > 0,
    staleTime: 60_000,
    queryFn: async ({ signal }) => {
      const params = filtersToApiParams(
        {
          ...DEFAULT_FILTERS,
          status: ["active", "passive"],
          qAny: settled.required,
          qNone: settled.exclude,
        },
        1,
        { page_size: 1 },
      );
      const data = await fetchCandidateListPage<{ total?: unknown }>(params, signal);
      return {
        total: typeof data?.total === "number" ? data.total : null,
        preferredRows: settled.preferredRows,
        requiredRows: settled.required.length,
      };
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
  /**
   * `critical_resolution` zapisanego profilu (`GET …/champion-profile`) —
   * z niej liczba wie, które wiersze są obowiązkowe. Brak = nie wiadomo,
   * nic nie jest obowiązkowe (jak „Szukaj w bazie” bez odpowiedzi serwera).
   */
  critical?: CriticalResolution | null;
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
  critical = null,
  className,
}: SearchRequirementsEditorProps) {
  const clean = cleanRows(rows);
  const split = splitByCritical(clean, [], critical);
  const count = useRequirementsCount(
    split.required,
    split.preferred.length,
    exclude,
    countEnabled && !readOnly,
  );
  const sentence = describeKeywordSearch({ rows, exclude, scopeLabel: null });
  // Odpowiedź bez liczby to „nie wiemy”, nie wieczne „Liczę…”.
  const countLabel = count.isSuccess
    ? count.data.total != null
      ? requirementsCountLabel(count.data)
      : null
    : count.isError
      ? "Nie udało się policzyć osób w bazie."
      : "Liczę osoby w bazie…";
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
        {clean.length > 0 && countEnabled && countLabel && (
          <span className="font-semibold tabular-nums text-primary">{countLabel}</span>
        )}
        <span className="text-foreground">
          {clean.length === 0
            ? invalid
              ? "Dodaj co najmniej jedno wymaganie — bez niego rekrutacja nie trafi do searchu."
              : "Rekruter zacznie „Szukaj ręcznie” od tych wymagań."
            : sentence}
        </span>
        {clean.length > 0 && critical ? (
          <span className="basis-full text-xs text-muted-foreground">
            {mandatorySourceNote(split)}
          </span>
        ) : null}
      </div>
    </div>
  );
}
