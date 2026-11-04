/**
 * Preferencja „zwinięty nagłówek rekrutacji” (K-D5, decyzja Artura 14.10.2026):
 * przycisk „Zwiń” zostawia jedną linię — priorytet, tytuł, status i awatary
 * rekruterów — a Tablica dostaje resztę ekranu laptopa.
 *
 * Pamiętana per osoba w przeglądarce (`useRailCollapsed`, `"1"` / `"0"`),
 * domyślnie rozwinięta. Nie trafia do `clearSessionArtifacts`: to wybór osoby,
 * nie dane sesji (jak pamięć filtrów listy rekrutacji).
 *
 * Nowa nazwa klucza: do #1899 (29.09.2026) istniał `nexus:jobHeaderCollapsed:v3`
 * z domyślnie ZWINIĘTYM nagłówkiem — zapisane tam wartości nie mogą wrócić.
 */
export const JOB_HEADER_COLLAPSED_DEFAULT = false;

export function jobHeaderCollapsedKey(
  userId: number | string | null | undefined,
): string {
  return `nexus:job-header-collapsed:${userId ?? "anon"}`;
}
