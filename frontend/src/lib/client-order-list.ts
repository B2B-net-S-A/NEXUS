import { foldText } from "@/lib/contract-client-filter";
import type {
  ClientOrderRead,
  ContractWithOrdersRead,
} from "@/lib/api/dlPortal";
import type {
  OrderGroupRead,
  OrderLineRead,
} from "@/lib/api/orderGroups";

export type OrderSort =
  | "created_desc"
  | "consultant_asc"
  | "consultant_desc"
  | "md_asc"
  | "md_desc"
  | "cost_asc"
  | "cost_desc"
  | "revenue_asc"
  | "revenue_desc";

export interface OrderListFilters {
  startFrom: string;
  startTo: string;
  endFrom: string;
  endTo: string;
  sort: OrderSort;
  nearBudget: boolean;
  endingSoon: boolean;
  endingDays: number;
}

export const DEFAULT_ORDER_LIST_FILTERS: OrderListFilters = {
  startFrom: "",
  startTo: "",
  endFrom: "",
  endTo: "",
  sort: "created_desc",
  nearBudget: false,
  endingSoon: false,
  endingDays: 30,
};

function dateOnly(value: string | null | undefined): string | null {
  return value ? value.slice(0, 10) : null;
}

export function localTodayIso(now = new Date()): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function addDays(isoDate: string, days: number): string {
  const value = new Date(`${isoDate}T12:00:00`);
  value.setDate(value.getDate() + days);
  return localTodayIso(value);
}

function queryTokens(query: string): string[] {
  return foldText(query.trim())
    .split(/[\s/.,-]+/)
    .filter(Boolean);
}

/**
 * Imię i nazwisko dopasowują się tokenami, więc kolejność nie ma znaczenia:
 * „Kowal Jan”, „Jan Kow” i wersje bez polskich znaków wskazują tę samą osobę.
 */
export function consultantMatchesQuery(name: string, query: string): boolean {
  const tokens = queryTokens(query);
  if (tokens.length === 0) return true;
  const nameParts = queryTokens(name);
  return tokens.every((token) =>
    nameParts.some((part) => part.includes(token)),
  );
}

function groupOwnMatchesQuery(group: OrderGroupRead, query: string): boolean {
  const foldedQuery = foldText(query.trim());
  if (!foldedQuery) return true;
  if (foldText(group.order_number).includes(foldedQuery)) return true;
  return group.lines.some((line) =>
    consultantMatchesQuery(line.consultant_name, query),
  );
}

/** Wyszukiwanie obejmuje także zagnieżdżone przyszłe zamówienia. */
export function orderGroupMatchesQuery(
  group: OrderGroupRead,
  query: string,
): boolean {
  return (
    groupOwnMatchesQuery(group, query) ||
    group.future_orders.some((future) =>
      orderGroupMatchesQuery(future, query),
    )
  );
}

export function sortOrderLinesByConsultant(
  lines: readonly OrderLineRead[],
): OrderLineRead[] {
  return [...lines].sort((left, right) =>
    foldText(left.consultant_name).localeCompare(
      foldText(right.consultant_name),
      "pl",
    ),
  );
}

export interface OrderGroupMetrics {
  totalMd: number | null;
  averageCost: number | null;
  averageRevenue: number | null;
  budgetUsage: number | null;
}

function average(values: Array<number | null>): number | null {
  const present = values.filter((value): value is number => value !== null);
  if (present.length === 0) return null;
  return present.reduce((sum, value) => sum + value, 0) / present.length;
}

export function orderGroupMetrics(group: OrderGroupRead): OrderGroupMetrics {
  const mdLines = group.lines.filter((line) => line.md_total !== null);
  const totalMd = group.is_md_budget_based
    ? group.md_budget_total
    : mdLines.length > 0
      ? mdLines.reduce((sum, line) => sum + (line.md_total ?? 0), 0)
      : null;
  let budgetUsage: number | null = null;
  if (
    group.is_cost_based &&
    group.budget_amount !== null &&
    group.budget_amount > 0
  ) {
    budgetUsage = (group.budget_used ?? 0) / group.budget_amount;
  } else if (
    group.is_md_budget_based &&
    group.md_budget_total !== null &&
    group.md_budget_total > 0
  ) {
    budgetUsage = (group.md_budget_used ?? 0) / group.md_budget_total;
  } else if (totalMd !== null && totalMd > 0) {
    const used = mdLines.reduce(
      (sum, line) =>
        sum +
        (line.md_total ?? 0) +
        (line.md_manual_adjustment ?? 0) -
        (line.md_remaining ?? 0),
      0,
    );
    budgetUsage = used / totalMd;
  }
  return {
    totalMd,
    averageCost: average(group.lines.map((line) => line.rate_cost)),
    averageRevenue: average(group.lines.map((line) => line.rate_revenue)),
    budgetUsage,
  };
}

function matchesDateRange(
  value: string | null,
  from: string,
  to: string,
): boolean {
  if (!from && !to) return true;
  if (!value) return false;
  if (from && value < from) return false;
  if (to && value > to) return false;
  return true;
}

function isEndingSoon(
  endDate: string | null,
  days: number,
  todayIso: string,
): boolean {
  if (!endDate) return false;
  return endDate >= todayIso && endDate <= addDays(todayIso, days);
}

function compareNullable(
  left: number | null,
  right: number | null,
  direction: "asc" | "desc",
): number {
  if (left === null && right === null) return 0;
  if (left === null) return 1;
  if (right === null) return -1;
  return direction === "asc" ? left - right : right - left;
}

function compareCreated(
  left: { created_at: string; id: number },
  right: { created_at: string; id: number },
): number {
  return (
    right.created_at.localeCompare(left.created_at) || right.id - left.id
  );
}

/**
 * Klucz nazwiska do sortowania: same litery i cyfry, pusty gdy nazwiska nie ma.
 *
 * Interpunkcja LECI W CAŁOŚCI, bo do nazwisk w tej bazie potrafi się przykleić
 * śmieć — produkcja Nordei ma „{ } Wojciech Łazowski", a wcześniej „[acive/
 * Mariusz Szewczyk" (marker statusu wklejony w imię). `foldText` zdejmuje tylko
 * wielkość liter i diakrytykę, więc `{` zostawało i wynosiło taki wiersz na
 * SAM SZCZYT listy „A→Z" — czyli w miejsce, gdzie użytkownik szuka litery „A".
 *
 * To zrównuje nas z backendem: `normalize_person_name_part`
 * (`services/candidate_identity_quarantine.py`) też sprowadza nazwisko do
 * [a-z0-9] i dlatego dopasowanie importu takiego wiersza NIE gubi — rozjazd
 * był wyłącznie po stronie sortowania.
 *
 * Przy okazji obsługuje sentynel serwera: `consultant_display_name` zwraca „—"
 * dla linii bez kandydata, a myślnik wypada przed każdą literą.
 */
function consultantSortKey(name: string | null | undefined): string {
  return foldText(name ?? "")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Porównanie dwóch nazwisk konsultantów, na kluczach już przepuszczonych przez
 * `foldText`.
 *
 * Brak nazwiska sortuje się na KOŃCU w obu kierunkach — dokładnie tak, jak
 * `compareNullable` traktuje brakujące kwoty. Gdyby pusty klucz zachowywał się
 * jak zwykły ciąg, wiersz bez konsultanta otwierałby listę „A→Z", czyli miejsce,
 * w którym użytkownik spodziewa się realnego „A".
 */
function compareConsultantKey(
  left: string,
  right: string,
  direction: "asc" | "desc",
): number {
  if (!left && !right) return 0;
  if (!left) return 1;
  if (!right) return -1;
  const result = left.localeCompare(right, "pl");
  return direction === "asc" ? result : -result;
}

/**
 * Alfabetycznie pierwszy konsultant grupy.
 *
 * Grupa zamówień ma N linii, więc sortowanie „po konsultancie" musi wybrać
 * jedną z nich. Ten sam klucz obsługuje OBA kierunki — dla „Z→A" odwracamy
 * porównanie, a nie wybór linii. Wybieranie ostatniego konsultanta przy „Z→A"
 * dałoby listę, która nie jest odwrotnością „A→Z": grupa [Abacki, Zenon]
 * stałaby wtedy na czele obu porządków.
 */
function groupConsultantKey(group: OrderGroupRead): string {
  let best = "";
  for (const line of group.lines) {
    const key = consultantSortKey(line.consultant_name);
    if (!key) continue;
    if (!best || key.localeCompare(best, "pl") < 0) best = key;
  }
  return best;
}

function consultantDirection(sort: OrderSort): "asc" | "desc" {
  return sort.endsWith("_asc") ? "asc" : "desc";
}

export function filterAndSortOrderGroups(
  groups: readonly OrderGroupRead[],
  query: string,
  filters: OrderListFilters,
  todayIso = localTodayIso(),
): OrderGroupRead[] {
  const endingDays = Number.isFinite(filters.endingDays)
    ? Math.max(0, Math.trunc(filters.endingDays))
    : 30;
  const filtered = groups.filter((group) => {
    if (!orderGroupMatchesQuery(group, query)) return false;
    if (
      !matchesDateRange(
        dateOnly(group.start_date),
        filters.startFrom,
        filters.startTo,
      )
    ) {
      return false;
    }
    if (
      !matchesDateRange(
        dateOnly(group.end_date),
        filters.endFrom,
        filters.endTo,
      )
    ) {
      return false;
    }
    const metrics = orderGroupMetrics(group);
    if (filters.nearBudget && (metrics.budgetUsage ?? -Infinity) < 0.8) {
      return false;
    }
    if (
      filters.endingSoon &&
      !isEndingSoon(dateOnly(group.end_date), endingDays, todayIso)
    ) {
      return false;
    }
    return true;
  });

  return filtered.sort((left, right) => {
    if (filters.sort === "created_desc") return compareCreated(left, right);
    if (filters.sort.startsWith("consultant_")) {
      return (
        compareConsultantKey(
          groupConsultantKey(left),
          groupConsultantKey(right),
          consultantDirection(filters.sort),
        ) || compareCreated(left, right)
      );
    }
    const leftMetrics = orderGroupMetrics(left);
    const rightMetrics = orderGroupMetrics(right);
    const direction = filters.sort.endsWith("_asc") ? "asc" : "desc";
    const metric = filters.sort.startsWith("md_")
      ? compareNullable(leftMetrics.totalMd, rightMetrics.totalMd, direction)
      : filters.sort.startsWith("cost_")
        ? compareNullable(
            leftMetrics.averageCost,
            rightMetrics.averageCost,
            direction,
          )
        : compareNullable(
            leftMetrics.averageRevenue,
            rightMetrics.averageRevenue,
            direction,
          );
    return metric || compareCreated(left, right);
  });
}

export function flattenOrderGroupIds(
  groups: readonly OrderGroupRead[],
): number[] {
  return groups.flatMap((group) => [
    group.id,
    ...flattenOrderGroupIds(group.future_orders),
  ]);
}

function primaryOrder(
  contractor: ContractWithOrdersRead,
  todayIso: string,
): ClientOrderRead | null {
  const usable = contractor.orders.filter((order) => order.status !== "cancelled");
  const started = usable
    .filter((order) => !dateOnly(order.start_date) || dateOnly(order.start_date)! <= todayIso)
    .sort((left, right) =>
      (dateOnly(right.start_date) ?? "").localeCompare(
        dateOnly(left.start_date) ?? "",
      ),
    );
  if (started.length > 0) return started[0];
  return (
    usable
      .filter((order) => (dateOnly(order.start_date) ?? "") > todayIso)
      .sort((left, right) =>
        (dateOnly(left.start_date) ?? "").localeCompare(
          dateOnly(right.start_date) ?? "",
        ),
      )[0] ?? null
  );
}

export function contractorMatchesQuery(
  contractor: ContractWithOrdersRead,
  query: string,
): boolean {
  const foldedQuery = foldText(query.trim());
  if (!foldedQuery) return true;
  return (
    consultantMatchesQuery(contractor.candidate_name, query) ||
    contractor.orders.some((order) =>
      foldText(order.title).includes(foldedQuery),
    )
  );
}

export function filterAndSortContractors(
  contractors: readonly ContractWithOrdersRead[],
  query: string,
  filters: OrderListFilters,
  todayIso = localTodayIso(),
): ContractWithOrdersRead[] {
  const endingDays = Number.isFinite(filters.endingDays)
    ? Math.max(0, Math.trunc(filters.endingDays))
    : 30;
  const filtered = contractors.filter((contractor) => {
    if (!contractorMatchesQuery(contractor, query)) return false;
    const order = primaryOrder(contractor, todayIso);
    if (
      !matchesDateRange(
        dateOnly(order?.start_date),
        filters.startFrom,
        filters.startTo,
      )
    ) {
      return false;
    }
    if (
      !matchesDateRange(
        dateOnly(order?.end_date),
        filters.endFrom,
        filters.endTo,
      )
    ) {
      return false;
    }
    return (
      !filters.endingSoon ||
      isEndingSoon(dateOnly(order?.end_date), endingDays, todayIso)
    );
  });

  return filtered.sort((left, right) => {
    const leftOrder = primaryOrder(left, todayIso);
    const rightOrder = primaryOrder(right, todayIso);
    if (filters.sort === "created_desc") {
      return (
        (rightOrder?.created_at ?? "").localeCompare(
          leftOrder?.created_at ?? "",
        ) || right.contract_id - left.contract_id
      );
    }
    if (filters.sort.startsWith("consultant_")) {
      return (
        compareConsultantKey(
          consultantSortKey(left.candidate_name),
          consultantSortKey(right.candidate_name),
          consultantDirection(filters.sort),
        ) || right.contract_id - left.contract_id
      );
    }
    const direction = filters.sort.endsWith("_asc") ? "asc" : "desc";
    const metric = filters.sort.startsWith("cost_")
      ? compareNullable(left.rate_candidate, right.rate_candidate, direction)
      : compareNullable(
          leftOrder?.rate_client ?? null,
          rightOrder?.rate_client ?? null,
          direction,
        );
    return metric || right.contract_id - left.contract_id;
  });
}

/**
 * Eksport po nazwie konsultanta obejmuje wszystkie jego zamówienia. Gdy
 * trafienie pochodzi wyłącznie z numeru, wysyłamy tylko pasujące numery.
 */
export function visibleLegacyOrderIds(
  contractors: readonly ContractWithOrdersRead[],
  query: string,
): number[] {
  const foldedQuery = foldText(query.trim());
  return contractors.flatMap((contractor) => {
    if (!foldedQuery || consultantMatchesQuery(contractor.candidate_name, query)) {
      return contractor.orders.map((order) => order.id);
    }
    return contractor.orders
      .filter((order) => foldText(order.title).includes(foldedQuery))
      .map((order) => order.id);
  });
}
