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
  order_group_id?: number | null;
  order_type?: string | null;
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
 * Okres istniejącego zamówienia; zapisany z odwróconymi datami (sprzed blokady)
 * liczy się od wcześniejszej do późniejszej daty — lustro backendu (28.09.2026).
 */
function orderedPeriod(o: ExistingOrderPeriod): [string | null, string | null] {
  const start = iso(o.start_date);
  const end = iso(o.end_date);
  return start && end && start > end ? [end, start] : [start, end];
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
      overlaps(s, e, ...orderedPeriod(o)),
  );
  if (!clash) return null;
  return `Zamówienie ${clash.title} na ten okres już istnieje — popraw istniejące zamiast dodawać drugie.`;
}

function plDay(isoDate: string): string {
  const [y, m, d] = isoDate.split("-");
  return `${d}.${m}.${y}`;
}

function nextDay(isoDate: string): string {
  const d = new Date(`${isoDate}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString().slice(0, 10);
}

/** Statusy zamówień, które naprawdę obowiązują (lustro backendu). */
const OVERLAP_BLOCKING = new Set(["active", "paused", "completed"]);

/**
 * Runda 10 (F15): jedna osoba nie ma dwóch równoległych zamówień okresowych.
 * Lustro 409 `overlapping_order` z backendu (`_assert_no_overlapping_periodic_order`):
 * szkice i anulowane nie blokują, linie zamówień MD/kosztowych też nie,
 * zakończone bez daty końca nie są „otwarte”, odwrócony okres nie blokuje.
 */
export function overlappingOrderError(
  start: string | null | undefined,
  end: string | null | undefined,
  orders: readonly ExistingOrderPeriod[],
  excludeId?: number | null,
): string | null {
  const s = iso(start);
  const e = iso(end);
  if (!s && !e) return null;
  const clash = orders.find((o) => {
    if (o.id === excludeId || !OVERLAP_BLOCKING.has(o.status)) return false;
    if (o.order_group_id != null) return false;
    if (o.order_type && o.order_type !== "periodic") return false;
    const os = iso(o.start_date);
    const oe = iso(o.end_date);
    if (o.status === "completed" && !oe) return false;
    if (os && oe && oe < os) return false;
    return overlaps(s, e, os, oe);
  });
  if (!clash) return null;
  const os = iso(clash.start_date);
  const oe = iso(clash.end_date);
  const period = `${os ? plDay(os) : "—"}–${oe ? plDay(oe) : "bezterminowo"}`;
  const hint = oe
    ? `Zacznij nowe zamówienie od ${plDay(nextDay(oe))} albo najpierw skróć poprzednie.`
    : "Najpierw ustaw datę końca poprzedniego zamówienia.";
  return `Ta osoba ma już zamówienie ${clash.title ?? ""} (${period}), które nakłada się na ten okres. Jedna osoba nie ma dwóch równoległych zamówień. ${hint}`;
}
