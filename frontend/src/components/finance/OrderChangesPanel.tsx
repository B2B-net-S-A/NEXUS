"use client";

import type { ReactNode } from "react";
import { AlertTriangle, Download, Loader2 } from "lucide-react";

import { FilterBar, type FilterBarChip } from "@/components/ds/FilterBar";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { Input } from "@/components/ui/input";
import type { OrderChangesResponse } from "@/lib/api/finance";
import {
  STATUS_FILTER_LABELS,
  doneInMonthLabel,
  type StatusCounts,
  type StatusFilter,
} from "@/lib/finance-order-board";
import {
  formatDay,
  peopleLabel,
  type MonthOption,
} from "@/lib/finance-order-changes";
import { cn } from "@/lib/utils";

import {
  OrderChangesBoard,
  type OrderChangesBoardProps,
} from "./OrderChangesBoard";

export type OrderChangesSubTab =
  "changes" | "entries" | "exits" | "ending" | "gaps";

export const ORDER_CHANGES_SUB_TABS: readonly OrderChangesSubTab[] = [
  "changes",
  "entries",
  "exits",
  "ending",
  "gaps",
];

export const SUB_TAB_LABELS: Record<OrderChangesSubTab, string> = {
  changes: "Zmiany",
  entries: "Wejścia",
  exits: "Zejścia",
  // Klucz `ending` (URL `sub=ending`) zostaje — zmieniła się nazwa (D4, 24.09).
  ending: "Zamówienia bez kontynuacji",
  gaps: "Braki",
};

/** „Data" znaczy w każdej zakładce co innego — etykieta musi to mówić. */
export const DATE_FILTER_LABELS: Record<OrderChangesSubTab, string> = {
  changes: "Data zmiany",
  entries: "Data wejścia",
  exits: "Data zejścia",
  ending: "Data końca zamówienia",
  gaps: "Data wykrycia braku",
};

export interface OrderChangesFilterProps {
  search: string;
  onSearchChange: (value: string) => void;
  dateFrom: string;
  onDateFromChange: (value: string) => void;
  dateTo: string;
  onDateToChange: (value: string) => void;
  /**
   * Picker klienta podaje rodzic. Panel nie może sam odpytywać API — ten sam
   * komponent renderuje publiczny harness `/preview/finance-order-changes`,
   * który musi wykonywać ZERO zapytań.
   */
  clientPicker: ReactNode;
  clientLabel: string | null;
  onClearClient: () => void;
  /** Obie daty naraz — dwa osobne wywołania w jednym ticku zapisałyby do
   *  adresu nieaktualną wartość drugiego pola. */
  onClearDates: () => void;
  onClearAll: () => void;
}

interface OrderChangesPanelProps {
  data: OrderChangesResponse | null;
  /** `null` = dane jeszcze nie przyszły; wtedy liczniki się nie renderują. */
  body: ReactNode | null;
  subTab: OrderChangesSubTab;
  onSubTabChange: (next: OrderChangesSubTab) => void;
  month: string;
  months: MonthOption[];
  onMonthChange: (value: string) => void;
  onExport: () => void;
  exporting: boolean;
  filters: OrderChangesFilterProps;
  /** Filtr statusu „Do zrobienia / Zrobione / Wszystkie" (domyślnie pierwszy). */
  status?: StatusFilter;
  onStatusChange?: (next: StatusFilter) => void;
  /** Liczniki pozycji podzakładki po filtrach — `null` = dane jeszcze nie przyszły. */
  statusCounts?: StatusCounts | null;
}

function filterChips(
  subTab: OrderChangesSubTab,
  filters: OrderChangesFilterProps,
): FilterBarChip[] {
  const chips: FilterBarChip[] = [];
  if (filters.search.trim()) {
    chips.push({
      id: "q",
      label: `Szukaj: ${filters.search.trim()}`,
      onRemove: () => filters.onSearchChange(""),
    });
  }
  if (filters.clientLabel) {
    chips.push({
      id: "client",
      label: `Klient: ${filters.clientLabel}`,
      onRemove: filters.onClearClient,
    });
  }
  if (filters.dateFrom || filters.dateTo) {
    const range = [
      filters.dateFrom ? `od ${formatDay(filters.dateFrom)}` : null,
      filters.dateTo ? `do ${formatDay(filters.dateTo)}` : null,
    ]
      .filter(Boolean)
      .join(" ");
    chips.push({
      id: "date",
      label: `${DATE_FILTER_LABELS[subTab]}: ${range}`,
      onRemove: filters.onClearDates,
    });
  }
  return chips;
}

/**
 * Kontener widoku: podzakładki z licznikami, wybór miesiąca i eksport.
 * Treść listy (`body`) podaje rodzic — pozwala to pokazać stany ładowania
 * i awarii w miejscu listy, a liczniki dopiero po udanym odczycie (licznik
 * „0" przed odpowiedzią twierdziłby, że nic nie ma).
 */
export function OrderChangesPanel({
  data,
  body,
  subTab,
  onSubTabChange,
  month,
  months,
  onMonthChange,
  onExport,
  exporting,
  filters,
  status = "todo",
  onStatusChange,
  statusCounts = null,
}: OrderChangesPanelProps) {
  const counts = data?.counts;
  const tabs = ORDER_CHANGES_SUB_TABS.map((value) => ({
    value,
    label: SUB_TAB_LABELS[value],
    count: counts?.[value],
  }));
  const chips = filterChips(subTab, filters);

  return (
    <section className="space-y-4 rounded-xl border border-border bg-card p-4 shadow-xs sm:p-5">
      {/* Poniżej `2xl` podzakładki idą w osobnym wierszu nad postępem, miesiącem
          i eksportem — w jednym wierszu „Braki" chowały się za przewijaniem
          (~1000 px), a od paska „Zrobione we wrześniu" także przy 1512 px
          („Bra", audyt 24.09.2026). Zakładki się zawijają, nigdy nie ucinają. */}
      <div
        className="flex flex-col gap-3 2xl:flex-row 2xl:items-center 2xl:justify-between"
        data-help="finance.order_changes"
      >
        <TabbedNav
          tabs={tabs}
          value={subTab}
          onValueChange={(next) => onSubTabChange(next as OrderChangesSubTab)}
          ariaLabel="Rodzaj zmian w zamówieniach"
          overflow="wrap"
          className="min-w-0 2xl:w-auto 2xl:flex-1"
          listClassName="w-auto"
        />
        <div className="flex flex-wrap items-center gap-3">
          {data && statusCounts ? (
            <DoneProgress
              month={data.period.month}
              done={statusCounts.done}
              total={statusCounts.all}
            />
          ) : null}
          <select
            aria-label="Miesiąc rozliczeniowy"
            value={month}
            onChange={(event) => onMonthChange(event.target.value)}
            className="h-9 rounded-md border border-border bg-background px-3 text-sm text-foreground"
          >
            {months.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={onExport}
            disabled={exporting || !data}
            aria-label={`Eksport do Excela: ${SUB_TAB_LABELS[subTab]}`}
            data-help="finance.export"
            className="inline-flex h-9 items-center gap-1.5 rounded-md border border-border px-3 text-sm font-medium text-foreground transition-colors hover:bg-muted disabled:opacity-50"
          >
            {exporting ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <Download className="h-4 w-4" aria-hidden />
            )}
            Eksport zakładki do Excela
          </button>
        </div>
      </div>
      {onStatusChange ? (
        <StatusSwitch
          value={status}
          counts={statusCounts}
          onChange={onStatusChange}
        />
      ) : null}
      {/* Filtry zawężają WSZYSTKIE cztery zakładki i ich liczniki, a eksport
          bierze dokładnie to, co widać — liczy je serwer, jedną funkcją. */}
      <FilterBar
        ariaLabel="Filtry audytu zamówień"
        search={{
          value: filters.search,
          onChange: filters.onSearchChange,
          onClear: () => filters.onSearchChange(""),
          placeholder:
            "Szukaj po konsultancie, kliencie lub numerze zamówienia…",
          ariaLabel: "Szukaj w audycie zamówień",
        }}
        filters={
          <>
            {filters.clientPicker}
            <div
              className="flex w-full items-center gap-1.5 sm:w-auto"
              role="group"
              aria-label={`${DATE_FILTER_LABELS[subTab]} (zakres)`}
            >
              <Input
                type="date"
                aria-label={`${DATE_FILTER_LABELS[subTab]} od`}
                value={filters.dateFrom}
                onChange={(event) =>
                  filters.onDateFromChange(event.target.value)
                }
                className="h-9 min-w-0 flex-1 sm:w-[150px] sm:flex-none"
              />
              <span className="text-sm text-muted-foreground" aria-hidden>
                –
              </span>
              <Input
                type="date"
                aria-label={`${DATE_FILTER_LABELS[subTab]} do`}
                value={filters.dateTo}
                onChange={(event) => filters.onDateToChange(event.target.value)}
                className="h-9 min-w-0 flex-1 sm:w-[150px] sm:flex-none"
              />
            </div>
          </>
        }
        chips={chips}
        onClearAll={chips.length > 0 ? filters.onClearAll : undefined}
      />
      {body}
    </section>
  );
}

/** Pasek „Zrobione we wrześniu: X / Y" — pozycje podzakładki po filtrach. */
function DoneProgress({
  month,
  done,
  total,
}: {
  month: number;
  done: number;
  total: number;
}) {
  const label = doneInMonthLabel(month);
  const percent = total > 0 ? Math.round((done / total) * 100) : 0;
  return (
    <div className="min-w-[180px]" aria-label={`${label}: ${done} z ${total}`}>
      <div className="flex items-baseline justify-between gap-3 text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-semibold tabular-nums text-foreground">
          {done} / {total}
        </span>
      </div>
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={done}
        aria-label={label}
        className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-muted"
      >
        <div
          className="h-full rounded-full bg-primary transition-all"
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}

const STATUS_ORDER: StatusFilter[] = ["todo", "done", "all"];

function StatusSwitch({
  value,
  counts,
  onChange,
}: {
  value: StatusFilter;
  counts: StatusCounts | null;
  onChange: (next: StatusFilter) => void;
}) {
  return (
    <div
      role="radiogroup"
      aria-label="Status pozycji"
      className="inline-flex flex-wrap items-center gap-1 rounded-lg border border-border bg-muted/40 p-1"
    >
      {STATUS_ORDER.map((option) => {
        const active = option === value;
        const count = counts ? counts[option] : null;
        return (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(option)}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              active
                ? "bg-primary text-primary-foreground shadow-xs"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {STATUS_FILTER_LABELS[option]}
            {count !== null ? ` · ${count}` : ""}
          </button>
        );
      })}
    </div>
  );
}

function GapsBanner({
  count,
  onOpenGaps,
}: {
  count: number;
  onOpenGaps: () => void;
}) {
  if (count <= 0) return null;
  return (
    <div
      role="status"
      className="flex items-start gap-2 rounded-lg border border-warning/25 bg-warning-muted px-3 py-2.5 text-sm text-warning-muted-foreground"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <span>
        {peopleLabel(count)} zakończone zamówienie bez nowego wpisu —{" "}
        <button
          type="button"
          onClick={onOpenGaps}
          className="font-medium underline underline-offset-2"
        >
          sprawdź podzakładkę Braki
        </button>
        .
      </span>
    </div>
  );
}

/** Stan układu kart, który trzyma rodzic (zapytania, zapisy, adres). */
export type OrderChangesBoardState = Omit<
  OrderChangesBoardProps,
  "data" | "tab" | "banner" | "emptyText"
>;

function emptyText(
  data: OrderChangesResponse,
  subTab: OrderChangesSubTab,
): ReactNode {
  switch (subTab) {
    case "entries":
      return `Nikt nie rozpoczął z nami współpracy w miesiącu ${data.period.label}. Przedłużenia, zmiany klienta i dodatkowe projekty są w zakładce Zmiany.`;
    case "exits":
      return `Nikt nie zakończył współpracy w miesiącu ${data.period.label}. Zamówienia, które kończą się bez kolejnego, są w zakładce Zamówienia bez kontynuacji.`;
    case "ending":
      return `Żadne zamówienie nie kończy się w miesiącu ${data.period.label} bez kolejnego. Zamówienia, których brak jest już w zakładce Braki, stoją tylko tam.`;
    case "gaps":
      return `Brak zamówień zakończonych bez następnego zamówienia w miesiącu ${data.period.label}.`;
    case "changes":
      return (
        `Brak zmian stawek, dat końca i nowych zamówień osób już z nami współpracujących w miesiącu ${data.period.label}.` +
        (data.changes_tracked_since
          ? ""
          : " Dziennik zmian stawek i dat działa od wdrożenia tej zakładki — wcześniejsze zmiany nie zostały zapisane.")
      );
  }
}

/**
 * Treść wybranej podzakładki dla gotowych danych: klienci → karty zamówień.
 * Komunikaty pustki mówią, GDZIE są wiersze, których tu nie ma.
 */
export function OrderChangesList({
  data,
  subTab,
  onOpenGaps,
  filtersActive = false,
  board,
}: {
  data: OrderChangesResponse;
  subTab: OrderChangesSubTab;
  onOpenGaps: () => void;
  /** Pustka po filtrach czyta się jak „nic w tym miesiącu nie było" — musi
   *  być odróżnialna od prawdziwego braku danych. */
  filtersActive?: boolean;
  board: OrderChangesBoardState;
}) {
  const monthOpenGaps = data.gaps.filter((gap) => gap.status === "open").length;
  const banner =
    subTab !== "gaps" ? (
      <GapsBanner count={monthOpenGaps} onOpenGaps={onOpenGaps} />
    ) : null;
  const trackedSince =
    subTab === "changes" && data.changes_tracked_since
      ? formatDay(data.changes_tracked_since.slice(0, 10))
      : null;

  return (
    <div className="space-y-3">
      <OrderChangesBoard
        {...board}
        data={data}
        tab={subTab}
        banner={banner}
        emptyText={
          filtersActive
            ? "Żaden wiersz nie pasuje do ustawionych filtrów."
            : emptyText(data, subTab)
        }
      />
      {trackedSince ? (
        <p className="text-xs text-muted-foreground">
          Zmiany stawek i dat końca są zapisywane od {trackedSince}.
        </p>
      ) : null}
    </div>
  );
}

export function subTabFromParam(value: string | null): OrderChangesSubTab {
  return (ORDER_CHANGES_SUB_TABS as readonly string[]).includes(value ?? "")
    ? (value as OrderChangesSubTab)
    : "changes";
}
