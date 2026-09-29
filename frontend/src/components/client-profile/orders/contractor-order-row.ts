/**
 * Reguły wiersza kontraktora z zamówieniami okresowymi — czyste funkcje, bez
 * Reacta. Czyta je wiersz tabeli (`contractorRowSummary`) i panel szczegółów
 * (`ContractorOrderPanel`), więc tabela i panel nie mogą powiedzieć o tej
 * samej osobie dwóch różnych rzeczy.
 *
 * Tu mieszkają też reguły, które do 29.09.2026 żyły w
 * `components/OrdersAndContractsTab.tsx` (`splitOrders`,
 * `canTerminateContractor`, sufiksy stawek) — plik usunięty razem z kafelkami.
 */

import type { ClientOrderRead, ContractWithOrdersRead } from "@/lib/api/dlPortal";
import {
  contractClosed,
  daysUntil,
  endingWithoutSuccessorOrderId,
  endsInPhrase,
  isCurrentOrder,
  lacksCurrentOrder,
  localTodayIso,
  orderNotStarted,
} from "@/lib/client-order-list";
import { formatIsoDatePl } from "@/lib/date-pl";
import { normalizeOrderCurrency } from "@/components/orders/OrderRateUnitToggle";

function dateOnly(value: string | null | undefined): string | null {
  return value ? value.slice(0, 10) : null;
}

// ── Stany terminalne kontraktu ───────────────────────────────────────────────

/** Stany TERMINALNE kontraktu — jedyne, w których nie ma już czego kończyć. */
const TERMINAL_CONTRACT_STATUSES: ReadonlySet<string> = new Set([
  "ended",
  "void",
]);

/**
 * Czy pokazać „Zakończ współpracę". Bramka stoi na stanach TERMINALNYCH,
 * świadomie NIE na `active` — kontraktor bywa `draft`, bo „Nowy kontraktor"
 * zakłada szkic (dialog nie zbiera typu umowy ani trybu pracy), a konsultant
 * realnie pracuje. Jedyna droga rozstania — `POST /contracts/{id}/terminate`,
 * który żadnej bramki statusu nie ma, a `draft → ended` jest legalną krawędzią
 * cyklu życia — była zasłonięta przyciskiem, który się nie renderował.
 *
 * To jest bramka STANU. Bramka ROLI (kto w ogóle może kończyć współpracę)
 * stoi osobno w panelu: `canManageContractStatus` — ta sama co na stronie
 * kontraktu.
 */
export function canTerminateContractor(contractStatus: string | null): boolean {
  return !TERMINAL_CONTRACT_STATUSES.has(contractStatus ?? "");
}

// ── Podział osi zamówień ─────────────────────────────────────────────────────

export interface SplitOrders {
  /** Bieżąca pozycja — górna część panelu. */
  activeOrder: ClientOrderRead | null;
  /** Zamówienia, których okres jeszcze się nie zaczął (przedłużenia w kolejce). */
  futureOrders: ClientOrderRead[];
  /** Przeszłe / zastąpione i anulowane — za przełącznikiem „Historia". */
  historyOrders: ClientOrderRead[];
}

/**
 * Dzieli zamówienia kontraktora na bieżące, przyszłe i historyczne. Po dacie,
 * celowo: „przedłużenie" powstaje z `status=active` i przyszłą datą startu,
 * więc w dniu startu samo wchodzi na górę bez żadnego crona. `orders`
 * przychodzi posortowane po `start_date` malejąco.
 */
export function splitOrders(
  orders: ClientOrderRead[],
  todayIso: string = localTodayIso(),
): SplitOrders {
  const today = todayIso;
  const nonCancelled = orders.filter((o) => o.status !== "cancelled");
  const cancelled = orders.filter((o) => o.status === "cancelled");

  const future = nonCancelled.filter((o) => orderNotStarted(o, today));
  const started = nonCancelled.filter((o) => !orderNotStarted(o, today));

  let activeOrder: ClientOrderRead | null = null;
  let futureOrders: ClientOrderRead[] = future;
  if (started.length > 0) {
    // Zamówienie BIEŻĄCE (trwa dziś i nie jest zamknięte) wygrywa z samym
    // najnowszym startem: kontrakt z dwoma wierszami tego samego okresu —
    // stary `completed` z importu obok aktywnego — miał w slocie martwy
    // wiersz (zgłoszenie 29.09.2026). Bez bieżącego zamówienia zostaje
    // ostatnie rozpoczęte (historia osoby).
    activeOrder = started.find((o) => isCurrentOrder(o, today)) ?? started[0];
  } else if (future.length > 0) {
    // Nic się jeszcze nie zaczęło — najbliższe przyszłe jest bieżącą pozycją.
    const soonestFirst = [...future].sort((a, b) =>
      (dateOnly(a.start_date) ?? "").localeCompare(dateOnly(b.start_date) ?? ""),
    );
    activeOrder = soonestFirst[0];
    futureOrders = soonestFirst.slice(1);
  }

  const historyOrders = [
    ...started.filter((o) => o.id !== activeOrder?.id),
    ...cancelled,
  ].sort((a, b) =>
    (dateOnly(b.start_date) ?? "").localeCompare(dateOnly(a.start_date) ?? ""),
  );

  return { activeOrder, futureOrders, historyOrders };
}

// ── Kończące się zamówienie i brak zamówienia ────────────────────────────────

export interface ContractorEnding {
  order: ClientOrderRead;
  days: number;
  /** Zamówienie stoi na liście „Przyszłe zamówienie" (okres się nie zaczął). */
  isFuture: boolean;
  /** Tekst plakietki — ten sam w wierszu tabeli i w panelu. */
  label: string;
}

/**
 * Zamówienie bez kontynuacji, które kończy się w 30 dni. Regułę liczy serwer
 * (`ending_without_successor_order_id`, audyt 24.09.2026) — ta sama co panel
 * „Moi klienci", dzwonek i kafelek pulpitu; lokalny zapas tylko dla
 * odpowiedzi bez pola.
 *
 * „Przyszłe zamówienie X kończy się…" pada WYŁĄCZNIE dla zamówienia z listy
 * przyszłych (okres jeszcze się nie zaczął, #1921). Zamówienie, które trwa
 * i za chwilę się kończy, mówi „kończy się za N dni" bez numeru — także gdy
 * jest jedynym, które jeszcze się nie zaczęło (stoi wtedy w górnym slocie).
 */
export function contractorEnding(
  contractor: ContractWithOrdersRead,
  split: SplitOrders,
  todayIso: string = localTodayIso(),
): ContractorEnding | null {
  const endingOrderId = endingWithoutSuccessorOrderId(contractor, todayIso);
  if (endingOrderId === null) return null;
  const order = contractor.orders.find((item) => item.id === endingOrderId);
  if (!order) return null;
  const days =
    contractor.ending_without_successor_days ?? daysUntil(order.end_date, todayIso);
  if (days === null) return null;
  const isFuture = split.futureOrders.some((item) => item.id === order.id);
  const label = isFuture
    ? `przyszłe zamówienie ${order.title} kończy się ${endsInPhrase(days)}`
    : `kończy się ${endsInPhrase(days)}`;
  return { order, days, isFuture, label };
}

/**
 * Dopisek „Brak zamówienia" (karta szkicu) albo „Brak aktywnego zamówienia"
 * (okres minął, a umowa trwa). Do „Zakończonych" przenosi wyłącznie umowa
 * z modułu Kontrakty (reguła 09.2026, `contractClosed`), nie upływ okresu.
 */
export function contractorMissingOrder(
  contractor: ContractWithOrdersRead,
  todayIso: string = localTodayIso(),
): { label: string; hint: string } | null {
  if (contractor.draft_card === true) {
    return {
      label: "Brak zamówienia",
      hint: "Kontrakt nie ma jeszcze zamówienia od klienta — uzupełnij szkic albo dodaj zamówienie",
    };
  }
  if (
    (contractor.contract_status === "active" ||
      contractor.contract_status === "ending") &&
    lacksCurrentOrder(contractor, todayIso)
  ) {
    return {
      label: "Brak aktywnego zamówienia",
      hint: "Okres zamówienia minął, a umowa trwa — dodaj przedłużenie albo zakończ współpracę w module Kontrakty",
    };
  }
  return null;
}

// ── Kwoty ────────────────────────────────────────────────────────────────────

export function fmtMoney(v: number | string | null | undefined): string {
  if (v === null || v === undefined) return "—";
  const num = typeof v === "string" ? parseFloat(v) : v;
  if (Number.isNaN(num)) return "—";
  return num.toLocaleString("pl-PL");
}

// Surowe stawki (rate_candidate / rate_client) są w jednostce zamówienia albo
// kontraktu — etykieta musi za nią podążać (Alior ma stawki godzinowe;
// „164,375/mc" to był bug). Marża NIE używa tego sufiksu — jest normalizowana
// do /mc po stronie serwera.
const RATE_UNIT_SUFFIX: Record<string, string> = {
  hourly: "/h",
  daily: "/MD",
  monthly: "/mc",
};

export function rateUnitSuffix(unit: string | null | undefined): string {
  return RATE_UNIT_SUFFIX[unit ?? "monthly"] ?? "/mc";
}

export interface ContractorRates {
  unit: string;
  costAmount: number | null;
  costCurrency: string;
  /** Stawka kosztowa pochodzi z kontraktu (źródło prawdy od 09.2026). */
  costFromContract: boolean;
  revenueAmount: number | null;
  revenueCurrency: string;
  contractRateClientCurrency: string;
  contractRateCandidateCurrency: string;
}

/** Stawki pokazywane przy bieżącym zamówieniu: zamówienie przed kontraktem. */
export function contractorRates(
  contractor: ContractWithOrdersRead,
  activeOrder: ClientOrderRead | null,
): ContractorRates {
  const contractRateClientCurrency = normalizeOrderCurrency(
    contractor.rate_client_currency,
    contractor.currency,
  );
  const contractRateCandidateCurrency = normalizeOrderCurrency(
    contractor.rate_candidate_currency,
    contractor.currency,
    contractor.rate_client_currency,
  );
  return {
    unit: activeOrder?.rate_unit ?? contractor.rate_unit,
    costAmount: activeOrder?.rate_candidate ?? contractor.rate_candidate,
    costCurrency: normalizeOrderCurrency(
      activeOrder?.rate_candidate_currency,
      contractRateCandidateCurrency,
    ),
    costFromContract: contractor.rate_candidate != null,
    revenueAmount: activeOrder?.rate_client ?? null,
    revenueCurrency: normalizeOrderCurrency(
      activeOrder?.rate_client_currency,
      activeOrder?.currency,
      contractRateClientCurrency,
    ),
    contractRateClientCurrency,
    contractRateCandidateCurrency,
  };
}

export function rateLabel(
  amount: number | null | undefined,
  currency: string,
  unit: string | null | undefined,
): string | null {
  if (amount === null || amount === undefined) return null;
  return `${fmtMoney(amount)} ${currency}${rateUnitSuffix(unit)}`;
}

export function periodLabel(
  order: Pick<ClientOrderRead, "start_date" | "end_date"> | null,
): string | null {
  if (!order || (!order.start_date && !order.end_date)) return null;
  const start = order.start_date ? formatIsoDatePl(dateOnly(order.start_date)) : "—";
  const end = order.end_date ? formatIsoDatePl(dateOnly(order.end_date)) : "bezterminowo";
  return `${start} → ${end}`;
}

// ── Wiersz tabeli ────────────────────────────────────────────────────────────

export type ContractorRowTone = "ok" | "warn" | "bad" | "mut";

export type ContractorRowStateKind =
  | "ended"
  | "no_order"
  | "no_active_order"
  | "ending"
  | "not_started"
  | "draft_order"
  | "paused"
  | "closed_order"
  | "active";

export interface ContractorRowSummary {
  key: string;
  contractId: number;
  name: string;
  orderNumber: string | null;
  periodLabel: string | null;
  /** `null`, gdy stawki nie ma albo rola nie widzi kwot. */
  costLabel: string | null;
  costFromContract: boolean;
  revenueLabel: string | null;
  state: { kind: ContractorRowStateKind; label: string; tone: ContractorRowTone };
  futureCount: number;
  historyCount: number;
  isDraftCard: boolean;
  isEnded: boolean;
}

export interface ContractorRowSummaryOptions {
  /** Rola bez kwot tego klienta: etykiety stawek zawsze `null`. Domyślnie `true`
   *  (serwer i tak redaguje kwoty); przekaż fałsz z tej samej bramki co panel. */
  canViewFinance?: boolean;
}

/**
 * Co pokazuje wiersz kontraktora w tabeli zamówień okresowych. Te same reguły
 * co panel: `splitOrders`, plakietka kończącego się zamówienia, dopisek
 * o braku zamówienia i „Zakończeni" wyłącznie po umowie (`contractClosed`).
 * Kolejność stanu: umowa zakończona → brak zamówienia → kończy się → stan
 * bieżącego zamówienia.
 */
export function contractorRowSummary(
  contractor: ContractWithOrdersRead,
  today: string = localTodayIso(),
  options: ContractorRowSummaryOptions = {},
): ContractorRowSummary {
  const canViewFinance = options.canViewFinance ?? true;
  const split = splitOrders(contractor.orders, today);
  const { activeOrder } = split;
  const rates = contractorRates(contractor, activeOrder);
  const ending = contractorEnding(contractor, split, today);
  const missing = contractorMissingOrder(contractor, today);
  const isEnded =
    contractClosed(contractor, today) || contractor.contract_status === "void";

  let state: ContractorRowSummary["state"];
  if (isEnded) {
    const end = dateOnly(contractor.contract_end_date);
    state = {
      kind: "ended",
      label:
        contractor.contract_status === "void"
          ? "Umowa unieważniona"
          : end
            ? `Zakończony ${formatIsoDatePl(end)}`
            : "Zakończony",
      tone: "mut",
    };
  } else if (missing) {
    state = {
      kind: contractor.draft_card === true ? "no_order" : "no_active_order",
      label: missing.label,
      tone: contractor.draft_card === true ? "warn" : "bad",
    };
  } else if (ending) {
    state = { kind: "ending", label: ending.label, tone: "warn" };
  } else if (!activeOrder) {
    state = { kind: "no_order", label: "Brak zamówienia", tone: "mut" };
  } else if (activeOrder.status === "completed" || activeOrder.status === "cancelled") {
    state = {
      kind: "closed_order",
      label: activeOrder.status === "cancelled" ? "Anulowane" : "Zakończone",
      tone: "mut",
    };
  } else if (activeOrder.status === "draft") {
    state = { kind: "draft_order", label: "Szkic zamówienia", tone: "mut" };
  } else if (activeOrder.status === "paused") {
    state = { kind: "paused", label: "Wstrzymane", tone: "warn" };
  } else if (orderNotStarted(activeOrder, today)) {
    state = {
      kind: "not_started",
      label: `Startuje ${formatIsoDatePl(dateOnly(activeOrder.start_date))}`,
      tone: "ok",
    };
  } else {
    state = { kind: "active", label: "Aktywne", tone: "ok" };
  }

  return {
    key: `contract-${contractor.contract_id}`,
    contractId: contractor.contract_id,
    name: contractor.candidate_name,
    orderNumber: activeOrder?.title ?? null,
    periodLabel: periodLabel(activeOrder),
    costLabel: canViewFinance
      ? rateLabel(rates.costAmount, rates.costCurrency, rates.unit)
      : null,
    costFromContract: canViewFinance && rates.costFromContract,
    revenueLabel: canViewFinance
      ? rateLabel(rates.revenueAmount, rates.revenueCurrency, rates.unit)
      : null,
    state,
    futureCount: split.futureOrders.length,
    historyCount: split.historyOrders.length,
    isDraftCard: contractor.draft_card === true,
    isEnded,
  };
}
