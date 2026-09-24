/**
 * Sprawdzenie okresu i duplikatu zamówienia przed ręcznym zapisem.
 *
 * Ticket OIT/0569/2026/ITVM (24.09.2026): „Dodaj przedłużenie” podpowiadało
 * start „dzień po ostatnim zamówieniu”, a ostatnim było już przyszłe
 * zamówienie 01.10–31.12.2026 — powstało drugie zamówienie o tym samym
 * numerze z okresem 01.01.2027 → 31.12.2026. Backend odrzuca oba przypadki
 * (422 / 409); te funkcje mówią to przy polu, zanim formularz wyśle żądanie.
 */

const ISO = /^\d{4}-\d{2}-\d{2}$/;

function iso(value: string | null | undefined): string | null {
  const v = (value ?? "").trim().slice(0, 10);
  return ISO.test(v) ? v : null;
}

export const ORDER_PERIOD_REVERSED_MESSAGE =
  "Data końca zamówienia jest wcześniejsza niż data startu — popraw okres.";

/** Komunikat, gdy koniec jest przed startem; `null`, gdy okres jest poprawny albo niepełny. */
export function orderPeriodError(
  start: string | null | undefined,
  end: string | null | undefined,
): string | null {
  const s = iso(start);
  const e = iso(end);
  if (!s || !e) return null;
  return e < s ? ORDER_PERIOD_REVERSED_MESSAGE : null;
}

export interface ExistingOrderPeriod {
  id: number;
  title: string | null;
  status: string;
  start_date: string | null;
  end_date: string | null;
}

function normalizeNumber(title: string | null | undefined): string {
  return (title ?? "").trim().replace(/\s+/g, " ").toUpperCase();
}

function overlaps(
  aStart: string | null,
  aEnd: string | null,
  bStart: string | null,
  bEnd: string | null,
): boolean {
  // Brak daty = otwarte w tę stronę.
  const startsBeforeOtherEnds = !aStart || !bEnd || aStart <= bEnd;
  const endsAfterOtherStarts = !aEnd || !bStart || aEnd >= bStart;
  return startsBeforeOtherEnds && endsAfterOtherStarts;
}

/**
 * Komunikat, gdy ta osoba ma już nieanulowane zamówienie o tym samym numerze
 * na nachodzący okres (lustro 409 `duplicate_order_number` z backendu).
 */
export function duplicateOrderError(
  title: string | null | undefined,
  start: string | null | undefined,
  end: string | null | undefined,
  orders: readonly ExistingOrderPeriod[],
  excludeId?: number | null,
): string | null {
  const number = normalizeNumber(title);
  // Zaślepka „(bez numeru)” nie jest numerem — szkiców bez numeru bywa kilka.
  if (!number || number === "(BEZ NUMERU)") return null;
  const s = iso(start);
  const e = iso(end);
  const clash = orders.find(
    (o) =>
      o.id !== excludeId &&
      o.status !== "cancelled" &&
      normalizeNumber(o.title) === number &&
      overlaps(s, e, iso(o.start_date), iso(o.end_date)),
  );
  if (!clash) return null;
  return `Zamówienie ${clash.title} na ten okres już istnieje — popraw istniejące zamiast dodawać drugie.`;
}
