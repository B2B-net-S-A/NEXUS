export const DATE_PLACEHOLDER = "RRRR-MM-DD lub DD.MM.RRRR";
export const DATE_PATTERN =
  "\\d{4}-\\d{1,2}-\\d{1,2}|\\d{4}\\.\\d{1,2}\\.\\d{1,2}|\\d{1,2}-\\d{1,2}-\\d{4}|\\d{1,2}\\.\\d{1,2}\\.\\d{4}|\\d{1,2}/\\d{1,2}/\\d{4}";

const YEAR_FIRST_DATE = /^(\d{4})([-.])(\d{1,2})\2(\d{1,2})$/;
const DAY_FIRST_DATE = /^(\d{1,2})([-./])(\d{1,2})\2(\d{4})$/;

function isLeapYear(year: number): boolean {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
}

function isValidDate(year: number, month: number, day: number): boolean {
  if (year < 1 || month < 1 || month > 12 || day < 1) return false;

  const daysInMonth = [31, isLeapYear(year) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return day <= daysInMonth[month - 1];
}

/**
 * Parses the date formats accepted when pasting into Nexus date fields.
 * Day-first inputs always use the Polish DD-MM-YYYY convention.
 */
export function parseDateInput(input: string): string | null {
  const trimmed = input.trim();
  if (!trimmed) return null;

  const yearFirst = trimmed.match(YEAR_FIRST_DATE);
  const dayFirst = trimmed.match(DAY_FIRST_DATE);

  let year: number;
  let month: number;
  let day: number;

  if (yearFirst) {
    year = Number(yearFirst[1]);
    month = Number(yearFirst[3]);
    day = Number(yearFirst[4]);
  } else if (dayFirst) {
    day = Number(dayFirst[1]);
    month = Number(dayFirst[3]);
    year = Number(dayFirst[4]);
  } else {
    return null;
  }

  if (!isValidDate(year, month, day)) return null;

  return [
    String(year).padStart(4, "0"),
    String(month).padStart(2, "0"),
    String(day).padStart(2, "0"),
  ].join("-");
}

export function normalizeDateInput(input: string): string {
  const trimmed = input.trim();
  if (!trimmed) return "";
  return parseDateInput(trimmed) ?? trimmed;
}
