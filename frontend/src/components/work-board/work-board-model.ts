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

import type { CaseArea, CaseCard, CasePriority, CaseSource, CaseStatus } from "@/lib/api/admin-cases";
import type { CardCase } from "@/lib/api/care";
import type { CareBoardCard, CareBoardColumn, CareBoardKind } from "@/lib/api/care-board";
import { formatDayMonthPl } from "@/lib/date-pl";
import { countPl, pluralPl } from "@/lib/plural-pl";

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

const DATA_NOT_MOVABLE =
  "Dane uzupełnia się u klienta — „Przejrzyj” otwiera „Ludzie i technologie”.";

const DONE_ACTION: Record<CareBoardKind, MoveAction> = {
  contact: { type: "open-conversation" },
  feedback: { type: "open-feedback" },
  // Zrobione = „Przekazana” albo „Nie dotyczy” (okno wyboru).
  decision: { type: "close-decision" },
  demand: { type: "open-demand" },
  data: { type: "forbidden", message: DATA_NOT_MOVABLE },
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
  const kind = item.card.kind;
  if (kind === "data") return { type: "forbidden", message: DATA_NOT_MOVABLE };
  if (target === "done") return DONE_ACTION[kind];
  if (target === "in_progress") {
    // Umówiona rozmowa (z konsultantem albo menedżerem) wymaga dnia i godziny.
    const ask = kind === "decision" ? null : "schedule";
    return { type: "care-state", column: "in_progress", ask };
  }
  if (target === "waiting") {
    // Decyzja „czeka na front office” bez daty; popyt „nie teraz” — serwer da +30 dni.
    const ask = kind === "contact" || kind === "feedback" ? "retry" : null;
    return { type: "care-state", column: "waiting", ask };
  }
  return { type: "care-state", column: "new", ask: null };
}

/** Pola „Przenieś na tablicy” w panelu (K2): trzy kolumny z podpowiedzią, bez „Zrobione”. */
export interface CareMoveOption {
  column: CareBoardColumn;
  label: string;
  hint: string;
}

export function careMoveOptions(kind: CareBoardKind): CareMoveOption[] {
  switch (kind) {
    case "contact":
      return [
        { column: "new", label: "Nowa", hint: "do zrobienia" },
        { column: "in_progress", label: "W toku · Umówiona", hint: "podaj dzień i godzinę" },
        { column: "waiting", label: "Czeka · Nie odbiera", hint: "spróbować ponownie dnia…" },
      ];
    case "feedback":
      return [
        { column: "new", label: "Nowa", hint: "prośba czeka" },
        { column: "in_progress", label: "W toku · Umówiona", hint: "z menedżerem — dzień i godzina" },
        { column: "waiting", label: "Czeka na menedżera", hint: "do dnia…" },
      ];
    case "decision":
      return [
        { column: "new", label: "Nowa", hint: "nowy sygnał" },
        { column: "in_progress", label: "W toku", hint: "rozmowa o przepięciu" },
        { column: "waiting", label: "Czeka", hint: "na front office" },
      ];
    case "demand":
      return [
        { column: "new", label: "Nowa", hint: "do sprawdzenia" },
        { column: "in_progress", label: "W toku · Umówiona", hint: "rozmowa z menedżerem" },
        { column: "waiting", label: "Czeka · Nie teraz", hint: "wraca za 30 dni" },
      ];
    case "data":
      return [];
  }
}

/** Jedyna akcja karty opieki. */
export const CARE_ACTION_LABELS: Record<CareBoardKind, string> = {
  contact: "Zapisz rozmowę",
  feedback: "Zapisz opinię",
  decision: "Przekaż do front office",
  demand: "Porozmawiaj z menedżerem",
  data: "Przejrzyj",
};

/** Popyt bez znanego menedżera działu: najpierw „Kto komu podlega” (R4). */
export function demandNeedsManager(card: Pick<CareBoardCard, "kind" | "demand">): boolean {
  return card.kind === "demand" && !card.demand?.manager;
}

export function careActionLabel(card: Pick<CareBoardCard, "kind" | "demand">): string {
  return demandNeedsManager(card) ? "Uzupełnij menedżera" : CARE_ACTION_LABELS[card.kind];
}

/** „Ludzie i technologie” klienta (`?tab=ludzie`, z `view` — widok Drzewo osób). */
export function clientPeopleHref(clientId: number, view?: "drzewo"): string {
  return `/clients/${clientId}?tab=ludzie${view ? `&view=${view}` : ""}`;
}

/**
 * Adres akcji, gdy nie ma okna (Sprawy bez okien opieki, dane, popyt bez
 * menedżera): dane i brak menedżera → „Ludzie i technologie” klienta.
 */
export function careActionHref(card: Pick<CareBoardCard, "kind" | "demand" | "client_id" | "contract_id" | "key">): string {
  if (card.kind === "data" && card.client_id) return clientPeopleHref(card.client_id);
  if (demandNeedsManager(card) && card.client_id) return clientPeopleHref(card.client_id, "drzewo");
  return careCardHref(card);
}

// ── Wygląd karty opieki (makiety K1, K2, P1) ────────────────────────────────

const TITLE_PREFIX: Partial<Record<CareBoardKind, string>> = {
  contact: "Rozmowa",
  feedback: "Opinia",
  decision: "Decyzja",
  data: "Dane",
};

/** Tytuł na tablicy: „Rozmowa: Karolina Przykładowa”, „Opinia: Piotr Menedżerski”. */
export function careTileTitle(card: Pick<CareBoardCard, "kind" | "title">): string {
  const prefix = TITLE_PREFIX[card.kind];
  if (!prefix || card.title.startsWith(`${prefix}:`)) return card.title;
  return `${prefix}: ${card.title}`;
}

const CONTACT_REASON: Record<string, string> = {
  day_7: "dzień 7",
  day_30: "dzień 30",
  day_90: "dzień 90",
  pre_end: "kamień",
  cadence: "z rytmu",
  quarterly: "kwartał",
  follow_up: "umówiony kontakt",
};

const DECISION_REASON: Record<string, string> = {
  wants_change: "chce zmiany",
  attrition_risk: "ryzyko odejścia",
  project_end: "koniec zamówienia",
};

/** Powód karty krótko: „dzień 30”, „kamień”, „chce zmiany”. */
export function careReasonShort(card: Pick<CareBoardCard, "kind" | "reason_kind" | "reason_label">): string | null {
  const kind = card.reason_kind ?? "";
  if (card.kind === "contact" && CONTACT_REASON[kind]) return CONTACT_REASON[kind];
  if (card.kind === "decision" && DECISION_REASON[kind]) return DECISION_REASON[kind];
  const label = (card.reason_label ?? "").replace(/^Decyzja:\s*/, "").trim();
  return label ? label.toLocaleLowerCase("pl-PL") : null;
}

/** Nagłówek karty (obok plakietki „Opieka”): „rozmowa · dzień 30”, „rozmowa · umówiona”. */
export function careHeaderText(card: CareBoardCard): string {
  const kind = card.kind === "feedback" ? "opinia menedżera" : card.kind === "data" ? "dane do uzupełnienia" : null;
  if (kind) return kind;
  const base = card.kind === "contact" ? "rozmowa" : card.kind === "decision" ? "decyzja" : "popyt";
  if (card.column === "in_progress" && card.scheduled_at) return `${base} · umówiona`;
  if (card.kind === "demand") return "popyt · klient zatrudnia";
  const reason = careReasonShort(card);
  return reason ? `${base} · ${reason}` : base;
}

/** „3 dni po” (karta) albo „3 dni po terminie” (panel). */
export function overdueText(days: number, long = false): string {
  return `${countPl(days, "dzień", "dni", "dni")} po${long ? " terminie" : ""}`;
}

const SCHEDULE_PARTS = new Intl.DateTimeFormat("pl-PL", {
  timeZone: "Europe/Warsaw",
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

/** Umówiony termin krótko, w czasie firmy: „24.10 · 14:00”. */
export function formatScheduledShort(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const moment = new Date(iso);
  if (Number.isNaN(moment.getTime())) return null;
  const parts = Object.fromEntries(SCHEDULE_PARTS.formatToParts(moment).map((part) => [part.type, part.value]));
  return `${parts.day}.${parts.month} · ${parts.hour}:${parts.minute}`;
}

/**
 * Plakietka terminu karty opieki (K1): umówiona — „24.10 · 14:00”, opinia —
 * „czeka od 19.10”, po terminie — „3 dni po”, dalej jak termin sprawy.
 */
export function careBadge(
  card: CareBoardCard,
  today: string | undefined,
  weekEnd: string | undefined,
): { text: string; tone: DueTone } | null {
  if (card.column === "in_progress" && card.scheduled_at) {
    const when = formatScheduledShort(card.scheduled_at);
    if (when) return { text: when, tone: "week" };
  }
  if (card.kind === "data") return null;
  if (card.kind === "feedback" && card.due_on && today && card.due_on <= today) {
    return { text: `czeka od ${formatDayMonthPl(card.due_on)}`, tone: card.overdue_days > 0 ? "overdue" : "week" };
  }
  if (card.due_on && card.overdue_days > 0) return { text: overdueText(card.overdue_days), tone: "overdue" };
  return careDueBadge(card, today, weekEnd);
}

/**
 * Linia stanu karty (ramka jak „odezwać się” przy sprawie): „nie odbiera —
 * spróbować 25.10”, „czeka na menedżera — do 25.10”, „czeka na front office”,
 * „nie teraz — wraca 21.11”; dochodzi notatka z przeniesienia (`state_note`).
 * Umówiony termin stoi w plakietce, więc sam nie robi linii.
 */
export function careStateText(card: CareBoardCard): string | null {
  let when: string | null = null;
  if (card.column === "waiting") {
    const day = card.retry_on ? formatDayMonthPl(card.retry_on) : null;
    if (card.kind === "contact") when = day ? `nie odbiera — spróbować ${day}` : "nie odbiera";
    else if (card.kind === "feedback") when = day ? `czeka na menedżera — do ${day}` : "czeka na menedżera";
    else if (card.kind === "decision") when = day ? `czeka na front office — do ${day}` : "czeka na front office";
    else if (card.kind === "demand") when = day ? `nie teraz — wraca ${day}` : "nie teraz";
  }
  const note = card.column !== "new" ? card.state_note?.trim() : null;
  if (when && note) return `${when} · ${note}`;
  return when ?? (note || null);
}

/** „Anna Przykładowa” → „Anna P.” (opiekun w podtytule panelu). */
export function shortPersonName(name: string | null | undefined): string {
  const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (parts.length < 2) return parts[0] ?? "";
  return `${parts[0]} ${parts[parts.length - 1][0]}.`;
}

/** „Katarzyna Kierownicza” → „K. Kierownicza” (menedżer w wierszu listy). */
export function initialSurname(name: string | null | undefined): string {
  const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (parts.length < 2) return parts[0] ?? "";
  return `${parts[0][0]}. ${parts.slice(1).join(" ")}`;
}

/** „2 pewne propozycje menedżera + 1 do sprawdzenia · 3 luki w mapie technologii”. */
export function dataSummaryText(data: NonNullable<CareBoardCard["data"]>): string {
  const parts: string[] = [];
  const proposals: string[] = [];
  if (data.certain) {
    proposals.push(
      `${data.certain} ${pluralPl(data.certain, "pewna propozycja", "pewne propozycje", "pewnych propozycji")} menedżera`,
    );
  }
  if (data.uncertain) {
    proposals.push(data.certain ? `${data.uncertain} do sprawdzenia` : `${countPl(data.uncertain, "propozycja", "propozycje", "propozycji")} menedżera do sprawdzenia`);
  }
  if (proposals.length) parts.push(proposals.join(" + "));
  if (data.gaps) parts.push(`${countPl(data.gaps, "luka", "luki", "luk")} w mapie technologii`);
  return parts.join(" · ");
}

/** Sprawa w „Opiece → Do zrobienia” tylko z terminem do piątku albo po terminie (S3). */
export function caseDueThisWeek(card: Pick<CaseCard, "due_on" | "overdue" | "status">, weekEnd: string | undefined): boolean {
  if (card.status === "done" || card.status === "closed") return true;
  if (card.overdue) return true;
  return Boolean(card.due_on && weekEnd && card.due_on <= weekEnd);
}

/**
 * Sprawa z karty konsultanta (`CardCase`) jako karta tablicy — panel sprawy
 * otwiera się od razu, a szczegóły dociąga `useCase` (priorytet, źródło, lista).
 */
export function caseStubFromCardCase(item: CardCase, today: string | undefined): CaseCard {
  const status = item.status as CaseStatus;
  const open = status !== "done" && status !== "closed";
  return {
    id: item.id,
    title: item.title,
    area: item.area as CaseArea,
    priority: "P2" as CasePriority,
    status,
    due_on: item.due_on,
    follow_up_on: item.follow_up_on,
    overdue: Boolean(open && item.due_on && today && item.due_on < today),
    assignee: item.assignee_name ? { id: 0, name: item.assignee_name } : null,
    subject_user: null,
    contract: null,
    source: item.source as CaseSource,
    checklist_done: 0,
    checklist_total: 0,
    created_at: "",
    updated_at: "",
    closed_at: null,
  };
}

/** Nagłówek „Zrobione” (K1): jedna liczba i „41 spraw w miesiącu · 5 rozmów i opinii w tym tygodniu”. */
export function doneSummary(input: { casesMonth: number | null; careWeek: number | null }): {
  total: number;
  text: string;
} {
  const parts: string[] = [];
  if (input.casesMonth != null) parts.push(`${countPl(input.casesMonth, "sprawa", "sprawy", "spraw")} w miesiącu`);
  if (input.careWeek != null) {
    parts.push(
      `${countPl(input.careWeek, "rozmowa lub opinia", "rozmowy i opinie", "rozmów i opinii")} w tym tygodniu`,
    );
  }
  return { total: (input.casesMonth ?? 0) + (input.careWeek ?? 0), text: parts.join(" · ") };
}

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

export type ListGroupKey = "overdue" | "week" | "decisions" | "demand" | "data" | "later";

export const LIST_GROUP_LABELS: Record<ListGroupKey, string> = {
  overdue: "Po terminie",
  week: "Do piątku",
  decisions: "Decyzje",
  demand: "Popyt do sprawdzenia",
  data: "Dane do uzupełnienia",
  later: "Później i bez terminu",
};

const LIST_ORDER: readonly ListGroupKey[] = ["overdue", "week", "decisions", "demand", "data", "later"];

function dueOf(item: WorkItem): string | null {
  return item.card.due_on;
}

function overdueOf(item: WorkItem): boolean {
  return item.type === "case" ? item.card.overdue : item.card.overdue_days > 0;
}

export function listGroupOf(item: WorkItem, weekEnd: string | undefined): ListGroupKey {
  if (item.type === "care" && item.card.kind === "decision") return "decisions";
  if (item.type === "care" && item.card.kind === "demand") return "demand";
  if (item.type === "care" && item.card.kind === "data") return "data";
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

/** Kolejka przy setkach zaległych (prod: 482) — tyle wierszy na „Pokaż więcej”. */
export const LIST_PAGE = 50;

/** Pierwsze `limit` wierszy w kolejności grup; puste grupy po przycięciu znikają. */
export function paginateGroups<T extends { items: WorkItem[] }>(
  groups: readonly T[],
  limit: number,
): { groups: T[]; hidden: number } {
  let left = limit;
  let hidden = 0;
  const out: T[] = [];
  for (const group of groups) {
    const take = Math.max(0, Math.min(left, group.items.length));
    hidden += group.items.length - take;
    left -= take;
    if (take > 0) out.push({ ...group, items: group.items.slice(0, take) });
  }
  return { groups: out, hidden };
}

// ── Filtr kolejki (chipy listy i `/care?filter=`) ───────────────────────────

export type ListFilter = "all" | "overdue" | "week" | "contact" | "feedback" | "decision" | "data" | "demand";

/** Wartości `?filter=` (linki z dzwonków) → filtr. */
export const LIST_FILTER_PARAMS: Record<string, ListFilter> = {
  "po-terminie": "overdue",
  "do-piatku": "week",
  rozmowy: "contact",
  opinie: "feedback",
  decyzje: "decision",
  dane: "data",
  popyt: "demand",
};

export const LIST_FILTER_LABELS: Record<ListFilter, string> = {
  all: "Wszystko",
  overdue: "Po terminie",
  week: "Do piątku",
  contact: "Rozmowy",
  feedback: "Opinie menedżerów",
  decision: "Decyzje",
  data: "Dane",
  demand: "Popyt",
};

export function listFilterFromParam(value: string | null | undefined): ListFilter {
  return (value && LIST_FILTER_PARAMS[value]) || "all";
}

export function matchesListFilter(item: WorkItem, filter: ListFilter, weekEnd: string | undefined): boolean {
  const column = itemColumn(item);
  if (column === "done" || column === "closed") return false;
  switch (filter) {
    case "all":
      return true;
    case "overdue":
      return overdueOf(item);
    case "week": {
      const due = dueOf(item);
      return overdueOf(item) || Boolean(due && weekEnd && due <= weekEnd);
    }
    default:
      return item.type === "care" && item.card.kind === filter;
  }
}

/** Liczniki chipów listy: te same karty, każdy filtr osobno. */
export function listFilterCounts(items: readonly WorkItem[], weekEnd: string | undefined): Record<ListFilter, number> {
  const filters: ListFilter[] = ["all", "overdue", "week", "contact", "feedback", "decision", "data", "demand"];
  return Object.fromEntries(
    filters.map((filter) => [filter, items.filter((item) => matchesListFilter(item, filter, weekEnd)).length]),
  ) as Record<ListFilter, number>;
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

/** `decision:end:<kontrakt>` — decyzja z samego końca zamówienia, jeszcze bez wpisu. */
export function isOrderEndDecision(key: string): boolean {
  return /^decision:end:\d+$/.test(key);
}

// ── Panel karty opieki (makieta K2) ─────────────────────────────────────────

/** „OPIEKA · ROZMOWA · DZIEŃ 30 · 3 DNI PO TERMINIE” (wielkie litery robi CSS). */
export function carePanelKicker(card: CareBoardCard): string {
  const parts = ["Opieka", careHeaderText(card)];
  if (card.overdue_days > 0 && card.kind !== "data") parts.push(overdueText(card.overdue_days, true));
  return parts.join(" · ");
}

/** „QA · Telekom Wzorcowy · opiekun Natalia O.” (zdrowie słowem dokłada panel). */
export function carePanelSubtitle(card: CareBoardCard): string {
  if (card.kind === "data") return card.subtitle ?? "";
  if (card.kind === "demand") return card.subtitle ?? card.client_name ?? "";
  const parts = [card.role_label, card.client_name];
  if (card.kind !== "feedback" && card.owner_name) parts.push(`opiekun ${shortPersonName(card.owner_name)}`);
  return parts.filter(Boolean).join(" · ");
}

/** Skrót karty konsultanta, którego potrzebuje panel (podzbiór `CareContractCardSummary`). */
export interface ConsultantBriefSource {
  cadence: { label: string; until_on: string | null } | null;
  kpis: {
    last_contact: { on: string; days_ago: number } | null;
    satisfaction: { value: number; previous: number | null } | null;
    order_end: { on: string; days: number } | null;
  };
  known_project: { manager: { name: string; position: string | null } | null } | null;
}

/**
 * „Konsultant w skrócie” (K2): ostatnia rozmowa z oceną i cytatem, menedżer
 * u klienta z czekającą prośbą o opinię, koniec zamówienia, rytm. Bez stawek.
 */
export function consultantBriefRows(
  card: CareBoardCard,
  summary: ConsultantBriefSource | null | undefined,
): { label: string; value: string }[] {
  const lastOn = summary?.kpis.last_contact?.on ?? card.note_on ?? null;
  const score = card.last_satisfaction ?? summary?.kpis.satisfaction?.value ?? null;
  const last = lastOn
    ? [formatDayMonthPl(lastOn), score != null ? `${score}/5` : null, card.note_excerpt ? `„${card.note_excerpt}”` : null]
        .filter(Boolean)
        .join(" · ")
    : "jeszcze nie było";
  const managerName = summary?.known_project?.manager?.name ?? card.manager?.name ?? null;
  const waiting = card.manager?.feedback_due_on
    ? `prośba o opinię czeka od ${formatDayMonthPl(card.manager.feedback_due_on)}`
    : null;
  const manager = managerName ? [managerName, waiting].filter(Boolean).join(" · ") : "nie wskazano";
  const end = summary?.kpis.order_end ?? null;
  const endText = end
    ? `${formatDayMonthPl(end.on)} · ${end.days >= 0 ? `za ${countPl(end.days, "dzień", "dni", "dni")}` : "po końcu"}`
    : card.end_on
      ? formatDayMonthPl(card.end_on)
      : "bez końca";
  const cadence = summary?.cadence
    ? [summary.cadence.label, summary.cadence.until_on ? `do ${formatDayMonthPl(summary.cadence.until_on)}` : null]
        .filter(Boolean)
        .join(" · ")
    : "—";
  return [
    { label: "Ostatnia rozmowa", value: last },
    { label: "Menedżer u klienta", value: manager },
    { label: "Koniec zamówienia", value: endText },
    { label: "Rytm", value: cadence },
  ];
}

/** Otwarte sprawy osoby (zamknięte i zrobione nie stoją w panelu). */
export function openPersonCases(cases: readonly CardCase[]): CardCase[] {
  return cases.filter((item) => item.status !== "done" && item.status !== "closed");
}
