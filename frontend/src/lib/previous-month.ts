import { warsawToday } from "@/lib/warsaw-date";

export interface MonthRange {
  from: string;
  to: string;
}

/** Poprzedni miesiąc w kalendarzu firmy: „RRRR-MM” i pierwszy oraz ostatni dzień. */
export function previousMonth(today: string = warsawToday()): MonthRange & { key: string } {
  const [year, month] = today.split("-").map(Number);
  const prevYear = month === 1 ? year - 1 : year;
  const prevMonth = month === 1 ? 12 : month - 1;
  const lastDay = new Date(Date.UTC(prevYear, prevMonth, 0)).getUTCDate();
  const mm = String(prevMonth).padStart(2, "0");
  return {
    key: `${prevYear}-${mm}`,
    from: `${prevYear}-${mm}-01`,
    to: `${prevYear}-${mm}-${String(lastDay).padStart(2, "0")}`,
  };
}
