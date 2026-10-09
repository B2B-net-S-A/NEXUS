/**
 * Filtry listy „Nowe rekrutacje — kto prowadzi” — po stronie przeglądarki.
 *
 * Lista przychodzi z `GET /api/board-tasks` w całości (kilkadziesiąt wierszy
 * z ostatnich dni), więc nie ma po co pytać serwera przy każdej zmianie
 * filtra. Opcje powstają z samych wierszy: w polu wyboru jest tylko to, co
 * naprawdę stoi na liście. Czyste funkcje — testy w
 * `__tests__/new-job-leads-filters.test.ts`.
 */

import type { NewJobLeadRow } from "@/lib/api/boardTasks";
import {
  PRIORITY_LEVELS,
  PRIORITY_LEVEL_LABEL,
  isPriorityLevel,
  type PriorityLevel,
} from "@/lib/request-priority";

/** Wartość „bez …” w polach kategorii, Delivery Leada i prowadzącego. */
export const NONE = "none";

export interface LeadFilters {
  /** Nazwa klienta. */
  client: string;
  /** Id kategorii albo `none` (rekrutacja bez kategorii). */
  cat: string;
  /** Imię i nazwisko Delivery Leada albo `none`. */
  dl: string;
  /** Id rekrutera prowadzącego albo `none` (nikt nie prowadzi). */
  who: string;
  prio: "" | PriorityLevel;
}

export const EMPTY_LEAD_FILTERS: LeadFilters = {
  client: "",
  cat: "",
  dl: "",
  who: "",
  prio: "",
};

export interface LeadFilterOption {
  value: string;
  label: string;
}

export interface LeadFilterOptions {
  client: LeadFilterOption[];
  cat: LeadFilterOption[];
  dl: LeadFilterOption[];
  who: LeadFilterOption[];
  prio: LeadFilterOption[];
}

const byLabel = (a: LeadFilterOption, b: LeadFilterOption) =>
  a.label.localeCompare(b.label, "pl");

function catValue(row: NewJobLeadRow): string {
  return row.category_id == null ? NONE : String(row.category_id);
}

function dlValue(row: NewJobLeadRow): string {
  return row.delivery_lead_name?.trim() || NONE;
}

function whoValue(row: NewJobLeadRow): string {
  return row.lead_user_id == null ? NONE : String(row.lead_user_id);
}

/**
 * Opcje pól wyboru z wierszy listy. Pozycja „bez …” jest na końcu i tylko
 * wtedy, gdy taki wiersz istnieje — inaczej rekrutację bez kategorii albo
 * bez prowadzącego dałoby się znaleźć wyłącznie przez przewijanie.
 */
export function leadFilterOptions(
  rows: readonly NewJobLeadRow[],
  categoryLabel: (row: NewJobLeadRow) => string | null = (row) => row.category_name,
): LeadFilterOptions {
  const clients = new Set<string>();
  const cats = new Map<string, string>();
  const dls = new Set<string>();
  const people = new Map<string, string>();
  const levels = new Set<string>();
  let noCat = false;
  let noDl = false;
  let noLead = false;

  for (const row of rows) {
    const client = row.client_name?.trim();
    if (client) clients.add(client);
    if (row.category_id == null) noCat = true;
    else cats.set(String(row.category_id), categoryLabel(row)?.trim() || `#${row.category_id}`);
    const dl = row.delivery_lead_name?.trim();
    if (dl) dls.add(dl);
    else noDl = true;
    if (row.lead_user_id == null) noLead = true;
    else people.set(String(row.lead_user_id), row.lead_name?.trim() || `#${row.lead_user_id}`);
    levels.add(row.priority_level);
  }

  const named = (names: Set<string>) =>
    [...names].map((name) => ({ value: name, label: name })).sort(byLabel);
  const keyed = (entries: Map<string, string>) =>
    [...entries].map(([value, label]) => ({ value, label })).sort(byLabel);

  return {
    client: named(clients),
    cat: [...keyed(cats), ...(noCat ? [{ value: NONE, label: "Bez kategorii" }] : [])],
    dl: [...named(dls), ...(noDl ? [{ value: NONE, label: "Bez Delivery Leada" }] : [])],
    who: [...keyed(people), ...(noLead ? [{ value: NONE, label: "Bez prowadzącego" }] : [])],
    prio: PRIORITY_LEVELS.filter((level) => levels.has(level)).map((level) => ({
      value: level,
      label: PRIORITY_LEVEL_LABEL[level],
    })),
  };
}

/**
 * Filtry, które nadal mają o co się zaczepić. Wiersz znika z listy po
 * „Potwierdź” — gdy była to ostatnia rekrutacja wybranego klienta, wybór
 * przestaje istnieć w polu, więc przestaje też filtrować (pole wróciłoby do
 * „Wszyscy”, a lista zostałaby pusta bez widocznego powodu).
 */
export function liveLeadFilters(filters: LeadFilters, options: LeadFilterOptions): LeadFilters {
  const keep = (key: keyof LeadFilters) =>
    options[key].some((option) => option.value === filters[key]) ? filters[key] : "";
  const prio = keep("prio");
  return {
    client: keep("client"),
    cat: keep("cat"),
    dl: keep("dl"),
    who: keep("who"),
    prio: isPriorityLevel(prio) ? prio : "",
  };
}

export function hasLeadFilters(filters: LeadFilters): boolean {
  return Object.values(filters).some(Boolean);
}

/** Wiersze spełniające wszystkie ustawione filtry, w kolejności z serwera. */
export function filterLeads<T extends NewJobLeadRow>(
  rows: readonly T[],
  filters: LeadFilters,
): T[] {
  return rows.filter(
    (row) =>
      (!filters.client || row.client_name?.trim() === filters.client) &&
      (!filters.cat || catValue(row) === filters.cat) &&
      (!filters.dl || dlValue(row) === filters.dl) &&
      (!filters.who || whoValue(row) === filters.who) &&
      (!filters.prio || row.priority_level === filters.prio),
  );
}
