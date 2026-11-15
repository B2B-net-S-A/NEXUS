// Rejestry VAT (K5a) — etykiety grup, pól JPK i salda miesiąca (bez Reacta).

import type { ImportGroup, VatGroup, VatGroupKey, VatIssue, VatIssueKind, VatRow } from "@/lib/api/accounting-vat";

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
  imp_other: "import usług",
  imp_28b: "import usług UE",
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

/** Listy „do sprawdzenia”, przy których JPK nie powstanie (jak `jpk.BLOCKING` w backendzie). */
const JPK_BLOCKING: readonly VatIssueKind[] = ["rates", "missing_sales", "drafts"];

export function jpkBlockers(issues: readonly VatIssue[]): string[] {
  return issues.filter((issue) => JPK_BLOCKING.includes(issue.kind)).map((issue) => `${issue.label.split(" — ")[0].toLowerCase()}: ${issue.count}`);
}

// ── Zakup zagraniczny i znaczniki (K5b-2) ───────────────────────────────────

/** Pola JPK importu usług i dlaczego — podpowiedź w formularzu i na liście. */
export const IMPORT_GROUP_LABEL: Record<ImportGroup, string> = {
  imp_28b: "K_29 / K_30 — usługa od podatnika VAT z UE (art. 28b)",
  imp_other: "K_27 / K_28 — import usług spoza UE albo bez numeru VAT UE",
};

/** Kraje UE bez Polski (kody ISO) — jak prefiksy VAT UE w backendzie (Grecja: GR). */
const EU_COUNTRIES = new Set([
  "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR", "HR", "HU",
  "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PT", "RO", "SE", "SI", "SK",
]);

/** Grupa JPK nowego dostawcy przed zapisem (serwer liczy ją sam z numeru VAT UE). */
export function supplierGroup(country: string, taxId: string): ImportGroup {
  return EU_COUNTRIES.has(country.trim().toUpperCase()) && taxId.trim() ? "imp_28b" : "imp_other";
}

/** Netto z formularza: liczba z najwyżej dwoma miejscami po przecinku, różna od zera. */
export function netValid(text: string): boolean {
  const value = text.replace(/\s/g, "").replace(",", ".");
  return /^-?\d+(\.\d{1,2})?$/.test(value) && Number(value) !== 0;
}

/**
 * Miesiąc usługi z wysłanym JPK_V7M jako „MM.RRRR” — faktura za ten miesiąc
 * (także otrzymana po miesiącach) zmienia jego rejestry, więc JPK trzeba
 * skorygować; `null` = bez korekty. VAT należny i naliczony importu usług
 * zostają w miesiącu usługi (art. 86 ust. 10b pkt 3, bez terminu 3 miesięcy
 * od 7.09.2021).
 */
export function sentJpkMonth(serviceDate: string, sent: readonly string[]): string | null {
  const month = /^(\d{4})-(\d{2})-\d{2}$/.exec(serviceDate);
  if (!month) return null;
  return sent.includes(`${month[1]}-${month[2]}`) ? `${month[2]}.${month[1]}` : null;
}

/** Data otrzymania przed wystawieniem — niemożliwa (serwer odmawia, 422). */
export function receivedBeforeIssue(issueDate: string, receivedDate: string): boolean {
  return Boolean(issueDate && receivedDate && receivedDate < issueDate);
}

/** Znaczniki JPK kontrahenta po przecinku (kolejność z serwera). */
export function markersLabel(markers: readonly string[]): string {
  return markers.length ? markers.join(", ") : "bez znaczników";
}
