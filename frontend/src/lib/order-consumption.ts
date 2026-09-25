/**
 * Okno „Zużycie MD" — lista miesięcy do wyboru (ticket 7, 25.09.2026).
 *
 * Pole „Miesiąc" było pełną datą (`<input type="month">` bywa w przeglądarce
 * kalendarzem dni). Wpis dotyczy MIESIĄCA okresu osoby na zamówieniu, więc
 * lista to miesiące od startu do końca udziału — najwyżej do bieżącego
 * (zużycia za przyszły miesiąc nie ma jeszcze kto raportować).
 */

const MONTHS_PL = [
  "styczeń",
  "luty",
  "marzec",
  "kwiecień",
  "maj",
  "czerwiec",
  "lipiec",
  "sierpień",
  "wrzesień",
  "październik",
  "listopad",
  "grudzień",
];

/** Najwięcej miesięcy na liście — zamówienie bezterminowe z 2019 nie może
 *  zamienić listy w przewijany rok po roku. */
export const MAX_MONTH_OPTIONS = 36;

function monthKey(year: number, monthIndex: number): string {
  return `${year}-${String(monthIndex + 1).padStart(2, "0")}`;
}

function parseIsoMonth(value: string | null | undefined): [number, number] | null {
  const match = value ? /^(\d{4})-(\d{2})/.exec(value) : null;
  if (!match) return null;
  return [Number(match[1]), Number(match[2]) - 1];
}

/** „sierpień 2026" z `YYYY-MM`. */
export function monthLabelPl(period: string): string {
  const parsed = parseIsoMonth(period);
  if (!parsed) return period;
  return `${MONTHS_PL[parsed[1]]} ${parsed[0]}`;
}

export interface MonthOption {
  value: string;
  label: string;
}

/**
 * Miesiące od `start` do `min(end, today)`, od najnowszego. Bez startu —
 * ostatnie 12 miesięcy. Koniec przed startem (dane nie do rozliczenia) daje
 * choćby miesiąc startu, a nie pustą listę bez wyjaśnienia.
 */
export function consumptionMonthOptions(
  start: string | null | undefined,
  end: string | null | undefined,
  today: Date,
): MonthOption[] {
  const todayKey: [number, number] = [today.getFullYear(), today.getMonth()];
  const endParsed = parseIsoMonth(end);
  const last =
    endParsed && (endParsed[0] < todayKey[0] ||
      (endParsed[0] === todayKey[0] && endParsed[1] < todayKey[1]))
      ? endParsed
      : todayKey;
  let first = parseIsoMonth(start);
  if (!first) {
    const back = new Date(last[0], last[1] - 11, 15);
    first = [back.getFullYear(), back.getMonth()];
  }
  const options: MonthOption[] = [];
  let [year, month] = last;
  while (
    options.length < MAX_MONTH_OPTIONS &&
    (year > first[0] || (year === first[0] && month >= first[1]))
  ) {
    const value = monthKey(year, month);
    options.push({ value, label: monthLabelPl(value) });
    month -= 1;
    if (month < 0) {
      month = 11;
      year -= 1;
    }
  }
  if (options.length === 0) {
    const value = monthKey(first[0], first[1]);
    options.push({ value, label: monthLabelPl(value) });
  }
  return options;
}
