// „Ludzie w NEXUSIE” — Microsoft 365 dla urlopów (karta w Ustawieniach → Kadry).
//
// Lustro `backend/app/api/hr_m365.py` (`/api/hr/admin/m365`). Tryb pochodzi
// z env (`HR_M365_MODE`), więc karta go tylko pokazuje. Operacje nie niosą
// rodzaju nieobecności (D6) — nie ma go też tutaj.

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

export interface M365Status {
  mode: M365Mode;
  credentials_configured: boolean;
  allowlist: string[];
  counts: Record<M365OperationStatus, number>;
  deferred: number;
  last_reconcile: {
    day: string;
    status: "claimed" | "done" | "skipped" | "failed";
    finished_at: string | null;
    counts: Record<string, number>;
  } | null;
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

const keys = {
  status: ["hr", "m365", "status"] as const,
  operations: (tab: M365QueueTab) => ["hr", "m365", "operations", tab] as const,
};

export function useM365Status(enabled = true) {
  return useQuery({
    queryKey: keys.status,
    queryFn: async () =>
      (await api.get<M365Status>("/api/hr/admin/m365/status")).data,
    enabled,
    refetchInterval: 60_000,
  });
}

export function useM365Operations(tab: M365QueueTab, enabled = true) {
  return useQuery({
    queryKey: keys.operations(tab),
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
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["hr", "m365"] }),
  });
}
