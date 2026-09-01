"use client";

import { useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  ChevronsUpDown,
  Info,
  Loader2,
  Users,
} from "lucide-react";
import type { InsightsPeriodParams } from "@/lib/insights-api";
import {
  insightsTeamApi,
  insightsTeamQueryKeys,
  type TeamTableMetricKey,
  type TeamTableRow,
} from "@/lib/insights-team-api";
import { cn } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { count } from "./InsightsFormat";
import { SectionError } from "./_shared";

interface Props {
  period: InsightsPeriodParams;
  /**
   * Plakietki ostrzeżeń pod nazwiskiem (`/api/insights/performance-flags`).
   *
   * Wstrzykiwane, a nie pobierane tutaj: flagi są osobną powierzchnią
   * z osobnym endpointem i osobnym cyklem życia. Gdyby ta sekcja je wołała,
   * awaria flag przewracałaby tabelę wyników — dwie niezależne rzeczy
   * dzieliłyby jeden stan zapytania.
   */
  renderFlags?: (userId: number) => ReactNode;
}

type SortKey = "person" | "role" | TeamTableMetricKey;
type SortDirection = "asc" | "desc";

const METRIC_KEYS: TeamTableMetricKey[] = [
  "verifications",
  "recommendations",
  "interviews",
  "placements",
];

const METRIC_LABEL: Record<TeamTableMetricKey, string> = {
  verifications: "Weryfikacje",
  recommendations: "Rekomendacje",
  interviews: "Interviews",
  placements: "Placements",
};

/**
 * Chip roli — klasy TOKENOWE, dobierane po surowej wartości enuma, nie po
 * przetłumaczonej etykiecie (tłumaczenie może się zmienić, enum nie).
 */
const ROLE_CHIP: Record<string, string> = {
  recruiter: "bg-info-muted text-info-muted-foreground",
  tac: "bg-success-muted text-success-muted-foreground",
  sourcer: "bg-secondary text-secondary-foreground",
};
const ROLE_CHIP_FALLBACK = "bg-muted text-muted-foreground";

/**
 * Medal 1–3 w tokenach, nie w złocie/srebrze/brązie.
 *
 * Paleta medali nie ma odpowiednika w DS-ie, a zaszycie `bg-yellow-400`
 * wywróciłoby ekran w dark/soft/kids (i złamałoby regułę token-first).
 * Trzy tokeny o malejącej emfazie czytają się jako ta sama hierarchia.
 */
const MEDAL_CHIP = [
  "bg-warning-muted text-warning-muted-foreground",
  "bg-secondary text-secondary-foreground",
  "bg-muted text-muted-foreground",
] as const;

/** „Julia Świdkiewicz" → „JŚ". Bez nazwiska nie ma z czego zbudować inicjałów. */
export function initialsOf(name: string | null | undefined): string {
  const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  return parts
    .slice(0, 2)
    .map((p) => p[0]!.toLocaleUpperCase("pl-PL"))
    .join("");
}

/**
 * Wiersz bez nazwiska przegrywa — to nie jest wartość, tylko jej brak.
 *
 * Wynik jest ZAWSZE liczony w kierunku rosnącym i nie wolno go przepuszczać
 * przez mnożnik kierunku sortowania (patrz `sortRows`).
 */
function missingNameLast(a: TeamTableRow, b: TeamTableRow): number {
  return (a.name ? 0 : 1) - (b.name ? 0 : 1);
}

function compareRows(a: TeamTableRow, b: TeamTableRow, key: SortKey): number {
  if (key === "person") {
    return (a.name ?? "").localeCompare(b.name ?? "", "pl");
  }
  if (key === "role") {
    return (a.role_label ?? "").localeCompare(b.role_label ?? "", "pl");
  }
  return a[key] - b[key];
}

export function sortRows(
  rows: TeamTableRow[],
  key: SortKey,
  direction: SortDirection,
): TeamTableRow[] {
  const factor = direction === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    if (key === "person") {
      // Ta reguła MUSI stać PONAD kierunkiem sortowania. Wpuszczona do
      // `compareRows` i przemnożona przez `factor` odwraca się razem z nim,
      // więc przy „malejąco" wiersz BEZ nazwiska ląduje na szczycie kolumny
      // „Osoba" — brak danych wygrywa wtedy sortowanie po danych, i to
      // dokładnie w miejscu, w którym siada medal.
      const missing = missingNameLast(a, b);
      if (missing !== 0) return missing;
    }
    const primary = compareRows(a, b, key) * factor;
    if (primary !== 0) return primary;
    // Remis zawsze po nazwisku rosnąco — bez tego kolejność osób z równym
    // wynikiem zmieniałaby się między renderami i tabela „migałaby". Wiersz
    // bez nazwiska przegrywa remis WPROST, a nie przez sentinel wstawiony do
    // napisu: porównanie sztucznego znaku regułami ICU dla „pl" nie ma
    // gwarancji, że wypadnie na końcu.
    const missingOnTie = missingNameLast(a, b);
    if (missingOnTie !== 0) return missingOnTie;
    return (a.name ?? "").localeCompare(b.name ?? "", "pl");
  });
}

/**
 * „Performance per osoba" — serce zakładki Rekrutacja.
 *
 * Dwie rzeczy, których ta sekcja nie może zgubić:
 *
 * 1. **`unattributed` jest wyrenderowane obok sumy kolumny.** Kamień, którego
 *    nie da się przypisać nikomu (operator Traffita bez dopasowania konta),
 *    nie ma swojego wiersza — ale wchodzi w lejek. Wycięty po cichu sprawia,
 *    że suma kolumny nie zgadza się z lejkiem, a tabela wygląda na ZEPSUTĄ,
 *    nie na niekompletną.
 * 2. **Były pracownik zostaje.** Wiersz z `is_active === false` dostaje chip
 *    „były pracownik" i liczy się normalnie. Wycięcie go kasowałoby wstecz
 *    wyniki, które ta osoba osiągnęła w tym oknie.
 */
export function InsightsTeamTable({ period, renderFlags }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("verifications");
  const [sortDir, setSortDir] = useState<SortDirection>("desc");

  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: insightsTeamQueryKeys.teamTable(period),
    queryFn: () => insightsTeamApi.teamTable(period),
  });

  const rows = useMemo(
    () => sortRows(data?.rows ?? [], sortKey, sortDir),
    [data?.rows, sortKey, sortDir],
  );

  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: (data?.rows.length ?? 0) === 0,
  });

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "desc" ? "asc" : "desc"));
      return;
    }
    setSortKey(key);
    // Metryki otwierają się od najlepszych, kolumny opisowe od A do Z.
    setSortDir(key === "person" || key === "role" ? "asc" : "desc");
  }

  // Medal należy do RANKINGU, a ranking istnieje tylko przy sortowaniu
  // metryką malejąco. „Pierwszy od końca" i „pierwszy alfabetycznie" to nie
  // są podia — złoty krążek przy najsłabszym wyniku byłby czytany jako pochwała.
  const showMedals =
    sortDir === "desc" && sortKey !== "person" && sortKey !== "role";

  const totals = data?.totals;
  const unattributedTotal = totals
    ? METRIC_KEYS.reduce((sum, key) => sum + totals.unattributed[key], 0)
    : 0;

  return (
    <section className="bg-card rounded-xl border border-border p-6 shadow-xs">
      <h2 className="mb-4 flex items-center gap-2 text-base font-semibold text-foreground">
        <Users className="h-5 w-5 text-primary" aria-hidden="true" />
        Performance per osoba
        {totals && (
          <span className="ml-auto text-xs font-normal text-muted-foreground">
            {count(totals.users)} osób
            {totals.former_employees > 0
              ? ` · ${count(totals.former_employees)} byłych pracowników`
              : ""}
          </span>
        )}
      </h2>

      {viewState === "loading" ? (
        <div className="flex items-center justify-center py-8">
          <Loader2
            className="h-5 w-5 animate-spin text-muted-foreground"
            aria-label="Wczytywanie"
          />
        </div>
      ) : isBlockingViewState(viewState) ? (
        <SectionError
          label="Performance per osoba"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : viewState === "empty" ? (
        <div className="space-y-2 py-6 text-center">
          <p className="text-sm text-muted-foreground">
            Nikt nie odnotował kamienia milowego w wybranym okresie.
          </p>
          {unattributedTotal > 0 && (
            // Pustka przy niezerowych „nieprzypisanych" znaczy co innego niż
            // pustka przy zerze: ruch BYŁ, tylko nie wiadomo czyj.
            <p className="mx-auto max-w-xl text-xs text-muted-foreground">
              W tym oknie jest {count(unattributedTotal)} kamieni bez
              przypisanego autora — ruch się wydarzył, ale nie dało się go
              powiązać z kontem w NEXUSIE.
            </p>
          )}
        </div>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-xs uppercase text-muted-foreground">
                  <SortableHeader
                    label="Osoba"
                    columnKey="person"
                    sortKey={sortKey}
                    sortDir={sortDir}
                    onSort={toggleSort}
                    align="left"
                  />
                  <SortableHeader
                    label="Rola"
                    columnKey="role"
                    sortKey={sortKey}
                    sortDir={sortDir}
                    onSort={toggleSort}
                    align="left"
                  />
                  {METRIC_KEYS.map((key) => (
                    <SortableHeader
                      key={key}
                      label={METRIC_LABEL[key]}
                      columnKey={key}
                      sortKey={sortKey}
                      sortDir={sortDir}
                      onSort={toggleSort}
                      align="right"
                    />
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => (
                  <tr key={row.user_id} className="border-b border-border/50">
                    <td className="py-2 pr-3 align-top">
                      <div className="flex items-start gap-2">
                        <span className="flex w-6 shrink-0 justify-center pt-1">
                          {showMedals && index < 3 ? (
                            <span
                              className={cn(
                                "flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-semibold tabular-nums",
                                MEDAL_CHIP[index],
                              )}
                              aria-label={`Miejsce ${index + 1}`}
                            >
                              {index + 1}
                            </span>
                          ) : null}
                        </span>
                        <span
                          className={cn(
                            "flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
                            row.is_active === false
                              ? "bg-muted text-muted-foreground"
                              : "bg-primary/10 text-primary",
                          )}
                          aria-hidden="true"
                        >
                          {initialsOf(row.name)}
                        </span>
                        <span className="min-w-0">
                          <span className="flex flex-wrap items-center gap-1.5">
                            <span className="font-medium text-foreground">
                              {/* Konto zniknęło, dorobek został — nie wolno
                                  zwinąć tego wiersza do „nieprzypisanych",
                                  bo autor JEST znany. */}
                              {row.name ??
                                `Nieznany użytkownik (#${row.user_id})`}
                            </span>
                            {row.is_active === false && (
                              <span className="rounded-full border border-border bg-muted px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground">
                                były pracownik
                              </span>
                            )}
                          </span>
                          <span className="block text-xs text-muted-foreground">
                            {row.role_label ?? "—"}
                          </span>
                          {renderFlags ? (
                            <span className="mt-1 block">
                              {renderFlags(row.user_id)}
                            </span>
                          ) : null}
                        </span>
                      </div>
                    </td>
                    <td className="py-2 pr-3 align-top">
                      <span
                        className={cn(
                          "inline-block rounded-full px-2 py-0.5 text-xs font-medium",
                          ROLE_CHIP[row.role ?? ""] ?? ROLE_CHIP_FALLBACK,
                        )}
                      >
                        {row.role_label ?? "—"}
                      </span>
                    </td>
                    {METRIC_KEYS.map((key) => (
                      <td
                        key={key}
                        className="px-2 py-2 text-right align-top tabular-nums text-foreground"
                      >
                        {count(row[key])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
              {totals && (
                <tfoot>
                  <tr className="border-t border-border text-foreground">
                    <td className="py-2 pr-3 font-semibold" colSpan={2}>
                      Razem (widoczne wiersze)
                    </td>
                    {METRIC_KEYS.map((key) => (
                      <td
                        key={key}
                        className="px-2 py-2 text-right font-semibold tabular-nums"
                      >
                        {count(totals.attributed[key])}
                      </td>
                    ))}
                  </tr>
                  {/* Zawsze widoczne, także gdy wszędzie zero — wiersz, który
                      znika przy zerze, nie pozwala odróżnić „sprawdzone, nic
                      nie brakuje" od „nie sprawdzaliśmy". */}
                  <tr className="text-muted-foreground">
                    <td className="py-2 pr-3 text-xs" colSpan={2}>
                      Nieprzypisane (bez autora)
                    </td>
                    {METRIC_KEYS.map((key) => (
                      <td
                        key={key}
                        className="px-2 py-2 text-right text-xs tabular-nums"
                      >
                        {`+${count(totals.unattributed[key])}`}
                      </td>
                    ))}
                  </tr>
                  <tr className="border-t border-border/50 text-foreground">
                    <td className="py-2 pr-3 text-xs font-medium" colSpan={2}>
                      Łącznie (zgodne z lejkiem)
                    </td>
                    {METRIC_KEYS.map((key) => (
                      <td
                        key={key}
                        className="px-2 py-2 text-right text-xs font-medium tabular-nums"
                      >
                        {count(totals.all[key])}
                      </td>
                    ))}
                  </tr>
                </tfoot>
              )}
            </table>
          </div>

          <p className="mt-3 flex items-start gap-1.5 text-xs text-muted-foreground">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span>
              „Nieprzypisane" to kamienie milowe, których autora nie dało się
              powiązać z kontem w NEXUSIE (najczęściej ruch operatora w
              Traffcie). Nie mają wiersza w tabeli, ale wchodzą do lejka —
              dlatego suma widocznych wierszy bywa mniejsza niż liczba z lejka.
            </span>
          </p>
        </>
      )}
    </section>
  );
}

function SortableHeader({
  label,
  columnKey,
  sortKey,
  sortDir,
  onSort,
  align,
}: {
  label: string;
  columnKey: SortKey;
  sortKey: SortKey;
  sortDir: SortDirection;
  onSort: (key: SortKey) => void;
  align: "left" | "right";
}) {
  const active = sortKey === columnKey;
  const Icon = !active
    ? ChevronsUpDown
    : sortDir === "asc"
      ? ArrowUp
      : ArrowDown;
  return (
    <th
      scope="col"
      className={cn(
        "py-2 font-medium",
        align === "right" ? "px-2 text-right" : "pr-3 text-left",
      )}
      aria-sort={
        active ? (sortDir === "asc" ? "ascending" : "descending") : "none"
      }
    >
      <button
        type="button"
        onClick={() => onSort(columnKey)}
        className={cn(
          "inline-flex items-center gap-1 rounded-sm uppercase hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          align === "right" ? "flex-row-reverse" : "",
          active ? "text-foreground" : "",
        )}
      >
        {label}
        <Icon className="h-3 w-3" aria-hidden="true" />
      </button>
    </th>
  );
}
