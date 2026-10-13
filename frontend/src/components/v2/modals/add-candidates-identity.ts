/**
 * Po czym rekruter poznaje osobę w oknie „Dodaj kandydatów do pipeline”
 * (13.10.2026, `docs/claude/rekrutacja-tablica/imiennicy-w-oknie-dodawania.md`).
 *
 * 14,5% bazy ma imiennika, a wiersz pokazywał tylko imię i nazwisko, kategorię,
 * miasto i źródło — dwie osoby wyglądały identycznie. Tu są czyste reguły:
 * kto jest imiennikiem, które wiersze mają ten sam numer, jak nazwać sposób
 * szukania i jak zapisać miesiąc.
 */
import type { SearchTextInterpretation } from "@/lib/candidate-search-api";

interface Person {
  id: number;
  name: string;
  lastname: string;
  phone?: string | null;
}

/**
 * Numer do porównań: ostatnie 9 cyfr — ta sama reguła co wyszukiwanie po
 * telefonie w backendzie (`phone_digits_clause`), więc „+48 601 204 118”
 * i „601-204-118” to ten sam numer. Krótszy zapis nie jest numerem.
 */
export function phoneKey(phone: string | null | undefined): string | null {
  const digits = (phone ?? "").replace(/\D/g, "");
  return digits.length >= 9 ? digits.slice(-9) : null;
}

/** Imię i nazwisko do porównań: bez wielkości liter i nadmiarowych spacji. */
export function nameKey(name: string, lastname: string): string {
  return `${name ?? ""} ${lastname ?? ""}`.trim().replace(/\s+/g, " ").toLocaleLowerCase("pl");
}

export interface HomonymGroup {
  /** Imię i nazwisko tak, jak jest zapisane u pierwszej osoby grupy. */
  label: string;
  count: number;
}

/**
 * Największa grupa osób o tym samym imieniu i nazwisku wśród wyników
 * i osób już w rekrutacji; `null`, gdy nikt się nie powtarza.
 */
export function largestHomonymGroup(people: readonly Person[]): HomonymGroup | null {
  const groups = new Map<string, HomonymGroup>();
  for (const person of people) {
    const key = nameKey(person.name, person.lastname);
    if (!key) continue;
    const group = groups.get(key);
    if (group) group.count += 1;
    else groups.set(key, { label: `${person.name} ${person.lastname}`.trim(), count: 1 });
  }
  let best: HomonymGroup | null = null;
  for (const group of groups.values()) {
    if (group.count >= 2 && (!best || group.count > best.count)) best = group;
  }
  return best;
}

export type SamePhoneRef =
  | { kind: "row"; id: number; row: number }
  | { kind: "in_job"; id: number };

/**
 * Wiersz wyników, którego numer ma już ktoś wyżej albo osoba z tej rekrutacji.
 * Ten sam numer u dwóch rekordów to zwykle ta sama osoba zapisana dwa razy
 * (np. z Traffita), a nie imiennik — 700 takich grup na produkcji 13.10.2026.
 * Pierwszy wiersz z numerem nie dostaje plakietki; osoba w rekrutacji ma
 * pierwszeństwo, bo jej karta już istnieje.
 */
export function samePhoneRefs(
  items: readonly Person[],
  inJob: readonly Person[],
): Map<number, SamePhoneRef> {
  const refs = new Map<number, SamePhoneRef>();
  const inJobByPhone = new Map<string, number>();
  for (const person of inJob) {
    const key = phoneKey(person.phone);
    if (key && !inJobByPhone.has(key)) inJobByPhone.set(key, person.id);
  }
  const firstRow = new Map<string, { id: number; row: number }>();
  items.forEach((person, index) => {
    const key = phoneKey(person.phone);
    if (!key) return;
    const inJobId = inJobByPhone.get(key);
    if (inJobId !== undefined && inJobId !== person.id) {
      refs.set(person.id, { kind: "in_job", id: inJobId });
      return;
    }
    const earlier = firstRow.get(key);
    if (earlier) refs.set(person.id, { kind: "row", ...earlier });
    else firstRow.set(key, { id: person.id, row: index + 1 });
  });
  return refs;
}

export function samePhoneLabel(ref: SamePhoneRef): string {
  return ref.kind === "row"
    ? `Ten sam telefon co ${ref.row}. wiersz`
    : "Ten sam telefon co osoba już w tej rekrutacji";
}

/** „Szukam po numerze telefonu” — tylko gdy fraza to numer albo adres. */
export function searchKindLine(
  interpretation: SearchTextInterpretation | null | undefined,
): string | null {
  if (interpretation?.kind === "phone") return "Szukam po numerze telefonu";
  if (interpretation?.kind === "email") return "Szukam po adresie e-mail";
  return null;
}

/** „03.2026” z `2026-03-15` albo z ISO z godziną — miesiąc w Europe/Warsaw. */
export function monthLabel(value: string | null | undefined): string | null {
  if (!value) return null;
  let day = value;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const moment = new Date(value);
    if (Number.isNaN(moment.getTime())) return null;
    day = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Europe/Warsaw",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(moment);
  }
  const match = /^(\d{4})-(\d{2})/.exec(day);
  return match ? `${match[2]}.${match[1]}` : null;
}
