// Katalog „Ludzie” wg makiety 19.10.2026 (kanwa „Ludzie i Sprzęt”, n_pe1):
// kolumna „Dziś”, grupy po dziale, staż i pigułka formy. Czyste funkcje —
// testy bez zapytań (`__tests__/directory-view.test.ts`).

import { shortName } from "@/components/hr/leave/leave-format";
import { isFullPerson, type EmploymentType, type Person } from "@/lib/api/hr";
import { formatDayMonthPl, formatWeekdayDayPl } from "@/lib/date-pl";
import { EMPLOYMENT_TERMS } from "@/lib/hr-employment-terms";
import { countPl } from "@/lib/plural-pl";

export type TodayTone = "success" | "info" | "warning" | "neutral";

export interface TodayChip {
  tone: TodayTone;
  label: string;
}

/**
 * Co dziś z osobą. Nieobecność bez rodzaju (D6 — katalog widzi cała firma);
 * słowo formy („przerwa”, „urlop”) tylko, gdy patrzący widzi formę (serwer
 * zwrócił `employment_type`), inaczej „nieobecność”. „W pracy” tylko, gdy
 * patrzący ma otwarty moduł urlopów albo czasu (`known`) — bez nich nie wiemy.
 */
export function todayChips(person: Person, today: string, known: boolean): TodayChip[] {
  const full = isFullPerson(person) ? person : null;
  const chips: TodayChip[] = [];
  const day = person.today ?? null;
  const startsLater = full?.work_start_date && full.work_start_date > today;
  if (startsLater) {
    return [{ tone: "neutral", label: `start ${formatDayMonthPl(full.work_start_date)}` }];
  }
  if (person.employment_status === "pending") {
    return [{ tone: "neutral", label: "przed startem" }];
  }
  if (day?.absent_until) {
    const word = full?.employment_type
      ? EMPLOYMENT_TERMS[full.employment_type].absence_short
      : "nieobecność";
    const when =
      day.absent_until === today
        ? day.half_day
          ? "dziś (pół dnia)"
          : "dziś"
        : `do ${formatWeekdayDayPl(day.absent_until)}`;
    const label = `${word} ${when}`;
    chips.push({
      tone: "info",
      label: day.substitute_name ? `${label} · zastępuje ${shortName(day.substitute_name)}` : label,
    });
  } else if (day?.presence === "business_trip") {
    chips.push({ tone: "neutral", label: "delegacja" });
  } else if (day?.presence === "remote") {
    chips.push({ tone: "success", label: "zdalnie" });
  } else if (known && person.employment_status !== "exited") {
    chips.push({ tone: "success", label: "w pracy" });
  }
  if (person.employment_status === "offboarding") {
    chips.push({
      tone: "warning",
      label: full?.last_working_day
        ? `odchodzi ${formatDayMonthPl(full.last_working_day)}`
        : "odchodzi",
    });
  }
  return chips;
}

/** Osoba nieobecna dziś (filtr „Dziś nieobecni”) — także delegacja (jak w kalendarzu). */
export function isAwayToday(person: Person): boolean {
  return Boolean(person.today?.absent_until) || person.today?.presence === "business_trip";
}

/** Pigułka formy: „B2B”, „UoP”, „Zlecenie · student”; `null` = forma niewidoczna. */
export function formLabel(person: Person): string | null {
  if (!isFullPerson(person)) return null;
  if (person.employment_type_pending) return "uzupełnij";
  if (!person.employment_type) return null;
  const base = FORM_SHORT[person.employment_type];
  return person.employment_type === "zlecenie" && person.student_contribution_exempt
    ? `${base} · student`
    : base;
}

export const FORM_SHORT: Record<EmploymentType, string> = {
  uop: EMPLOYMENT_TERMS.uop.form_short,
  b2b: EMPLOYMENT_TERMS.b2b.form_short,
  zlecenie: "Zlecenie",
};

/** „2 lata”, „8 mies.”, „1 rok 7 mies.” — od startu pracy do dziś (daty „RRRR-MM-DD”). */
export function tenureLabel(start: string | null | undefined, today: string): string | null {
  if (!start) return null;
  const [y1, m1, d1] = start.slice(0, 10).split("-").map(Number);
  const [y2, m2, d2] = today.slice(0, 10).split("-").map(Number);
  if (!y1 || !y2) return null;
  const months = (y2 - y1) * 12 + (m2 - m1) - (d2 < d1 ? 1 : 0);
  if (start > today) return null;
  if (months < 1) return "< 1 mies.";
  const years = Math.floor(months / 12);
  const rest = months % 12;
  if (years === 0) return `${rest} mies.`;
  const yearsText = countPl(years, "rok", "lata", "lat");
  return rest > 0 ? `${yearsText} ${rest} mies.` : yearsText;
}

export const NO_DEPARTMENT = "Bez działu";

export interface DepartmentGroup<T> {
  department: string;
  rows: T[];
}

/** Grupy po dziale (alfabetycznie, „Bez działu” na końcu); kolejność osób zostaje. */
export function groupByDepartment<T extends Pick<Person, "department">>(
  rows: readonly T[],
): DepartmentGroup<T>[] {
  const groups = new Map<string, T[]>();
  for (const row of rows) {
    const key = row.department?.trim() || NO_DEPARTMENT;
    const list = groups.get(key) ?? [];
    list.push(row);
    groups.set(key, list);
  }
  return [...groups.entries()]
    .sort(([a], [b]) =>
      a === NO_DEPARTMENT ? 1 : b === NO_DEPARTMENT ? -1 : a.localeCompare(b, "pl-PL"),
    )
    .map(([department, list]) => ({ department, rows: list }));
}

/** Kolor kropki działu — z palety wykresów (tokeny), stały dla nazwy w obrębie listy. */
const DEPARTMENT_DOTS = ["bg-chart-1", "bg-chart-2", "bg-chart-3", "bg-chart-4", "bg-chart-5"];

export function departmentDot(department: string, departments: readonly string[]): string {
  if (department === NO_DEPARTMENT) return "bg-muted-foreground/40";
  const index = departments.filter((name) => name !== NO_DEPARTMENT).indexOf(department);
  return DEPARTMENT_DOTS[(index < 0 ? 0 : index) % DEPARTMENT_DOTS.length];
}
