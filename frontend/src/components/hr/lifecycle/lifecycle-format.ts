// Wejście i odejście — czyste funkcje do ekranów (bez zapytań, testowalne).

import type { StatusDotTone } from "@/components/ds/StatusDot";
import type {
  AccountCloseResult,
  CaseKind,
  CaseProgress,
  CaseStatus,
} from "@/lib/api/hr-lifecycle";
import { countPl } from "@/lib/plural-pl";

/** „1 dzień roboczy”, „2 dni robocze”, „5 dni roboczych” (liczba bez znaku). */
export function workingDays(count: number): string {
  return countPl(Math.abs(count), "dzień roboczy", "dni robocze", "dni roboczych");
}

/** Termin pozycji szablonu: „2 dni robocze przed startem”, „w ostatnim dniu”. */
export function formatOffset(kind: CaseKind, days: number): string {
  if (days === 0) return kind === "onboarding" ? "w dniu startu" : "w ostatnim dniu";
  const anchor = kind === "onboarding" ? "startem" : "ostatnim dniem";
  return days < 0
    ? `${workingDays(days)} przed ${anchor}`
    : `${workingDays(days)} po ${kind === "onboarding" ? "starcie" : "ostatnim dniu"}`;
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

/** Kolor statusu sprawy wejścia i odejścia — ten sam w kartotece, sprawie i odejściu. */
export const CASE_STATUS_TONE: Record<CaseStatus, StatusDotTone> = {
  draft: "neutral",
  active: "info",
  done: "success",
  cancelled: "neutral",
};

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

/** „1 osoba”, „3 osoby”, „5 osób”. */
export function peopleCount(count: number): string {
  return countPl(Math.abs(count), "osoba", "osoby", "osób");
}

interface ReportsRowLike {
  kind: string;
  count: number | null;
  planned_count: number | null;
  receiver_name: string | null;
  status: string | null;
  result: Record<string, number> | null;
}

/**
 * Zdanie o podwładnych odchodzącej osoby (wiersz „Podwładni” przekazania, D5).
 * `null` — nie ma podwładnych albo liczby (lista spraw liczy je tylko w szczegółach).
 */
export function reportsSummary(rows: readonly ReportsRowLike[]): string | null {
  const row = rows.find((item) => item.kind === "reports");
  if (!row) return null;
  if (row.status === "done") {
    const moved = row.result?.people ?? row.planned_count ?? 0;
    if (!moved) return null;
    return `Podwładni przekazani (${peopleCount(moved)}) — ich przełożonym jest ${
      row.receiver_name ?? "wskazana osoba"
    }.`;
  }
  if (!row.count) return null;
  if (!row.receiver_name) {
    return `Podwładni: ${peopleCount(row.count)}. Wskaż, kto zostanie ich przełożonym — bez tego przekazanie nie przejdzie, a konto nie wyłączy się samo.`;
  }
  return `Podwładni: ${peopleCount(row.count)}. Po przekazaniu ich przełożonym będzie ${row.receiver_name} — od tej chwili wnioski i timesheety idą do tej osoby.`;
}

const CONDITION_FORM_LABELS: Record<string, string> = {
  uop: "UoP",
  b2b: "B2B",
  zlecenie: "zlecenie",
};

interface ConditionsLike {
  employment_types?: readonly string[];
  equipment?: "ours" | "client" | null;
  student?: boolean | null;
}

/** Kolumna „Warunek” ścieżki: „B2B · sprzęt od nas · student”; pusto = zawsze. */
export function conditionSummary(conditions: ConditionsLike | null | undefined): string {
  if (!conditions) return "";
  const parts: string[] = [];
  const forms = conditions.employment_types ?? [];
  if (forms.length) parts.push(forms.map((form) => CONDITION_FORM_LABELS[form] ?? form).join(", "));
  if (conditions.equipment === "ours") parts.push("sprzęt od nas");
  if (conditions.equipment === "client") parts.push("sprzęt od klienta");
  if (conditions.student) parts.push("student");
  return parts.join(" · ");
}

/** Baner „Dociągnij”: „3 trwające wejścia są na starszej wersji”. */
export function behindLabel(count: number, kind: CaseKind): string {
  const noun =
    kind === "onboarding"
      ? countPl(count, "trwające wejście jest", "trwające wejścia są", "trwających wejść jest")
      : countPl(count, "trwające odejście jest", "trwające odejścia są", "trwających odejść jest");
  return `${noun} na starszej wersji tej ścieżki.`;
}
