"use client";

import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Search } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { cn } from "@/lib/utils";
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
  formatPct,
} from "@/components/finance/FinanceResultsTable";

export function FinanceResultsTab({ canWrite = true }: { canWrite?: boolean }) {
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
  // Kafel „Marża" to suma kolumny „Marża PLN" z arkusza, a nie przychód −
  // koszt. Gdy te liczby się rozjeżdżają, mówimy to wprost — trzy kafle na
  // jednym ekranie nie mogą udawać, że się sumują.
  const revenueMinusCost = totals ? totals.revenue - totals.cost : null;
  const marginDiffers =
    totals != null &&
    revenueMinusCost != null &&
    Math.abs(totals.margin - revenueMinusCost) >= 0.01;

  // Liczba wierszy z brakami po imporcie — czwarty kafel. `null` = jeszcze
  // nie wiadomo (wyniki się wczytują albo padły), wtedy kafel pokazuje „—”.
  const needsCompletion = resultsQuery.data?.needs_completion_count ?? null;

  return (
    // Kolejność na ekranie: liczby → import → wyszukiwarka → tabela (makieta
    // 02.10.2026). Import stoi w drzewie PIERWSZY i jest przestawiany klasą
    // `order-*`, żeby zmiana stanu listy miesięcy go nie przemontowała
    // (wybrany plik zostaje w polu).
    <div className="flex flex-col gap-3.5">
      {canWrite && (
        <div className="order-2">
          <FinanceImportPanel
            onImported={(result) => {
              setSelected({ year: result.year, month: result.month });
              refreshAll();
            }}
          />
        </div>
      )}

      {/* Kolejność gałęzi jest istotna: awaria → „jeszcze nie wiem" → pustka →
          dane. Wcześniej warunek pustki brzmiał `periods.length === 0 &&
          !isLoading`, więc stan „lista miesięcy jeszcze się wczytuje" spadał do
          gałęzi z danymi i rysował KOMPLETNY moduł na pustce: trzy kafle
          z „—" i pusty selektor miesiąca. Wyglądało to jak zaimportowany
          miesiąc bez ani jednej złotówki, a nie jak „nic tu jeszcze nie ma". */}
      {periodsQuery.isError ? (
        <div className="order-3">
          <QueryStateNotice
            state="error"
            description="Nie udało się wczytać listy miesięcy."
            onRetry={() => periodsQuery.refetch()}
          />
        </div>
      ) : !periodsQuery.isSuccess ? (
        <div className="order-3 py-10 text-center text-sm text-muted-foreground">
          Ładowanie miesięcy…
        </div>
      ) : periods.length === 0 ? (
        <div className="order-3 rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
          {canWrite
            ? "Nie zaimportowano jeszcze żadnego miesiąca. Wgraj plik Excel powyżej."
            : "Nie zaimportowano jeszcze żadnego miesiąca."}
        </div>
      ) : (
        <>
          <div className="order-1 space-y-1.5">
            <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
              <Kpi
                label="KOSZT"
                value={formatMoney(totals?.cost ?? null)}
                note="Suma wynagrodzeń kontraktorów"
              />
              <Kpi
                label="PRZYCHÓD"
                value={formatMoney(totals?.revenue ?? null)}
                note="Suma wystawionych faktur"
              />
              <Kpi
                label="MARŻA"
                value={formatMoney(totals?.margin ?? null)}
                note={
                  totals?.avg_margin_pct != null
                    ? // Marża % miesiąca = Σ marży / Σ faktur (ważona przychodem,
                      // liczy serwer) — nie średnia procentów wierszy.
                      `marża ${formatPct(totals.avg_margin_pct)} przychodu · suma „Marża PLN” z arkusza`
                    : "Suma „Marża PLN” z arkusza"
                }
              />
              <Kpi
                label="DO UZUPEŁNIENIA"
                tone={needsCompletion ? "warning" : "default"}
                value={
                  needsCompletion == null
                    ? "—"
                    : `${needsCompletion} ${needsCompletion === 1 ? "wiersz" : "wierszy"}`
                }
                note={
                  needsCompletion
                    ? "Pola „brak danych” po imporcie"
                    : needsCompletion === 0
                      ? "Wszystkie wiersze mają komplet danych"
                      : "Wiersze z brakami po imporcie"
                }
              />
            </div>
            {marginDiffers && totals && (
              <p className="text-xs text-muted-foreground" data-testid="finance-margin-note">
                Marża nie jest różnicą „Przychód” − „Koszt” (
                {formatMoney(revenueMinusCost)}) — to suma kolumny „Marża PLN”
                z arkusza.
                {totals.rows_without_margin > 0 &&
                  ` ${totals.rows_without_margin} ${
                    totals.rows_without_margin === 1 ? "wiersz" : "wierszy"
                  } bez marży (koszt ${formatMoney(
                    totals.cost_without_margin,
                  )}, zwykle bez faktury) jest w kaflu „Koszt”, ale nie obniża marży.`}
              </p>
            )}
          </div>

          <div className="order-3 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative min-w-[14rem] flex-1 xl:max-w-sm">
                <Search
                  className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
                  aria-hidden
                />
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Szukaj po kandydacie, kliencie…"
                  aria-label="Szukaj wyników"
                  className="h-8 w-full rounded-md border border-border bg-background pl-9 pr-3 text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring pointer-coarse:h-10"
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
                className="h-8 rounded-md border border-border bg-background px-3 text-sm font-medium pointer-coarse:h-10"
              >
                {periods.map((p) => (
                  <option key={p.run_id} value={`${p.year}-${p.month}`}>
                    {p.label}
                  </option>
                ))}
              </select>

              {canWrite && (
                <p className="min-w-0 basis-full text-xs leading-4 text-muted-foreground xl:flex-1 xl:basis-0">
                  Kliknij dwukrotnie komórkę, aby ją edytować.
                  {needsCompletion ? (
                    <>
                      {" "}
                      Pola oznaczone jako{" "}
                      <span className="rounded bg-destructive/10 px-1 text-destructive">
                        brak danych
                      </span>{" "}
                      wymagają uzupełnienia po imporcie.
                    </>
                  ) : null}
                </p>
              )}
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
              <FinanceResultsTable
                rows={resultsQuery.data?.rows ?? []}
                sort={sort}
                direction={direction}
                onSort={toggleSort}
                onEdit={handleEdit}
                onError={(msg) => showToast(msg, "error")}
                searching={searching}
                readOnly={!canWrite}
              />
            )}
          </div>
        </>
      )}
    </div>
  );
}

/**
 * Zwarty kafel z liczbą miesiąca (wartość ok. 20 px). Cztery mieszczą się
 * w jednym rzędzie od `lg`, więc tabela zaczyna się wyżej niż przy dużych
 * kaflach z ikoną.
 */
function Kpi({
  label,
  value,
  note,
  tone = "default",
}: {
  label: string;
  value: string;
  note: string;
  tone?: "default" | "warning";
}) {
  const warning = tone === "warning";
  return (
    <div
      className={cn(
        "min-w-0 rounded-[10px] border px-3.5 py-2",
        warning
          ? "border-transparent bg-warning-muted text-warning-muted-foreground"
          : "border-border bg-card",
      )}
    >
      {/* Etykieta i dopowiedzenie w jednej linii (pełny tekst w dymku), pod
          nimi liczba — kafel ma dwie linie zamiast trzech. */}
      <div
        className={cn(
          "flex min-w-0 items-baseline gap-1.5 text-[11px] leading-4",
          !warning && "text-muted-foreground",
        )}
        title={note}
      >
        <span className="shrink-0 font-medium tracking-[0.04em]">{label}</span>
        <span className="truncate">· {note}</span>
      </div>
      <div className="font-display text-xl font-semibold leading-7 tabular-nums">
        {value}
      </div>
    </div>
  );
}
