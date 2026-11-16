// Płace K7b — pensje UoP, składniki miesiąca, oznaczenia L4, historia podstaw
// z Enovy, dekret LP z listy NEXUSA i porównanie z listą z Enovy.
//
// Lustro tras K7b w `backend/app/api/hr_payroll_lists.py`. Wszystko tylko dla
// uprawnienia „Rozliczenia” (`payroll`, admin zawsze, D2); rodzaj nieobecności
// to dana o zdrowiu — widzą go tylko Płace (D6). Kwoty jako tekst w złotych,
// kwoty LP i porównania w groszach (jak w imporcie listy z Enovy, K3c).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

import { payrollListKeys, type PayrollMonth } from "./payroll-lists";

const BASE = "/api/hr/payroll-lists";

export type ComponentKind = "variable" | "other" | "sick_base" | "equivalent_days";
export type SickRate = "80" | "100" | "zus";

export interface PayrollSalaryRow {
  id: number;
  user_id: number;
  monthly_amount: string;
  fte: string;
  effective_from: string;
  effective_to: string | null;
  note: string | null;
  set_by: number | null;
  set_at: string | null;
}

export interface SalariesOverview {
  /** Osoby na UoP (bez odeszłych). */
  people: { user_id: number; name: string }[];
  salaries: PayrollSalaryRow[];
  component_labels: Record<ComponentKind, string>;
  sick_rate_labels: Record<SickRate, string>;
}

export interface PayrollComponentRow {
  user_id: number;
  kind: ComponentKind;
  label: string;
  amount: string;
  note: string;
  entered_by: number | null;
  entered_at: string | null;
}

export interface MonthAbsence {
  id: string;
  user_id: number;
  person: string;
  leave_type: string;
  label: string;
  start: string;
  end: string;
  sick: boolean;
  sick_rate: SickRate;
  waiting_exempt: boolean;
  note: string | null;
}

export interface BasisHistoryRow {
  user_id: number;
  person: string;
  period: string;
  fixed_paid: string;
  fixed_full: string;
  variable: string;
  leave_variable: string;
  nominal_hours: string;
  worked_hours: string;
  paid_hours: string;
  full_month: boolean;
}

export interface HistoryImport {
  columns: Record<string, string>;
  rows: (BasisHistoryRow & { line: number })[];
  errors: { line: number; message: string }[];
  errors_total: number;
  saved: boolean;
}

export interface LedgerPosting {
  document: { id: number; number: string; status: string };
  lines: { side: "debit" | "credit"; account: string; amount: number; description: string }[];
  totals: { gross: number; employee: number; employer: number; zus: number; pit: number; ppk: number; net: number };
}

export interface CompareField {
  key: string;
  label: string;
  nexus: number;
  enova: number;
  diff: number;
}

export interface EnovaComparison {
  list: { id: number; number: string; status: string };
  fields: { key: string; label: string }[];
  people: { person: string; enova_line: number; nexus_lines: number; equal: boolean; fields: CompareField[] }[];
  only_nexus: { person: string }[];
  only_enova: { line: number; person: string; reason: string }[];
  totals: Record<string, { label: string; nexus: number; enova: number; diff: number }>;
  summary: {
    matched: number;
    equal: number;
    different: number;
    only_nexus: number;
    only_enova: number;
    all_equal: boolean;
  };
  errors: { line: number; message: string }[];
  warnings: { line: number; message: string }[];
  problems: string[];
}

export const payrollK7bKeys = {
  salaries: ["payroll-lists", "salaries"] as const,
  absences: (year: number, month: number) => ["payroll-lists", "absences", year, month] as const,
  history: ["payroll-lists", "basis-history"] as const,
};

export function useSalaries(enabled = true) {
  return useQuery({
    queryKey: payrollK7bKeys.salaries,
    queryFn: async () => (await api.get<SalariesOverview>(`${BASE}/salaries`)).data,
    enabled,
  });
}

function useSalaryMutation<TArgs>(request: (args: TArgs) => Promise<SalariesOverview>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: request,
    onSuccess: (data) => {
      client.setQueryData(payrollK7bKeys.salaries, data);
      client.invalidateQueries({ queryKey: payrollListKeys.months });
    },
  });
}

export function useSetSalary() {
  return useSalaryMutation(
    async (args: { userId: number; monthlyAmount: string; fte: string; effectiveFrom: string; note?: string }) =>
      (
        await api.put<SalariesOverview>(`${BASE}/salaries/users/${args.userId}`, {
          monthly_amount: args.monthlyAmount,
          fte: args.fte,
          effective_from: args.effectiveFrom,
          note: args.note || undefined,
        })
      ).data,
  );
}

export function useDeleteSalary() {
  return useSalaryMutation(
    async (salaryId: number) => (await api.delete<SalariesOverview>(`${BASE}/salaries/${salaryId}`)).data,
  );
}

export function useMonthAbsences(year: number, month: number, enabled = true) {
  return useQuery({
    queryKey: payrollK7bKeys.absences(year, month),
    queryFn: async () =>
      (await api.get<{ absences: MonthAbsence[] }>(`${BASE}/months/${year}/${month}/absences`)).data.absences,
    enabled,
  });
}

export function useSetAbsenceMark() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (args: { id: string; sickRate: SickRate; waitingExempt: boolean; note?: string | null }) =>
      (
        await api.put(`${BASE}/absences/${args.id}/mark`, {
          sick_rate: args.sickRate,
          waiting_exempt: args.waitingExempt,
          note: args.note || undefined,
        })
      ).data,
    onSettled: () => client.invalidateQueries({ queryKey: ["payroll-lists", "absences"] }),
  });
}

export function useSetComponent() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (args: {
      year: number;
      month: number;
      userId: number;
      kind: ComponentKind;
      amount: string | null;
      note?: string;
    }) =>
      (
        await api.put<PayrollMonth>(`${BASE}/months/${args.year}/${args.month}/components`, {
          user_id: args.userId,
          kind: args.kind,
          amount: args.amount,
          note: args.note || undefined,
        })
      ).data,
    onSuccess: (data) => client.setQueryData(payrollListKeys.month(data.year, data.month), data),
    onError: () => client.invalidateQueries({ queryKey: payrollListKeys.months }),
  });
}

export function useBasisHistory(enabled = true) {
  return useQuery({
    queryKey: payrollK7bKeys.history,
    queryFn: async () => (await api.get<{ rows: BasisHistoryRow[] }>(`${BASE}/basis-history`)).data.rows,
    enabled,
  });
}

export function useImportBasisHistory() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (args: { file: File; save: boolean }) => {
      const form = new FormData();
      form.append("file", args.file);
      return (
        await api.post<HistoryImport>(`${BASE}/basis-history/import`, form, {
          params: { save: args.save },
          headers: { "Content-Type": "multipart/form-data" },
        })
      ).data;
    },
    onSuccess: (data) => {
      if (data.saved) client.invalidateQueries({ queryKey: payrollK7bKeys.history });
    },
  });
}

export function usePostListToLedger() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (listId: number) => (await api.post<LedgerPosting>(`${BASE}/lists/${listId}/ledger`)).data,
    onSettled: () => client.invalidateQueries({ queryKey: payrollListKeys.months }),
  });
}

export function useCompareEnova() {
  return useMutation({
    mutationFn: async (args: { listId: number; file: File }) => {
      const form = new FormData();
      form.append("file", args.file);
      return (
        await api.post<EnovaComparison>(`${BASE}/lists/${args.listId}/compare-enova`, form, {
          headers: { "Content-Type": "multipart/form-data" },
        })
      ).data;
    },
  });
}
