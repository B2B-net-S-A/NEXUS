/**
 * Statystyki sprzed 12.10.2026 — skąd są liczby (decyzje Artura 17 i 18.10.2026).
 *
 * Zespół klika w NEXUS-ie od 12.10.2026. Wcześniejsze dni backend liczy
 * wyłącznie z DynaReportera; czego DynaReporter nie prowadził, tego nie ma
 * (do uzupełnienia), a nie „0 z Tablicy”. Ta funkcja mówi, czy okno ekranu
 * zaczyna się przed tym dniem, żeby ekran to napisał.
 */
import type { InsightsPeriodParams } from "@/lib/insights-api";

/** Pierwszy dzień, który liczy NEXUS (`competition_history.RESULTS_CUTOVER`). */
export const NEXUS_FIRST_DAY = "2026-10-12";

export const INSIGHTS_HISTORY_NOTE =
  "Dni do 11.10.2026 pochodzą z DynaReportera: od 2026 weryfikacje, rekomendacje, " +
  "rozmowy u klienta, placementy i wpisy Delivery Leadów, przed 2026 tylko placementy " +
  "firmy i klientów. Etapów Tablicy, źródeł, czasu do zatrudnienia ani hit ratio " +
  "DynaReporter nie prowadził — te liczby zaczynają się 12.10.2026, wcześniejsze " +
  "dni są do uzupełnienia.";

interface ResolvedStart {
  start: string;
}

function warsawToday(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Warsaw",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function iso(year: number, month: number, day: number): string {
  const d = new Date(Date.UTC(year, month - 1, day));
  return d.toISOString().slice(0, 10);
}

/** Pierwszy dzień okna (YYYY-MM-DD, kalendarz Warszawy) albo `null`. */
export function windowStartDay(
  value: InsightsPeriodParams,
  resolved?: ResolvedStart | null,
  today: string = warsawToday(),
): string | null {
  if (resolved?.start) return resolved.start.slice(0, 10);
  if (value.period === "custom") return value.date_from ?? null;
  const reference = value.anchor ?? today;
  const [y, m, d] = reference.split("-").map(Number);
  if (!y || !m || !d) return null;
  // Z kotwicą okres jest wskazany wprost — przesunięcie liczy się od teraz.
  const offset = value.anchor ? 0 : (value.offset ?? 0);
  switch (value.period) {
    case "day":
      return iso(y, m, d + offset);
    case "week": {
      const weekday = (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7;
      return iso(y, m, d - weekday + 7 * offset);
    }
    case "month":
      return iso(y, m + offset, 1);
    case "quarter":
      return iso(y, Math.floor((m - 1) / 3) * 3 + 1 + 3 * offset, 1);
    case "year":
      return iso(y + offset, 1, 1);
    default:
      return null;
  }
}

/** Czy okno ekranu zaczyna się przed 12.10.2026 (część liczb z DynaReportera). */
export function startsBeforeNexus(
  value: InsightsPeriodParams,
  resolved?: ResolvedStart | null,
  today?: string,
): boolean {
  const start = windowStartDay(value, resolved, today);
  return start !== null && start < NEXUS_FIRST_DAY;
}
