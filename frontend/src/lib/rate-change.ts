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
}

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
};

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
