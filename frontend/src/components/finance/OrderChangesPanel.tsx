"use client";

import type { ReactNode } from "react";
import { AlertTriangle, Download, Loader2 } from "lucide-react";

import { FilterBar, type FilterBarChip } from "@/components/ds/FilterBar";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import type { OrderChangesResponse } from "@/lib/api/finance";
import {
  changeMeta,
  changeTitle,
  changeValue,
  entryDetails,
  entryTags,
  exitDetails,
  exitTone,
  formatDay,
  gapDetails,
  gapStatusLabel,
  initials,
  orderTypeLabel,
  peopleLabel,
  type MonthOption,
  type Tone,
} from "@/lib/finance-order-changes";

export type OrderChangesSubTab =
  | "changes"
  | "entries"
  | "exits"
  | "ending"
  | "gaps";

export const ORDER_CHANGES_SUB_TABS: readonly OrderChangesSubTab[] = [
  "changes",
  "entries",
  "exits",
  "ending",
  "gaps",
];

const TONE_VARIANT: Record<Tone, "neutral" | "success" | "warning" | "danger"> = {
  neutral: "neutral",
  success: "success",
  warning: "warning",
  danger: "danger",
};

export const SUB_TAB_LABELS: Record<OrderChangesSubTab, string> = {
  changes: "Zmiany",
  entries: "Wejścia",
  exits: "Zejścia",
  ending: "Kończące się zamówienia",
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
      {/* Poniżej `xl` podzakładki idą w osobnym wierszu nad miesiącem i eksportem —
          w jednym wierszu na laptopie (~1000 px) „Braki" chowały się za
          przewijaniem, czyli akurat podzakładka, o którą chodzi. */}
      <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <TabbedNav
          tabs={tabs}
          value={subTab}
          onValueChange={(next) => onSubTabChange(next as OrderChangesSubTab)}
          ariaLabel="Rodzaj zmian w zamówieniach"
          overflow="scroll"
          className="min-w-0 xl:w-auto xl:flex-1"
          listClassName="w-auto"
        />
        <div className="flex flex-wrap items-center gap-2">
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
      {/* Filtry zawężają WSZYSTKIE cztery zakładki i ich liczniki, a eksport
          bierze dokładnie to, co widać — liczy je serwer, jedną funkcją. */}
      <FilterBar
        ariaLabel="Filtry audytu zamówień"
        search={{
          value: filters.search,
          onChange: filters.onSearchChange,
          onClear: () => filters.onSearchChange(""),
          placeholder: "Szukaj po konsultancie, kliencie lub numerze zamówienia…",
          ariaLabel: "Szukaj w audycie zamówień",
        }}
        filters={
          <>
            {filters.clientPicker}
            <div
              className="flex items-center gap-1.5"
              role="group"
              aria-label={`${DATE_FILTER_LABELS[subTab]} (zakres)`}
            >
              <Input
                type="date"
                aria-label={`${DATE_FILTER_LABELS[subTab]} od`}
                value={filters.dateFrom}
                onChange={(event) => filters.onDateFromChange(event.target.value)}
                className="h-9 w-[150px]"
              />
              <span className="text-sm text-muted-foreground" aria-hidden>
                –
              </span>
              <Input
                type="date"
                aria-label={`${DATE_FILTER_LABELS[subTab]} do`}
                value={filters.dateTo}
                onChange={(event) => filters.onDateToChange(event.target.value)}
                className="h-9 w-[150px]"
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

function Row({
  name,
  details,
  aside,
  footer,
}: {
  name: string;
  details: ReactNode;
  aside?: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <li className="flex items-start gap-3 rounded-lg border border-border bg-muted/30 px-3 py-2.5">
      <span
        aria-hidden
        className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary"
      >
        {initials(name)}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold text-foreground">{name}</p>
        <div className="text-xs text-muted-foreground">{details}</div>
        {footer ? <div className="mt-1 text-xs">{footer}</div> : null}
      </div>
      {aside ? <div className="flex shrink-0 flex-wrap justify-end gap-1">{aside}</div> : null}
    </li>
  );
}

function EmptyList({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
      {children}
    </p>
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

/** Treść wybranej podzakładki dla gotowych danych. */
export function OrderChangesList({
  data,
  subTab,
  onOpenGaps,
  filtersActive = false,
}: {
  data: OrderChangesResponse;
  subTab: OrderChangesSubTab;
  onOpenGaps: () => void;
  /** Pustka po filtrach czyta się jak „nic w tym miesiącu nie było" — musi
   *  być odróżnialna od prawdziwego braku danych. */
  filtersActive?: boolean;
}) {
  const monthOpenGaps = data.gaps.filter((gap) => gap.status === "open").length;
  const banner =
    subTab !== "gaps" ? (
      <GapsBanner count={monthOpenGaps} onOpenGaps={onOpenGaps} />
    ) : null;
  const filteredOut = filtersActive ? (
    <EmptyList>Żaden wiersz nie pasuje do ustawionych filtrów.</EmptyList>
  ) : null;

  if (subTab === "entries") {
    return (
      <div className="space-y-3">
        {data.entries.length === 0 ? (
          filteredOut ?? (
            <EmptyList>
              Nikt nie rozpoczął z nami współpracy w miesiącu {data.period.label}.
              Przedłużenia, zmiany klienta i dodatkowe projekty są w zakładce
              Zmiany.
            </EmptyList>
          )
        ) : (
          <ul className="space-y-2">
            {data.entries.map((item) => (
              <Row
                key={`e-${item.order_id}`}
                name={item.consultant_name}
                details={entryDetails(item)}
                footer={
                  <span className="flex flex-wrap gap-1">
                    {entryTags(item).map((tag) => (
                      <Badge
                        key={tag}
                        size="sm"
                        variant={tag === "Nowy konsultant" ? "info" : "outline"}
                      >
                        {tag}
                      </Badge>
                    ))}
                  </span>
                }
                aside={<Badge variant="soft">{orderTypeLabel(item.order_type)}</Badge>}
              />
            ))}
          </ul>
        )}
        {banner}
      </div>
    );
  }

  if (subTab === "exits" || subTab === "ending") {
    const items = subTab === "exits" ? data.exits : data.ending_orders;
    return (
      <div className="space-y-3">
        {items.length === 0 ? (
          filteredOut ??
          (subTab === "exits" ? (
            <EmptyList>
              Nikt nie zakończył współpracy w miesiącu {data.period.label}.
              Zamówienia, które kończą się bez kolejnego, są w zakładce
              Kończące się zamówienia.
            </EmptyList>
          ) : (
            <EmptyList>
              Żadne zamówienie nie kończy się w miesiącu {data.period.label} bez
              kolejnego.
            </EmptyList>
          ))
        ) : (
          <ul className="space-y-2">
            {items.map((item) => (
              <Row
                key={`x-${item.order_id}`}
                name={item.consultant_name}
                details={exitDetails(item)}
                footer={
                  <Badge variant={TONE_VARIANT[exitTone(item)]} size="md">
                    {item.verdict_label}
                  </Badge>
                }
                aside={<Badge variant="soft">{orderTypeLabel(item.order_type)}</Badge>}
              />
            ))}
          </ul>
        )}
        {banner}
      </div>
    );
  }

  if (subTab === "gaps") {
    return data.gaps.length === 0 ? (
      filteredOut ?? (
        <EmptyList>
          Brak zamówień zakończonych bez następnego zamówienia w miesiącu{" "}
          {data.period.label}.
        </EmptyList>
      )
    ) : (
      <ul className="space-y-2">
        {data.gaps.map((item) => (
          <Row
            key={`g-${item.gap_id}`}
            name={item.consultant_name}
            details={gapDetails(item)}
            footer={
              <Badge variant={item.status === "open" ? "danger" : "warning"} size="md">
                {gapStatusLabel(item)}
              </Badge>
            }
          />
        ))}
      </ul>
    );
  }

  const trackedSince = data.changes_tracked_since
    ? formatDay(data.changes_tracked_since.slice(0, 10))
    : null;
  return (
    <div className="space-y-3">
      {data.changes.length === 0 ? (
        filteredOut ?? (
          <EmptyList>
            Brak zmian stawek, dat końca i nowych zamówień osób już z nami
            współpracujących w miesiącu {data.period.label}.
            {!trackedSince
              ? " Dziennik zmian stawek i dat działa od wdrożenia tej zakładki — wcześniejsze zmiany nie zostały zapisane."
              : ""}
          </EmptyList>
        )
      ) : (
        <ul className="space-y-2">
          {data.changes.map((item, index) => (
            <Row
              key={`c-${item.kind}-${item.order_id ?? item.order_group_id}-${item.occurred_at ?? index}`}
              name={item.consultant_name}
              details={
                <>
                  <span className="font-medium text-foreground">{changeTitle(item)}:</span>{" "}
                  {changeValue(item)}
                </>
              }
              footer={<span className="text-muted-foreground">{changeMeta(item)}</span>}
            />
          ))}
        </ul>
      )}
      {trackedSince ? (
        <p className="text-xs text-muted-foreground">
          Zmiany stawek i dat końca są zapisywane od {trackedSince}.
        </p>
      ) : null}
      {banner}
    </div>
  );
}

export function subTabFromParam(value: string | null): OrderChangesSubTab {
  return (ORDER_CHANGES_SUB_TABS as readonly string[]).includes(value ?? "")
    ? (value as OrderChangesSubTab)
    : "changes";
}
