"use client";

// Karta sprawy rozliczenia („Co dalej”) i lista spraw — Finanse → Rozliczenia.
// Kontrakt: `backend/app/api/settlement_cases.py`, reguły
// `backend/app/services/client_settlements/cases.py`. NEXUS przygotowuje mail,
// telefon i skrypt; wysyła albo dzwoni człowiek („Wyślij” po potwierdzeniu,
// „Zadzwoniłem” zapisuje wynik). Treść maila liczy serwer — front jej nie wysyła.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

import type { SettlementStatus } from "./client-settlements";

const BASE = "/api/finance/settlements/cases";

/** Kto działa: konsultant, akceptujący u klienta, Delivery Lead (opiekun) albo Finanse. */
export type CaseActor = "consultant" | "client" | "dl" | "finance";
export type CaseStepKey = "mail" | "reminder" | "call" | "escalation" | "decision";
/** `planned` = krok po bieżącym (termin to prognoza). */
export type CaseStepState = "done" | "overdue" | "today" | "upcoming" | "planned";
export type CallResult = "reached" | "no_answer" | "wrong_number";

export interface CaseReason {
  code: string;
  title: string;
  detail: string | null;
}

export interface CaseRecipient {
  kind: "consultant" | "client" | "owner" | "none";
  label: string;
  name: string | null;
  address: string | null;
  cc: string | null;
  why: string | null;
  why_text: string | null;
}

export interface CaseStep {
  key: CaseStepKey;
  label: string;
  due: string;
  state: CaseStepState;
  done_on: string | null;
  done_by: string | null;
  note: string | null;
}

export interface CaseMail {
  to: string;
  cc: string | null;
  subject: string;
  text: string;
}

export interface CasePhone {
  who: string;
  name: string | null;
  /** `null` = brak numeru w NEXUS-ie (ekran mówi to wprost). */
  number: string | null;
  source: string | null;
}

export interface CaseLogEntry {
  on: string;
  action: "mail" | "call";
  step: string;
  by: string | null;
  to: string | null;
  address: string | null;
  outcome: "sent" | "simulated" | "failed" | "blocked" | null;
  result: CallResult | null;
  result_label: string | null;
  note: string | null;
}

export interface CaseDlCard {
  created_on: string;
  mail_sent: boolean;
  handled: boolean;
}

export interface SettlementCaseRow {
  key: string;
  settlement_id: number;
  contract_id: number;
  client_id: number;
  client_name: string;
  person: string;
  month: string;
  status: SettlementStatus;
  actor: CaseActor;
  actor_label: string;
  reasons: CaseReason[];
  recipient: CaseRecipient | null;
  day0: string;
  current: CaseStep | null;
  overdue_days: number;
  dl_card: CaseDlCard | null;
}

export interface SettlementCase extends SettlementCaseRow {
  steps: CaseStep[];
  mail: CaseMail | null;
  mail_step: "mail" | "reminder" | "extra" | null;
  escalation: { to: CaseRecipient | null; mail: CaseMail | null };
  phones: CasePhone[];
  script: string[];
  log: CaseLogEntry[];
}

export type CaseCountKey = "all" | "overdue" | CaseActor;

export interface CasesMonth {
  month: string;
  today: string;
  counts: Record<CaseCountKey, number>;
  clients: { client_id: number; name: string; count: number }[];
  cases: SettlementCaseRow[];
}

export const caseKeys = {
  all: ["settlement-cases"] as const,
  month: (month: string, clientId: number | null) => ["settlement-cases", "month", month, clientId ?? "all"] as const,
  contract: (contractId: number, month: string) => ["settlement-cases", "contract", contractId, month] as const,
};

export function useSettlementCases(month: string, clientId: number | null) {
  return useQuery({
    queryKey: caseKeys.month(month, clientId),
    queryFn: async () =>
      (await api.get<CasesMonth>(BASE, { params: clientId == null ? { month } : { month, client_id: clientId } })).data,
  });
}

/**
 * `version` = stan karty rozliczenia (status, MD, uwagi): po przyjęciu, „Do poprawy”
 * albo przeliczeniu sprawa liczy się od nowa i znika, gdy wady już nie ma.
 */
export function useContractCases(contractId: number, month: string, version = "", enabled = true) {
  return useQuery({
    queryKey: [...caseKeys.contract(contractId, month), version],
    queryFn: async () => (await api.get<{ cases: SettlementCase[] }>(`${BASE}/contract/${contractId}`, { params: { month } })).data,
    enabled,
  });
}

function useCaseWrite<Vars extends { settlementId: number; contractId: number; month: string }, Body>(
  path: "send" | "call",
  body: (vars: Vars) => Body,
) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (vars: Vars) =>
      (await api.post<{ cases: SettlementCase[]; outcome?: string }>(`${BASE}/${vars.settlementId}/${path}`, body(vars))).data,
    onSuccess: (data, vars) => {
      client.setQueriesData({ queryKey: caseKeys.contract(vars.contractId, vars.month) }, { cases: data.cases });
      void client.invalidateQueries({ queryKey: ["settlement-cases", "month"] });
    },
  });
}

export function useSendCaseMail() {
  return useCaseWrite("send", (vars: { settlementId: number; contractId: number; month: string; actor: CaseActor; escalation: boolean }) => ({
    actor: vars.actor,
    escalation: vars.escalation,
  }));
}

export function useLogCaseCall() {
  return useCaseWrite(
    "call",
    (vars: { settlementId: number; contractId: number; month: string; actor: CaseActor; result: CallResult; note: string }) => ({
      actor: vars.actor,
      result: vars.result,
      note: vars.note.trim() || null,
    }),
  );
}
