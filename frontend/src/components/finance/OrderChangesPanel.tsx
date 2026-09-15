"use client";

import type { ReactNode } from "react";
import { AlertTriangle, Download, Loader2 } from "lucide-react";

import { TabbedNav } from "@/components/ds/TabbedNav";
import { Badge } from "@/components/ui/badge";
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

export type OrderChangesSubTab = "changes" | "entries" | "exits" | "gaps";

export const ORDER_CHANGES_SUB_TABS: readonly OrderChangesSubTab[] = [
  "changes",
  "entries",
  "exits",
  "gaps",
];

const TONE_VARIANT: Record<Tone, "neutral" | "success" | "warning" | "danger"> = {
  neutral: "neutral",
  success: "success",
  warning: "warning",
  danger: "danger",
};

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
}: OrderChangesPanelProps) {
  const counts = data?.counts;
  const tabs = [
    { value: "changes", label: "Zmiany", count: counts?.changes },
    { value: "entries", label: "Wejścia", count: counts?.entries },
    { value: "exits", label: "Zejścia", count: counts?.exits },
    { value: "gaps", label: "Braki", count: counts?.gaps },
  ];

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
            className="inline-flex h-9 items-center gap-1.5 rounded-md border border-border px-3 text-sm font-medium text-foreground transition-colors hover:bg-muted disabled:opacity-50"
          >
            {exporting ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <Download className="h-4 w-4" aria-hidden />
            )}
            Eksport do Excela
          </button>
        </div>
      </div>
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
}: {
  data: OrderChangesResponse;
  subTab: OrderChangesSubTab;
  onOpenGaps: () => void;
}) {
  const monthOpenGaps = data.gaps.filter((gap) => gap.status === "open").length;
  const banner =
    subTab !== "gaps" ? (
      <GapsBanner count={monthOpenGaps} onOpenGaps={onOpenGaps} />
    ) : null;

  if (subTab === "entries") {
    return (
      <div className="space-y-3">
        {data.entries.length === 0 ? (
          <EmptyList>Brak zamówień rozpoczynających się w miesiącu {data.period.label}.</EmptyList>
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
                        variant={
                          tag === "Nowy konsultant"
                            ? "info"
                            : tag === "Dodatkowy projekt"
                              ? "warning"
                              : "outline"
                        }
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

  if (subTab === "exits") {
    return (
      <div className="space-y-3">
        {data.exits.length === 0 ? (
          <EmptyList>Brak zamówień kończących się w miesiącu {data.period.label}.</EmptyList>
        ) : (
          <ul className="space-y-2">
            {data.exits.map((item) => (
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
      <EmptyList>
        Brak zamówień zakończonych bez następnego zamówienia w miesiącu{" "}
        {data.period.label}.
      </EmptyList>
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
        <EmptyList>
          Brak zmian stawek, dat końca i dodatkowych projektów w miesiącu{" "}
          {data.period.label}.
          {!trackedSince
            ? " Dziennik zmian stawek i dat działa od wdrożenia tej zakładki — wcześniejsze zmiany nie zostały zapisane."
            : ""}
        </EmptyList>
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
