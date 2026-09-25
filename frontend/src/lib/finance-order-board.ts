// Finanse → Zmiany w zamówieniach: układ „klienci → karty zamówień".
//
// Czyste funkcje (bez Reacta): pozycje każdej podzakładki sprowadzone do
// jednego kształtu, karty zamówień, kafelki klientów, liczniki statusu.
// Klucz pozycji i stan odhaczenia liczy SERWER — tu tylko układ i opis.

import type {
  InvoiceLine,
  OrderChangeItem,
  OrderChangesResponse,
  OrderChangesTab,
  OrderEntryItem,
  OrderExitItem,
  OrderGapItem,
  OrderItemCheck,
  OrderPdfRef,
  OrderSupersededCheck,
} from "@/lib/api/finance";
import {
  formatDay,
  formatMoment,
  formatRate,
  gapStatusLabel,
} from "@/lib/finance-order-changes";

export type StatusFilter = "todo" | "done" | "all";

export const STATUS_FILTER_LABELS: Record<StatusFilter, string> = {
  todo: "Do zrobienia",
  done: "Zrobione",
  all: "Wszystkie",
};

/** Etykiety typu zmiany na karcie (kolejność = kolejność wyświetlania). */
export type BoardLabel =
  | "new_order"
  | "extension"
  | "period"
  | "rate_revenue"
  | "rate_cost"
  | "exit"
  | "ending"
  | "gap";

export const BOARD_LABEL_TEXT: Record<BoardLabel, string> = {
  new_order: "Nowe zamówienie",
  extension: "Przedłużenie",
  period: "Zmiana okresu",
  rate_revenue: "Stawka przychodowa",
  rate_cost: "Stawka kosztowa",
  exit: "Zejście",
  ending: "Bez kontynuacji",
  gap: "Brak zamówienia",
};

const LABEL_ORDER: BoardLabel[] = [
  "new_order",
  "extension",
  "period",
  "rate_revenue",
  "rate_cost",
  "exit",
  "ending",
  "gap",
];

export const ORDER_MAIL_ADDRESS = "zamowienia@b2bnetwork.pl";

export interface BoardItem {
  key: string;
  tab: OrderChangesTab;
  cardKey: string;
  orderId: number | null;
  orderGroupId: number | null;
  clientId: number | null;
  clientName: string;
  consultantName: string;
  orderNumber: string;
  orderStart: string | null;
  orderEnd: string | null;
  label: BoardLabel;
  /** Pole, którego dotyczy zmiana — ponowna zmiana tego samego pola
   *  przykrywa wcześniejszą, odhaczoną („Zmieniono ponownie"). */
  field: string;
  title: string;
  before: string | null;
  after: string | null;
  note: string | null;
  /** „21.09.2026, 12:41" — chwila wprowadzenia (wpis albo założenie). */
  enteredAt: string | null;
  /** Autor albo „dodane automatycznie (…)"; `null` = pozycja z dat. */
  enteredBy: string | null;
  done: OrderItemCheck | null;
  pdf: OrderPdfRef | null;
  /** Do sortowania chronologicznego w karcie. */
  sortAt: string;
  /** Nordea, Wejścia: gotowa pozycja faktury cyklicznej (ticket 8). */
  invoiceLines?: InvoiceLine[] | null;
}

function cardKeyOf(item: {
  order_id: number | null;
  order_group_id: number | null;
}): string {
  if (item.order_id != null) return `o:${item.order_id}`;
  if (item.order_group_id != null) return `g:${item.order_group_id}`;
  return "x:?";
}

function enteredByText(
  item: {
    entered_by?: string | null;
    entered_automatically?: boolean;
    from_order_mail?: boolean;
  },
  automaticText: string,
): string | null {
  if (item.from_order_mail)
    return `dodane automatycznie (${ORDER_MAIL_ADDRESS})`;
  if (item.entered_by) return item.entered_by;
  if (item.entered_automatically) return automaticText;
  return null;
}

function base(
  tab: OrderChangesTab,
  item: OrderChangeItem | OrderEntryItem | OrderExitItem | OrderGapItem,
  fallbackKey: string,
) {
  return {
    key: item.item_key || fallbackKey,
    tab,
    cardKey: cardKeyOf(item),
    orderId: item.order_id,
    orderGroupId: item.order_group_id,
    clientId: item.client_id,
    clientName: item.client_name,
    consultantName: item.consultant_name,
    orderNumber: item.order_number,
    orderStart: item.order_start ?? null,
    orderEnd: item.order_end ?? null,
    done: item.done ?? null,
    pdf: item.pdf ?? null,
    enteredAt: item.entered_at ? formatMoment(item.entered_at) : null,
  };
}

function ratesText(
  item: Pick<
    OrderChangeItem,
    "rate_cost" | "rate_revenue" | "rate_unit" | "currency"
  >,
): string {
  return (
    `stawka przychodowa ${formatRate(item.rate_revenue, item.rate_unit, item.currency)} · ` +
    `stawka kosztowa ${formatRate(item.rate_cost, item.rate_unit, item.currency)}`
  );
}

function endLabel(value: string | null): string {
  return value ? formatDay(value) : "bezterminowo";
}

function changeItem(item: OrderChangeItem, index: number): BoardItem {
  const common = {
    ...base("changes", item, `changes:${index}`),
    enteredBy: enteredByText(
      item,
      item.event_id != null ? "zmiana automatyczna" : "dodane automatycznie",
    ),
    sortAt: item.entered_at ?? item.occurred_at ?? item.effective_date ?? "",
  };
  switch (item.kind) {
    case "rate_cost":
    case "rate_revenue":
      return {
        ...common,
        label: item.kind,
        field: item.kind,
        title:
          item.kind === "rate_cost" ? "Stawka kosztowa" : "Stawka przychodowa",
        // Stara strona w SWOJEJ walucie — sama zmiana waluty też jest zmianą.
        before: formatRate(
          item.old_amount,
          item.old_unit,
          item.old_currency ?? item.currency,
        ),
        after: formatRate(item.new_amount, item.new_unit, item.currency),
        note: item.is_whole_order ? "całe zamówienie" : null,
      };
    case "end_date": {
      // Późniejsza data (albo „bezterminowo") = przedłużenie; wcześniejsza —
      // skrócenie, czyli zmiana okresu.
      const extended =
        item.new_date === null
          ? item.old_date !== null
          : item.old_date !== null && item.new_date > item.old_date;
      return {
        ...common,
        label: extended ? "extension" : "period",
        field: "end_date",
        title: "Data końca",
        before: endLabel(item.old_date),
        after: endLabel(item.new_date),
        note: item.is_whole_order ? "całe zamówienie" : null,
      };
    }
    case "order_continuation":
      return {
        ...common,
        label: "extension",
        field: "new_order",
        title: "Przedłużenie",
        before: null,
        after: ratesText(item),
        note: item.previous_order_number
          ? `po zam. ${item.previous_order_number} (do ${formatDay(item.previous_end_date)})`
          : item.engagement_since
            ? `współpraca od ${formatDay(item.engagement_since)}`
            : null,
      };
    case "client_change":
      return {
        ...common,
        label: "new_order",
        field: "new_order",
        title: "Nowe zamówienie (zmiana klienta)",
        before: null,
        after: ratesText(item),
        note: `wcześniej u: ${item.previous_client_name ?? "—"}`,
      };
    case "additional_project":
      return {
        ...common,
        label: "new_order",
        field: "new_order",
        title: "Nowe zamówienie (dodatkowy projekt)",
        before: null,
        after: ratesText(item),
        note: `równolegle u: ${item.other_client_names.join(", ") || "—"}`,
      };
  }
}

function entryItem(item: OrderEntryItem, index: number): BoardItem {
  return {
    ...base("entries", item, `entries:${index}`),
    enteredBy: enteredByText(item, "dodane automatycznie"),
    sortAt: item.entered_at ?? item.start_date ?? "",
    label: "new_order",
    field: "new_order",
    title: "Nowe zamówienie",
    before: null,
    after: ratesText(item),
    note: item.status === "draft" ? "szkic" : null,
    invoiceLines: item.invoice_lines ?? null,
  };
}

function exitLikeItem(
  tab: "exits" | "ending",
  item: OrderExitItem,
  index: number,
): BoardItem {
  return {
    ...base(tab, item, `${tab}:${index}`),
    enteredBy: null,
    sortAt: item.end_date,
    label: tab === "exits" ? "exit" : "ending",
    field: tab,
    title: tab === "exits" ? "Zejście" : "Koniec zamówienia",
    before: null,
    after: formatDay(item.end_date),
    note: item.verdict_label,
  };
}

function gapItem(item: OrderGapItem, index: number): BoardItem {
  return {
    ...base("gaps", item, `gaps:${index}`),
    enteredBy: null,
    sortAt: item.detected_on,
    label: "gap",
    field: "gap",
    title: "Brak kolejnego zamówienia",
    before: null,
    after: `po ${formatDay(item.ended_on)} (wykryto ${formatDay(item.detected_on)})`,
    note: gapStatusLabel(item),
  };
}

/** Pozycje jednej podzakładki w jednym kształcie. */
export function boardItems(
  data: OrderChangesResponse,
  tab: OrderChangesTab,
): BoardItem[] {
  switch (tab) {
    case "changes":
      return data.changes.map(changeItem);
    case "entries":
      return data.entries.map(entryItem);
    case "exits":
      return data.exits.map((item, i) => exitLikeItem("exits", item, i));
    case "ending":
      return data.ending_orders.map((item, i) =>
        exitLikeItem("ending", item, i),
      );
    case "gaps":
      return data.gaps.map(gapItem);
  }
}

const ALL_TABS: OrderChangesTab[] = [
  "changes",
  "entries",
  "exits",
  "ending",
  "gaps",
];

/** Wszystkie pozycje miesiąca jednego zamówienia (każda podzakładka). */
export function cardItemsAllTabs(
  data: OrderChangesResponse,
  cardKey: string,
): BoardItem[] {
  return ALL_TABS.flatMap((tab) =>
    boardItems(data, tab).filter((item) => item.cardKey === cardKey),
  );
}

// ── Liczniki ────────────────────────────────────────────────────────────────

export interface StatusCounts {
  todo: number;
  done: number;
  all: number;
}

export function statusCounts(items: BoardItem[]): StatusCounts {
  const done = items.filter((item) => item.done).length;
  return { todo: items.length - done, done, all: items.length };
}

// ── Klienci ─────────────────────────────────────────────────────────────────

export interface ClientTile {
  key: string;
  clientId: number | null;
  name: string;
  total: number;
  todo: number;
}

export function clientKey(clientId: number | null): string {
  return clientId == null ? "none" : String(clientId);
}

/**
 * Kafelki klientów: najpierw ci z pozycjami do zrobienia (najwięcej na górze),
 * klienci ze wszystkim zrobionym na dole.
 */
export function clientTiles(items: BoardItem[]): ClientTile[] {
  const tiles = new Map<string, ClientTile>();
  for (const item of items) {
    const key = clientKey(item.clientId);
    const tile = tiles.get(key) ?? {
      key,
      clientId: item.clientId,
      name: item.clientId == null ? "Bez klienta" : item.clientName,
      total: 0,
      todo: 0,
    };
    tile.total += 1;
    if (!item.done) tile.todo += 1;
    tiles.set(key, tile);
  }
  return [...tiles.values()].sort((a, b) => {
    const aDone = a.todo === 0;
    const bDone = b.todo === 0;
    if (aDone !== bDone) return aDone ? 1 : -1;
    if (a.todo !== b.todo) return b.todo - a.todo;
    return a.name.localeCompare(b.name, "pl");
  });
}

// ── Karty zamówień ──────────────────────────────────────────────────────────

export interface EarlierDone {
  summary: string;
  done: OrderItemCheck;
}

export interface BoardCardItem {
  item: BoardItem;
  /** Wcześniejsze, odhaczone zmiany tego samego pola, przykryte tą pozycją. */
  earlier: EarlierDone[];
}

export interface BoardCard {
  key: string;
  clientId: number | null;
  clientName: string;
  consultantName: string;
  orderNumber: string;
  orderStart: string | null;
  orderEnd: string | null;
  orderId: number | null;
  orderGroupId: number | null;
  pdf: OrderPdfRef | null;
  labels: BoardLabel[];
  changedAgain: boolean;
  todo: number;
  done: number;
  /** Pozycje do pokazania (zależne od filtru statusu). */
  visible: BoardCardItem[];
  /** Wszystkie pozycje karty w tej podzakładce (chronologicznie). */
  items: BoardItem[];
  /** Odhaczenia pozycji, których po ponownej zmianie już nie ma. */
  previous: EarlierDone[];
}

/** „Zam. 286139 · 01.10.2026 – 31.12.2026 · Axel Gocan" — format z „Zamówień PDF". */
export function cardTitle(
  card: Pick<
    BoardCard,
    "orderNumber" | "orderStart" | "orderEnd" | "consultantName"
  >,
): string {
  const start = card.orderStart ? formatDay(card.orderStart) : "—";
  const end = card.orderEnd ? formatDay(card.orderEnd) : "bezterminowo";
  return `Zam. ${card.orderNumber} · ${start} – ${end} · ${card.consultantName}`;
}

export function itemSummary(item: BoardItem): string {
  if (item.before !== null)
    return `${item.title}: ${item.before} → ${item.after}`;
  return item.after ? `${item.title}: ${item.after}` : item.title;
}

function supersededMatches(
  check: OrderSupersededCheck,
  card: { orderId: number | null; orderGroupId: number | null },
): boolean {
  if (check.order_id != null) return check.order_id === card.orderId;
  return card.orderId == null && check.order_group_id === card.orderGroupId;
}

/**
 * Karty zamówień jednej podzakładki (po filtrze klienta).
 *
 * Ponowna zmiana tego samego pola: starsza, odhaczona pozycja chowa się pod
 * nowszą jako „wcześniejsza zmiana … oznaczona jako zrobiona", a karta
 * dostaje „Zmieniono ponownie". W filtrze „Zrobione" widać każdą odhaczoną
 * pozycję osobno — tam pytanie brzmi „co zostało zrobione", nie „co zostało".
 */
export function buildCards(
  items: BoardItem[],
  status: StatusFilter,
  superseded: OrderSupersededCheck[] = [],
  tab?: OrderChangesTab,
): BoardCard[] {
  const groups = new Map<string, BoardItem[]>();
  for (const item of items) {
    const list = groups.get(item.cardKey) ?? [];
    list.push(item);
    groups.set(item.cardKey, list);
  }

  const cards: BoardCard[] = [];
  for (const [key, list] of groups) {
    const ordered = [...list].sort((a, b) => a.sortAt.localeCompare(b.sortAt));
    const first = ordered[0];
    const card = {
      orderId: first.orderId,
      orderGroupId: first.orderGroupId,
    };

    // Starsze odhaczone pozycje przykryte nowszą pozycją „Do zrobienia"
    // tego samego pola.
    const hidden = new Set<string>();
    const earlierOf = new Map<string, EarlierDone[]>();
    for (let i = 0; i < ordered.length; i += 1) {
      const current = ordered[i];
      if (current.done) continue;
      const earlier = ordered
        .slice(0, i)
        .filter((other) => other.field === current.field && other.done);
      if (earlier.length === 0) continue;
      earlier.forEach((other) => hidden.add(other.key));
      earlierOf.set(
        current.key,
        earlier.map((other) => ({
          summary: itemSummary(other),
          done: other.done!,
        })),
      );
    }

    const previous = superseded
      .filter((check) => (tab ? check.tab === tab : true))
      .filter((check) => supersededMatches(check, card))
      .map((check) => ({ summary: check.summary, done: check.done }));

    const todo = ordered.filter((item) => !item.done).length;
    const done = ordered.length - todo;
    const visible: BoardCardItem[] =
      status === "done"
        ? ordered
            .filter((item) => item.done)
            .map((item) => ({ item, earlier: [] }))
        : ordered
            .filter((item) => !hidden.has(item.key))
            .map((item) => ({ item, earlier: earlierOf.get(item.key) ?? [] }));

    const labels = LABEL_ORDER.filter((label) =>
      ordered.some((item) => item.label === label),
    );
    cards.push({
      key,
      clientId: first.clientId,
      clientName: first.clientName,
      consultantName: first.consultantName,
      orderNumber: first.orderNumber,
      orderStart: first.orderStart,
      orderEnd: first.orderEnd,
      orderId: first.orderId,
      orderGroupId: first.orderGroupId,
      pdf: ordered.find((item) => item.pdf)?.pdf ?? null,
      labels,
      changedAgain: todo > 0 && (hidden.size > 0 || previous.length > 0),
      todo,
      done,
      visible,
      items: ordered,
      previous,
    });
  }

  return cards
    .filter((card) => (status === "done" ? card.done > 0 : true))
    .sort((a, b) => {
      if (a.todo > 0 !== b.todo > 0) return a.todo > 0 ? -1 : 1;
      return a.consultantName.localeCompare(b.consultantName, "pl");
    });
}

/** Karty z czymś do zrobienia i karty w całości zrobione (sekcja „Zrobione"). */
export function splitCards(
  cards: BoardCard[],
  status: StatusFilter,
): {
  open: BoardCard[];
  finished: BoardCard[];
} {
  if (status === "done") return { open: cards, finished: [] };
  return {
    open: cards.filter((card) => card.todo > 0),
    finished: cards.filter((card) => card.todo === 0),
  };
}

/** „Zrobione: Anna Korycka · 22.09.2026, 09:14" */
export function doneLabel(done: OrderItemCheck): string {
  return `Zrobione: ${done.by_name} · ${formatMoment(done.at)}`;
}

/** Zmiana stanu jednej pozycji w danych z serwera (optymistycznie). */
export function withCheck(
  data: OrderChangesResponse,
  key: string,
  done: OrderItemCheck | null,
): OrderChangesResponse {
  const patch = <T extends { item_key?: string }>(list: T[]): T[] =>
    list.map((item) => (item.item_key === key ? { ...item, done } : item));
  return {
    ...data,
    changes: patch(data.changes),
    entries: patch(data.entries),
    exits: patch(data.exits),
    ending_orders: patch(data.ending_orders),
    gaps: patch(data.gaps),
  };
}

/**
 * Zapisana poprawka pozycji faktury. Serwer oddaje WSZYSTKIE linie zamówienia,
 * a karta pokazuje tylko linie swojej osoby — podmieniamy je po indeksie.
 */
export function withInvoiceLines(
  data: OrderChangesResponse,
  orderId: number,
  saved: InvoiceLine[],
): OrderChangesResponse {
  const byIndex = new Map(saved.map((line) => [line.index, line]));
  return {
    ...data,
    entries: data.entries.map((entry) =>
      entry.order_id === orderId && entry.invoice_lines
        ? {
            ...entry,
            invoice_lines: entry.invoice_lines.map(
              (line) => byIndex.get(line.index) ?? line,
            ),
          }
        : entry,
    ),
  };
}

/** „Zrobione we wrześniu" — nazwa miesiąca w miejscowniku. */
const MONTHS_LOCATIVE = [
  "styczniu",
  "lutym",
  "marcu",
  "kwietniu",
  "maju",
  "czerwcu",
  "lipcu",
  "sierpniu",
  "wrześniu",
  "październiku",
  "listopadzie",
  "grudniu",
] as const;

export function doneInMonthLabel(month: number): string {
  const name = MONTHS_LOCATIVE[month - 1] ?? "";
  const preposition = month === 9 ? "we" : "w";
  return `Zrobione ${preposition} ${name}`;
}
