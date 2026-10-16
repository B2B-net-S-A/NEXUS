// Wejście i odejście — czyste funkcje do ekranów (bez zapytań, testowalne).

import type {
  AccountCloseResult,
  CaseKind,
  CaseProgress,
  CaseStatus,
} from "@/lib/api/hr-lifecycle";

/** „1 dzień roboczy”, „2 dni robocze”, „5 dni roboczych”. */
export function workingDays(count: number): string {
  const n = Math.abs(count);
  if (n === 1) return "1 dzień roboczy";
  const lastTwo = n % 100;
  const last = n % 10;
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) {
    return `${n} dni robocze`;
  }
  return `${n} dni roboczych`;
}

/** Termin pozycji szablonu: „2 dni robocze przed startem”, „w ostatnim dniu”. */
export function formatOffset(kind: CaseKind, days: number): string {
  if (days === 0) return kind === "onboarding" ? "w dniu startu" : "w ostatnim dniu";
  const anchor = kind === "onboarding" ? "startem" : "ostatnim dniem";
  return days < 0
    ? `${workingDays(days)} przed ${anchor}`
    : `${workingDays(days)} po ${kind === "onboarding" ? "starcie" : "ostatnim dniu"}`;
}

const WEEKDAY = new Intl.DateTimeFormat("pl-PL", { weekday: "short", timeZone: "UTC" });

/** „pon 30.11” — data kalendarzowa (YYYY-MM-DD) bez przesunięcia strefy. */
export function formatDayShort(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number);
  if (!year || !month || !day) return "—";
  const date = new Date(Date.UTC(year, month - 1, day));
  const weekday = WEEKDAY.format(date).replace(".", "");
  return `${weekday} ${day}.${String(month).padStart(2, "0")}`;
}

const MOMENT = new Intl.DateTimeFormat("pl-PL", {
  day: "numeric",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/Warsaw",
});

/** „30.11, 18:00” — chwila w czasie firmy (Warszawa). */
export function formatMoment(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return MOMENT.format(date);
}

export function isLiveStatus(status: CaseStatus): boolean {
  return status === "draft" || status === "active";
}

/** „2 z 6 zadań · 1 po terminie”. */
export function progressLabel(progress: CaseProgress): string {
  if (progress.total === 0) return "bez zadań";
  const base = `${progress.done} z ${progress.total} ${
    progress.total === 1 ? "zadania" : "zadań"
  }`;
  return progress.overdue > 0 ? `${base} · ${progress.overdue} po terminie` : base;
}

export const ACCOUNT_RESULT_LABELS: Record<AccountCloseResult, string> = {
  deactivated: "Konto wyłączone",
  already_inactive: "Konto było już wyłączone",
  skipped_admin: "Konto administratora zostaje — wyłącza je admin ręcznie",
};

/** Czy Kadry mogą już wyłączyć konto ręcznie (dzień wyłączenia minął). */
export function canDeactivateNow(
  deactivateOn: string | null,
  accountClosedAt: string | null,
  status: CaseStatus,
  today: string,
): boolean {
  if (status !== "active" || accountClosedAt || !deactivateOn) return false;
  return today >= deactivateOn.slice(0, 10);
}

/** Dzisiejsza data w kalendarzu firmy (YYYY-MM-DD, Europe/Warsaw). */
export function warsawToday(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Warsaw",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}
