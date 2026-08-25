/**
 * Przelicznik jednostki stawki: godzinowa ↔ MD (8 h).
 *
 * Moduł zamówień MD rozlicza się WYŁĄCZNIE w zł/MD (`md_rate_cost`,
 * `md_rate_revenue` — patrz CLAUDE.md), a stawki przychodzą z dwóch źródeł:
 * z kontraktu (godzinowa) i z zamówienia klienta (MD). Przełącznik pozwala
 * wpisać to, co operator ma przed sobą, ale ZAPISYWANA wartość jest zawsze
 * w jednostce rozliczeniowej modułu — przeliczenie jest wyłącznie warstwą
 * wprowadzania danych.
 *
 * Wyniesione z komponentu, żeby regułę dało się przetestować bez montowania
 * modala — i żeby druga powierzchnia, która tego zechce, nie dopisała drugiej
 * kopii mnożnika.
 */

/** Roboczodzień (MD) = 8 godzin. Ta sama stała co po stronie parsera PDF. */
export const HOURS_PER_MD = 8;

export type RateUnit = "hour" | "md";

/** Etykiety przy przełączniku — jedno źródło dla UI i dla testów. */
export const RATE_UNIT_LABELS: Record<RateUnit, string> = {
  hour: "godzinowa (zł/h)",
  md: "MD 8h (zł/MD)",
};

/**
 * Zaokrąglenie do 2 miejsc, half-up, ODPORNE na błąd binarny.
 *
 * `Math.round(x * 100) / 100` gubi się na wartościach, których zapis
 * zmiennoprzecinkowy leży minimalnie poniżej połowy (klasyczne 1.005 → 1),
 * a tutaj chodzi o kwoty widoczne obok siebie w dwóch jednostkach: operator
 * natychmiast zauważy, że ×8 i ÷8 nie wracają do tej samej liczby.
 */
export function roundTo2(value: number): number {
  if (!Number.isFinite(value)) return NaN;
  const shifted = Number(`${value}e2`);
  return Number(`${Math.round(shifted)}e-2`);
}

/**
 * Przelicz kwotę między jednostkami. Zwraca `null` dla wejścia, którego nie da
 * się przeliczyć (NaN/Infinity) — wołający zostawia wtedy pole nietknięte
 * zamiast wpisywać do niego „NaN”.
 */
export function convertRate(
  value: number,
  from: RateUnit,
  to: RateUnit,
): number | null {
  if (!Number.isFinite(value)) return null;
  if (from === to) return roundTo2(value);
  const converted =
    from === "hour" ? value * HOURS_PER_MD : value / HOURS_PER_MD;
  return roundTo2(converted);
}

/**
 * Wartość do ZAPISU — zawsze w zł/MD, niezależnie od wybranej jednostki.
 *
 * To jest jedyne miejsce, które wie, że baza mówi w MD. Gdyby przeliczenie
 * zostało w komponencie, przełącznik ustawiony na „godzinowa” zapisywałby
 * stawkę godzinową do kolumny opisanej jako MD — błąd cichy i ośmiokrotny.
 */
export function toMdRate(value: number, unit: RateUnit): number | null {
  return convertRate(value, unit, "md");
}
