// Rejestry VAT (K5a) — etykiety grup, pól JPK i salda miesiąca (bez Reacta).

import type { VatGroup, VatGroupKey, VatIssueKind, VatRow } from "@/lib/api/accounting-vat";

import { gr } from "./ledger-model";

/** Krótka etykieta grupy w wierszu rejestru. */
export const GROUP_SHORT: Record<VatGroupKey, string> = {
  "23": "23%",
  "8": "8%",
  "5": "5%",
  "0": "0%",
  "0_wdt": "WDT 0%",
  "0_ex": "eksport 0%",
  zw: "zw",
  np: "np",
  np_ue: "np UE",
  assets: "środki trwałe",
  other: "pozostałe",
};

/** Pola JPK_V7M grupy: „K_19 / K_20”, „K_11 (w tym K_12)”. */
export function fieldsLabel(group: Pick<VatGroup, "net_field" | "vat_field" | "also">): string {
  const base = group.vat_field ? `${group.net_field} / ${group.vat_field}` : group.net_field;
  return group.also ? `${base} (w tym ${group.also})` : base;
}

/** Grupy wiersza po przecinku; wiersz bez podziału = „do sprawdzenia”. */
export function rowGroups(row: Pick<VatRow, "groups" | "problem">): string {
  if (!row.groups.length) return "do sprawdzenia";
  return row.groups.map((item) => GROUP_SHORT[item.key] ?? item.key).join(", ");
}

/** Saldo miesiąca: do zapłaty (≥ 0) albo nadwyżka naliczonego. */
export function dueLabel(due: number): { label: string; value: string } {
  return due >= 0
    ? { label: "Do zapłaty", value: `${gr(due)} zł` }
    : { label: "Nadwyżka naliczonego", value: `${gr(-due)} zł` };
}

/** NIP albo VAT UE z krajem, gdy inny niż PL. */
export function taxIdLabel(row: Pick<VatRow, "tax_id" | "country">): string {
  if (!row.tax_id) return "bez NIP";
  return row.country && row.country !== "PL" && !row.tax_id.startsWith(row.country)
    ? `${row.country} ${row.tax_id}`
    : row.tax_id;
}

/** Gdzie naprawić pozycję listy „do sprawdzenia” (bufor, Źródła, dokumenty miesiąca). */
export function issueLink(kind: VatIssueKind, year: number, month: number): { href: string; label: string } {
  const query = `year=${year}&month=${month}`;
  if (kind === "drafts") return { href: `/accounting/documents?${query}&status=draft`, label: "Bufor" };
  if (kind === "missing_sales" || kind === "missing_costs") return { href: `/accounting/sources?${query}`, label: "Źródła" };
  return { href: `/accounting/documents?${query}&status=approved`, label: "Dokumenty" };
}
