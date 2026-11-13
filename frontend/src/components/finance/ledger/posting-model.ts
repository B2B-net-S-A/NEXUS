// Logika dekretu i eksportu (E2) bez Reacta (testy w __tests__).
//
// Dekret, kontrolę i paczki liczy serwer (`services/finance_ledger/posting.py`);
// tu tylko szkic ręcznej korekty: kwoty w groszach, sumy Wn/Ma, czy można
// zapisać, i podgląd opisu z wzoru reguły. Serwer sprawdza bilans jeszcze raz.

import type { CostStage } from "@/lib/api/finance-ledger";
import type {
  DecreeInput,
  DecreeSection,
  Deduction,
  PositionKind,
  Register,
  Side,
} from "@/lib/api/finance-posting";

export const KIND_LABELS: Record<PositionKind, string> = {
  cost: "Koszt",
  vat: "VAT",
  counterparty: "Rozrachunek",
};

export const REGISTER_LABELS: Record<Register, string> = {
  purchase: "Zakup",
  sale: "Sprzedaż",
};

export const DEDUCTION_LABELS: Record<Deduction, string> = {
  full: "100%",
  none: "brak",
};

export const TEMPLATE_FIELDS = ["{usługa}", "{MM}", "{RRRR}", "{numer}", "{kontrahent}"] as const;

export interface DraftRow {
  key: number;
  kind: PositionKind;
  account: string;
  side: Side;
  amount: string;
  vat_rate: string | null;
  deduction: Deduction | null;
}

export interface Draft {
  register: Register;
  doc_type: string;
  description: string;
  rows: DraftRow[];
}

/** „1 234,56” / „1234.56” → grosze; pusta, ujemna, zero albo 3 miejsca → null. */
export function toGrosze(raw: string): number | null {
  const text = raw.replace(/[\s ]/g, "").replace(",", ".");
  if (!/^\d+(\.\d{1,2})?$/.test(text)) return null;
  const [whole, fraction = ""] = text.split(".");
  const value = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  return value > 0 && Number.isSafeInteger(value) ? value : null;
}

/** Grosze → „1 234,56”. */
export function formatGrosze(value: number): string {
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  const whole = Math.floor(abs / 100)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  return `${sign}${whole},${String(abs % 100).padStart(2, "0")}`;
}

let nextKey = 1;

export function emptyRow(kind: PositionKind = "cost"): DraftRow {
  return {
    key: nextKey++,
    kind,
    account: "",
    side: kind === "counterparty" ? "credit" : "debit",
    amount: "",
    vat_rate: null,
    deduction: kind === "counterparty" ? null : "full",
  };
}

/** Szkic korekty z dekretu na karcie (albo pusty: koszt, VAT, rozrachunek). */
export function draftFromSection(section: DecreeSection): Draft {
  const rows: DraftRow[] = section.positions.length
    ? section.positions.map((position) => ({
        key: nextKey++,
        kind: position.kind,
        account: position.account ?? "",
        side: position.side,
        amount: position.amount.replace(".", ","),
        vat_rate: position.vat_rate,
        deduction: position.deduction,
      }))
    : [emptyRow("cost"), emptyRow("vat"), emptyRow("counterparty")];
  return {
    register: section.register ?? "purchase",
    doc_type: section.doc_type ?? "FVZ",
    description: section.description ?? "",
    rows,
  };
}

export interface DraftCheck {
  debit: number;
  credit: number;
  balanced: boolean;
  /** Komunikaty, przez które „Zapisz” jest wyłączone. */
  problems: string[];
}

const ACCOUNT = /^[0-9A-Za-z][0-9A-Za-z\-./]*$/;

export function checkDraft(draft: Draft): DraftCheck {
  let debit = 0;
  let credit = 0;
  const problems: string[] = [];
  if (draft.rows.length === 0) problems.push("Dodaj co najmniej jedną pozycję.");
  draft.rows.forEach((row, index) => {
    const amount = toGrosze(row.amount);
    if (!ACCOUNT.test(row.account.replace(/\s/g, ""))) {
      problems.push(`Pozycja ${index + 1}: wpisz numer konta.`);
    }
    if (amount === null) {
      problems.push(`Pozycja ${index + 1}: kwota większa od zera, najwyżej dwa miejsca po przecinku.`);
      return;
    }
    if (row.side === "debit") debit += amount;
    else credit += amount;
  });
  if (!/^[0-9A-Za-z]{1,8}$/.test(draft.doc_type.trim())) {
    problems.push("Typ dokumentu: od 1 do 8 liter albo cyfr (np. FVZ).");
  }
  const balanced = debit === credit && debit > 0;
  if (!balanced && problems.length === 0) {
    problems.push(`Suma Wn (${formatGrosze(debit)}) różni się od sumy Ma (${formatGrosze(credit)}).`);
  }
  return { debit, credit, balanced, problems };
}

export function draftToInput(draft: Draft): DecreeInput {
  return {
    register: draft.register,
    doc_type: draft.doc_type.trim().toUpperCase(),
    description: draft.description.trim(),
    positions: draft.rows.map((row) => {
      const grosze = toGrosze(row.amount) ?? 0;
      return {
        kind: row.kind,
        account: row.account.replace(/\s/g, ""),
        side: row.side,
        amount: `${Math.floor(grosze / 100)}.${String(grosze % 100).padStart(2, "0")}`,
        vat_rate: row.vat_rate,
        deduction: row.kind === "counterparty" ? null : row.deduction,
      };
    }),
  };
}

/** Podgląd opisu z wzoru reguły (jak `posting.render_description`). */
export function previewDescription(
  template: string,
  service: string,
  period: { year: number; month: number },
): string {
  const values: Record<string, string> = {
    usługa: service,
    MM: String(period.month).padStart(2, "0"),
    RRRR: String(period.year),
    numer: "FV/1/2026",
    kontrahent: "Kontrahent",
  };
  return template
    .replace(/\{([^{}]*)\}/g, (match, name: string) => values[name] ?? match)
    .replace(/\s+/g, " ")
    .trim();
}

/** Nieznane pola we wzorze opisu (serwer odrzuca je 422). */
export function unknownTemplateFields(template: string): string[] {
  const known = new Set(TEMPLATE_FIELDS.map((field) => field.slice(1, -1)));
  return [...template.matchAll(/\{([^{}]*)\}/g)]
    .map((match) => match[1])
    .filter((name) => !known.has(name));
}

/** Kategoria wybiera regułę dekretu: po „Gotowa”, w paczce i po zaksięgowaniu
 * jej nie zmienia się (serwer odmawia 409) — najpierw Cofnij / anuluj paczkę. */
export function categoryLocked(stage: CostStage, inBatch: boolean): boolean {
  return inBatch || stage === "ready" || stage === "booked";
}

/** „Kurs NBP EUR 4,2512 z 03.11.2026” albo `null` dla PLN. */
export function fxLabel(section: DecreeSection): string | null {
  if (!section.fx_rate || !section.currency || section.currency === "PLN") return null;
  const day = section.fx_date ? section.fx_date.split("-").reverse().join(".") : "—";
  return `Kurs NBP ${section.currency} ${section.fx_rate.replace(".", ",")} z ${day}`;
}

/** Poprzedni miesiąc „RRRR-MM” (eksport robi się zwykle za miniony miesiąc). */
export function previousMonth(today: string): string {
  const [year, month] = today.split("-").map(Number);
  return month === 1 ? `${year - 1}-12` : `${year}-${String(month - 1).padStart(2, "0")}`;
}
