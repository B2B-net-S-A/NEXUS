/**
 * Szeroka tabela listy (zgłoszenie 02.10.2026: na dużym monitorze lista
 * kończyła się na 1400 px, a Traffit rozciągał kolumny na cały ekran).
 *
 * Listy mają limit `LIST_PAGE_MAX_WIDTH`, a dane upchnięte drobnym drukiem
 * pod główną wartością (klient pod tytułem, rekrutacja pod klientem, „umowa
 * do” pod datą startu) dostają własne kolumny, gdy TABELA ma co najmniej
 * 1700 px (przy 1920 px z przypiętym menu zostaje układ zwarty — tytuł
 * rekrutacji miałby tam 260 px). Próg liczy się od kontenera (`@container`
 * na `WIDE_TABLE_CONTAINER`), nie od okna: przypięte menu, dok podglądu
 * i panel szczegółów zabierają tabeli miejsce niezależnie od szerokości ekranu.
 *
 * Klasy są pełnymi literałami — Tailwind zbiera je ze źródeł, więc nie składaj
 * ich z kawałków.
 */

/** Limit szerokości stron-list (ten sam co lista kandydatów). */
export const LIST_PAGE_MAX_WIDTH = "max-w-[2400px]";

/** Opakowanie tabeli — od jego szerokości zależą klasy poniżej. */
export const WIDE_TABLE_CONTAINER = "@container";

/** `<th>` / `<td>` widoczne dopiero w szerokiej tabeli. */
export const WIDE_ONLY_CELL = "hidden @min-[1700px]:table-cell";

/** `<col>` kolumny widocznej dopiero w szerokiej tabeli. */
export const WIDE_ONLY_COL = "hidden @min-[1700px]:table-column";

/** Element w linii widoczny dopiero w szerokiej tabeli. */
export const WIDE_ONLY_INLINE = "hidden @min-[1700px]:inline";

/** Rząd (`flex`) widoczny dopiero w szerokiej tabeli. */
export const WIDE_ONLY_FLEX = "hidden @min-[1700px]:flex";

/** Drobny druk, który w szerokiej tabeli ma własną kolumnę. */
export const WIDE_HIDDEN = "@min-[1700px]:hidden";
