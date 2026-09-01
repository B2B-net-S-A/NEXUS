/**
 * Okres `/insights` w URL-u — JEDNO miejsce dla trzech zakładek.
 *
 * Powstało, bo trzy panele (Rekrutacja, Klienci, Zarząd) miały po własnej
 * kopii tej logiki i wszystkie trzy gubiły to samo: granulacja „Wszystko"
 * (`custom`) niesie `date_from`/`date_to`, a `setPeriod` zapisywał do URL-a
 * wyłącznie `period` i `offset`. Daty przepadały, `custom` nie przechodziło
 * przez listę dozwolonych granulacji i przy najbliższym renderze wracało na
 * „Miesiąc" — przycisk wyglądał na zepsuty, choć każdy pojedynczy kawałek
 * działał. Test pickera tego nie łapał, bo asertował argument `onChange`
 * i nigdy nie przechodził przez URL panelu.
 *
 * Dwie reguły, które ten moduł utrzymuje:
 *
 * 1. **`custom` i `offset` wykluczają się.** Backend zwraca 422 na `offset`
 *    podany razem z jawnym zakresem (`resolve_period`), więc URL nie może
 *    nieść obu naraz.
 * 2. **`custom` bez obu dat nie istnieje.** Sam `?period=custom` skończyłby
 *    się 422 przy pierwszym zapytaniu, więc przy odczycie degradujemy go do
 *    domyślnego miesiąca zamiast wysyłać żądanie skazane na błąd.
 */

import {
  DEFAULT_INSIGHTS_OFFSET,
  type InsightsPeriodKind,
  type InsightsPeriodParams,
} from "@/lib/insights-api";

/** Granulacje dozwolone w URL-u — `custom` WŁĄCZNIE, patrz nagłówek modułu. */
export const INSIGHTS_URL_KINDS: InsightsPeriodKind[] = [
  "week",
  "month",
  "quarter",
  "year",
  "custom",
];

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Domyślne okno, gdy URL nic nie mówi.
 *
 * Ten sam typ co okres, celowo: panel podaje tu DOKŁADNIE tę stałą, którą
 * przekazuje „Resetowi" w `PeriodPicker`. Osobny kształt (`{kind, offset}`)
 * byłby drugą definicją tej samej rzeczy — a wtedy „Reset" i odczyt z URL-a
 * mogą po cichu wskazywać dwa różne okna.
 *
 * Trzy zakładki mają trzy różne domyślne i to NIE jest dług: Zarząd patrzy
 * kwartałami, Rekrutacja miesiącami.
 */
export const INSIGHTS_FALLBACK_PERIOD: InsightsPeriodParams = {
  period: "month",
  offset: DEFAULT_INSIGHTS_OFFSET,
};

/** Odczyt okresu z parametrów URL-a. Nigdy nie rzuca — zawsze da się renderować. */
export function readPeriodFromParams(
  params: URLSearchParams,
  fallback: InsightsPeriodParams = INSIGHTS_FALLBACK_PERIOD,
): InsightsPeriodParams {
  const rawKind = params.get("period");
  const kind = (
    INSIGHTS_URL_KINDS.includes(rawKind as InsightsPeriodKind)
      ? rawKind
      : fallback.period
  ) as InsightsPeriodKind;

  if (kind === "custom") {
    const from = params.get("date_from");
    const to = params.get("date_to");
    if (from && to && ISO_DAY.test(from) && ISO_DAY.test(to)) {
      // Bez `offset` — backend odrzuca go razem z jawnym zakresem.
      return { period: "custom", date_from: from, date_to: to };
    }
    // Niekompletny `custom` to nie jest okres, tylko literówka w linku.
    // Renderujemy okno domyślne zamiast wysyłać żądanie pewne 422.
    return fallback;
  }

  const rawOffset = params.get("offset");
  const fallbackOffset = fallback.offset ?? 0;
  const offset =
    rawOffset === null ? fallbackOffset : Number.parseInt(rawOffset, 10);
  return {
    period: kind,
    offset: Number.isFinite(offset) ? offset : fallbackOffset,
  };
}

/**
 * Zapis okresu do parametrów URL-a — na KOPII, żeby pozostałe parametry
 * (np. `tab`) przetrwały.
 *
 * Parametry nieużywane przez daną granulację są KASOWANE, nie zostawiane:
 * zwietrzały `offset` obok `custom` to 422, a zwietrzałe `date_from` obok
 * `month` to link, który po powrocie znaczy co innego niż w chwili kliknięcia.
 */
export function writePeriodToParams(
  current: URLSearchParams,
  next: InsightsPeriodParams,
): URLSearchParams {
  const params = new URLSearchParams(current.toString());
  params.set("period", next.period);

  if (next.period === "custom" && next.date_from && next.date_to) {
    params.set("date_from", next.date_from);
    params.set("date_to", next.date_to);
    params.delete("offset");
    return params;
  }

  params.delete("date_from");
  params.delete("date_to");
  params.set("offset", String(next.offset ?? 0));
  return params;
}
