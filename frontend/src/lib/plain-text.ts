const ENTITIES: Record<string, string> = {
  "&amp;": "&",
  "&lt;": "<",
  "&gt;": ">",
  "&quot;": '"',
  "&#39;": "'",
  "&nbsp;": " ",
};

/**
 * Tekst z pola, które bywa zapisane jako HTML (np. tytuł transkrypcji
 * Fireflies „<p>Rozmowa…</p>”) — bez znaczników, z rozwiniętymi podstawowymi
 * encjami i zwiniętymi odstępami. Wynik renderujemy jako tekst, nie HTML.
 */
export function stripHtmlTags(value: string | null | undefined): string {
  if (!value) return "";
  return value
    .replace(/<[^>]*>/g, " ")
    .replace(/&(amp|lt|gt|quot|#39|nbsp);/g, (entity) => ENTITIES[entity] ?? entity)
    .replace(/\s+/g, " ")
    .trim();
}
