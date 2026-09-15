/**
 * Tagi kandydata w formularzu edycji (UAT B60).
 *
 * Kolumna `tags` miesza zwykłe napisy z obiektami importu — Traffit dopisuje
 * `{type: "traffit_source", value, domain, url}`, z których szybki podgląd
 * czyta źródło pozyskania. Formularz robił `tags.join(", ")`, więc w polu stało
 * „[object Object], [object Object]”, a zapis zamieniał obiekty w te napisy
 * i gubił źródło. Pole tekstowe edytuje wyłącznie napisy; obiekty wracają do
 * zapisu nietknięte.
 */
import { getTagName } from "@/components/v2/pages/candidate-list-helpers";

/** Napisy do pola tekstowego — bez obiektów importu. */
export function editableTagText(tags: unknown): string {
  if (typeof tags === "string") return tags;
  if (!Array.isArray(tags)) return "";
  return tags
    .filter((t): t is string => typeof t === "string")
    .map(t => t.trim())
    .filter(Boolean)
    .join(", ");
}

/** Wpisy, których pole tekstowe nie edytuje (obiekty z importu). */
export function structuredTags(tags: unknown): unknown[] {
  return Array.isArray(tags) ? tags.filter(t => t != null && typeof t === "object") : [];
}

/** Czytelne nazwy tagów z importu — do podpisu pod polem. */
export function structuredTagLabels(tags: unknown): string[] {
  return structuredTags(tags)
    .map(getTagName)
    .filter((name): name is string => Boolean(name));
}

/**
 * Tablica do zapisu: edytowane napisy + zachowane obiekty.
 * `undefined` = brak zmian (PATCH nie dotyka kolumny).
 */
export function mergeEditedTags(text: string, original: unknown): unknown[] | undefined {
  const edited = text.split(",").map(t => t.trim()).filter(Boolean);
  if (text === editableTagText(original)) return undefined;
  return [...edited, ...structuredTags(original)];
}
