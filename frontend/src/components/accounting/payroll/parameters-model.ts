/**
 * Parametry płac (K7a) — czyste funkcje ekranu „Parametry”: wartości po
 * polsku, grupy z katalogu, sprawdzenie nowej wersji jak na serwerze
 * (liczba, zakres, całkowita) i różnica do obowiązującej wersji.
 */
import type { ParamCatalogItem, PayrollCompany } from "@/lib/api/payroll-lists";

import { zl } from "./payroll-model";

/** „9,76%”, „282 600,00 zł”, „26 lat” — wartość parametru z jednostką. */
export function paramText(value: string | null | undefined, unit: string): string {
  if (value == null || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  if (unit === "zł") return `${zl(value)} zł`;
  const plain = String(number).replace(".", ",");
  if (unit === "%") return `${plain}%`;
  return unit ? `${plain} ${unit}` : plain;
}

/** Wartość z bazy do pola formularza („9.76” → „9,76”). */
export function paramField(value: string | null | undefined): string {
  if (value == null || value === "") return "";
  const number = Number(value);
  return Number.isFinite(number) ? String(number).replace(".", ",") : value;
}

/** Pole formularza do API: bez spacji, kropka dziesiętna („282 600,5” → „282600.5”). */
export function paramValue(raw: string): string {
  return raw.replace(/[\s ]/g, "").replace(",", ".");
}

export interface ParamGroup {
  group: string;
  items: ParamCatalogItem[];
}

/** Katalog w grupach w kolejności z serwera (ZUS, płaca minimalna, PIT, PPK, wiek). */
export function paramGroups(catalog: readonly ParamCatalogItem[]): ParamGroup[] {
  const groups: ParamGroup[] = [];
  for (const item of catalog) {
    const found = groups.find((group) => group.group === item.group);
    if (found) found.items.push(item);
    else groups.push({ group: item.group, items: [item] });
  }
  return groups;
}

/** Problemy nowej wersji (te same zdania co serwer); pusta lista = można zapisać. */
export function paramProblems(catalog: readonly ParamCatalogItem[], values: Record<string, string>): string[] {
  const problems: string[] = [];
  for (const item of catalog) {
    const text = paramValue(values[item.key] ?? "");
    const number = Number(text);
    if (!text || !/^-?\d+(\.\d+)?$/.test(text) || !Number.isFinite(number)) {
      problems.push(`${item.label}: podaj liczbę.`);
      continue;
    }
    if (item.integer === "1" && !Number.isInteger(number)) {
      problems.push(`${item.label}: liczba całkowita.`);
      continue;
    }
    if ((text.split(".")[1] ?? "").length > 4) {
      problems.push(`${item.label}: najwyżej 4 miejsca po przecinku.`);
      continue;
    }
    if (number < Number(item.min) || number > Number(item.max)) {
      problems.push(`${item.label}: od ${paramField(item.min)} do ${paramField(item.max)} ${item.unit}`.trimEnd() + ".");
    }
  }
  const number = (key: string) => Number(paramValue(values[key] ?? ""));
  if (number("pit_rate_high") < number("pit_rate_low")) {
    problems.push("Druga stawka skali PIT nie może być niższa od pierwszej.");
  }
  if (number("kup_increased") < number("kup_standard")) {
    problems.push("Podwyższone koszty uzyskania nie mogą być niższe od zwykłych.");
  }
  return problems;
}

/** Ile parametrów różni się od obowiązującej wersji (porównanie liczb). */
export function changedParams(
  catalog: readonly ParamCatalogItem[],
  before: Record<string, string>,
  values: Record<string, string>,
): ParamCatalogItem[] {
  return catalog.filter((item) => Number(before[item.key]) !== Number(paramValue(values[item.key] ?? "")));
}

/** Pierwszy dzień następnego miesiąca po `today` jako „RRRR-MM” (pole `type="month"`). */
export function nextMonth(today: string): string {
  const year = Number(today.slice(0, 4));
  const month = Number(today.slice(5, 7));
  return month === 12 ? `${year + 1}-01` : `${year}-${String(month + 1).padStart(2, "0")}`;
}

const COMPANY_MISSING: Record<string, string> = {
  regon: "REGON",
  tax_office_code: "kod urzędu skarbowego",
};

/** „REGON, kod urzędu skarbowego” — czego brakuje w danych płatnika. */
export function companyMissing(company: Pick<PayrollCompany, "missing">): string {
  return company.missing.map((code) => COMPANY_MISSING[code] ?? code).join(", ");
}
