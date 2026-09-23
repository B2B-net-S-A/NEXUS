/** Widoki modułu Finanse (`/finance?view=`). */
export type FinanceViewMode =
  | "results"
  | "archive"
  | "md"
  | "order-changes"
  | "order-pdfs";

const VIEW_MODES: readonly FinanceViewMode[] = [
  "results",
  "archive",
  "md",
  "order-changes",
  "order-pdfs",
];

/** `?view=` → widok; nieznany albo brak = „Wyniki miesięczne” (FE-N09). */
export function parseFinanceView(raw: string | null | undefined): FinanceViewMode {
  return VIEW_MODES.includes(raw as FinanceViewMode)
    ? (raw as FinanceViewMode)
    : "results";
}
