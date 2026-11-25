/**
 * Kolejka „Raporty ze strony” (N6, decyzje Artura 25.11.2026) — typy i czysta
 * logika ekranu: stan raportu słowami, licznik do terminu, co wolno zrobić
 * i walidacja poprawionych warunków (lustro `ReportConditions` z backendu).
 *
 * Raport bez reakcji rekrutera wychodzi sam o `send_due_at` (zgłoszenie + 23 h);
 * wstrzymany nie wyjdzie, a kandydat dostał obietnicę raportu w 24 godziny.
 */

export type ReportStatus =
  | "waiting_cv"
  | "ready"
  | "sent"
  | "skipped"
  | "opted_out"
  | "failed";

export type ContractForm = "b2b" | "uop" | "any";
export type WorkMode = "remote" | "hybrid" | "onsite";
export type StartWhen = "now" | "1m" | "2-3m" | "browsing";

export interface PersonRef {
  id: number;
  name: string;
}

export interface ReportConditions {
  rate: number;
  current_rate?: number | null;
  contract: ContractForm;
  modes: WorkMode[];
  office_days_max?: number | null;
  office_cities: string[];
  start?: StartWhen | null;
}

export interface ReportListItem {
  id: number;
  candidate: PersonRef;
  role_label: string | null;
  conditions_summary: string;
  status: ReportStatus;
  owner: PersonRef | null;
  created_at: string;
  send_due_at: string;
  hours_left: number;
  held: boolean;
  held_at: string | null;
  sent_at: string | null;
}

export interface ReportDetail extends ReportListItem {
  email: string;
  conditions: ReportConditions;
  snapshot: Record<string, unknown> | null;
  preview_subject: string | null;
  preview_html: string | null;
  held_by: PersonRef | null;
  sent_by: PersonRef | null;
  ready_at: string | null;
  attempts: number;
  last_error: string | null;
  warning: string | null;
  owner_choices: PersonRef[];
}

export type ReportScope = "mine" | "all";
/** `open` = czeka na wysyłkę (waiting_cv, ready, failed); `""` = wszystkie. */
export type ReportStatusFilter = "open" | "sent" | "";

export type ChipTone = "neutral" | "info" | "success" | "warning" | "danger";

export const STATUS_LABELS: Record<ReportStatus, string> = {
  waiting_cv: "Czeka na CV",
  ready: "Gotowy",
  sent: "Wysłany",
  skipped: "Bez raportu",
  opted_out: "Wypisany",
  failed: "Błąd wysyłki",
};

const STATUS_TONES: Record<ReportStatus, ChipTone> = {
  waiting_cv: "neutral",
  ready: "info",
  sent: "success",
  skipped: "neutral",
  opted_out: "neutral",
  failed: "danger",
};

export interface StatusChip {
  label: string;
  tone: ChipTone;
}

/** Chipy stanu: stan raportu i — osobno — „Wstrzymany”. */
export function statusChips(report: Pick<ReportListItem, "status" | "held">): StatusChip[] {
  const chips: StatusChip[] = [
    {
      label: STATUS_LABELS[report.status] ?? "Nieznany stan",
      tone: STATUS_TONES[report.status] ?? "neutral",
    },
  ];
  if (report.held && isOpen(report.status)) {
    chips.push({ label: "Wstrzymany", tone: "warning" });
  }
  return chips;
}

const OPEN: readonly ReportStatus[] = ["waiting_cv", "ready", "failed"];

export function isOpen(status: ReportStatus): boolean {
  return OPEN.includes(status);
}

export function canSendNow(report: Pick<ReportDetail, "status" | "snapshot">): boolean {
  return (report.status === "ready" || report.status === "failed") && report.snapshot != null;
}

export function canHold(report: Pick<ReportListItem, "status" | "held">): boolean {
  return isOpen(report.status) && !report.held;
}

export function canRelease(report: Pick<ReportListItem, "status" | "held">): boolean {
  return isOpen(report.status) && report.held;
}

export function canEdit(report: Pick<ReportListItem, "status">): boolean {
  return isOpen(report.status);
}

export type DeadlineTone = "late" | "soon" | "ok" | "done";

export interface Deadline {
  text: string;
  tone: DeadlineTone;
}

/** Poniżej tylu godzin termin świeci ostrzegawczo. */
export const SOON_HOURS = 3;

function spanText(totalMinutes: number): string {
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours === 0) return `${minutes} min`;
  if (minutes === 0) return `${hours} h`;
  return `${hours} h ${minutes} min`;
}

/**
 * Licznik do terminu wysyłki: „za 5 h 20 min”, „po terminie 40 min”.
 * Raport już rozstrzygnięty (wysłany, wypisany, bez raportu) nie ma licznika.
 */
export function formatDeadline(
  report: Pick<ReportListItem, "status" | "send_due_at" | "held">,
  now: Date = new Date(),
): Deadline {
  if (!isOpen(report.status)) return { text: "—", tone: "done" };
  const due = new Date(report.send_due_at).getTime();
  if (Number.isNaN(due)) return { text: "—", tone: "done" };
  const diffMinutes = Math.round((due - now.getTime()) / 60_000);
  if (diffMinutes <= 0) {
    return { text: `po terminie ${spanText(-diffMinutes)}`, tone: "late" };
  }
  const text = `za ${spanText(diffMinutes)}`;
  // Wstrzymany raport nie wyjdzie sam — bliski termin jest tym pilniejszy.
  if (diffMinutes < SOON_HOURS * 60 || report.held) return { text, tone: "soon" };
  return { text, tone: "ok" };
}

export const CONTRACT_OPTIONS: { value: ContractForm; label: string }[] = [
  { value: "b2b", label: "B2B" },
  { value: "uop", label: "UoP" },
  { value: "any", label: "Obojętnie" },
];

export const MODE_OPTIONS: { value: WorkMode; label: string }[] = [
  { value: "remote", label: "Zdalnie" },
  { value: "hybrid", label: "Hybrydowo" },
  { value: "onsite", label: "W biurze" },
];

export const START_OPTIONS: { value: StartWhen; label: string }[] = [
  { value: "now", label: "Od zaraz" },
  { value: "1m", label: "Za miesiąc" },
  { value: "2-3m", label: "Za 2–3 miesiące" },
  { value: "browsing", label: "Rozgląda się" },
];

/** Formularz trzyma liczby jako tekst — tak, jak je wpisuje rekruter. */
export interface ConditionsDraft {
  rate: string;
  current_rate: string;
  contract: ContractForm;
  modes: WorkMode[];
  office_days_max: string;
  office_cities: string;
  start: StartWhen | "";
}

export function draftFromConditions(c: ReportConditions): ConditionsDraft {
  return {
    rate: String(c.rate),
    current_rate: c.current_rate != null ? String(c.current_rate) : "",
    contract: c.contract,
    modes: [...c.modes],
    office_days_max: c.office_days_max != null ? String(c.office_days_max) : "",
    office_cities: c.office_cities.join(", "),
    start: c.start ?? "",
  };
}

function parseIntIn(raw: string, min: number, max: number): number | null | "invalid" {
  const value = raw.trim();
  if (value === "") return null;
  if (!/^\d+$/.test(value)) return "invalid";
  const n = Number(value);
  return n < min || n > max ? "invalid" : n;
}

export type ConditionsResult =
  | { ok: true; body: ReportConditions }
  | { ok: false; errors: Partial<Record<keyof ConditionsDraft, string>> };

/** Te same granice co `ReportConditions` w backendzie (stawka 1–2000, dni 0–5). */
export function conditionsFromDraft(draft: ConditionsDraft): ConditionsResult {
  const errors: Partial<Record<keyof ConditionsDraft, string>> = {};
  const rate = parseIntIn(draft.rate, 1, 2000);
  const current = parseIntIn(draft.current_rate, 1, 2000);
  const days = parseIntIn(draft.office_days_max, 0, 5);
  if (rate === null || rate === "invalid") errors.rate = "Stawka to liczba od 1 do 2000 zł/h.";
  if (current === "invalid") errors.current_rate = "Obecna stawka to liczba od 1 do 2000 zł/h.";
  if (days === "invalid") errors.office_days_max = "Dni w biurze: od 0 do 5.";
  if (Object.keys(errors).length > 0) return { ok: false, errors };
  const cities = draft.office_cities
    .split(",")
    .map((city) => city.trim())
    .filter((city, i, all) => city !== "" && all.indexOf(city) === i);
  return {
    ok: true,
    body: {
      rate: rate as number,
      current_rate: current as number | null,
      contract: draft.contract,
      modes: MODE_OPTIONS.map((o) => o.value).filter((m) => draft.modes.includes(m)),
      office_days_max: days as number | null,
      office_cities: cities,
      start: draft.start === "" ? null : draft.start,
    },
  };
}

const DATE_TIME = new Intl.DateTimeFormat("pl-PL", {
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/Warsaw",
});

/** „26.11, 14:05” w czasie firmy. */
export function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "—" : DATE_TIME.format(date);
}
