/**
 * Filtr „Kto dodał” na Tablicy rekrutacji (prośba rekrutera, decyzje Artura
 * D2, D3 i D5 z 14.10.2026; makiety: https://claude.ai/artifact/XdnEDtUXR7PRm7TtJhn4kj).
 *
 * „Dodał” = osoba z PIERWSZEGO wpisu etapu pary kandydat–rekrutacja
 * (`added_to_job_by_id`), ta sama, którą karta pokazuje inicjałami i imieniem.
 * Nie rezerwacja „Biorę” i nie osoba z bieżącego etapu. Porównanie po numerze —
 * po imieniu myliłoby imienników.
 *
 * Osoby dodane przez silnik „Nowi na 20” (`entry_source = "system"`, 23.10.2026)
 * nie mają osoby dodającej — w menu to osobna pozycja „System”, nie „Brak danych”.
 *
 * Filtr żyje tylko w adresie strony (`?added_by=<numer>|none|system`); nowe wejście
 * w rekrutację pokazuje wszystkich (D3). Zasady:
 * docs/claude/rekrutacja-tablica/nastepna-osoba-po-odrzuceniu.md („Kolejka w kolumnie…”).
 */
import { placeStage, type StageLike } from "@/lib/board-stages";

export type AddedByFilter =
  | { kind: "all" }
  | { kind: "user"; userId: number }
  | { kind: "none" }
  | { kind: "system" };

export const ADDED_BY_ALL: AddedByFilter = { kind: "all" };
/** Parametr adresu strony rekrutacji. */
export const ADDED_BY_PARAM = "added_by";

export interface AddedByItem {
  candidate_id: number;
  added_to_job_by_id?: number | null;
  added_to_job_by_name?: string | null;
  entry_source?: string | null;
}

interface AddedByColumn extends StageLike {
  items: readonly AddedByItem[];
}

export function parseAddedBy(raw: string | null | undefined): AddedByFilter {
  if (raw === "none") return { kind: "none" };
  if (raw === "system") return { kind: "system" };
  if (raw && /^[1-9]\d{0,9}$/.test(raw)) return { kind: "user", userId: Number(raw) };
  return ADDED_BY_ALL;
}

/** Wartość parametru adresu; `null` = parametr zdjęty („wszyscy”). */
export function addedByParam(filter: AddedByFilter): string | null {
  if (filter.kind === "user") return String(filter.userId);
  if (filter.kind === "none") return "none";
  if (filter.kind === "system") return "system";
  return null;
}

export function addedByKey(filter: AddedByFilter): string {
  if (filter.kind === "user") return `user:${filter.userId}`;
  return filter.kind;
}

export function isSystemAdded(item: Pick<AddedByItem, "entry_source">): boolean {
  return item.entry_source === "system";
}

export function matchesAddedBy(item: AddedByItem, filter: AddedByFilter): boolean {
  if (filter.kind === "all") return true;
  if (filter.kind === "system") return isSystemAdded(item);
  if (isSystemAdded(item)) return false;
  const id = item.added_to_job_by_id ?? null;
  return filter.kind === "none" ? id == null : id === filter.userId;
}

/**
 * Osoby w toku na Tablicy: kolumny bez zamkniętych (ta sama reguła co
 * `foldBoardColumns`) i karty „Poza szablonem”, każda osoba raz.
 */
export function peopleInProgress(
  columns: readonly AddedByColumn[],
  extraItems: readonly AddedByItem[] = [],
): AddedByItem[] {
  const seen = new Set<number>();
  const people: AddedByItem[] = [];
  const take = (item: AddedByItem) => {
    if (seen.has(item.candidate_id)) return;
    seen.add(item.candidate_id);
    people.push(item);
  };
  for (const col of columns) {
    if (placeStage(col).column === "closed") continue;
    col.items.forEach(take);
  }
  extraItems.forEach(take);
  return people;
}

export interface AddedByOption {
  filter: AddedByFilter;
  /** Stabilny klucz (`all`, `user:12`, `none`) — wartość pozycji menu. */
  key: string;
  label: string;
  /** Osoby w toku na Tablicy. */
  count: number;
  isViewer: boolean;
}

/**
 * Pozycje menu: „Wszyscy”, „Ty” (zawsze, także z zerem), pozostałe osoby od
 * największej liczby, potem „System” (osoby od silnika „Nowi na 20”) i na
 * końcu „Brak danych” (karty bez zapisanej osoby dodającej — głównie
 * z Traffita), gdy takie są.
 */
export function addedByOptions(
  people: readonly AddedByItem[],
  viewer: { id: number | null; name?: string | null },
): AddedByOption[] {
  const byUser = new Map<number, { count: number; name: string | null }>();
  let withoutAdder = 0;
  let bySystem = 0;
  for (const person of people) {
    if (isSystemAdded(person)) {
      bySystem += 1;
      continue;
    }
    const id = person.added_to_job_by_id ?? null;
    if (id == null) {
      withoutAdder += 1;
      continue;
    }
    const entry = byUser.get(id) ?? { count: 0, name: null };
    entry.count += 1;
    entry.name ??= person.added_to_job_by_name?.trim() || null;
    byUser.set(id, entry);
  }

  const options: AddedByOption[] = [
    { filter: ADDED_BY_ALL, key: "all", label: "Wszyscy", count: people.length, isViewer: false },
  ];
  if (viewer.id != null) {
    const filter: AddedByFilter = { kind: "user", userId: viewer.id };
    const viewerName = viewer.name?.trim();
    options.push({
      filter,
      key: addedByKey(filter),
      label: viewerName ? `Ty (${viewerName})` : "Ty",
      count: byUser.get(viewer.id)?.count ?? 0,
      isViewer: true,
    });
  }
  const others = Array.from(byUser.entries())
    .filter(([id]) => id !== viewer.id)
    .map(([id, { count, name }]): AddedByOption => {
      const filter: AddedByFilter = { kind: "user", userId: id };
      return { filter, key: addedByKey(filter), label: name ?? `Konto nr ${id}`, count, isViewer: false };
    })
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, "pl"));
  options.push(...others);
  if (bySystem > 0) {
    const filter: AddedByFilter = { kind: "system" };
    options.push({ filter, key: "system", label: "System", count: bySystem, isViewer: false });
  }
  if (withoutAdder > 0) {
    const filter: AddedByFilter = { kind: "none" };
    options.push({ filter, key: "none", label: "Brak danych", count: withoutAdder, isViewer: false });
  }
  return options;
}

function selectedUserLabel(
  filter: Extract<AddedByFilter, { kind: "user" }>,
  options: readonly AddedByOption[],
): string {
  const option = options.find((o) => o.key === addedByKey(filter));
  return option ? option.label : "osoba spoza tej Tablicy";
}

/** Krótka nazwa wybranej osoby na przycisku: „Ty”, imię i nazwisko, „brak danych”. */
export function addedByChoiceLabel(filter: AddedByFilter, options: readonly AddedByOption[]): string {
  if (filter.kind === "all") return "wszyscy";
  if (filter.kind === "none") return "brak danych";
  if (filter.kind === "system") return "System";
  const option = options.find((o) => o.key === addedByKey(filter));
  if (option?.isViewer) return "Ty";
  return selectedUserLabel(filter, options);
}

/** Dopisek do nazwy kolejki w panelu („Nowi · dodani przez Ciebie”); `null` bez filtra. */
export function addedByQueueSuffix(
  filter: AddedByFilter,
  options: readonly AddedByOption[],
): string | null {
  if (filter.kind === "all") return null;
  if (filter.kind === "none") return "bez danych o dodającym";
  if (filter.kind === "system") return "od systemu";
  const option = options.find((o) => o.key === addedByKey(filter));
  if (option?.isViewer) return "dodani przez Ciebie";
  return `dodani przez ${selectedUserLabel(filter, options)}`;
}

/** Napis w kolumnie, w której filtr schował wszystkie karty. */
export function addedByEmptyColumnText(
  filter: AddedByFilter,
  options: readonly AddedByOption[],
): string {
  if (filter.kind === "none") return "Brak osób bez zapisanej osoby dodającej.";
  if (filter.kind === "system") return "Brak osób od systemu.";
  if (filter.kind === "user") {
    const option = options.find((o) => o.key === addedByKey(filter));
    if (option?.isViewer) return "Brak osób dodanych przez Ciebie.";
    return `Brak osób dodanych przez ${selectedUserLabel(filter, options)}.`;
  }
  return "Brak osób.";
}
