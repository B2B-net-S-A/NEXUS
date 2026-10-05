// Zmiana stawki kandydata w trakcie procesu (0418, decyzje Artura 04.10.2026).
//
// Serwer (`services/candidate_rate_change.py`) zapisuje stawkę, ślad i wysyła
// powiadomienia: od „Zweryfikowany” dzwonek DL i Head of Recruitment, a wzrost
// po wysłaniu CV to zadanie DL. Tu tylko typy, wywołania i teksty ekranu.

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

export type RateChangeStatus =
  | "noted"
  | "requested"
  | "negotiating"
  | "agreed"
  | "closed"
  | "superseded";

export type RateChangeReason = "conversation" | "email" | "typo" | "other";
export type RateNegotiable = "no" | "maybe" | "unknown";
export type RateChangeUnit = "hourly" | "daily" | "monthly";

export interface RateValue {
  amount: string | number;
  unit: string | null;
  currency: string;
  hourly: string | number | null;
  label: string;
}

export interface RateChange {
  id: number;
  status: RateChangeStatus;
  requires_decision: boolean;
  board_column: string | null;
  previous: RateValue | null;
  requested: RateValue;
  agreed: RateValue | null;
  source: string;
  source_label: string;
  reason: RateChangeReason;
  reason_label: string;
  note: string | null;
  negotiable: RateNegotiable | null;
  created_at: string;
  created_by_name: string | null;
  negotiator_id: number | null;
  negotiator_name: string | null;
  negotiation_target_hourly: string | number | null;
  negotiation_due: string | null;
  outcome: string | null;
  outcome_note: string | null;
  decision: string | null;
  decided_at: string | null;
  decided_by_name: string | null;
  /** Czy oglądający może zapisać wynik negocjacji tej sprawy. */
  can_record_outcome?: boolean;
}

export interface NegotiatorOption {
  id: number;
  name: string;
  role_label: string;
}

export interface RateChangesView {
  candidate_id: number;
  job_id: number;
  current: RateValue | null;
  board_column: string | null;
  notifies: boolean;
  cv_at_client: boolean;
  client_rate: RateValue | null;
  changes: RateChange[];
  /** Zlecenie negocjacji: DL rekrutacji, Head of Recruitment, admin. */
  can_manage?: boolean;
  /** Decyzja o stawce do klienta: DL rekrutacji albo admin. */
  can_decide?: boolean;
  negotiator_options?: NegotiatorOption[];
}

export type RateOutcome = "lower" | "kept" | "withdrew";
export type RateDecision = "raise_client" | "keep_client" | "withdraw";

/** Sprawa w „Czeka na Ciebie” (`rate_changes`, `rate_changes_by_others`). */
export interface RateChangeTaskRow {
  change_id: number;
  reason: "decide" | "negotiate" | "waiting";
  status: RateChangeStatus;
  candidate_id: number;
  candidate_name: string;
  job_id: number;
  job_title: string;
  client_name: string | null;
  previous_label: string | null;
  requested_label: string;
  agreed_label: string | null;
  negotiator_name: string | null;
  negotiation_due: string | null;
  since: string;
  waiting_on: string | null;
}

/** Plakietka otwartej sprawy na karcie Tablicy (`rate_change` w kanbanie). */
export interface RateChangeBadge {
  id: number;
  status: RateChangeStatus;
  requires_decision: boolean;
  previous_hourly: number | null;
  requested_hourly: number | null;
  requested_label: string;
  agreed_hourly: number | null;
  negotiator_name: string | null;
  negotiation_due: string | null;
  created_at: string | null;
}

export interface RateChangeInput {
  candidate_id: number;
  job_id: number;
  amount: string;
  unit: RateChangeUnit;
  currency?: string;
  reason: RateChangeReason;
  note?: string | null;
  negotiable?: RateNegotiable | null;
  /** „profile” — okno stawki w profilu pyta o trwające procesy (D4). */
  source?: "manual" | "profile";
}

/** Rekrutacja kandydata od „Zweryfikowany” (okno stawki w profilu). */
export interface ActiveProcess {
  job_id: number;
  job_title: string;
  client_name: string | null;
  board_column: string;
  current_label: string | null;
}

export const activeProcessesQueryKey = (candidateId: number) =>
  ["rate-changes", "active-processes", candidateId] as const;

export const rateChangesQueryKey = (candidateId: number, jobId: number) =>
  ["rate-changes", candidateId, jobId] as const;

export const rateChangesApi = {
  get: (candidateId: number, jobId: number) =>
    api
      .get<RateChangesView>("/api/rate-changes", {
        params: { candidate_id: candidateId, job_id: jobId },
      })
      .then((r) => r.data),
  create: (input: RateChangeInput) =>
    api
      .post<{ unchanged: boolean; change: RateChange | null }>("/api/rate-changes", input)
      .then((r) => r.data),
  activeProcesses: (candidateId: number) =>
    api
      .get<ActiveProcess[]>("/api/rate-changes/active-processes", {
        params: { candidate_id: candidateId },
      })
      .then((r) => r.data),
  negotiate: (
    changeId: number,
    body: { negotiator_id: number; target_hourly?: string | null; due?: string | null },
  ) => api.post<RateChange>(`/api/rate-changes/${changeId}/negotiation`, body).then((r) => r.data),
  outcome: (
    changeId: number,
    body: { outcome: RateOutcome; agreed_amount?: string | null; note?: string | null },
  ) => api.post<RateChange>(`/api/rate-changes/${changeId}/outcome`, body).then((r) => r.data),
  decide: (
    changeId: number,
    body: { decision: RateDecision; client_rate?: { amount: string; unit?: string } | null },
  ) => api.post<RateChange>(`/api/rate-changes/${changeId}/decision`, body).then((r) => r.data),
};

const OPEN: RateChangeStatus[] = ["requested", "negotiating", "agreed"];

/** Otwarta sprawa pary (najnowsza), `null` gdy nic nie czeka. */
export function openRateChange(view: RateChangesView | null | undefined): RateChange | null {
  return view?.changes.find((c) => OPEN.includes(c.status)) ?? null;
}

/** Jedno zdanie o otwartej sprawie: „Kandydat chce 130 zł/h (było 110 zł/h) · czeka na DL”. */
export function openCaseLine(change: RateChange): string {
  const was = change.previous ? ` (było ${change.previous.label})` : "";
  const parts = [`Kandydat chce ${change.requested.label}${was}`];
  if (change.status === "negotiating") {
    const who = change.negotiator_name ? ` — rozmawia ${change.negotiator_name}` : "";
    const due = change.negotiation_due ? ` do ${dayMonth(change.negotiation_due)}` : "";
    parts.push(`w negocjacji${who}${due}`);
  } else if (change.status === "agreed") {
    parts.push(`ustalona ${change.agreed?.label ?? "?"} · decyzja o stawce do klienta należy do DL`);
  } else {
    parts.push(change.requires_decision ? "CV jest u klienta — czeka na decyzję DL" : "zgłoszona");
  }
  return parts.join(" · ");
}

/** Podpowiedź nowej stawki do klienta: obecna + różnica stawki kandydata. */
export function suggestedClientRate(
  clientRate: RateValue | null | undefined,
  change: RateChange,
): string {
  const client = clientRate?.hourly != null ? Number(clientRate.hourly) : null;
  const from = change.previous?.hourly != null ? Number(change.previous.hourly) : null;
  const to = (change.agreed ?? change.requested).hourly;
  const toN = to != null ? Number(to) : null;
  if (client == null || from == null || toN == null) return "";
  const next = Math.round((client + (toN - from)) * 100) / 100;
  return next > 0 ? String(next) : "";
}

export function rateTaskLine(row: RateChangeTaskRow): string {
  const was = row.previous_label ? `${row.previous_label} → ` : "";
  const agreed = row.agreed_label ? ` · ustalona ${row.agreed_label}` : "";
  return `${was}${row.requested_label}${agreed}`;
}

export function useRateChanges(candidateId: number | null, jobId: number | null) {
  return useQuery({
    queryKey: rateChangesQueryKey(candidateId ?? 0, jobId ?? 0),
    enabled: candidateId != null && jobId != null,
    queryFn: () => rateChangesApi.get(candidateId as number, jobId as number),
    staleTime: 15_000,
  });
}

export const REASON_OPTIONS: { value: RateChangeReason; label: string }[] = [
  { value: "conversation", label: "Rozmowa z kandydatem" },
  { value: "email", label: "Mail od kandydata" },
  { value: "typo", label: "Pomyłka przy wpisie" },
  { value: "other", label: "Inne" },
];

export const NEGOTIABLE_OPTIONS: { value: RateNegotiable; label: string }[] = [
  { value: "no", label: "Nie, to jego minimum" },
  { value: "maybe", label: "Możliwe, warto porozmawiać" },
  { value: "unknown", label: "Nie wiem" },
];

const STATUS_LABEL: Record<RateChangeStatus, string> = {
  noted: "zmieniona",
  requested: "czeka na DL",
  negotiating: "w negocjacji",
  agreed: "ustalona",
  closed: "zamknięta",
  superseded: "zastąpiona",
};

export function rateChangeStatusLabel(status: RateChangeStatus): string {
  return STATUS_LABEL[status] ?? status;
}

/** Plakietka na karcie: „stawka ↑ czeka na DL”, „w negocjacji · Anna do 06.10”. */
export function rateChangeBadgeText(badge: RateChangeBadge): string {
  if (badge.status === "negotiating") {
    const who = badge.negotiator_name ? ` · ${badge.negotiator_name}` : "";
    const due = badge.negotiation_due ? ` do ${dayMonth(badge.negotiation_due)}` : "";
    return `w negocjacji${who}${due}`;
  }
  if (badge.status === "agreed") {
    return `ustalona ${amount(badge.agreed_hourly)} zł/h · decyzja DL`;
  }
  const arrow =
    badge.previous_hourly != null && badge.requested_hourly != null
      ? badge.requested_hourly > badge.previous_hourly
        ? "↑"
        : "↓"
      : "";
  return `stawka ${arrow} czeka na DL`.replace("  ", " ");
}

function amount(value: number | string | null | undefined): string {
  if (value == null) return "?";
  const n = Number(value);
  return Number.isFinite(n) ? n.toLocaleString("pl-PL", { maximumFractionDigits: 2 }) : "?";
}

export function rateArrowLine(badge: RateChangeBadge): string | null {
  if (badge.previous_hourly == null || badge.requested_hourly == null) return null;
  return `${amount(badge.previous_hourly)} → ${amount(badge.requested_hourly)} zł/h`;
}

function dayMonth(iso: string): string {
  const [, m, d] = iso.split("-");
  return d && m ? `${d}.${m}` : iso;
}

/**
 * Zdanie pod polem stawki: kto dostanie informację. Liczy z odpowiedzi
 * serwera (kolumna Tablicy), więc nie zgaduje etapu na froncie.
 */
export function notifyLine(
  view: Pick<RateChangesView, "notifies" | "cv_at_client"> | null | undefined,
  { rising, reason }: { rising: boolean | null; reason: RateChangeReason },
): string {
  if (!view) return "";
  if (!view.notifies) {
    return "Kandydat jest przed weryfikacją — zmiana zapisze się w historii stawek bez powiadomień.";
  }
  const base = "Zapis od razu powiadomi Delivery Leada rekrutacji i Head of Recruitment.";
  if (view.cv_at_client && rising !== false && reason !== "typo") {
    return `${base} CV jest już u klienta, więc przy wyższej stawce DL dostanie zadanie: renegocjować z kandydatem albo zdecydować o stawce do klienta.`;
  }
  return base;
}

/** Stawka w zł/h z kwoty i jednostki (MD ÷ 8, miesiąc ÷ 168) — do porównania. */
export function toHourly(amountText: string, unit: RateChangeUnit): number | null {
  const n = Number(String(amountText).replace(",", "."));
  if (!Number.isFinite(n) || n <= 0) return null;
  if (unit === "daily") return n / 8;
  if (unit === "monthly") return n / 168;
  return n;
}
