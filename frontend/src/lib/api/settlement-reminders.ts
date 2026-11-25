"use client";

// Przypomnienia o brakującym raporcie godzin (RCP) — Finanse → Rozliczenia.
// Kontrakt: `backend/app/api/settlement_reminders.py`. Te same dane czyta widok
// „Przebieg miesiąca”: per klient liczba brakujących, adresat i ostatnie przypomnienie.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

const BASE = "/api/finance/settlements/reminders";

/** Co dostanie kontrakt: mail do konsultanta, dzwonek opiekuna albo nic (bez adresata). */
export type ReminderAction = "mail" | "bell" | "none";

export type ConsultantReason =
  | "ok"
  | "portal_closed"
  | "no_panel"
  | "client_report"
  | "no_email"
  | "no_settlements_address";

export type OwnerSource = "contract_care" | "client_care" | "client_dl";

export interface ReminderEntry {
  sent_on: string;
  step: "day3" | "day5" | "day7" | "manual";
  channel: "consultant" | "owner";
  outcome: "pending" | "sent" | "simulated" | "failed" | "blocked";
}

export interface ReminderRow {
  contract_id: number;
  person: string;
  action: ReminderAction;
  consultant: { reachable: boolean; reason: ConsultantReason; email: string | null };
  owner: { user_id: number; name: string; source: OwnerSource } | null;
  last_reminder: ReminderEntry | null;
}

export interface ReminderClient {
  client_id: number;
  client_name: string;
  missing: number;
  /** Automat 3., 5. i 7. dnia roboczego obejmuje klienta (ma zapisane reguły rozliczeń). */
  automatic: boolean;
  to_consultant: number;
  to_owner: number;
  without_recipient: number;
  last_reminder_on: string | null;
  mail: { subject: string; text: string };
  rows: ReminderRow[];
}

export interface ReminderOverview {
  enabled: boolean;
  portal_state: string;
  month: string;
  schedule: Partial<Record<"day3" | "day5" | "day7", string>>;
  settlements_address: string | null;
  clients: ReminderClient[];
}

export interface ReminderSendResult {
  missing: number;
  mails: number;
  bells: number;
  already_today: number;
  without_recipient: number;
  failed: number;
}

/**
 * Informacja zwrotna o wadach rozliczenia (`services/client_settlements/feedback.py`):
 * `off` nic, `dry_run` zapisuje „wysłałbym: komu, co, kiedy”, `on` wysyła.
 * `external`: do ludzi spoza firmy nic (`off`), tylko przy otwartym panelu (`panel`), wszyscy (`all`).
 */
export type FeedbackMode = "off" | "dry_run" | "on";
export type FeedbackExternal = "off" | "panel" | "all";

export interface FeedbackSettings {
  mode: FeedbackMode;
  external: FeedbackExternal;
  every_days: number;
}

export interface ReminderSwitchState {
  enabled: boolean;
  /** Brak pola = backend sprzed informacji zwrotnej (przełącznik się nie pokazuje). */
  feedback?: FeedbackSettings;
}

export const FEEDBACK_MODE_OPTIONS: { value: FeedbackMode; label: string; confirm: string }[] = [
  {
    value: "off",
    label: "Wyłączona",
    confirm: "NEXUS przestanie zapisywać wady i wysyłać komunikaty. Dziennik zostaje.",
  },
  {
    value: "dry_run",
    label: "Na sucho",
    confirm:
      "NEXUS zapisze w dzienniku, komu, co i kiedy by wysłał, ale nic nie wyśle. Dobre na pierwszy miesiąc.",
  },
  {
    value: "on",
    label: "Włączona",
    confirm:
      "NEXUS wyśle komunikaty o wadach i przypomnienia do skutku. Bez wysyłki poza firmę dostają je tylko opiekunowie (dzwonek).",
  },
];

export const FEEDBACK_EXTERNAL_OPTIONS: { value: FeedbackExternal; label: string; confirm: string }[] = [
  {
    value: "off",
    label: "Nie",
    confirm: "Do konsultantów i klientów nic nie wyjdzie. Wady do przekazania dostaje opiekun.",
  },
  {
    value: "panel",
    label: "Przy panelu",
    confirm:
      "Maile do konsultantów i akceptujących u klienta tylko przy kontraktach z otwartym panelem konsultanta. To wysyłka do ludzi spoza firmy.",
  },
  {
    value: "all",
    label: "Wszyscy",
    confirm:
      "Maile do wszystkich konsultantów i akceptujących u klienta, także przy panelu „Tylko zespół”. To wysyłka do ludzi spoza firmy.",
  },
];

export const reminderKeys = {
  switch: ["settlement-reminders", "switch"] as const,
  overview: (month: string, clientId: number | null) =>
    ["settlement-reminders", "overview", month, clientId ?? "all"] as const,
};

export function useReminderOverview(month: string, clientId: number | null, enabled = true) {
  return useQuery({
    queryKey: reminderKeys.overview(month, clientId),
    queryFn: async () =>
      (
        await api.get<ReminderOverview>(BASE, {
          params: clientId == null ? { month } : { month, client_id: clientId },
        })
      ).data,
    enabled,
  });
}

export function useSendReminders() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ clientId, month }: { clientId: number; month: string }) =>
      (await api.post<ReminderSendResult>(`${BASE}/send`, { client_id: clientId, month })).data,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["settlement-reminders"] });
    },
  });
}

export function useReminderSwitch(enabled: boolean) {
  return useQuery({
    queryKey: reminderKeys.switch,
    queryFn: async () => (await api.get<ReminderSwitchState>(`${BASE}/settings`)).data,
    enabled,
    retry: false,
  });
}

export function useSetFeedbackSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (feedback: Partial<FeedbackSettings>) =>
      (await api.put<{ feedback: FeedbackSettings }>(`${BASE}/settings`, { feedback })).data,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["settlement-reminders"] });
    },
  });
}

export function useSetReminderSwitch() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (enabled: boolean) =>
      (await api.put<{ enabled: boolean }>(`${BASE}/settings`, { enabled })).data,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["settlement-reminders"] });
    },
  });
}

const REASON_TEXT: Record<ConsultantReason, string> = {
  ok: "mail do konsultanta",
  portal_closed: "panel konsultanta zamknięty",
  no_panel: "konsultant bez aktywnego panelu",
  client_report: "raport przysyła klient",
  no_email: "brak adresu konsultanta w kontrakcie",
  no_settlements_address: "brak adresu rozliczeń w konfiguracji",
};

const OWNER_TEXT: Record<OwnerSource, string> = {
  contract_care: "opiekun kontraktu",
  client_care: "opiekun klienta",
  client_dl: "Delivery Lead klienta",
};

/** Jedno zdanie: do kogo pójdzie przypomnienie o tym kontrakcie. */
export function recipientText(row: ReminderRow): string {
  if (row.action === "mail") {
    const copy = row.owner ? `, w kopii ${row.owner.name}` : "";
    return `mail do konsultanta${copy}`;
  }
  const why = REASON_TEXT[row.consultant.reason];
  if (row.action === "bell" && row.owner) {
    return `dzwonek: ${row.owner.name} (${OWNER_TEXT[row.owner.source]}); ${why}`;
  }
  return `bez adresata: brak opiekuna i DL-a klienta; ${why}`;
}
