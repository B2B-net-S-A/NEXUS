/**
 * Podgląd lat w siatce okna formularza CV klienta (19.11.2026).
 *
 * Wartość pola liczy serwer (`client_form_years.recompute`) — tu ta sama
 * arytmetyka tylko po to, żeby kolumna „Lata” zmieniała się od razu po
 * kliknięciu roli, zanim rekruter zapisze siatkę: suma przedziałów
 * (nakładki raz), „obecnie” do bieżącego miesiąca, rok bez miesiąca od
 * stycznia na starcie i do grudnia na końcu.
 */
import type { ClientFormYears, ClientFormYearsRole } from "@/lib/api/clientForms";
import { warsawToday } from "@/lib/warsaw-date";

function parse(value: string | null): [number, number | null] | null {
  const match = value ? /^(\d{4})(?:-(\d{2}))?$/.exec(value) : null;
  return match ? [Number(match[1]), match[2] ? Number(match[2]) : null] : null;
}

export function currentMonthIndex(today: string = warsawToday()): number {
  const [year, month] = today.split("-").map(Number);
  return year * 12 + month - 1;
}

export function unionMonths(roles: Pick<ClientFormYearsRole, "start" | "end">[], now: number): number {
  const bounds: [number, number][] = [];
  for (const role of roles) {
    const start = parse(role.start);
    if (!start) continue;
    const first = start[0] * 12 + (start[1] ?? 1) - 1;
    const end = parse(role.end);
    const last = Math.min(end ? end[0] * 12 + (end[1] ?? 12) - 1 : now, now);
    if (last >= first) bounds.push([first, last]);
  }
  bounds.sort((a, b) => a[0] - b[0]);
  let total = 0;
  let current: [number, number] | null = null;
  for (const [first, last] of bounds) {
    if (current && first <= current[1] + 1) current = [current[0], Math.max(current[1], last)];
    else {
      if (current) total += current[1] - current[0] + 1;
      current = [first, last];
    }
  }
  return current ? total + current[1] - current[0] + 1 : total;
}

function yearsWord(years: number): string {
  if (years === 1) return "rok";
  const last = years % 10;
  const lastTwo = years % 100;
  return last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14) ? "lata" : "lat";
}

/** „3 lata 8 mies.”, „1 rok”, „5 mies.” — jak `cv_tenure_checks.months_text`. */
export function monthsText(months: number): string {
  const years = Math.floor(Math.max(months, 0) / 12);
  const rest = Math.max(months, 0) % 12;
  if (!years) return `${rest} mies.`;
  return rest ? `${years} ${yearsWord(years)} ${rest} mies.` : `${years} ${yearsWord(years)}`;
}

/** Wartość pola dla wybranych ról: lata, lata ponad minimum albo punkty. */
export function previewValue(years: ClientFormYears, on: Set<string>, now: number): string | null {
  const months = unionMonths(
    years.basis.filter((role) => on.has(role.key)),
    now,
  );
  if (!months || years.minimum_unknown) return null;
  if (years.kind === "points") {
    const best = years.thresholds.reduce(
      (acc, row) => (months >= row.years * 12 ? Math.max(acc, row.points) : acc),
      0,
    );
    return String(Math.min(best, years.max_points ?? best));
  }
  if (years.minimum_months) {
    const over = months - years.minimum_months;
    return over > 0 ? monthsText(over) : null;
  }
  return monthsText(months);
}
