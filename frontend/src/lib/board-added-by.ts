/**
 * Filtr „Kto dodał” na Tablicy rekrutacji (prośba rekrutera, decyzje Artura
 * D2, D3 i D5 z 14.10.2026; makiety: https://claude.ai/artifact/XdnEDtUXR7PRm7TtJhn4kj).
 *
 * „Dodał” = osoba z PIERWSZEGO wpisu etapu pary kandydat–rekrutacja
 * (`added_to_job_by_id`), ta sama, którą karta pokazuje inicjałami i imieniem.
 * Nie osoba z bieżącego etapu. Porównanie po numerze — po imieniu myliłoby
 * imienników. Osoba, która kliknęła „Biorę”, wygrywa z dodającą (prośba
 * rekruterki, decyzja Artura 27.10.2026: wzięła ludzi kolegi do telefonu
 * i nie mogła ich znaleźć na pełnej Tablicy). Od „Zweryfikowanego” w prawo
 * liczy się osoba, która zweryfikowała — ta sama, którą pokazuje karta
 * (`cardOwner`; zgłoszenie rekruterki z 29.10.2026: w „CV wysłane” cztery
 * karty z jej imieniem, a „Ty” pokazywał jedną).
 *
 * Osoby dodane przez silnik „Nowi na 20” (`entry_source = "system"`, 23.10.2026)
 * nie mają osoby dodającej — w menu to osobna pozycja „System”, nie „Brak danych”.
 *
 * Karty osób z wyłączonym kontem, które domyka Delivery Lead (odejście z firmy,
 * 28.10.2026, `lib/departed-care.ts`), mają własną pozycję „Po osobach, które
 * odeszły” — z dowolną osobą karty.
 *
 * Filtr żyje tylko w adresie strony (`?added_by=<numer>|none|system|departed`); nowe wejście
 * w rekrutację pokazuje wszystkich (D3). Zasady:
 * docs/claude/rekrutacja-tablica/nastepna-osoba-po-odrzuceniu.md („Kolejka w kolumnie…”).
 */
import { placeStage, type BoardColumnKey, type StageLike } from "@/lib/board-stages";

export type AddedByFilter =
  | { kind: "all" }
  | { kind: "user"; userId: number }
  | { kind: "none" }
  | { kind: "system" }
  | { kind: "departed" };

export const ADDED_BY_ALL: AddedByFilter = { kind: "all" };
/** Parametr adresu strony rekrutacji. */
export const ADDED_BY_PARAM = "added_by";

export interface AddedByItem {
  candidate_id: number;
  added_to_job_by_id?: number | null;
  added_to_job_by_name?: string | null;
  entry_source?: string | null;
  /** „Prowadzi” (25.10.2026) — przypisana osoba liczy się jak dodająca. */
  owner_user_id?: number | null;
  owner_name?: string | null;
  /** Ostatnia osoba, która kliknęła „Biorę” (do weryfikacji, 27.10.2026). */
  taken_by_user_id?: number | null;
  taken_by_name?: string | null;
  /** Odejście z firmy (28.10.2026): para w opiece Delivery Leada. */
  care_user_id?: number | null;
  /** Pierwsza osoba, która zweryfikowała parę (20.10.2026). */
  verified_by_id?: number | null;
  verified_by_name?: string | null;
  /** Kolumna Tablicy karty — dokłada ją `peopleInProgress`. */
  board_column?: BoardColumnKey | null;
}

/** Kolumny, w których nikt jeszcze nie zweryfikował osoby (jak `cardOwner`). */
const BEFORE_VERIFIED: ReadonlySet<BoardColumnKey> = new Set(["new", "screening"]);

/** Co liczy się w kolumnie: „Biorę” przed weryfikacją, weryfikująca od niej. */
function phase(column: BoardColumnKey | null): { taker: boolean; verifier: boolean } {
  if (column == null) return { taker: true, verifier: false };
  const before = BEFORE_VERIFIED.has(column);
  return { taker: before, verifier: !before };
}

/** Osoba karty w filtrze: przypisana „Prowadzi”, potem ta, która wzięła
 *  „Biorę” (przed weryfikacją), ta, która zweryfikowała (od „Zweryfikowanego”),
 *  a bez tego ta, która dodała. `null` = osoba karty spoza zapisanych. */
function cardPerson(
  item: AddedByItem,
  column: BoardColumnKey | null,
): { id: number; name: string | null } | null {
  const { taker, verifier } = phase(column);
  if (item.owner_user_id != null) return { id: item.owner_user_id, name: item.owner_name ?? null };
  if (taker && item.taken_by_user_id != null) {
    return { id: item.taken_by_user_id, name: item.taken_by_name ?? null };
  }
  if (verifier && item.verified_by_id != null) {
    return { id: item.verified_by_id, name: item.verified_by_name ?? null };
  }
  if (item.added_to_job_by_id != null) {
    return { id: item.added_to_job_by_id, name: item.added_to_job_by_name ?? null };
  }
  return null;
}

function adderId(item: AddedByItem, column: BoardColumnKey | null): number | null {
  return cardPerson(item, column)?.id ?? null;
}

function adderName(item: AddedByItem, column: BoardColumnKey | null): string | null {
  return cardPerson(item, column)?.name?.trim() || null;
}

interface AddedByColumn extends StageLike {
  items: readonly AddedByItem[];
}

export function parseAddedBy(raw: string | null | undefined): AddedByFilter {
  if (raw === "none") return { kind: "none" };
  if (raw === "system") return { kind: "system" };
  if (raw === "departed") return { kind: "departed" };
  if (raw && /^[1-9]\d{0,9}$/.test(raw)) return { kind: "user", userId: Number(raw) };
  return ADDED_BY_ALL;
}

/** Wartość parametru adresu; `null` = parametr zdjęty („wszyscy”). */
export function addedByParam(filter: AddedByFilter): string | null {
  if (filter.kind === "user") return String(filter.userId);
  if (filter.kind === "none") return "none";
  if (filter.kind === "system") return "system";
  if (filter.kind === "departed") return "departed";
  return null;
}

export function addedByKey(filter: AddedByFilter): string {
  if (filter.kind === "user") return `user:${filter.userId}`;
  return filter.kind;
}

export function isSystemAdded(
  item: Pick<
    AddedByItem,
    "entry_source" | "owner_user_id" | "taken_by_user_id" | "verified_by_id"
  >,
  column: BoardColumnKey | null = null,
): boolean {
  const { taker, verifier } = phase(column);
  return (
    item.entry_source === "system" &&
    item.owner_user_id == null &&
    !(taker && item.taken_by_user_id != null) &&
    !(verifier && item.verified_by_id != null)
  );
}

/** `column` = kolumna Tablicy karty; bez niej ta z `peopleInProgress`,
 *  a bez niczego — reguła sprzed weryfikacji (jak karta bez kolumny). */
export function matchesAddedBy(
  item: AddedByItem,
  filter: AddedByFilter,
  column: BoardColumnKey | null = item.board_column ?? null,
): boolean {
  if (filter.kind === "all") return true;
  if (filter.kind === "system") return isSystemAdded(item, column);
  if (filter.kind === "departed") return item.care_user_id != null;
  if (isSystemAdded(item, column)) return false;
  const id = adderId(item, column);
  return filter.kind === "none" ? id == null : id === filter.userId;
}

/**
 * Osoby w toku na Tablicy: kolumny bez zamkniętych (ta sama reguła co
 * `foldBoardColumns`) i karty „Poza szablonem”, każda osoba raz, z kolumną
 * karty w `board_column` (karty „Poza szablonem” bez kolumny).
 */
export function peopleInProgress(
  columns: readonly AddedByColumn[],
  extraItems: readonly AddedByItem[] = [],
): AddedByItem[] {
  const seen = new Set<number>();
  const people: AddedByItem[] = [];
  const take = (item: AddedByItem, column: BoardColumnKey | null) => {
    if (seen.has(item.candidate_id)) return;
    seen.add(item.candidate_id);
    people.push({ ...item, board_column: column });
  };
  for (const col of columns) {
    const column = placeStage(col).column;
    if (column === "closed") continue;
    for (const item of col.items) take(item, column);
  }
  for (const item of extraItems) take(item, null);
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
  let departed = 0;
  for (const person of people) {
    if (person.care_user_id != null) departed += 1;
    const column = person.board_column ?? null;
    if (isSystemAdded(person, column)) {
      bySystem += 1;
      continue;
    }
    const id = adderId(person, column);
    if (id == null) {
      withoutAdder += 1;
      continue;
    }
    const entry = byUser.get(id) ?? { count: 0, name: null };
    entry.count += 1;
    entry.name ??= adderName(person, column);
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
  if (departed > 0) {
    const filter: AddedByFilter = { kind: "departed" };
    options.push({
      filter,
      key: "departed",
      label: "Po osobach, które odeszły",
      count: departed,
      isViewer: false,
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
  if (filter.kind === "departed") return "po osobach, które odeszły";
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
  if (filter.kind === "departed") return "po osobach, które odeszły";
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
  if (filter.kind === "departed") return "Brak osób po osobach, które odeszły.";
  if (filter.kind === "user") {
    const option = options.find((o) => o.key === addedByKey(filter));
    if (option?.isViewer) return "Brak osób dodanych przez Ciebie.";
    return `Brak osób dodanych przez ${selectedUserLabel(filter, options)}.`;
  }
  return "Brak osób.";
}
