// Czyste funkcje ekranów K7b: pensje UoP, nieobecności, rozbicie pozycji z pensji,
// dekret LP i porównanie z Enovą. Bez Reacta — testy w `__tests__/k7b-model.test.ts`.

import type { PayrollLine } from "@/lib/api/payroll-lists";
import type {
  ComponentKind,
  EnovaComparison,
  PayrollComponentRow,
  PayrollSalaryRow,
  SickRate,
} from "@/lib/api/payroll-k7b";

import { gr } from "../ledger-model";
import { plural, zl } from "./payroll-model";

export const SICK_RATE_OPTIONS: readonly { value: SickRate; label: string }[] = [
  { value: "80", label: "80%" },
  { value: "100", label: "100% (ciąża, wypadek w drodze, dawstwo)" },
  { value: "zus", label: "Zasiłek z ZUS od 1. dnia (np. opieka)" },
];

export const COMPONENT_KINDS: readonly ComponentKind[] = ["variable", "other", "sick_base", "equivalent_days"];

export const COMPONENT_SHORT: Record<ComponentKind, string> = {
  variable: "Zmienne",
  other: "Poza podstawami",
  sick_base: "Podstawa L4",
  equivalent_days: "Dni ekwiwalentu",
};

/** Pierwszy dzień miesiąca jako „RRRR-MM-01”. */
export function firstOfMonth(year: number, month: number): string {
  return `${year}-${String(month).padStart(2, "0")}-01`;
}

/** Pensja obowiązująca w dniu `on` (pensje zaczynają się 1. dnia miesiąca). */
export function salaryOn(rows: readonly PayrollSalaryRow[], userId: number, on: string): PayrollSalaryRow | null {
  return (
    rows
      .filter(
        (row) =>
          row.user_id === userId && row.effective_from <= on && (row.effective_to == null || row.effective_to >= on),
      )
      .sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0] ?? null
  );
}

export function salaryHistory(rows: readonly PayrollSalaryRow[], userId: number): PayrollSalaryRow[] {
  return rows
    .filter((row) => row.user_id === userId)
    .sort((a, b) => b.effective_from.localeCompare(a.effective_from));
}

/** „1” → „pełny etat”, „0.5” → „0,5 etatu”. */
export function fteLabel(fte: string): string {
  const value = Number(fte);
  if (!Number.isFinite(value) || value >= 1) return "pełny etat";
  return `${String(value).replace(".", ",")} etatu`;
}

/** „2026-11-01” → „11.2026”. */
export function monthOf(day: string): string {
  const [year, month] = day.split("-");
  return `${month}.${year}`;
}

export function componentFor(
  rows: readonly PayrollComponentRow[],
  userId: number,
  kind: ComponentKind,
): PayrollComponentRow | null {
  return rows.find((row) => row.user_id === userId && row.kind === kind) ?? null;
}

/** Kwota pensji: tekst z przecinkiem albo kropką → „8000.00”; `null` = nieczytelna. */
export function parseSalary(raw: string): string | null {
  const text = raw.replace(/\s/g, "").replace(",", ".");
  if (!/^\d{1,8}(\.\d{1,2})?$/.test(text)) return null;
  const value = Number(text);
  return value > 0 ? value.toFixed(2) : null;
}

/** Etat: „1”, „1/2”, „0,5” → tekst dziesiętny; `null` = spoza (0, 1]. */
export function parseFte(raw: string): string | null {
  const text = raw.replace(/\s/g, "").replace(",", ".");
  const fraction = /^(\d+)\/(\d+)$/.exec(text);
  const value = fraction ? Number(fraction[1]) / Number(fraction[2]) : Number(text);
  if (!text || !Number.isFinite(value) || value <= 0 || value > 1) return null;
  return String(Math.round(value * 1000) / 1000);
}

interface SickPart {
  rate: string;
  base: string;
  daily: string;
  paid_days: number;
  zus_days: number;
  waiting_days: number;
  amount: string;
}

interface K7bData {
  salary_part?: string;
  sick_pay?: string;
  leave_variable?: string;
  equivalent?: string;
  variable?: string;
  other?: string;
  bonuses?: string;
  nominal_hours?: string;
  worked_hours?: string;
  sick?: SickPart[];
}

export interface K7bRow {
  label: string;
  value: string;
  detail?: string;
}

function k7bOf(line: PayrollLine): K7bData | null {
  const data = line.basis?.k7b;
  return data && typeof data === "object" ? (data as K7bData) : null;
}

/** Skąd brutto pozycji z pensji: pensja, chorobowe (dni, podstawa), urlopowe, ekwiwalent. */
export function k7bRows(line: PayrollLine): K7bRow[] {
  const data = k7bOf(line);
  if (!data) return [];
  const rows: K7bRow[] = [
    {
      label: "Pensja za przepracowaną część",
      value: zl(data.salary_part),
      detail:
        data.nominal_hours != null
          ? `wymiar ${String(data.nominal_hours).replace(".", ",")} h, przepracowane ${String(data.worked_hours ?? "0").replace(".", ",")} h`
          : undefined,
    },
  ];
  for (const part of data.sick ?? []) {
    const days = [
      part.paid_days ? plural(part.paid_days, "dzień", "dni", "dni") + ` × ${zl(part.daily)}` : null,
      part.waiting_days ? `okres wyczekiwania: ${plural(part.waiting_days, "dzień", "dni", "dni")}` : null,
      part.zus_days ? `zasiłek ZUS: ${plural(part.zus_days, "dzień", "dni", "dni")}` : null,
    ].filter(Boolean);
    rows.push({
      label: `Wynagrodzenie chorobowe ${part.rate}%`,
      value: zl(part.amount),
      detail: `${days.join(" · ")}${Number(part.base) > 0 ? ` · podstawa ${zl(part.base)}` : ""}`,
    });
  }
  for (const [key, label] of [
    ["leave_variable", "Urlopowe za składniki zmienne"],
    ["equivalent", "Ekwiwalent za urlop"],
    ["variable", "Składniki zmienne"],
    ["other", "Inne składniki"],
    ["bonuses", "Premie"],
  ] as const) {
    const value = data[key];
    if (value != null && Number(value) !== 0) rows.push({ label, value: zl(value) });
  }
  return rows;
}

/** Grosze ze znakiem → „+1,00” / „−0,01” / „0,00”. */
export function diffLabel(grosze: number): string {
  const text = gr(Math.abs(grosze));
  if (grosze > 0) return `+${text}`;
  if (grosze < 0) return `−${text}`;
  return text;
}

/** Jedno zdanie o wyniku porównania z Enovą. */
export function comparisonSummary(result: EnovaComparison): string {
  const { summary } = result;
  if (summary.all_equal) {
    return `Zgodne do grosza: ${plural(summary.equal, "osoba", "osoby", "osób")}.`;
  }
  const parts = [
    `zgodne: ${summary.equal} z ${summary.matched}`,
    summary.different ? `z różnicą: ${summary.different}` : null,
    summary.only_nexus ? `tylko w NEXUSIE: ${summary.only_nexus}` : null,
    summary.only_enova ? `tylko w Enovie: ${summary.only_enova}` : null,
  ].filter(Boolean);
  return `${parts.join(" · ")}.`;
}

export interface K7bAction {
  enabled: boolean;
  reason: string | null;
  label: string;
}

/** „Do księgi”: tylko zatwierdzona lista; zatwierdzony LP poprawia się stornem w księdze. */
export function ledgerAction(list: { status: string; ledger_document?: { number: string; status: string } | null }): K7bAction {
  const doc = list.ledger_document;
  if (list.status !== "approved") {
    return { enabled: false, reason: "Do księgi idzie zatwierdzona lista.", label: "LP do księgi" };
  }
  if (doc && doc.status !== "draft") {
    return {
      enabled: false,
      reason: `LP ${doc.number} jest zatwierdzony w księdze — popraw go stornem.`,
      label: `LP ${doc.number} w księdze`,
    };
  }
  return { enabled: true, reason: null, label: doc ? "Przebuduj LP w buforze" : "LP do księgi" };
}
