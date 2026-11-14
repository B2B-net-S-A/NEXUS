/**
 * Środki trwałe (K6) — czyste funkcje ekranu: formularz środka → ciało
 * żądania (z tymi samymi warunkami co serwer), etykiety, okno planu wokół
 * wybranego miesiąca, komunikat po „Nalicz amortyzację”.
 */
import type {
  AssetInput,
  AssetKind,
  AssetMethod,
  AssetPlanRow,
  AssetsSyncResult,
} from "@/lib/api/accounting-assets";

import { parseAmount } from "./ledger-model";

export const METHOD_LABELS: Record<AssetMethod, string> = {
  linear: "liniowa",
  degressive: "degresywna",
  one_off: "jednorazowa",
  none: "bez amortyzacji",
};

export const DEFAULT_ACCOUNTS: Record<AssetKind, { asset: string; depreciation: string }> = {
  fixed: { asset: "010", depreciation: "070" },
  intangible: { asset: "020", depreciation: "071" },
};

/** MPK środka: piony z kartoteki i koszty ogólne; klient jako `K<id>`. */
export const MPK_OPTIONS: ReadonlyArray<{ code: string; label: string }> = [
  { code: "OG", label: "Koszty ogólne" },
  { code: "FO", label: "Front office" },
  { code: "BO", label: "Back office" },
];

const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const KST_RE = /^\d{1,3}([.-]\d{1,3}){0,3}$/;
const MPK_RE = /^(FO|BO|OG|K\d{1,9})$/;

/** „2026-10” → „10.2026”. */
export function monthText(value: string | null | undefined): string {
  if (!value) return "—";
  const [year, month] = value.split("-");
  return `${month}.${year}`;
}

/** „30.00” / „30” / „12.5” → „30%” / „12,5%”. */
export function rateText(value: string | null | undefined): string {
  if (value == null || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return `${String(Number(number.toFixed(2))).replace(".", ",")}%`;
}

export function planLabel(method: AssetMethod, rate: string): string {
  if (method === "one_off" || method === "none") return METHOD_LABELS[method];
  return `${METHOD_LABELS[method]}, ${rateText(rate)} rocznie`;
}

/** Stawka z pola („30”, „12,5”, „30%”) → „30.00” albo `null`, gdy spoza 0–100. */
export function parseRate(raw: string): string | null {
  const text = raw.replace(/[\s%]/g, "").replace(",", ".");
  if (!/^\d{1,3}(\.\d{1,2})?$/.test(text)) return null;
  const value = Number(text);
  if (value < 0 || value > 100) return null;
  return value.toFixed(2);
}

export interface AssetFormValues {
  name: string;
  kind: AssetKind;
  kst: string;
  inventoryNumber: string;
  acceptedOn: string;
  initialValue: string;
  assetAccount: string;
  depreciationAccount: string;
  mpk: string;
  balanceMethod: AssetMethod;
  balanceRate: string;
  taxMethod: AssetMethod;
  taxRate: string;
  coefficient: string;
  note: string;
  equipmentItemId: number | null;
  costEntryId: number | null;
  postIntake: boolean;
  counterAccount: string;
  fromSymfonia: boolean;
  openingMonth: string;
  openingBalance: string;
  openingTax: string;
  openingBalanceYear: string;
  openingTaxYear: string;
}

export function emptyAssetForm(today: string, intakeAccount: string): AssetFormValues {
  return {
    name: "",
    kind: "fixed",
    kst: "",
    inventoryNumber: "",
    acceptedOn: today,
    initialValue: "",
    assetAccount: DEFAULT_ACCOUNTS.fixed.asset,
    depreciationAccount: DEFAULT_ACCOUNTS.fixed.depreciation,
    mpk: "OG",
    balanceMethod: "linear",
    balanceRate: "",
    taxMethod: "linear",
    taxRate: "",
    coefficient: "2,0",
    note: "",
    equipmentItemId: null,
    costEntryId: null,
    postIntake: true,
    counterAccount: intakeAccount,
    fromSymfonia: false,
    openingMonth: today.slice(0, 7),
    openingBalance: "0",
    openingTax: "",
    openingBalanceYear: "",
    openingTaxYear: "",
  };
}

function needsRate(method: AssetMethod): boolean {
  return method === "linear" || method === "degressive";
}

/** Kwota umorzenia: puste = 0 (gdy `zeroIfEmpty`), inaczej tekst dla API albo błąd. */
function accumulated(raw: string, zeroIfEmpty: boolean): string | null | undefined {
  if (!raw.trim()) return zeroIfEmpty ? "0.00" : undefined;
  if (/^0+([.,]0{1,2})?$/.test(raw.replace(/[\s ]/g, ""))) return "0.00";
  const amount = parseAmount(raw);
  if (amount == null || amount.startsWith("-")) return null;
  return amount;
}

/**
 * Formularz → ciało POST /assets (albo PATCH, gdy `planLocked` — wtedy tylko
 * opis) i lista problemów w kolejności pól. Pusta lista = można wysłać.
 */
export function assetBody(
  values: AssetFormValues,
  { planLocked = false }: { planLocked?: boolean } = {},
): { body: AssetInput; problems: string[] } {
  const problems: string[] = [];
  const name = values.name.trim();
  if (!name) problems.push("Podaj nazwę środka.");
  const kst = values.kst.replace(/\s/g, "");
  if (values.kind === "fixed" && !KST_RE.test(kst)) problems.push("Podaj symbol KŚT (np. 491).");
  const descriptive: AssetInput = {
    name,
    kst: values.kind === "fixed" ? kst : null,
    inventory_number: values.inventoryNumber.trim() || null,
    note: values.note.trim(),
    equipment_item_id: values.equipmentItemId,
  };
  if (planLocked) return { body: descriptive, problems };

  if (!DATE_RE.test(values.acceptedOn)) problems.push("Podaj datę przyjęcia.");
  const initial = parseAmount(values.initialValue);
  if (initial == null || initial.startsWith("-")) problems.push("Podaj wartość początkową większą od zera.");
  const mpk = values.mpk.replace(/\s/g, "").toUpperCase();
  if (!MPK_RE.test(mpk)) problems.push("MPK: OG, FO, BO albo K<id klienta>.");
  const balanceRate = parseRate(values.balanceRate || "0");
  const taxRate = parseRate(values.taxRate || values.balanceRate || "0");
  if (balanceRate == null) problems.push("Stawka bilansowa: od 0 do 100%.");
  else if (needsRate(values.balanceMethod) && Number(balanceRate) <= 0)
    problems.push("Plan bilansowy: podaj stawkę.");
  if (taxRate == null) problems.push("Stawka podatkowa: od 0 do 100%.");
  else if (needsRate(values.taxMethod) && Number(taxRate) <= 0) problems.push("Plan podatkowy: podaj stawkę.");
  if (values.kind === "intangible" && values.taxMethod === "degressive")
    problems.push("WNiP podatkowo: liniowa albo jednorazowa (art. 16k ustawy o CIT).");
  const usesCoefficient = values.balanceMethod === "degressive" || values.taxMethod === "degressive";
  const coefficient = values.coefficient.replace(",", ".").trim();
  if (usesCoefficient && !(Number(coefficient) >= 1 && Number(coefficient) <= 2))
    problems.push("Współczynnik degresywnej: od 1,0 do 2,0.");

  const body: AssetInput = {
    ...descriptive,
    kind: values.kind,
    accepted_on: values.acceptedOn,
    initial_value: initial ?? undefined,
    asset_account: values.assetAccount.trim() || null,
    depreciation_account: values.depreciationAccount.trim() || null,
    mpk,
    balance_method: values.balanceMethod,
    balance_rate: balanceRate ?? undefined,
    tax_method: values.taxMethod,
    tax_rate: taxRate ?? undefined,
    coefficient: usesCoefficient ? Number(coefficient).toFixed(2) : null,
  };

  if (values.fromSymfonia) {
    if (!MONTH_RE.test(values.openingMonth)) problems.push("Stan z Symfonii: podaj miesiąc stanu.");
    const balance = accumulated(values.openingBalance, true);
    const tax = accumulated(values.openingTax, false);
    const balanceYear = accumulated(values.openingBalanceYear, false);
    const taxYear = accumulated(values.openingTaxYear, false);
    if ([balance, tax, balanceYear, taxYear].some((value) => value === null))
      problems.push("Stan z Symfonii: umorzenie jako kwota (np. 1234,56).");
    body.opening = {
      month: `${values.openingMonth}-01`,
      balance: balance ?? "0.00",
      tax: tax ?? null,
      balance_year: balanceYear ?? null,
      tax_year: taxYear ?? null,
    };
  } else {
    body.opening = null;
    body.post_intake = values.postIntake;
    body.counter_account = values.postIntake ? values.counterAccount.trim() || null : null;
    body.cost_entry_id = values.costEntryId;
  }
  return { body, problems };
}

/** Wiersze planu wokół wybranego miesiąca (z nim w środku), żeby lista nie miała 800 pozycji. */
export function planWindow(rows: readonly AssetPlanRow[], month: string, size = 12): AssetPlanRow[] {
  if (rows.length <= size) return [...rows];
  const index = rows.findIndex((row) => row.month >= month);
  const anchor = index === -1 ? rows.length - 1 : index;
  const start = Math.max(0, Math.min(anchor - Math.floor(size / 3), rows.length - size));
  return rows.slice(start, start + size);
}

function syncPart(label: string, result: AssetsSyncResult["operations"]): string | null {
  const parts = [
    result.created && `nowe ${result.created}`,
    result.rebuilt && `przebudowane ${result.rebuilt}`,
    result.deleted && `usunięte ${result.deleted}`,
    result.unchanged && `bez zmian ${result.unchanged}`,
  ].filter(Boolean);
  return parts.length ? `${label}: ${parts.join(", ")}` : null;
}

/** Komunikat po „Nalicz amortyzację” — co trafiło do bufora. */
export function assetsSyncMessage(result: AssetsSyncResult): string {
  const parts = [
    syncPart("AM", result.depreciation),
    syncPart("dokumenty środków", result.operations),
  ].filter(Boolean);
  const problems = result.depreciation.problems_total + result.operations.problems_total;
  const head = parts.length ? `Do bufora — ${parts.join("; ")}.` : "Nic nowego do zaksięgowania w tym miesiącu.";
  return problems ? `${head} Do wyjaśnienia: ${problems} (szczegóły w „Źródłach”).` : head;
}
