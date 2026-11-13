/** Widoki modułu Finanse (`/finance?view=`). */
export type FinanceViewMode =
  | "results"
  | "archive"
  | "md"
  | "order-changes"
  | "order-pdfs"
  | "sales-invoices"
  | "rate-divergences"
  | "approved-expenses"
  | "settlements"
  | "costs"
  | "counterparties"
  | "payments"
  | "booking"
  | "accounts";

const VIEW_MODES: readonly FinanceViewMode[] = [
  "results",
  "archive",
  "md",
  "order-changes",
  "order-pdfs",
  "sales-invoices",
  "rate-divergences",
  "approved-expenses",
  "settlements",
  "costs",
  "counterparties",
  "payments",
  "booking",
  "accounts",
];

/** `?view=` → widok; nieznany albo brak = „Wyniki miesięczne” (FE-N09). */
export function parseFinanceView(raw: string | null | undefined): FinanceViewMode {
  return VIEW_MODES.includes(raw as FinanceViewMode)
    ? (raw as FinanceViewMode)
    : "results";
}
