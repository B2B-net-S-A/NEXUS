import { foldText } from "@/lib/contract-client-filter";
import type {
  ClientOrderRead,
  ContractWithOrdersRead,
} from "@/lib/api/dlPortal";
import type { OrderGroupRead, OrderLineRead } from "@/lib/api/orderGroups";

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

/** Wspólny zestaw filtrów statusu dla połączonej listy grup i zamówień. */
export type UnifiedOrderPill =
  "all" | "active" | "ending_30d" | "completed" | "exhausted" | "draft" | "cancelled";

/** Kolejność biznesowa sekcji na profilu klienta. */
export const ORDER_TYPE_ORDER = ["md", "cost", "periodic"] as const;
export type EffectiveOrderType = (typeof ORDER_TYPE_ORDER)[number];
/** Znaczenie trwałego markera `ClientOrder.order_type=NULL` u danego klienta. */
export type LegacyClientOrderType = "periodic" | "md";

/** Jedna pozycja wspólnej listy — domena pozostaje jawna, ale sort jest wspólny. */
export type UnifiedOrderListItem =
  | { kind: "group"; group: OrderGroupRead }
  | { kind: "contractor"; contractor: ContractWithOrdersRead };

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
    group.future_orders.some((future) => orderGroupMatchesQuery(future, query))
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

/**
 * „Zakończone" na karcie zamówienia — najnowsze zejścia na górze.
 *
 * Sekcja odpowiada na pytanie „kto ostatnio zszedł z tego zamówienia", więc
 * alfabet (jak w aktywnej obsadzie) stawiałby sprzed roku obok wczorajszego.
 * Data zejścia to `cooperation_ended_on` (zdarzenie, sprawa offboardingu albo
 * zakończona umowa), a w jej braku własna `end_date` linii. Wiersz bez żadnej
 * daty — usunięty z zamówienia albo anulowany — idzie na koniec: nie ma czym
 * go umieścić w czasie, a wciśnięty na górę udawałby najświeższy.
 */
export function sortOrderLinesByEnd(
  lines: readonly OrderLineRead[],
): OrderLineRead[] {
  const endOf = (line: OrderLineRead): string | null =>
    dateOnly(line.cooperation_ended_on) ?? dateOnly(line.end_date);
  return [...lines].sort((left, right) => {
    const a = endOf(left);
    const b = endOf(right);
    if (a !== b) {
      if (a === null) return 1;
      if (b === null) return -1;
      return a < b ? 1 : -1;
    }
    return foldText(left.consultant_name).localeCompare(
      foldText(right.consultant_name),
      "pl",
    );
  });
}

// Zapas dla odpowiedzi bez pola `uses_shared_md_pool` (harnessy, stare mocki).
// Regułę liczy serwer (`shared_md_orders.uses_shared_md_pool`, audyt
// 24.09.2026, S13) — ta lista nie jest źródłem prawdy.
const SHARED_MD_POOL_CLIENT_IDS = new Set([155, 38339]);

export function clientUsesSharedMdPool(clientId: number): boolean {
  return SHARED_MD_POOL_CLIENT_IDS.has(clientId);
}

/** Deliberate shared-MD variant limited to Lotte Wedel and Cyfrowy Polsat. */
export function usesSharedMdPool(
  group: Pick<
    OrderGroupRead,
    "client_id" | "is_md_budget_based" | "md_budget_mode"
  > &
    Partial<Pick<OrderGroupRead, "uses_shared_md_pool">>,
): boolean {
  if (typeof group.uses_shared_md_pool === "boolean")
    return group.uses_shared_md_pool;
  if (group.md_budget_mode != null)
    return group.md_budget_mode === "shared" && group.is_md_budget_based;
  return group.is_md_budget_based && clientUsesSharedMdPool(group.client_id);
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
  const sharedMd = usesSharedMdPool(group);
  const totalMd = sharedMd
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
    sharedMd &&
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

function normalizedEndingDays(days: number): number {
  return Number.isFinite(days) ? Math.max(0, Math.trunc(days)) : 30;
}

/**
 * Czy zamówienie trwa (albo dopiero się zacznie) po `endedOn` — czyli czy jest
 * zaplanowaną kontynuacją zamówienia, które kończy się tego dnia.
 *
 * Lustro backendowego `covers_after` (`services/order_facts.py`), z którego
 * liczą się „Kończące się zamówienia" w Finansach — oba ekrany mają mówić to
 * samo o tym samym zamówieniu. Szkic się liczy (ticket 09.2026: niedokończone
 * przyszłe zamówienie to też zaplanowana kontynuacja). Zamówienie bez daty
 * końca liczy się, dopóki nie jest zamknięte — zamknięty wiersz bez daty to
 * historia, nie następca.
 */
function coversAfter(
  status: string,
  endDate: string | null | undefined,
  endedOn: string,
  todayIso: string,
  revenue?: number | null,
): boolean {
  if (status === "cancelled" || status === "exhausted") return false;
  const end = dateOnly(endDate);
  // Porzucony szkic (bez końca i bez stawki przychodowej — np. szkic z podpisu
  // umowy) nie jest kontynuacją (audyt 24.09.2026, W2).
  if (
    status === "draft" &&
    end === null &&
    revenue !== undefined &&
    (revenue === null || revenue <= 0)
  ) {
    return false;
  }
  if (end === null) return status !== "completed";
  // Zakończone z datą w przyszłości nikt już nie wykona (N2).
  if (status === "completed" && end > todayIso) return false;
  return end > endedOn;
}

/**
 * Zamówienie kontraktora, które kończy się w ciągu `days` dni i NIE ma
 * dodanego zamówienia, które przejmuje po nim okres.
 *
 * To jest reguła zakładki „Kończące się" (ticket 09.2026). Do tej zmiany karta
 * trafiała tam po `days_to_latest_end`, a filtr „kończy się w ciągu N dni" po
 * zamówieniu bieżącym — zamówienie z już dodaną kontynuacją wisiało na liście,
 * choć nie wymaga działania. Ocena idzie po KAŻDYM zamówieniu niezależnie:
 * przyszłe zamówienie, które samo zbliża się do końca (i nie ma następnego),
 * też się kwalifikuje. Z kilku zwraca to, które kończy się najwcześniej.
 */
export function endingOrderWithoutSuccessor<
  T extends Pick<ClientOrderRead, "id" | "status" | "start_date" | "end_date"> &
    Partial<Pick<ClientOrderRead, "rate_client">>,
>(orders: readonly T[], days: number, todayIso = localTodayIso()): T | null {
  const horizon = normalizedEndingDays(days);
  let found: T | null = null;
  for (const order of orders) {
    // Lustro serwera (`ENDING_ORDER_STATUSES`): szkic nie jest zamówieniem.
    if (order.status !== "active" && order.status !== "paused") continue;
    const end = dateOnly(order.end_date);
    if (!isEndingSoon(end, horizon, todayIso)) continue;
    const continued = orders.some(
      (other) =>
        other.id !== order.id &&
        coversAfter(
          other.status,
          other.end_date,
          end!,
          todayIso,
          "rate_client" in other ? (other.rate_client ?? null) : undefined,
        ),
    );
    if (continued) continue;
    if (found === null || end! < dateOnly(found.end_date)!) found = order;
  }
  return found;
}

/** „dziś" / „za 1 dzień" / „za N dni" — do plakietek końca zamówienia. */
export function endsInPhrase(days: number | null): string {
  if (days === null) return "";
  if (days <= 0) return "dziś";
  return days === 1 ? "za 1 dzień" : `za ${days} dni`;
}

/** Dni do końca zamówienia z `endingOrderWithoutSuccessor` (0 = dziś). */
export function daysUntil(endDate: string | null, todayIso = localTodayIso()): number | null {
  if (!endDate) return null;
  const end = new Date(`${endDate.slice(0, 10)}T12:00:00`);
  const today = new Date(`${todayIso}T12:00:00`);
  return Math.round((end.getTime() - today.getTime()) / 86_400_000);
}

/**
 * Rodziny zamówień MD/kosztowych: łańcuch przedłużeń po `predecessor_group_id`.
 *
 * Lista grup przychodzi z serwera z przedłużeniami ZAGNIEŻDŻONYMI w
 * `future_orders` karty poprzednika, więc najpierw spłaszczamy całe drzewo —
 * inaczej następca nie byłby widoczny dla swojego poprzednika. Klucz rodziny
 * to korzeń łańcucha, jak `_group_family_root_id` na backendzie.
 */
export interface OrderGroupFamilies {
  membersByGroupId: Map<number, OrderGroupRead[]>;
}

function flattenOrderGroups(groups: readonly OrderGroupRead[]): OrderGroupRead[] {
  return groups.flatMap((group) => [
    group,
    ...flattenOrderGroups(group.future_orders ?? []),
  ]);
}

export function buildOrderGroupFamilies(
  groups: readonly OrderGroupRead[],
): OrderGroupFamilies {
  const all = flattenOrderGroups(groups);
  const byId = new Map(all.map((group) => [group.id, group]));
  const rootOf = (group: OrderGroupRead): number => {
    let current = group;
    const seen = new Set([group.id]);
    while (
      current.predecessor_group_id !== null &&
      byId.has(current.predecessor_group_id) &&
      !seen.has(current.predecessor_group_id)
    ) {
      current = byId.get(current.predecessor_group_id)!;
      seen.add(current.id);
    }
    return current.id;
  };
  const byRoot = new Map<number, OrderGroupRead[]>();
  const rootByGroupId = new Map<number, number>();
  for (const group of byId.values()) {
    const root = rootOf(group);
    rootByGroupId.set(group.id, root);
    byRoot.set(root, [...(byRoot.get(root) ?? []), group]);
  }
  const membersByGroupId = new Map<number, OrderGroupRead[]>();
  for (const [groupId, root] of rootByGroupId) {
    membersByGroupId.set(groupId, byRoot.get(root) ?? []);
  }
  return { membersByGroupId };
}

const GROUP_ENDING_STATUSES = new Set(["draft", "active", "scheduled"]);

/**
 * Zamówienie MD/kosztowe z drzewa karty (ona sama + zagnieżdżone przedłużenia),
 * które kończy się w ciągu `days` dni bez przedłużenia po sobie. Ta sama reguła
 * co `endingOrderWithoutSuccessor`, z rodziną przedłużeń zamiast kontraktu.
 */
export function endingGroupWithoutSuccessor(
  group: OrderGroupRead,
  days: number,
  todayIso = localTodayIso(),
  families: OrderGroupFamilies = buildOrderGroupFamilies([group]),
): OrderGroupRead | null {
  const horizon = normalizedEndingDays(days);
  let found: OrderGroupRead | null = null;
  for (const candidate of flattenOrderGroups([group])) {
    if (!GROUP_ENDING_STATUSES.has(candidate.status)) continue;
    const end = dateOnly(candidate.end_date);
    if (!isEndingSoon(end, horizon, todayIso)) continue;
    const family = families.membersByGroupId.get(candidate.id) ?? [candidate];
    const continued = family.some(
      (other) =>
        other.id !== candidate.id &&
        coversAfter(other.status, other.end_date, end!, todayIso),
    );
    if (continued) continue;
    if (found === null || end! < dateOnly(found.end_date)!) found = candidate;
  }
  return found;
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
  return right.created_at.localeCompare(left.created_at) || right.id - left.id;
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
  families: OrderGroupFamilies = buildOrderGroupFamilies(groups),
): OrderGroupRead[] {
  const endingDays = normalizedEndingDays(filters.endingDays);
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
      !endingGroupWithoutSuccessor(group, endingDays, todayIso, families)
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

/** Id kontraktów zmaterializowanych już jako linie grupy, także następcy. */
export function orderGroupContractIds(
  groups: readonly OrderGroupRead[],
): Set<number> {
  const result = new Set<number>();
  const visit = (group: OrderGroupRead) => {
    for (const line of group.lines) result.add(line.contract_id);
    for (const future of group.future_orders) visit(future);
  };
  for (const group of groups) visit(group);
  return result;
}

/**
 * Ukryj kartę kontraktora, którą reprezentuje już linia zamówienia grupowego.
 *
 * Warunkiem jest brak ŻYWEGO zamówienia samodzielnego, a nie brak zamówień
 * w ogóle. Osoba obsadzona na zamówieniu MD, której został po historii wyłącznie
 * wiersz zakończony albo anulowany (np. duplikat sprzątnięty przez migrację
 * 0262), pokazywała się na liście DWA razy: raz jako linia grupy, raz jako
 * własna karta z martwym zamówieniem. Kontraktor z realnym, otwartym
 * zamówieniem okresowym obok linii MD nadal ma obie pozycje — to dwa różne
 * zaangażowania i właśnie o ich rozdzielenie chodzi.
 *
 * Kontrakt bez żadnej linii grupowej zostaje niezależnie od stanu zamówień —
 * to prawidłowy workflow draftu do uzupełnienia.
 */
export function filterMaterializedContractorShells(
  contractors: readonly ContractWithOrdersRead[],
  groups: readonly OrderGroupRead[],
  todayIso = localTodayIso(),
): ContractWithOrdersRead[] {
  const groupedContractIds = orderGroupContractIds(groups);
  return contractors.filter(
    (contractor) =>
      !groupedContractIds.has(contractor.contract_id) ||
      contractor.orders.some(
        (order) =>
          order.status !== "completed" &&
          order.status !== "cancelled" &&
          (dateOnly(order.end_date) ?? "9999-12-31") >= todayIso,
      ),
  );
}

/** Historyczne rekordy bez jawnego typu zachowują dotychczasową semantykę. */
export function effectiveGroupOrderType(
  group: Pick<OrderGroupRead, "order_type" | "is_cost_based">,
): EffectiveOrderType {
  return group.order_type ?? (group.is_cost_based ? "cost" : "md");
}

/** `NULL` zachowuje marker legacy; jego znaczenie wynika z konfiguracji klienta. */
export function effectiveClientOrderType(
  order: Pick<ClientOrderRead, "order_type"> | null | undefined,
  legacyNullOrderType: LegacyClientOrderType = "periodic",
): EffectiveOrderType {
  return order?.order_type ?? legacyNullOrderType;
}

export function primaryOrder(
  contractor: ContractWithOrdersRead,
  todayIso: string,
): ClientOrderRead | null {
  const usable = contractor.orders.filter(
    (order) => order.status !== "cancelled",
  );
  const started = usable
    .filter(
      (order) =>
        !dateOnly(order.start_date) || dateOnly(order.start_date)! <= todayIso,
    )
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

/**
 * Zamówienie reprezentujące kartę kontraktora.
 *
 * Bieżące/przyszłe zamówienie ma pierwszeństwo. Jeżeli wszystkie wpisy
 * są anulowane, karta nadal nie jest pustym shellem — jej typ bierze się z
 * najpóźniejszego wpisu historii, zamiast z klientowego fallbacku.
 */
export function representativeOrder(
  contractor: ContractWithOrdersRead,
  todayIso = localTodayIso(),
): ClientOrderRead | null {
  const primary = primaryOrder(contractor, todayIso);
  if (primary) return primary;
  return (
    [...contractor.orders].sort((left, right) =>
      (dateOnly(right.start_date) ?? "").localeCompare(
        dateOnly(left.start_date) ?? "",
      ) ||
      right.created_at.localeCompare(left.created_at) ||
      right.id - left.id,
    )[0] ?? null
  );
}

export function contractorOrderType(
  contractor: ContractWithOrdersRead,
  legacyNullOrderType: LegacyClientOrderType = "periodic",
  todayIso = localTodayIso(),
): EffectiveOrderType {
  return effectiveClientOrderType(
    representativeOrder(contractor, todayIso),
    legacyNullOrderType,
  );
}

function numericOrderValue(
  value: string | number | null | undefined,
): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function unifiedCreatedAt(
  item: UnifiedOrderListItem,
  todayIso: string,
): string {
  return item.kind === "group"
    ? item.group.created_at
    : (representativeOrder(item.contractor, todayIso)?.created_at ?? "");
}

function unifiedStableId(item: UnifiedOrderListItem): number {
  return item.kind === "group" ? item.group.id : item.contractor.contract_id;
}

function compareUnifiedCreated(
  left: UnifiedOrderListItem,
  right: UnifiedOrderListItem,
  todayIso: string,
): number {
  return (
    unifiedCreatedAt(right, todayIso).localeCompare(
      unifiedCreatedAt(left, todayIso),
    ) ||
    unifiedStableId(right) - unifiedStableId(left) ||
    left.kind.localeCompare(right.kind)
  );
}

function unifiedConsultantKey(item: UnifiedOrderListItem): string {
  return item.kind === "group"
    ? groupConsultantKey(item.group)
    : consultantSortKey(item.contractor.candidate_name);
}

function unifiedMetric(
  item: UnifiedOrderListItem,
  sort: OrderSort,
  todayIso: string,
): number | null {
  if (item.kind === "group") {
    const metrics = orderGroupMetrics(item.group);
    if (sort.startsWith("md_")) return metrics.totalMd;
    if (sort.startsWith("cost_")) return metrics.averageCost;
    return metrics.averageRevenue;
  }
  const order = representativeOrder(item.contractor, todayIso);
  if (sort.startsWith("md_")) return numericOrderValue(order?.md_quantity);
  if (sort.startsWith("cost_")) return item.contractor.rate_candidate;
  return order?.rate_client ?? null;
}

/**
 * Sortuje grupy i karty kontraktorów jednym comparatorem. Kolejność typów
 * jest nakładana przez wywołującego; ta funkcja porządkuje pozycje wewnątrz
 * jednej sekcji i zachowuje braki kwot/nazwisk na końcu w obu kierunkach.
 */
export function sortUnifiedOrderItems(
  items: readonly UnifiedOrderListItem[],
  sort: OrderSort,
  todayIso = localTodayIso(),
): UnifiedOrderListItem[] {
  return [...items].sort((left, right) => {
    if (sort === "created_desc") {
      return compareUnifiedCreated(left, right, todayIso);
    }
    if (sort.startsWith("consultant_")) {
      return (
        compareConsultantKey(
          unifiedConsultantKey(left),
          unifiedConsultantKey(right),
          consultantDirection(sort),
        ) || compareUnifiedCreated(left, right, todayIso)
      );
    }
    return (
      compareNullable(
        unifiedMetric(left, sort, todayIso),
        unifiedMetric(right, sort, todayIso),
        sort.endsWith("_asc") ? "asc" : "desc",
      ) || compareUnifiedCreated(left, right, todayIso)
    );
  });
}

/** Predykaty są wspólne dla liczników i zawartości pigułek. */
/**
 * Umowa ZAMKNIĘTA = status końcowy ORAZ data końca, która już minęła.
 *
 * Reguła zakładki „Zakończeni" (09.2026): o przynależności decyduje wyłącznie
 * umowa z modułu Kontrakty — status i data zakończenia — nigdy sam upływ
 * okresu zamówienia. Do daty końca włącznie osoba pracuje, więc jest
 * w „Aktywni"; od dnia następnego przechodzi do „Zakończonych". Umowa bez daty
 * (bezterminowa) nie ma czego minąć — „ended" bez daty to zaszłość danych,
 * którą backend leczy na `active`, nie zakończenie współpracy.
 */
export function contractClosed(
  contractor: Pick<ContractWithOrdersRead, "contract_status" | "contract_end_date">,
  todayIso = localTodayIso(),
): boolean {
  if (contractor.contract_status !== "ended") return false;
  const end = dateOnly(contractor.contract_end_date);
  return end !== null && end < todayIso;
}

/**
 * Kontraktor bez zamówienia, które obejmuje dziś albo dopiero się zacznie:
 * okres zamówienia minął, a umowa trwa. To powód do dopisku „Brak aktywnego
 * zamówienia" przy osobie w „Aktywnych" — NIE do przeniesienia jej do
 * „Zakończonych" (patrz `contractClosed`).
 */
export function lacksCurrentOrder(
  contractor: Pick<ContractWithOrdersRead, "orders">,
  todayIso = localTodayIso(),
): boolean {
  return !contractor.orders.some((order) => {
    if (order.status === "completed" || order.status === "cancelled") return false;
    const end = dateOnly(order.end_date);
    return end === null || end >= todayIso;
  });
}

const LIVE_ORDER_STATUSES = new Set(["active", "paused", "draft"]);

export function contractorMatchesPill(
  contractor: ContractWithOrdersRead,
  pill: UnifiedOrderPill,
  todayIso = localTodayIso(),
): boolean {
  if (pill === "all") return true;
  if (pill === "active") {
    // Karta szkicu (żywy kontrakt bez zamówień poza szkicami) nie jest aktywną
    // obsadą — stoi w „Draft" (ticket 09.2026, sekcja „Szkice").
    if (contractor.draft_card) return false;
    return (
      contractor.contract_status === "active" ||
      contractor.contract_status === "ending" ||
      ((contractor.contract_status === "draft" ||
        contractor.contract_status === "ready_for_signature") &&
        contractor.orders.some((order) => order.status === "active")) ||
      // Umowa z datą końca dziś albo później: do tego dnia włącznie osoba
      // pracuje, więc jest tu, a nie w „Zakończonych".
      (contractor.contract_status === "ended" &&
        !contractClosed(contractor, todayIso))
    );
  }
  if (pill === "ending_30d") {
    return endingWithoutSuccessorOrderId(contractor, todayIso) !== null;
  }
  if (pill === "completed") {
    return contractClosed(contractor, todayIso);
  }
  if (pill === "draft") {
    // Umowa „gotowa do podpisu" to też szkic współpracy — do 24.09.2026 nie
    // trafiała do żadnej pigułki (N9).
    const draftContract =
      contractor.contract_status === "draft" ||
      contractor.contract_status === "ready_for_signature";
    return (
      contractor.draft_card === true ||
      contractor.orders.some((order) => order.status === "draft") ||
      (draftContract &&
        !contractor.orders.some((order) => order.status === "active"))
    );
  }
  if (pill === "cancelled") {
    // Anulowane zamówienie okresowe (N9) — do 24.09.2026 pigułka łapała
    // wyłącznie grupy MD/kosztowe. Osoba z żywym zamówieniem (aktywne,
    // wstrzymane, szkic) pracuje — stary anulowany szkic nie przenosi jej do
    // „Anulowanych" (audyt 24.09.2026, M4).
    return (
      contractor.orders.some((order) => order.status === "cancelled") &&
      !contractor.orders.some((order) => LIVE_ORDER_STATUSES.has(order.status))
    );
  }
  return false;
}

/**
 * Zamówienie kontraktora, które kończy się w 30 dni BEZ kontynuacji.
 *
 * Regułę liczy serwer (`services/order_continuation`, audyt 24.09.2026, S1) —
 * ta sama co panel „Moi klienci", dzwonek i kafelek pulpitu. Zapas lokalny
 * wyłącznie dla odpowiedzi bez pola (harnessy, starsze mocki).
 */
export function endingWithoutSuccessorOrderId(
  contractor: ContractWithOrdersRead,
  todayIso = localTodayIso(),
): number | null {
  if (contractor.ending_without_successor_order_id !== undefined) {
    return contractor.ending_without_successor_order_id ?? null;
  }
  return endingOrderWithoutSuccessor(contractor.orders, 30, todayIso)?.id ?? null;
}

/**
 * Czy najbliższe zamówienie okresowe BEZ kontynuacji kończy się w `days` dni.
 *
 * Regułę liczy serwer (`next_ending_without_successor_days`, bez horyzontu) —
 * ta sama co pigułka „Bez kontynuacji 30d" i plakietka. Lokalne liczenie
 * czytało `rate_client`, który rolom bez kwot serwer zeruje, więc szkic-
 * następca ze stawką wyglądał jak porzucony (audyt 24.09.2026, M6). Zapas
 * lokalny wyłącznie dla odpowiedzi bez pola (harnessy, starsze mocki).
 */
export function endsWithoutSuccessorWithin(
  contractor: ContractWithOrdersRead,
  days: number,
  todayIso = localTodayIso(),
): boolean {
  const horizon = normalizedEndingDays(days);
  if (contractor.next_ending_without_successor_days !== undefined) {
    const left = contractor.next_ending_without_successor_days;
    return left !== null && left <= horizon;
  }
  return endingOrderWithoutSuccessor(contractor.orders, horizon, todayIso) !== null;
}

export function orderGroupMatchesPill(
  group: OrderGroupRead,
  pill: UnifiedOrderPill,
  todayIso = localTodayIso(),
  families?: OrderGroupFamilies,
): boolean {
  if (pill === "all") return true;
  if (pill === "draft") return group.status === "draft";
  if (pill === "active") return group.status === "active";
  if (pill === "completed") return group.status === "completed";
  if (pill === "exhausted") return group.status === "exhausted";
  if (pill === "cancelled") return group.status === "cancelled";
  if (pill === "ending_30d") {
    return endingGroupWithoutSuccessor(group, 30, todayIso, families) !== null;
  }
  // Szkice grupowe pochodzą z tej samej populacji ClientOrder co `/orders`.
  // Liczymy/renderujemy je wyłącznie po stronie kontraktorów, bez duplikatu.
  return false;
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
  const endingDays = normalizedEndingDays(filters.endingDays);
  const filtered = contractors.filter((contractor) => {
    if (!contractorMatchesQuery(contractor, query)) return false;
    const order = representativeOrder(contractor, todayIso);
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
      endsWithoutSuccessorWithin(contractor, endingDays, todayIso)
    );
  });

  return filtered.sort((left, right) => {
    const leftOrder = representativeOrder(left, todayIso);
    const rightOrder = representativeOrder(right, todayIso);
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
    const metric = filters.sort.startsWith("md_")
      ? compareNullable(null, null, direction)
      : filters.sort.startsWith("cost_")
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
 * Czy zamówienie OBOWIĄZUJE w danym dniu.
 *
 * Brak daty końca = bezterminowo; brak daty startu = już obowiązuje (rekordy
 * historyczne nagminnie nie mają startu, a ich wykluczenie zabierałoby
 * z arkusza czyjąś realną współpracę). Zamówienie „kończące się" mieści się
 * w tej regule — dopóki data końca nie minęła, konsultant pracuje.
 */
export function isCurrentOrder(
  order: Pick<ClientOrderRead, "status" | "start_date" | "end_date">,
  todayIso = localTodayIso(),
): boolean {
  if (order.status === "completed" || order.status === "cancelled") return false;
  const start = dateOnly(order.start_date);
  if (start !== null && start > todayIso) return false;
  const end = dateOnly(order.end_date);
  return end === null || end >= todayIso;
}

/**
 * Zamówienia do eksportu: DOKŁADNIE JEDNO na konsultanta i tylko takie, które
 * obowiązuje dziś.
 *
 * Wcześniej szła tu cała historia kontraktora, więc ta sama osoba pojawiała się
 * w arkuszu tyle razy, ile zamówień przewinęło się przez jej kontrakt — razem
 * z zakończonymi i jeszcze nierozpoczętymi. Gdy trafienie wyszukiwania pochodzi
 * wyłącznie z numeru zamówienia, zawężamy dodatkowo do pasujących numerów:
 * inaczej eksport pokazywałby wiersz, którego na liście nie widać.
 */
export function visibleLegacyOrderIds(
  contractors: readonly ContractWithOrdersRead[],
  query: string,
  todayIso = localTodayIso(),
): number[] {
  const foldedQuery = foldText(query.trim());
  return contractors.flatMap((contractor) => {
    const matchesConsultant =
      !foldedQuery || consultantMatchesQuery(contractor.candidate_name, query);
    const candidates = contractor.orders.filter(
      (order) =>
        isCurrentOrder(order, todayIso) &&
        (matchesConsultant || foldText(order.title).includes(foldedQuery)),
    );
    if (candidates.length === 0) return [];
    // Kilka zamówień może obowiązywać jednocześnie (nakładające się okresy).
    // Bierzemy to o najpóźniejszym starcie — najnowsze warunki są tym, co
    // opisuje dzisiejszą współpracę.
    const [current] = [...candidates].sort((left, right) =>
      (dateOnly(right.start_date) ?? "").localeCompare(
        dateOnly(left.start_date) ?? "",
      ),
    );
    return [current.id];
  });
}

/** Cel deep linku z panelu „Moi klienci" (`?order=` / `?group=`). */
export type OrderFocusTarget =
  | { kind: "group"; groupId: number }
  | { kind: "contractor"; contractId: number; orderId: number; isDraft: boolean };

/**
 * Znajdź na liście zamówień klienta to, na co wskazuje link z powiadomienia.
 *
 * `groupId` — zamówienie MD/kosztowe (także zagnieżdżone przedłużenie).
 * `orderId` — linia takiej grupy (wtedy celem jest jej grupa) albo zamówienie
 * okresowe na karcie kontraktora. `null` = obiekt nie jest już widoczny na
 * liście (usunięty, anulowany, bez uprawnień) — wołający mówi o tym wprost,
 * zamiast po cichu zostawić użytkownika na górze zakładki.
 */
export function resolveOrderFocus(
  groups: readonly OrderGroupRead[],
  contractors: readonly ContractWithOrdersRead[],
  target: { orderId?: number | null; groupId?: number | null },
): OrderFocusTarget | null {
  if (target.groupId && flattenOrderGroupIds(groups).includes(target.groupId)) {
    return { kind: "group", groupId: target.groupId };
  }
  const orderId = target.orderId;
  if (!orderId) return null;
  const visit = (group: OrderGroupRead): number | null => {
    if (group.lines.some((line) => line.id === orderId)) return group.id;
    for (const future of group.future_orders) {
      const found = visit(future);
      if (found !== null) return found;
    }
    return null;
  };
  for (const group of groups) {
    const found = visit(group);
    if (found !== null) return { kind: "group", groupId: found };
  }
  for (const contractor of contractors) {
    const order = contractor.orders.find((item) => item.id === orderId);
    if (order) {
      return {
        kind: "contractor",
        contractId: contractor.contract_id,
        orderId,
        isDraft: order.status === "draft",
      };
    }
  }
  return null;
}
