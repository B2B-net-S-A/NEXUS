/**
 * Logika wspólnej tablicy „Sprawy” + „Opieka · Do zrobienia” (22.10.2026) —
 * bez Reacta, z testami (`__tests__/work-board-model.test.ts`).
 *
 * Na tablicy stoją dwa rodzaje kart: sprawy administracja@ (`GET /api/cases`,
 * kolumna = status) i karty opieki (`GET /api/care/board`, kolumna = stan
 * tablicy). Kolumny są te same: Nowa · W toku · Czeka na kogoś · Zrobione.
 * Ruch karty opieki na „Zrobione” nie zmienia stanu — otwiera okno zapisu
 * (rozmowa, opinia), decyzję zamyka, popyt rozstrzyga oknem z menedżerem.
 */

import type { CaseArea, CaseCard, CaseStatus } from "@/lib/api/admin-cases";
import type { CareBoardCard, CareBoardColumn, CareBoardKind } from "@/lib/api/care-board";

import { dueBadge, type DueTone } from "../admin-cases/case-format";

export type WorkScope = "cases" | "care";
export type WorkColumn = "new" | "in_progress" | "waiting" | "done";
export type WorkView = "board" | "list";
/** Obszar w chipach: obszar sprawy albo „Opieka” (karty opieki). */
export type WorkArea = CaseArea | "care";

export const OPEN_WORK_COLUMNS: readonly WorkColumn[] = ["new", "in_progress", "waiting"];
export const WORK_COLUMNS: readonly WorkColumn[] = [...OPEN_WORK_COLUMNS, "done"];

export const WORK_COLUMN_LABELS: Record<WorkColumn, string> = {
  new: "Nowa",
  in_progress: "W toku",
  waiting: "Czeka na kogoś",
  done: "Zrobione",
};

/** Kart opieki w kolumnie przed „Pokaż wszystkie” (jak plan dni opieki: prod miał setki zaległych). */
export const CARE_COLUMN_VISIBLE = 8;

export type WorkItem =
  | { type: "case"; key: string; card: CaseCard }
  | { type: "care"; key: string; card: CareBoardCard };

export function caseItemKey(id: number): string {
  return `case:${id}`;
}

export function caseItem(card: CaseCard): WorkItem {
  return { type: "case", key: caseItemKey(card.id), card };
}

export function careItem(card: CareBoardCard): WorkItem {
  return { type: "care", key: card.key, card };
}

/** Kolumna karty; sprawa zamknięta nie stoi w żadnej (jest pod „Pokaż zamknięte”). */
export function itemColumn(item: WorkItem): WorkColumn | "closed" {
  if (item.type === "care") return item.card.column;
  return item.card.status;
}

export interface WorkFilters {
  area: WorkArea | null;
  week: boolean;
  unassigned: boolean;
  query: string;
}

function normalize(text: string): string {
  return text
    .toLocaleLowerCase("pl-PL")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/ł/g, "l");
}

/** Sprawy pokazujemy, o ile chip obszaru nie wskazuje „Opieki”. */
export function showsCases(filters: Pick<WorkFilters, "area">): boolean {
  return filters.area !== "care";
}

/** Karty opieki pokazujemy przy „Wszystkich obszarach” i przy chipie „Opieka”. */
export function showsCare(filters: Pick<WorkFilters, "area">): boolean {
  return filters.area === null || filters.area === "care";
}

/**
 * Filtry chipów dla kart opieki — liczy przeglądarka (odpowiedź tablicy opieki
 * jest kompletna, bez limitu jak lista spraw): „Na ten tydzień” = po terminie
 * albo z terminem do piątku, „Bez osoby” = bez opiekuna, szukanie po tytule,
 * podtytule, kliencie i notatce.
 */
export function filterCareCards(
  cards: readonly CareBoardCard[],
  filters: WorkFilters,
  weekEnd: string | undefined,
): CareBoardCard[] {
  if (!showsCare(filters)) return [];
  const query = normalize(filters.query.trim());
  return cards.filter((card) => {
    if (filters.unassigned && card.owner_user_id != null) return false;
    if (filters.week) {
      const inWeek = card.overdue_days > 0 || (!!card.due_on && !!weekEnd && card.due_on <= weekEnd);
      if (!inWeek) return false;
    }
    if (query) {
      const haystack = normalize(
        [card.title, card.subtitle, card.client_name, card.note_excerpt, card.owner_name]
          .filter(Boolean)
          .join(" "),
      );
      if (!haystack.includes(query)) return false;
    }
    return true;
  });
}

function careUrgency(a: CareBoardCard, b: CareBoardCard): number {
  return (
    b.overdue_days - a.overdue_days ||
    (a.due_on ?? "9999-12-31").localeCompare(b.due_on ?? "9999-12-31")
  );
}

export type WorkColumns = Record<WorkColumn | "closed", WorkItem[]>;

/**
 * Karty w kolumnach. Sprawy zostają w kolejności serwera (priorytet, termin);
 * karty opieki — od najbardziej zaległej. W „Opiece” (scope `care`) karty
 * opieki stoją nad sprawami, w „Sprawach” — pod nimi. `overrides` to ruchy
 * w toku (karta stoi już w nowej kolumnie, zanim serwer odpowie).
 */
export function buildColumns(
  items: readonly WorkItem[],
  options: { careFirst: boolean; overrides?: ReadonlyMap<string, WorkColumn> },
): WorkColumns {
  const columns: WorkColumns = { new: [], in_progress: [], waiting: [], done: [], closed: [] };
  const cases: WorkItem[] = [];
  const care: WorkItem[] = [];
  for (const item of items) (item.type === "case" ? cases : care).push(item);
  care.sort((a, b) =>
    a.type === "care" && b.type === "care" ? careUrgency(a.card, b.card) : 0,
  );
  const ordered = options.careFirst ? [...care, ...cases] : [...cases, ...care];
  for (const item of ordered) {
    const column = options.overrides?.get(item.key) ?? itemColumn(item);
    columns[column].push(item);
  }
  return columns;
}

/**
 * Kolumna z limitem kart opieki: sprawy zawsze wszystkie (lista ma limit
 * serwera), karty opieki — pierwsze `CARE_COLUMN_VISIBLE`, chyba że rozwinięte.
 */
export function visibleColumnItems(
  items: readonly WorkItem[],
  expanded: boolean,
): { visible: WorkItem[]; hiddenCare: number } {
  if (expanded) return { visible: [...items], hiddenCare: 0 };
  let care = 0;
  const visible: WorkItem[] = [];
  for (const item of items) {
    if (item.type === "care") {
      care += 1;
      if (care > CARE_COLUMN_VISIBLE) continue;
    }
    visible.push(item);
  }
  return { visible, hiddenCare: Math.max(0, care - CARE_COLUMN_VISIBLE) };
}

// ── Ruch karty ──────────────────────────────────────────────────────────────

export type MoveAction =
  | { type: "none" }
  | { type: "forbidden"; message: string }
  | { type: "case-status"; status: CaseStatus }
  | { type: "care-state"; column: CareBoardColumn; ask: "schedule" | "retry" | null }
  | { type: "open-conversation" }
  | { type: "open-feedback" }
  | { type: "close-decision" }
  | { type: "open-demand" };

const DONE_ACTION: Record<CareBoardKind, MoveAction> = {
  contact: { type: "open-conversation" },
  feedback: { type: "open-feedback" },
  decision: { type: "close-decision" },
  demand: { type: "open-demand" },
};

/**
 * Co zrobić, gdy karta trafia do kolumny `target` (przeciągnięcie albo menu
 * „Przenieś do…”). Sprawa: status z wersją karty, tylko obsługa skrzynki.
 * Karta opieki: „W toku” rozmowy i opinii pyta o dzień i godzinę, „Czeka”
 * o dzień ponownej próby, „Zrobione” otwiera okno zapisu.
 */
export function moveAction(
  item: WorkItem,
  target: WorkColumn,
  options: { canManageCases: boolean },
): MoveAction {
  if (itemColumn(item) === target) return { type: "none" };
  if (item.type === "case") {
    if (!options.canManageCases) {
      return {
        type: "forbidden",
        message: "Status sprawy zmienia obsługa skrzynki — możesz ją komentować.",
      };
    }
    return { type: "case-status", status: target };
  }
  if (target === "done") return DONE_ACTION[item.card.kind];
  if (target === "in_progress") {
    const ask = item.card.kind === "contact" || item.card.kind === "feedback" ? "schedule" : null;
    return { type: "care-state", column: "in_progress", ask };
  }
  if (target === "waiting") return { type: "care-state", column: "waiting", ask: "retry" };
  return { type: "care-state", column: "new", ask: null };
}

/** Jedyna akcja karty opieki. */
export const CARE_ACTION_LABELS: Record<CareBoardKind, string> = {
  contact: "Zapisz rozmowę",
  feedback: "Zapisz opinię",
  decision: "Przekaż do front office",
  demand: "Porozmawiaj z menedżerem",
};

/** Termin karty opieki w kolorze — ta sama reguła co termin sprawy. */
export function careDueBadge(
  card: Pick<CareBoardCard, "due_on" | "overdue_days">,
  today: string | undefined,
  weekEnd: string | undefined,
): { text: string; tone: DueTone } | null {
  if (!card.due_on) return null;
  return dueBadge(
    { due_on: card.due_on, overdue: card.overdue_days > 0, status: "new" },
    today,
    weekEnd,
  );
}

/** Adres karty opieki poza /care (Ludzie → Sprawy bez okien opieki). */
export function careCardHref(card: Pick<CareBoardCard, "contract_id" | "key">): string {
  return card.contract_id
    ? `/care?contract=${card.contract_id}`
    : `/care?card=${encodeURIComponent(card.key)}`;
}

// ── Widok „Lista” ───────────────────────────────────────────────────────────

export type ListGroupKey = "overdue" | "week" | "decisions" | "demand" | "later";

export const LIST_GROUP_LABELS: Record<ListGroupKey, string> = {
  overdue: "Po terminie",
  week: "Do piątku",
  decisions: "Decyzje",
  demand: "Popyt",
  later: "Później i bez terminu",
};

const LIST_ORDER: readonly ListGroupKey[] = ["overdue", "week", "decisions", "demand", "later"];

function dueOf(item: WorkItem): string | null {
  return item.card.due_on;
}

function overdueOf(item: WorkItem): boolean {
  return item.type === "case" ? item.card.overdue : item.card.overdue_days > 0;
}

export function listGroupOf(item: WorkItem, weekEnd: string | undefined): ListGroupKey {
  if (item.type === "care" && item.card.kind === "decision") return "decisions";
  if (item.type === "care" && item.card.kind === "demand") return "demand";
  if (overdueOf(item)) return "overdue";
  const due = dueOf(item);
  if (due && weekEnd && due <= weekEnd) return "week";
  return "later";
}

/**
 * Kolejka „Lista”: te same karty co na tablicy, bez zrobionych, w grupach
 * Po terminie · Do piątku · Decyzje · Popyt (i reszta). W grupie od
 * najwcześniejszego terminu; puste grupy znikają.
 */
export function listGroups(
  items: readonly WorkItem[],
  weekEnd: string | undefined,
): { key: ListGroupKey; label: string; items: WorkItem[] }[] {
  const buckets = new Map<ListGroupKey, WorkItem[]>();
  for (const item of items) {
    const column = itemColumn(item);
    if (column === "done" || column === "closed") continue;
    const key = listGroupOf(item, weekEnd);
    const bucket = buckets.get(key) ?? [];
    bucket.push(item);
    buckets.set(key, bucket);
  }
  return LIST_ORDER.filter((key) => buckets.has(key)).map((key) => ({
    key,
    label: LIST_GROUP_LABELS[key],
    items: [...(buckets.get(key) ?? [])].sort((a, b) =>
      (dueOf(a) ?? "9999-12-31").localeCompare(dueOf(b) ?? "9999-12-31"),
    ),
  }));
}

// ── Okienko „W toku” / „Czeka” ──────────────────────────────────────────────

/** Dzień i godzina z pól formularza (czas przeglądarki = czas firmy) → chwila ISO. */
export function scheduledIso(day: string, time: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || !/^\d{2}:\d{2}$/.test(time)) return null;
  const moment = new Date(`${day}T${time}:00`);
  return Number.isNaN(moment.getTime()) ? null : moment.toISOString();
}

/** Komunikat błędu okienka albo `null`, gdy można zapisać. */
export function validateBoardState(
  ask: "schedule" | "retry",
  input: { day: string; time: string },
  today: string,
): string | null {
  if (!input.day) return ask === "schedule" ? "Podaj dzień rozmowy." : "Podaj dzień ponownej próby.";
  if (ask === "schedule") {
    if (!input.time) return "Podaj godzinę.";
    if (!scheduledIso(input.day, input.time)) return "Nieprawidłowy dzień albo godzina.";
    return null;
  }
  // Dzień ≤ dziś wróciłby od razu do „Nowa” — serwer i tak przenosi kartę po tej dacie.
  if (input.day <= today) return "Ponowna próba najwcześniej jutro.";
  return null;
}

// ── Pamięć widoku (per osoba, localStorage w try/catch) ─────────────────────

function viewKey(scope: WorkScope, userId: number | null): string {
  return `nexus:work-board:view:${scope}:${userId ?? "anon"}`;
}

export function readViewPreference(
  scope: WorkScope,
  userId: number | null,
  fallback: WorkView,
): WorkView {
  try {
    const value = window.localStorage.getItem(viewKey(scope, userId));
    return value === "board" || value === "list" ? value : fallback;
  } catch {
    return fallback;
  }
}

export function writeViewPreference(scope: WorkScope, userId: number | null, view: WorkView): void {
  try {
    window.localStorage.setItem(viewKey(scope, userId), view);
  } catch {
    // Prywatne okno albo zablokowana pamięć — wybór działa do odświeżenia strony.
  }
}

// ── Klucze kart opieki ──────────────────────────────────────────────────────

/** `contact:plan:<id>` → id punktu planu (okno rozmowy zamyka ten punkt). */
export function planItemIdOf(key: string): number | null {
  const match = /^contact:plan:(\d+)$/.exec(key);
  return match ? Number(match[1]) : null;
}

/** `decision:<id>` → id wpisu „Do przepięcia”. */
export function decisionIdOf(key: string): number | null {
  const match = /^decision:(\d+)$/.exec(key);
  return match ? Number(match[1]) : null;
}
