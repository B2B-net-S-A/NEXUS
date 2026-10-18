// „Ludzie w NEXUSIE” — Microsoft 365 dla urlopów (karta w Ustawieniach → Kadry).
//
// Lustro `backend/app/api/hr_m365.py` (`/api/hr/admin/m365`). Tryb pochodzi
// z env (`HR_M365_MODE`), więc karta go tylko pokazuje. Operacje nie niosą
// rodzaju nieobecności (D6) — nie ma go też tutaj. Karta pokazuje też ostatni
// odczyt profili z katalogu i termin sekretu rejestracji „NEXUS Kadry”
// (`HR_M365_CLIENT_SECRET_EXPIRES_ON`).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

export type M365Mode = "off" | "simulate" | "live";
export type M365OperationStatus =
  | "pending"
  | "running"
  | "failed"
  | "simulated"
  | "skipped"
  | "done";
export type M365OperationKind =
  | "set_oof"
  | "clear_oof"
  | "calendar_event_upsert"
  | "calendar_event_delete"
  | "forward_rule_open"
  | "forward_rule_close";
/** Zakładki karty — „pending” obejmuje też operacje w trakcie wykonania. */
export type M365QueueTab = "pending" | "failed" | "simulated";

export interface M365SimulatedRequest {
  method: string;
  path: string;
  params?: Record<string, string>;
  body?: unknown;
}

export interface M365Operation {
  id: number;
  kind: M365OperationKind;
  status: M365OperationStatus;
  user_id: number;
  user_name: string | null;
  leave_request_id: string | null;
  window_start: string | null;
  window_end: string | null;
  attempts: number;
  next_attempt_at: string | null;
  last_error: string | null;
  deferred: boolean;
  created_at: string | null;
  done_at: string | null;
  simulated_request: {
    mailbox: string | null;
    requests: M365SimulatedRequest[];
    at: string;
  } | null;
}

/** Przebieg zadania dziennego (`hr_job_runs`): uzgadnianie albo odczyt profili. */
export interface M365JobRun {
  day: string;
  status: "claimed" | "done" | "skipped" | "failed";
  finished_at: string | null;
  counts: Record<string, number | string>;
  error: string | null;
}

/** `missing` = rejestracja pracuje na żywo bez daty; `not_set` = nic jej jeszcze nie używa. */
export type M365SecretState = "ok" | "expiring" | "expired" | "missing" | "not_set";

export interface M365Secret {
  expires_on: string | null;
  days_left: number | null;
  state: M365SecretState;
}

export interface M365Status {
  mode: M365Mode;
  credentials_configured: boolean;
  allowlist: string[];
  counts: Record<M365OperationStatus, number>;
  deferred: number;
  last_reconcile: M365JobRun | null;
  last_profile_sync: M365JobRun | null;
  secret: M365Secret;
  custom_oof_mailboxes: { user_id: number; name: string; last_reconciled_at: string | null }[];
  mailbox_errors: { user_id: number; name: string; last_error: string }[];
}

export const M365_MODE_LABELS: Record<M365Mode, string> = {
  off: "Wyłączone",
  simulate: "Symulacja",
  live: "Na żywo",
};

export const M365_KIND_LABELS: Record<M365OperationKind, string> = {
  set_oof: "Autoodpowiedź",
  clear_oof: "Zdjęcie autoodpowiedzi",
  calendar_event_upsert: "Wydarzenie „Poza biurem”",
  calendar_event_delete: "Usunięcie wydarzenia",
  forward_rule_open: "Przekierowanie poczty",
  forward_rule_close: "Zamknięcie przekierowania",
};

const REASON_LABELS: Record<string, string> = {
  not_allowlisted: "Skrzynka spoza listy próbnej",
  waiting_for_window: "Czeka na pierwszy dzień urlopu",
  other_leave_oof: "Czeka na koniec autoodpowiedzi innego urlopu",
  user_custom: "Osoba ma własną autoodpowiedź",
  leave_not_active: "Urlop nie jest już zatwierdzony",
  leave_ended: "Urlop już minął",
  leave_missing: "Brak urlopu w NEXUSIE",
  no_consent: "Osoba nie zgodziła się na przekierowanie",
  not_owned: "Autoodpowiedź nie należy do tego urlopu",
  other_leave_same_window: "Inny urlop w tych samych dniach",
  leave_changed: "Wniosek zmieniony — operacja z nowym terminem jest w kolejce",
  still_active: "Przekierowanie nadal potrzebne",
  bad_payload: "Uszkodzona operacja",
  no_mailbox_address: "Konto bez adresu skrzynki",
  substitute_unavailable: "Zastępca nieaktywny albo bez adresu",
  forbidden: "Brak uprawnień aplikacji w Exchange",
  throttled: "Microsoft chwilowo ogranicza ruch",
  server_error: "Błąd po stronie Microsoft",
  timeout: "Microsoft nie odpowiedział na czas",
  network: "Brak połączenia z Microsoft",
  auth: "Brak tokenu aplikacji",
  no_mailbox: "Konto bez skrzynki Exchange",
  not_found: "Nie znaleziono w skrzynce",
  conflict: "Konflikt w skrzynce",
  bad_request: "Microsoft odrzucił żądanie",
  rejected: "Microsoft odrzucił żądanie",
  internal: "Błąd po stronie NEXUSA",
};

/** `last_error` z serwera → zdanie dla Kadr. Kategoria może nieść kod („forbidden (403)”). */
export function m365ReasonLabel(code: string | null | undefined): string | null {
  if (!code) return null;
  const match = /^([a-z_]+)(?:\s*\((\d{3})\))?$/.exec(code.trim());
  if (!match) return code;
  const label = REASON_LABELS[match[1]];
  if (!label) return code;
  return match[2] ? `${label} (${match[2]})` : label;
}

export type M365Tone = "success" | "warning" | "danger" | "info" | "neutral";

/** „2026-11-02” → „2.11.2026” bez przeliczania strefy. */
export function m365Day(value: string | null): string | null {
  if (!value) return null;
  const [year, month, day] = value.split("-");
  if (!year || !month || !day) return value;
  return `${Number(day)}.${month}.${year}`;
}

export interface M365View {
  label: string;
  tone: M365Tone;
  note?: string;
}

/** Termin sekretu rejestracji „NEXUS Kadry” → etykieta i kolor (ostrzeżenie nad kartą osobno). */
export function m365SecretView(secret: M365Secret): M365View {
  const day = m365Day(secret.expires_on) ?? undefined;
  const days = secret.days_left ?? 0;
  switch (secret.state) {
    case "expired":
      return { label: days === 0 ? "Wygasa dziś" : "Wygasł", tone: "danger", note: day };
    case "expiring":
      return {
        label: days === 1 ? "Wygasa jutro" : `Wygasa za ${days} dni`,
        tone: "warning",
        note: day,
      };
    case "ok":
      return { label: `Ważny do ${day}`, tone: "success" };
    case "missing":
      return { label: "Brak daty wygaśnięcia", tone: "warning" };
    case "not_set":
      return { label: "Data wygaśnięcia nieustawiona", tone: "neutral" };
  }
}

const PROFILE_SYNC_ERRORS: Record<string, string> = {
  forbidden: "aplikacja nie ma uprawnienia User.Read.All",
  auth: "brak tokenu aplikacji",
  all_reads_failed: "Microsoft nie odpowiadał",
};

function count(run: M365JobRun, key: string): number {
  const value = run.counts[key];
  return typeof value === "number" ? value : 0;
}

/** Ostatni odczyt stanowisk, działów i telefonów z katalogu → etykieta i liczby. */
export function m365ProfileSyncView(run: M365JobRun | null): M365View {
  if (!run) return { label: "Jeszcze się nie odbył", tone: "neutral" };
  const day = m365Day(run.day);
  if (run.status === "failed") {
    const reason = (run.error && PROFILE_SYNC_ERRORS[run.error]) || "błąd po stronie NEXUSA";
    return { label: `${day} · nie udał się`, tone: "danger", note: reason };
  }
  if (run.status === "claimed") return { label: `${day} · w trakcie`, tone: "info" };
  if (run.counts.mode === "simulate") {
    return {
      label: `${day} · symulacja`,
      tone: "info",
      note: `Kont do odczytu: ${count(run, "read")} · kartoteka bez zmian`,
    };
  }
  const parts = [`zaktualizowano ${count(run, "updated")} z ${count(run, "read")}`];
  const kept = count(run, "kept_manual");
  if (kept) parts.push(`zostawione zmiany Kadr: ${kept}`);
  const missing = count(run, "not_found");
  if (missing) parts.push(`bez konta w Microsoft 365: ${missing}`);
  return { label: `${day} · zakończony`, tone: "success", note: parts.join(" · ") };
}

/** Kolor kropki i etykieta stanu operacji. */
export function m365StatusView(op: Pick<M365Operation, "status" | "deferred">): {
  label: string;
  tone: M365Tone;
} {
  switch (op.status) {
    case "pending":
      return op.deferred
        ? { label: "Czeka", tone: "neutral" }
        : { label: "W kolejce", tone: "info" };
    case "running":
      return { label: "W trakcie", tone: "info" };
    case "failed":
      return { label: "Nie udało się", tone: "danger" };
    case "simulated":
      return { label: "Zasymulowano", tone: "info" };
    case "skipped":
      return { label: "Pominięto", tone: "warning" };
    case "done":
      return { label: "Wykonano", tone: "success" };
  }
}

export const m365Keys = {
  all: ["hr", "m365"] as const,
  status: ["hr", "m365", "status"] as const,
  operations: (tab: M365QueueTab) => ["hr", "m365", "operations", tab] as const,
  forwards: ["hr", "m365", "forwards"] as const,
};

export function useM365Status(enabled = true) {
  return useQuery({
    queryKey: m365Keys.status,
    queryFn: async () =>
      (await api.get<M365Status>("/api/hr/admin/m365/status")).data,
    enabled,
    refetchInterval: 60_000,
  });
}

export function useM365Operations(tab: M365QueueTab, enabled = true) {
  return useQuery({
    queryKey: m365Keys.operations(tab),
    queryFn: async () =>
      (
        await api.get<{ items: M365Operation[]; total: number }>(
          "/api/hr/admin/m365/operations",
          { params: { status: tab, limit: 50 } },
        )
      ).data,
    enabled,
  });
}

export function useRetryM365Operation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (operationId: number) =>
      (
        await api.post<M365Operation>(
          `/api/hr/admin/m365/operations/${operationId}/retry`,
        )
      ).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: m365Keys.all }),
  });
}


// ── Przekierowania poczty i „Uzgodnij teraz” (Compass AdminForwardRules) ─────

/**
 * `ok` — trwa i ma regułę; `waiting` — nadejdzie; `missing` — trwa, a reguły
 * w skrzynce nie ma; `orphan` — reguła po urlopie albo po wyłączeniu zgody;
 * `unknown` — reguła NEXUSA/Compassa bez wniosku w NEXUSIE.
 */
export type M365ForwardHealth = "ok" | "waiting" | "missing" | "orphan" | "unknown";

export interface M365SavedForward {
  leave_request_id: string;
  user_id: number;
  user_name: string | null;
  substitute_user_id: number | null;
  substitute_name: string | null;
  start_date: string;
  end_date: string;
  status: string;
  consent: boolean;
  health: M365ForwardHealth;
  reason: string | null;
  last_operation: { id: number; kind: M365OperationKind; status: M365OperationStatus; last_error: string | null } | null;
}

export interface M365MailboxRule {
  rule_id: string | null;
  rule_name: string | null;
  owner: "nexus" | "compass" | null;
  leave_request_id: string;
  known: boolean;
  user_id: number;
  user_name: string | null;
  start_date: string | null;
  end_date: string | null;
  substitute_name: string | null;
  health: M365ForwardHealth;
  reason: string | null;
}

export interface M365MailboxCheck {
  available: boolean;
  mode: M365Mode;
  message: string | null;
  scanned?: number;
  unreadable?: { user_id: number; name: string; error: string }[];
  items: M365MailboxRule[];
}

export interface M365ReconcileResult {
  status: "done";
  mode: M365Mode;
  counts: Record<string, number | string>;
}

export const M365_FORWARD_HEALTH: Record<M365ForwardHealth, M365View> = {
  ok: { label: "Działa", tone: "success" },
  waiting: { label: "Czeka na pierwszy dzień", tone: "neutral" },
  missing: { label: "Brak reguły w skrzynce", tone: "danger" },
  orphan: { label: "Do zamknięcia", tone: "warning" },
  unknown: { label: "Reguła bez wniosku", tone: "warning" },
};

/** Czy z wiersza można zamknąć regułę przez kolejkę (nie trwający urlop ze zgodą). */
export function canCloseRule(row: { health: M365ForwardHealth }): boolean {
  return row.health === "orphan" || row.health === "unknown";
}

/** Krótkie podsumowanie przebiegu „Uzgodnij teraz” dla komunikatu. */
export function reconcileSummary(counts: Record<string, number | string>): string {
  const number = (key: string) => (typeof counts[key] === "number" ? (counts[key] as number) : 0);
  const parts = [`skrzynek: ${number("mailboxes")}`];
  const added =
    number("oof_enqueued") +
    number("forward_open_enqueued") +
    number("forward_close_enqueued") +
    number("forward_takeover") +
    number("calendar_enqueued");
  parts.push(added ? `operacji do kolejki: ${added}` : "bez nowych operacji");
  const requests = number("oof_request_created");
  if (requests) parts.push(`wnioski z Outlooka: ${requests}`);
  const errors = number("read_errors");
  if (errors) parts.push(`błędy odczytu: ${errors}`);
  return parts.join(" · ");
}

export function useM365Forwards(enabled = true) {
  return useQuery({
    queryKey: m365Keys.forwards,
    queryFn: async () =>
      (
        await api.get<{ mode: M365Mode; today: string; items: M365SavedForward[] }>(
          "/api/hr/admin/m365/forwards",
        )
      ).data,
    enabled,
  });
}

/** „Sprawdź skrzynki” — odczyt reguł na żywo (bez zapisu), wynik tylko w karcie. */
export function useCheckM365Mailboxes() {
  return useMutation({
    mutationFn: async () =>
      (await api.post<M365MailboxCheck>("/api/hr/admin/m365/forwards/check")).data,
  });
}

export function useCloseM365Rule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { user_id: number; leave_request_id: string }) =>
      (
        await api.post<{ queued: boolean; leave_request_id: string; known: boolean }>(
          "/api/hr/admin/m365/forwards/close",
          input,
        )
      ).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: m365Keys.all }),
  });
}

/** „Uzgodnij teraz” — jeden przebieg uzgadniania na żądanie. */
export function useReconcileM365Now() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      (await api.post<M365ReconcileResult>("/api/hr/admin/m365/reconcile")).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: m365Keys.all }),
  });
}
