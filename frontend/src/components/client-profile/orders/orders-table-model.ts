// Model tabeli zamówień klienta (wersja B, 29.09.2026): z sekcji listy
// (zamówienia MD/kosztowe i kontraktorzy okresowi) składa płaskie wiersze
// tabeli i rozstrzyga, co jest zaznaczone. Czysta logika — bez Reacta.

import type { ContractWithOrdersRead } from "@/lib/api/dlPortal";
import type { OrderGroupRead, OrderLineRead, OrderType } from "@/lib/api/orderGroups";
import { sortOrderLinesByConsultant, sortOrderLinesByEnd } from "@/lib/client-order-list";
import { requiresDecision, sortEndedLines } from "@/lib/order-ended-line";

/** Zaznaczenie w tabeli = to, co pokazuje panel. */
export type OrderSelection =
  | { kind: "group"; groupId: number }
  | { kind: "line"; groupId: number; lineId: number }
  | { kind: "contractor"; contractId: number };

export function selectionKey(selection: OrderSelection): string {
  switch (selection.kind) {
    case "group":
      return `g:${selection.groupId}`;
    case "line":
      return `l:${selection.lineId}`;
    case "contractor":
      return `c:${selection.contractId}`;
  }
}

/** Osoby, które DZIŚ pracują na zamówieniu, plus szkice przypisań i
 *  zaplanowane zastępstwa (należą do bieżącej obsady, nie do „Zakończonych"). */
export function isCurrentLine(line: OrderLineRead): boolean {
  return line.is_active || line.status === "draft" || line.takeover_scheduled === true;
}

export interface GroupRoster {
  current: OrderLineRead[];
  ended: OrderLineRead[];
  pendingDecisions: number;
}

/** Ta sama kolejność co na dawnej karcie: obsada alfabetycznie, zakończeni
 *  datą zejścia malejąco z decyzjami na górze. */
export function groupRoster(group: OrderGroupRead): GroupRoster {
  const sorted = sortOrderLinesByConsultant(group.lines);
  const current = sorted.filter(isCurrentLine);
  const ended = sortEndedLines(sortOrderLinesByEnd(sorted.filter((line) => !isCurrentLine(line))));
  return { current, ended, pendingDecisions: ended.filter(requiresDecision).length };
}

/** Suma MD obsady zamówienia rozliczanego per osoba (wiersz zamówienia
 *  w tabeli). `null`, gdy żadna bieżąca linia nie ma budżetu MD. */
export function perPersonMdTotals(
  lines: readonly OrderLineRead[],
): { remaining: number; total: number } | null {
  let remaining = 0;
  let total = 0;
  let any = false;
  for (const line of lines) {
    if (line.md_total == null) continue;
    any = true;
    total += line.md_total;
    remaining += line.md_remaining ?? 0;
  }
  return any ? { remaining, total } : null;
}

export type OrdersTableRow =
  | { kind: "group"; key: string; group: OrderGroupRead; roster: GroupRoster }
  | { kind: "line"; key: string; group: OrderGroupRead; line: OrderLineRead; ended: false }
  | { kind: "ended-toggle"; key: string; group: OrderGroupRead; count: number; pendingDecisions: number; open: boolean }
  | { kind: "line"; key: string; group: OrderGroupRead; line: OrderLineRead; ended: true }
  | { kind: "future"; key: string; group: OrderGroupRead; parent: OrderGroupRead }
  | { kind: "contractor"; key: string; contractor: ContractWithOrdersRead };

export type OrdersSectionItem =
  | { kind: "group"; group: OrderGroupRead }
  | { kind: "contractor"; contractor: ContractWithOrdersRead };

export interface OrdersTableSection {
  type: OrderType;
  rows: OrdersTableRow[];
  /** Liczba pozycji listy (zamówień i kontraktorów), jak w dawnym nagłówku sekcji. */
  itemCount: number;
}

function flattenFutures(group: OrderGroupRead): OrderGroupRead[] {
  return group.future_orders.flatMap((future) => [future, ...flattenFutures(future)]);
}

/**
 * Wiersze jednej sekcji. Sekcja „Zakończone" zamówienia jest rozwinięta,
 * gdy czeka w niej decyzja, gdy szukane nazwisko jest wśród zakończonych,
 * albo gdy użytkownik ją rozwinął (`expandedEnded`).
 */
export function buildSectionRows(
  items: readonly OrdersSectionItem[],
  options: {
    expandedEnded: ReadonlySet<number>;
    collapsedEnded: ReadonlySet<number>;
    matchesSearch?: (name: string) => boolean;
  },
): OrdersTableRow[] {
  const rows: OrdersTableRow[] = [];
  for (const item of items) {
    if (item.kind === "contractor") {
      rows.push({ kind: "contractor", key: `c:${item.contractor.contract_id}`, contractor: item.contractor });
      continue;
    }
    const { group } = item;
    const roster = groupRoster(group);
    rows.push({ kind: "group", key: `g:${group.id}`, group, roster });
    for (const line of roster.current) {
      rows.push({ kind: "line", key: `l:${line.id}`, group, line, ended: false });
    }
    if (roster.ended.length > 0) {
      const searchHit =
        options.matchesSearch != null &&
        roster.ended.some((line) => options.matchesSearch?.(line.consultant_name) ?? false);
      const open =
        !options.collapsedEnded.has(group.id) &&
        (options.expandedEnded.has(group.id) || roster.pendingDecisions > 0 || searchHit);
      rows.push({
        kind: "ended-toggle",
        key: `e:${group.id}`,
        group,
        count: roster.ended.length,
        pendingDecisions: roster.pendingDecisions,
        open,
      });
      if (open) {
        for (const line of roster.ended) {
          rows.push({ kind: "line", key: `l:${line.id}`, group, line, ended: true });
        }
      }
    }
    for (const future of flattenFutures(group)) {
      rows.push({ kind: "future", key: `g:${future.id}`, group: future, parent: group });
    }
  }
  return rows;
}

/** Klucze wierszy, które można zaznaczyć (↑/↓), w kolejności tabeli. */
export function selectableKeys(sections: readonly OrdersTableSection[]): string[] {
  return sections.flatMap((section) =>
    section.rows.filter((row) => row.kind !== "ended-toggle").map((row) => row.key),
  );
}

export function selectionFromKey(
  key: string,
  sections: readonly OrdersTableSection[],
): OrderSelection | null {
  for (const section of sections) {
    for (const row of section.rows) {
      if (row.key !== key) continue;
      if (row.kind === "group" || row.kind === "future") return { kind: "group", groupId: row.group.id };
      if (row.kind === "line") return { kind: "line", groupId: row.group.id, lineId: row.line.id };
      if (row.kind === "contractor") return { kind: "contractor", contractId: row.contractor.contract_id };
    }
  }
  return null;
}

/** Zamówienie po id — także zagnieżdżone przedłużenie. */
export function findGroup(groups: readonly OrderGroupRead[], groupId: number): OrderGroupRead | null {
  for (const group of groups) {
    if (group.id === groupId) return group;
    const nested = findGroup(group.future_orders, groupId);
    if (nested) return nested;
  }
  return null;
}

/** Linia zamówienia po id razem z jej zamówieniem (także przedłużeniem). */
export function findLine(
  groups: readonly OrderGroupRead[],
  lineId: number,
): { group: OrderGroupRead; line: OrderLineRead } | null {
  for (const group of groups) {
    const line = group.lines.find((item) => item.id === lineId);
    if (line) return { group, line };
    const nested = findLine(group.future_orders, lineId);
    if (nested) return nested;
  }
  return null;
}

/** Zamówienie najwyższego poziomu, pod którym stoi `groupId` (albo ono samo). */
export function topLevelGroupOf(groups: readonly OrderGroupRead[], groupId: number): OrderGroupRead | null {
  for (const group of groups) {
    if (group.id === groupId || findGroup(group.future_orders, groupId)) return group;
  }
  return null;
}
