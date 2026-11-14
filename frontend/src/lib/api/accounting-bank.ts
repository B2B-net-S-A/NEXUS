// Księgowość → Bank (K4a, 0705): jeden import wyciągu, rozpoznanie operacji,
// konto przeciwstawne i dokument WB w buforze.
//
// Lustro tras `/api/accounting/bank*` i `PUT /config/bank` z
// `backend/app/api/ledger.py`. Bramki: „Moduł Finanse” i przełączniki modułów
// `ledger` + `bank` (wyłączony = 404, admin widzi). Wypłaty dla osób z zespołu
// (pozycje płacowe) serwer pokazuje tylko osobie z Płacami i administratorowi
// (D2) — reszta dostaje tylko flagę `payroll_hidden`, bez liczby (numery
// pozycji też są w zasięgu osoby, bez luk). Rachunki firmy zmienia
// administrator; inni widzą tylko końcówkę numeru.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { accountingKeys, type DocStatus, type Side } from "@/lib/api/accounting";

const BASE = "/api/accounting";

export interface CompanyBankAccount {
  /** 26 cyfr NRB (administrator) albo „…1234” (pozostali). */
  number: string;
  /** Konto rachunku w planie kont (130-x). */
  account: string;
  name: string;
}

export interface BankSettings {
  accounts: CompanyBankAccount[];
  fees_account: string;
  zus_account: string;
  vat_account: string;
  pit_account: string;
  cit_account: string;
}

export type BankLineKind =
  | "cost_invoice"
  | "team"
  | "sales_invoice"
  | "zus"
  | "tax"
  | "fee"
  | "manual"
  | "unmatched"
  | "duplicate";

export interface BankLine {
  id: number;
  position: number;
  booked_on: string;
  direction: Side;
  /** Grosze, zawsze dodatnie — kierunek mówi `direction`. */
  amount: number;
  title: string;
  counterparty_name: string;
  counterparty_last4: string | null;
  kind: BankLineKind;
  kind_label: string;
  counter_account: string | null;
  payroll: boolean;
  note: string;
  resolved: boolean;
}

export interface BankStatementDocument {
  id: number;
  number: string;
  status: DocStatus;
  payroll: boolean;
}

export interface BankStatement {
  id: number;
  format: string;
  bank_account_last4: string;
  account_name: string;
  ledger_account: string;
  first_day: string;
  last_day: string;
  debit_total: number;
  credit_total: number;
  lines: BankLine[];
  /** Wyciąg ma wypłaty dla zespołu, których ta osoba nie widzi (D2 — bez liczby). */
  payroll_hidden: boolean;
  counts: Partial<Record<BankLineKind, number>>;
  unresolved: number;
  documents: BankStatementDocument[];
  /** Tylko w odpowiedzi importu: ten sam plik był już wczytany. */
  already_imported?: boolean;
}

export interface BankStatementRow {
  id: number;
  bank_account_last4: string;
  account_name: string;
  ledger_account: string;
  first_day: string;
  last_day: string;
  operations: number;
  unresolved: number;
  debit_total: number;
  credit_total: number;
  /** Stan WB w zasięgu osoby: `draft`, gdy choć jeden jest w buforze. */
  wb: DocStatus | null;
  /** Są operacje do WB bez dokumentu (zwykłe albo — dla Płac — płacowe). */
  to_post: boolean;
}

export interface BankOverview {
  statements: BankStatementRow[];
  settings: BankSettings;
}

export interface BankPostResult {
  created: number;
  rebuilt: number;
  unchanged: number;
  documents: { id: number; number: string }[];
}

export const bankKeys = {
  all: ["accounting", "bank"] as const,
  month: (year: number, month: number) => ["accounting", "bank", "month", year, month] as const,
  statement: (id: number) => ["accounting", "bank", "statement", id] as const,
};

export function useBank(year: number, month: number, enabled = true) {
  return useQuery({
    queryKey: bankKeys.month(year, month),
    queryFn: async () => (await api.get<BankOverview>(`${BASE}/bank`, { params: { year, month } })).data,
    enabled,
  });
}

/** Wyciąg zmieniają tylko import, przypisanie i księgowanie — każde z nich wpisuje albo odświeża dane. */
export function useBankStatement(id: number | null) {
  return useQuery({
    queryKey: bankKeys.statement(id ?? 0),
    queryFn: async () => (await api.get<BankStatement>(`${BASE}/bank/statements/${id}`)).data,
    enabled: id != null,
    staleTime: 30 * 1000,
  });
}

/** Odpowiedź z wyciągiem wpisuje się od razu do jego zapytania; listy się odświeżają. */
function useStoreStatement() {
  const client = useQueryClient();
  return (statement: BankStatement) => {
    client.setQueryData(bankKeys.statement(statement.id), statement);
    client.invalidateQueries({ queryKey: ["accounting", "bank", "month"] });
  };
}

export function useBankImport() {
  const store = useStoreStatement();
  return useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return (
        await api.post<BankStatement>(`${BASE}/bank/import`, form, {
          headers: { "Content-Type": "multipart/form-data" },
        })
      ).data;
    },
    onSuccess: (statement) => store(statement),
  });
}

export function useAssignBankLine() {
  const store = useStoreStatement();
  return useMutation({
    mutationFn: async ({ lineId, account }: { lineId: number; account: string }) =>
      (await api.patch<BankStatement>(`${BASE}/bank/lines/${lineId}`, { account })).data,
    onSuccess: (statement) => store(statement),
  });
}

/** WB trafia do bufora: odświeżają się bank, dokumenty, miesiąc i obroty. */
export function usePostBankStatement() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (statementId: number) =>
      (await api.post<BankPostResult>(`${BASE}/bank/statements/${statementId}/post`)).data,
    onSettled: () => client.invalidateQueries({ queryKey: accountingKeys.all }),
  });
}

export function useSetBankSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (settings: BankSettings) =>
      (await api.put<BankSettings>(`${BASE}/config/bank`, settings)).data,
    onSettled: () => client.invalidateQueries({ queryKey: accountingKeys.all }),
  });
}
