/**
 * Spokojna tabela — wspólny wygląd list w Klientach, Kontraktach i Finansach
 * (makiety z 02.10.2026). Zebra, pionowe kreski, kwoty czcionką maszynową
 * i plakietka w każdym wierszu robiły z tabeli szum; tu zostaje jedna cienka
 * linia między wierszami, liczby w równych kolumnach i jednostka raz, w nagłówku.
 *
 * Klasy są pełnymi literałami — Tailwind zbiera je ze źródeł, więc nie składaj
 * ich z kawałków. Prymityw `components/ui/table.tsx` zostaje bez zmian (ma
 * innych konsumentów); te stałe dokłada się przez `className`.
 */

/** Nagłówek kolumny. */
export const CALM_HEAD =
  "text-[10.5px] font-semibold uppercase tracking-[0.05em] text-muted-foreground";

/** Wiersz danych: jedna cienka linia, bez zebry. */
export const CALM_ROW = "border-b border-border/60";

/** Komórka z kwotą albo liczbą. */
export const CALM_AMOUNT = "text-right tabular-nums whitespace-nowrap";

/** Jednostka przy nagłówku albo kwocie („zł/h”, „zł/MD”). */
export const CALM_UNIT = "ml-1 text-[11px] font-normal normal-case tracking-normal text-muted-foreground";

/** Druga linia komórki (rekrutacja pod klientem, okres pod numerem). */
export const CALM_SUBLINE = "mt-0.5 block text-[11.5px] leading-4 text-muted-foreground";

/** Brak wartości („—”) — ma być widać, że to brak, a nie dana. */
export const CALM_EMPTY = "text-muted-foreground/50";
