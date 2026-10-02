"use client";

import { ChevronDown, CornerDownRight } from "lucide-react";

import { ContractPersonLink } from "@/components/contracts/ContractPersonLink";
import { cn } from "@/lib/utils";
import type { OrderGroupRead, OrderLineRead } from "@/lib/api/orderGroups";
import { consultantMatchesQuery, effectiveGroupOrderType, usesSharedMdPool } from "@/lib/client-order-list";
import {
  decisionLabel,
  ENDED_STATUS_LABEL,
  endedPeriod,
  endedStatus,
  endedUsage,
  hasPendingPoolDecision,
  requiresDecision,
} from "@/lib/order-ended-line";
import { hasScopedMd } from "@/lib/order-line-usage";
import { formatDate, formatPLN } from "@/types/client-profile";
import { rowActivationProps } from "@/hooks/useRowNavigation";
import { warsawDateOf } from "@/lib/warsaw-date";

import { ConsumptionButton } from "./ConsumptionButton";
import { formatPeriodMonthPl } from "./LineConsumptionTable";
import { formatMd, MdBudgetBar } from "./MdBudgetBar";
import { MdScopeBars } from "./MdScopeBars";
import { OrderTypeBadge, orderTypeLabel } from "./OrderTypeBadge";
import { contractorRowSummary } from "./contractor-order-row";
import { displayLineRate, orderLineAnchorId } from "./order-line-display";
import { executiveContractLabel, orderGroupAnchorId, periodLabel, STATUS_BADGE } from "./order-group-parts";
import {
  buildSectionTiles,
  type OrdersTableRow,
  type OrdersTableSection,
} from "./orders-table-model";

/** Zakładka panelu linii otwierana wprost z tabeli (np. przycisk „Zużycie"). */
export type LinePanelTab = "zuzycie" | "szczegoly" | "historia";

export interface OrdersTableProps {
  sections: OrdersTableSection[];
  selectedKey: string | null;
  onSelect: (key: string, tab?: LinePanelTab) => void;
  onToggleEnded: (groupId: number, open: boolean) => void;
  searchQuery: string;
  canDecide: boolean;
  canManage: boolean;
  /** Kwoty kontraktorów okresowych — ta sama bramka co panel (`canViewClientFinance`). */
  canViewFinance: boolean;
}

const TONE_CLASS = {
  ok: "bg-success-muted text-success-muted-foreground",
  warn: "bg-warning-muted text-warning-muted-foreground",
  bad: "bg-destructive/10 text-destructive",
  mut: "bg-muted text-muted-foreground",
} as const;

function Chip({ tone, children }: { tone: keyof typeof TONE_CLASS; children: React.ReactNode }) {
  return (
    <span className={cn("inline-flex items-center whitespace-nowrap rounded px-1.5 py-0.5 text-[11px] font-medium", TONE_CLASS[tone])}>
      {children}
    </span>
  );
}

function rowClass(selected: boolean, extra?: string) {
  return cn(
    "cursor-pointer border-b border-border outline-none transition-colors",
    "hover:bg-accent/60 focus-visible:bg-accent/60 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
    selected && "bg-primary/5 hover:bg-primary/10 [&>td:first-child]:shadow-[inset_3px_0_0_hsl(var(--primary))]",
    extra,
  );
}

const CELL = "px-2 py-1.5 align-middle";
const FIRST_CELL = cn(CELL, "sticky left-0 z-[1] bg-card");

function LineBudgetCell({ group, line, ended }: { group: OrderGroupRead; line: OrderLineRead; ended: boolean }) {
  if (group.is_cost_based) {
    return (
      <span className="text-xs text-muted-foreground">
        zafakturowano{" "}
        <span className="font-medium text-foreground">
          {line.invoiced_total == null || line.invoiced_total === 0 ? "—" : formatPLN(line.invoiced_total)}
        </span>
      </span>
    );
  }
  if (usesSharedMdPool(group)) return <span className="text-xs text-muted-foreground">wspólna pula</span>;
  // MD przeniesione na następcę nie są już „pozostało" u osoby odchodzącej.
  const transferredOut =
    ended &&
    line.replaced_by_md != null &&
    (line.replaced_by_kind === "swap" || line.replaced_by_kind === "takeover") &&
    !line.replaced_by_scheduled;
  const barLine = transferredOut ? { ...line, md_remaining: 0 } : line;
  if (hasScopedMd(line, group)) return <MdScopeBars line={barLine} />;
  return <MdBudgetBar remaining={barLine.md_remaining} total={line.md_total} />;
}

function lineBadge(group: OrderGroupRead, line: OrderLineRead): { label: string; tone: keyof typeof TONE_CLASS } | null {
  if (line.returned_from_contract_id != null) return { label: "Powrót po przerwie", tone: "warn" };
  if (line.takeover_scheduled === true) return { label: `Zastępstwo od ${formatDate(line.start_date)}`, tone: "mut" };
  if (line.status === "draft" && group.status !== "draft") return { label: "Draft — uzupełnij", tone: "mut" };
  if (line.assignment_kind === "takeover") return { label: "Zastępstwo", tone: "mut" };
  if (line.assignment_kind === "join") return { label: "Dołączona", tone: "mut" };
  return null;
}

function lineNotes(line: OrderLineRead): Array<{ label: string; tone: keyof typeof TONE_CLASS }> {
  const notes: Array<{ label: string; tone: keyof typeof TONE_CLASS }> = [];
  if (line.missing_consumption_month) {
    notes.push({ label: `Brak zejścia za ${formatPeriodMonthPl(line.missing_consumption_month)}`, tone: "warn" });
  }
  if (line.unsettled_total != null && line.unsettled_total > 0) {
    notes.push({ label: `Nierozliczone ${formatPLN(line.unsettled_total)}`, tone: "bad" });
  }
  if (line.replaced_by_order_id != null) {
    notes.push({
      label: line.replaced_by_scheduled
        ? `Zastępstwo od ${formatDate(line.replaced_by_start_date ?? null)}`
        : `Zastąpiony${line.replaced_by_consultant_name ? `: ${line.replaced_by_consultant_name}` : ""}`,
      tone: "mut",
    });
  }
  return notes;
}

/** Kolumna „Zostało MD” / „Budżet” u osoby, która już nie pracuje na zamówieniu. */
function endedBudgetText(group: OrderGroupRead, line: OrderLineRead): string | null {
  if (group.is_cost_based) {
    return line.invoiced_total == null ? null : `zafakturowano ${formatPLN(line.invoiced_total)}`;
  }
  return line.md_remaining == null ? null : `zostało ${formatMd(line.md_remaining)} MD`;
}

export function OrdersTable({
  sections,
  selectedKey,
  onSelect,
  onToggleEnded,
  searchQuery,
  canDecide,
  canManage,
  canViewFinance,
}: OrdersTableProps) {
  const query = searchQuery.trim();
  const hit = (name: string) => query !== "" && consultantMatchesQuery(name, query);

  return (
    <div className="flex flex-col gap-4" data-orders-table data-help="client.orders.table">
      {sections.map((section) => {
        const periodic = section.type === "periodic";
        const renderRow = (row: OrdersTableRow) => (
          <OrdersTableRowView
            key={row.key}
            row={row}
            selected={row.key === selectedKey}
            onSelect={onSelect}
            onToggleEnded={onToggleEnded}
            searchHit={hit}
            canDecide={canDecide}
            canManage={canManage}
            canViewFinance={canViewFinance}
            periodicColumns={periodic}
          />
        );
        return (
          <section key={section.type} aria-labelledby={`orders-${section.type}-heading`} className="min-w-0">
            <h3
              id={`orders-${section.type}-heading`}
              className="mb-1.5 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground"
            >
              {orderTypeLabel(section.type)} ({section.itemCount})
            </h3>
            {periodic ? (
              <div className="relative overflow-x-auto rounded-lg border border-border bg-card">
                <table className="w-full min-w-[760px] border-collapse text-sm tabular-nums">
                  <thead>
                    <tr className="border-b border-border bg-muted/50 text-left text-xs font-medium text-muted-foreground">
                      <th className="sticky left-0 z-[1] bg-muted px-2 py-1.5 font-medium">Konsultant</th>
                      <th className="px-2 py-1.5 font-medium">Nr zamówienia</th>
                      <th className="px-2 py-1.5 font-medium">Okres</th>
                      <th className="px-2 py-1.5 text-right font-medium">Koszt</th>
                      <th className="px-2 py-1.5 text-right font-medium">Przychód</th>
                      <th className="px-2 py-1.5 font-medium">Stan</th>
                    </tr>
                  </thead>
                  <tbody>{section.rows.map(renderRow)}</tbody>
                </table>
              </div>
            ) : (
              // Ticket 11: każde zamówienie MD / kosztowe to osobny kafelek.
              // Wspólny przewijany kontener i `table-fixed` z tym samym
              // <colgroup> trzymają kolumny w jednej linii we wszystkich kafelkach.
              <div className="relative overflow-x-auto">
                <div className="flex min-w-[940px] flex-col gap-3 pb-0.5">
                  {buildSectionTiles(section.rows).map((tile) => (
                    <div
                      key={tile.key}
                      data-order-tile={tile.header ? "group" : "contractor"}
                      className="overflow-clip rounded-lg border border-border bg-card shadow-sm"
                    >
                      <table className="w-full table-fixed border-collapse text-sm tabular-nums">
                        <colgroup>
                          <col className="w-[26%]" />
                          <col className="w-[7rem]" />
                          <col className="w-[7rem]" />
                          <col className="w-[11.5rem]" />
                          <col className="w-[10.5rem]" />
                          <col />
                        </colgroup>
                        <thead>
                          {tile.header ? renderRow(tile.header) : null}
                          <tr className="border-b border-border bg-card text-left text-[11px] font-medium text-muted-foreground">
                            <th scope="col" className="sticky left-0 z-[1] bg-card px-2 py-1 font-medium">
                              {tile.header ? "Konsultant" : "Kontraktor"}
                            </th>
                            <th scope="col" className="px-2 py-1 text-right font-medium">Koszt</th>
                            <th scope="col" className="px-2 py-1 text-right font-medium">Przychód</th>
                            <th scope="col" className="px-2 py-1 font-medium">
                              {section.type === "cost" ? "Budżet" : "Zostało MD"}
                            </th>
                            <th scope="col" className="px-2 py-1 font-medium">Zużycie</th>
                            <th scope="col" className="px-2 py-1 font-medium">Uwagi</th>
                          </tr>
                        </thead>
                        <tbody>{tile.rows.map(renderRow)}</tbody>
                      </table>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}

function OrdersTableRowView({
  row,
  selected,
  onSelect,
  onToggleEnded,
  searchHit,
  canDecide,
  canManage,
  canViewFinance,
  periodicColumns,
}: {
  row: OrdersTableRow;
  selected: boolean;
  onSelect: (key: string, tab?: LinePanelTab) => void;
  onToggleEnded: (groupId: number, open: boolean) => void;
  searchHit: (name: string) => boolean;
  canDecide: boolean;
  canManage: boolean;
  canViewFinance: boolean;
  /** Kolumny sekcji „Okresowe"; w sekcjach MD i kosztowej kontraktor z
   *  pojedynczym zamówieniem tego typu dostaje ich kolumny (bez przesunięcia). */
  periodicColumns: boolean;
}) {
  if (row.kind === "ended-toggle") {
    return (
      <tr className="border-b border-border bg-muted/20">
        <td colSpan={6} className="px-2 py-1">
          <button
            type="button"
            onClick={() => onToggleEnded(row.group.id, !row.open)}
            aria-expanded={row.open}
            className="inline-flex items-center gap-1 rounded pl-6 text-xs font-medium text-muted-foreground hover:text-foreground"
          >
            <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", !row.open && "-rotate-90")} aria-hidden="true" />
            Zakończone ({row.count})
            {row.pendingDecisions > 0 ? (
              <span className="font-semibold text-destructive">
                {` · ${row.pendingDecisions} ${row.pendingDecisions === 1 ? "wymaga decyzji" : "wymagają decyzji"}`}
              </span>
            ) : null}
          </button>
        </td>
      </tr>
    );
  }

  const activation = rowActivationProps(row.key, (key) => onSelect(key));

  if (row.kind === "contractor") {
    const summary = contractorRowSummary(row.contractor, undefined, { canViewFinance });
    const futureNote =
      summary.futureCount > 0 ? (
        <span className="block text-muted-foreground">
          +{summary.futureCount} {summary.futureCount === 1 ? "przyszłe zamówienie" : "przyszłe zamówienia"}
        </span>
      ) : null;
    const costCell = (
      <td className={cn(CELL, "whitespace-nowrap text-right text-xs")}>
        {summary.costLabel ?? "—"}
        {summary.costFromContract ? <span className="block text-muted-foreground">z kontraktu</span> : null}
      </td>
    );
    const revenueCell = (
      <td className={cn(CELL, "whitespace-nowrap text-right text-xs")}>{summary.revenueLabel ?? "—"}</td>
    );
    const stateChip = <Chip tone={summary.state.tone}>{summary.state.label}</Chip>;
    return (
      <tr
        {...activation}
        id={`contractor-row-${summary.contractId}`}
        aria-selected={selected}
        data-order-row="contractor"
        className={rowClass(selected, cn(summary.isEnded && "text-muted-foreground", searchHit(summary.name) && "bg-primary/5"))}
      >
        <td className={cn(FIRST_CELL, selected && "bg-primary/5")}>
          {/* Nazwisko prowadzi do kontraktu Z TEGO WIERSZA (jak na dawnej
              karcie) — klik w link nie otwiera panelu (`rowActivationProps`). */}
          <ContractPersonLink contractId={summary.contractId} name={summary.name} className="font-medium text-foreground" />
        </td>
        {periodicColumns ? (
          <>
            <td className={cn(CELL, "font-mono text-xs")}>{summary.orderNumber ?? "—"}</td>
            <td className={cn(CELL, "whitespace-nowrap text-xs")}>
              {summary.periodLabel ?? "—"}
              {futureNote}
            </td>
            {costCell}
            {revenueCell}
            <td className={CELL}>{stateChip}</td>
          </>
        ) : (
          <>
            {costCell}
            {revenueCell}
            {/* Kolumny „Zostało MD / Budżet" i „Zużycie" opisują zamówienia
                grupowe — tu numer i okres pojedynczego zamówienia. */}
            <td className={cn(CELL, "text-xs")}>
              {/* Karta szkicu nie ma ani numeru, ani okresu — pusta komórka,
                  nie dwie kreski udające dane; stan mówi „Brak zamówienia”. */}
              {summary.orderNumber ? <span className="font-mono">{summary.orderNumber}</span> : null}
              {summary.periodLabel ? (
                <span className="block whitespace-nowrap text-muted-foreground">{summary.periodLabel}</span>
              ) : null}
              {futureNote}
            </td>
            <td className={CELL} />
            <td className={CELL}>{stateChip}</td>
          </>
        )}
      </tr>
    );
  }

  if (row.kind === "group" || row.kind === "future") {
    const group = row.group;
    const isFuture = row.kind === "future";
    const current = isFuture ? group.lines : row.roster.current;
    const missing = current.filter((line) => line.missing_consumption_month).length;
    const pending = isFuture ? 0 : row.roster.pendingDecisions;
    const exhausted =
      group.status === "exhausted" ||
      (usesSharedMdPool(group) && group.md_budget_total != null && (group.md_budget_remaining ?? 0) <= 0);
    return (
      <tr
        {...activation}
        id={orderGroupAnchorId(group.id)}
        aria-selected={selected}
        data-order-row={isFuture ? "future" : "group"}
        className={rowClass(selected, cn(!isFuture && "[&>td]:py-2", !isFuture && !selected && "bg-muted", isFuture && "text-sm"))}
      >
        {/* Przedłużenie opisuje się jednym zdaniem — bez pustych komórek stawek. */}
        <td colSpan={isFuture ? 3 : undefined} className={cn(FIRST_CELL, isFuture && "pl-6", !isFuture && !selected && "bg-muted", selected && "bg-primary/5")}>
          {isFuture ? (
            <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
              <CornerDownRight className="h-3.5 w-3.5" aria-hidden="true" />
              Przyszłe zamówienie <span className="font-mono text-foreground">{group.order_number}</span>
              · od {formatDate(group.start_date)} · {group.lines.length} os.
            </span>
          ) : (
            <>
              <span className="flex flex-wrap items-center gap-1.5">
                <span className="select-text text-[15px] font-semibold text-foreground">Zamówienie nr {group.order_number}</span>
                <OrderTypeBadge type={effectiveGroupOrderType(group)} />
                {group.status !== "active" ? (
                  <span
                    className={cn(
                      "rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                      STATUS_BADGE[group.status] ?? "bg-muted text-muted-foreground",
                    )}
                  >
                    {group.status_label}
                  </span>
                ) : null}
              </span>
              <span className="block text-xs text-muted-foreground">
                {periodLabel(group)}
                {group.closure_date ? ` · zakończone ${formatDate(group.closure_date)}` : ""}
                {group.status === "cancelled" && group.cancelled_at
                  ? ` · anulowane ${formatDate(warsawDateOf(group.cancelled_at) ?? group.cancelled_at)}`
                  : ""}
                {` · ${row.roster.current.length} os.`}
              </span>
              {group.executive_contract ? (
                <span className="block text-xs text-muted-foreground">{executiveContractLabel(group.executive_contract)}</span>
              ) : null}
            </>
          )}
        </td>
        {/* Nagłówek nie powtarza zużycia: pasek i „X / Y MD” stoją w wierszach
            osób, a pula całego zamówienia w panelu po kliknięciu nagłówka. */}
        <td colSpan={isFuture ? 2 : 4} className={CELL} />
        <td className={cn(CELL, "space-x-1 [&>span]:whitespace-normal")}>
          {missing > 0 ? <Chip tone="warn">{missing} bez zejścia</Chip> : null}
          {pending > 0 ? <Chip tone="bad">{pending === 1 ? "1 decyzja" : `${pending} decyzje`}</Chip> : null}
          {exhausted ? <Chip tone="bad">Budżet wyczerpany</Chip> : null}
        </td>
      </tr>
    );
  }

  // Wiersz osoby — bieżąca obsada albo zakończona.
  const { group, line, ended } = row;
  const perPersonMd = !group.is_cost_based && !usesSharedMdPool(group);
  const badge = ended ? null : lineBadge(group, line);
  const notes = ended ? [] : lineNotes(line);
  const needsDecision = ended && requiresDecision(line);
  const decided = ended ? decisionLabel(line) : null;
  return (
    <tr
      {...activation}
      id={orderLineAnchorId(line.id)}
      aria-selected={selected}
      data-order-row={ended ? "ended-line" : "line"}
      className={rowClass(
        selected,
        cn(
          ended && !needsDecision && "text-muted-foreground",
          needsDecision && "bg-destructive/5",
          !ended && !line.is_active && line.takeover_scheduled !== true && "opacity-70",
          searchHit(line.consultant_name) && !selected && "bg-primary/5",
        ),
      )}
    >
      <td className={cn(FIRST_CELL, "pl-6", needsDecision && "bg-destructive/5", selected && "bg-primary/5")}>
        <span className="flex flex-wrap items-center gap-1.5">
          <ContractPersonLink
            contractId={line.contract_id}
            name={line.consultant_name}
            className={cn("font-medium", ended ? "text-muted-foreground" : "text-foreground")}
          />
          {ended ? <Chip tone="mut">{ENDED_STATUS_LABEL[endedStatus(line)]}</Chip> : null}
          {badge ? <Chip tone={badge.tone}>{badge.label}</Chip> : null}
        </span>
        {ended ? (
          <span className="block text-xs text-muted-foreground">{endedPeriod(line)}</span>
        ) : line.assignment_kind === "takeover" && line.takeover_from_name ? (
          <span className="block text-xs text-muted-foreground">
            {line.takeover_scheduled ? "przejmie po" : "przejęła po"}: {line.takeover_from_name}
          </span>
        ) : line.predecessor_consultant_name ? (
          <span className="block text-xs text-muted-foreground">zastąpił: {line.predecessor_consultant_name}</span>
        ) : null}
      </td>
      <td className={cn(CELL, "whitespace-nowrap text-right text-xs")}>{displayLineRate(line, "cost")}</td>
      <td className={cn(CELL, "whitespace-nowrap text-right text-xs")}>{displayLineRate(line, "revenue")}</td>
      <td className={cn(CELL, "min-w-[10rem]")}>
        {ended ? (
          // Makieta B: w „Zostało MD” pozostała pula (ta, o której decyduje DL),
          // w „Zużycie” to, co osoba wykorzystała. Samo „0 MD · 0,00 zł” w tej
          // kolumnie czytało się jak pusta pula przy 63 MD czekających na decyzję.
          endedBudgetText(group, line) ? (
            <span className="text-xs tabular-nums text-muted-foreground">{endedBudgetText(group, line)}</span>
          ) : null
        ) : (
          <LineBudgetCell group={group} line={line} ended={false} />
        )}
      </td>
      <td className={CELL}>
        {ended ? (
          // Kosztowe: „zafakturowano …” stoi już w kolumnie budżetu.
          !group.is_cost_based && endedUsage(group, line) ? (
            <span className="text-xs tabular-nums text-muted-foreground" title="Wykorzystane na tym zamówieniu">
              {endedUsage(group, line)}
            </span>
          ) : null
        ) : perPersonMd ? (
          <span data-row-stop>
            <ConsumptionButton line={line} onClick={() => onSelect(row.key, "zuzycie")} />
          </span>
        ) : null}
      </td>
      <td className={cn(CELL, "space-x-1 [&>span]:whitespace-normal")}>
        {needsDecision ? (
          canDecide && (canManage || !hasPendingPoolDecision(line)) ? (
            <Chip tone="bad">Podejmij decyzję</Chip>
          ) : (
            <Chip tone="bad">Oczekuje na decyzję Delivery Leada</Chip>
          )
        ) : decided ? (
          <span className="text-xs text-muted-foreground">{decided}</span>
        ) : null}
        {notes.map((note) => (
          <Chip key={note.label} tone={note.tone}>
            {note.label}
          </Chip>
        ))}
      </td>
    </tr>
  );
}
