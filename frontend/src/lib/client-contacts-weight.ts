/**
 * Kontakty klienta według wagi (makieta 19.11.2026, wariant A ekranu
 * „Ludzie klienta”): najpierw decydenci i kluczowe relacje, potem kierownicy
 * i dyrektorzy (po stanowisku), na końcu reszta — zwinięta, gdy jest długa.
 * Do 19.11.2026 lista szła alfabetycznie: u PKO BP jedyny decydent stał
 * między 89 osobami, a nikt nie miał zapisanej rozmowy.
 */

export interface WeightedContact {
  is_decision_maker: boolean;
  is_key_relationship?: boolean;
  position: string | null;
}

export type ContactWeightGroup = "key" | "managers" | "others";

/** Stanowiska kierownicze — ten sam zestaw słów co przy przeglądzie danych 19.11.2026. */
const MANAGER_POSITION = /(dyrektor|kierownik|manager|menedżer|menadżer|head|lider|leader|szef|prezes|wiceprezes|cto|cio|ceo)/i;

/** Pozostali zwijają się, gdy grup wyżej jest coś do pokazania, a ich samych więcej niż tyle. */
export const OTHERS_COLLAPSE_FROM = 10;

export function contactWeight(contact: WeightedContact): ContactWeightGroup {
  if (contact.is_decision_maker || contact.is_key_relationship) return "key";
  if (contact.position && MANAGER_POSITION.test(contact.position)) return "managers";
  return "others";
}

const GROUP_LABEL: Record<ContactWeightGroup, string> = {
  key: "Decydenci i kluczowe relacje",
  managers: "Kierownicy i dyrektorzy",
  others: "Pozostali",
};

export type ContactEntry<T> =
  | { kind: "header"; group: ContactWeightGroup; label: string; count: number; collapsible: boolean }
  | { kind: "contact"; contact: T };

/**
 * Wiersze tabeli: nagłówek grupy i jej kontakty, w kolejności, w jakiej
 * przyszły (wywołujący sortuje w grupie). „Pozostali” zwinięci, dopóki
 * `othersOpen` nie jest `true`.
 */
export function contactWeightEntries<T extends WeightedContact>(
  contacts: readonly T[],
  othersOpen: boolean,
): ContactEntry<T>[] {
  const groups: Record<ContactWeightGroup, T[]> = { key: [], managers: [], others: [] };
  for (const contact of contacts) groups[contactWeight(contact)].push(contact);
  const hasPriority = groups.key.length + groups.managers.length > 0;
  const entries: ContactEntry<T>[] = [];
  for (const group of ["key", "managers", "others"] as const) {
    const items = groups[group];
    if (items.length === 0) continue;
    const collapsible = group === "others" && hasPriority && items.length > OTHERS_COLLAPSE_FROM;
    entries.push({ kind: "header", group, label: GROUP_LABEL[group], count: items.length, collapsible });
    if (collapsible && !othersOpen) continue;
    for (const contact of items) entries.push({ kind: "contact", contact });
  }
  return entries;
}
