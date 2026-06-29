import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatCurrency(amount: number | null | undefined, currency = "PLN"): string {
  if (amount == null) return "—";
  return new Intl.NumberFormat("pl-PL", {
    style: "currency",
    currency,
    maximumFractionDigits: 3,
  }).format(amount);
}

export function formatDate(date: string | Date | null | undefined): string {
  if (!date) return "—";
  return new Intl.DateTimeFormat("pl-PL").format(new Date(date));
}

export function formatRelativeTime(date: string | Date | null | undefined): string {
  if (!date) return "—";
  const now = new Date();
  const d = new Date(date);
  const diffMs = now.getTime() - d.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  const diffH = Math.floor(diffMin / 60);
  const diffDays = Math.floor(diffH / 24);

  if (diffMin < 1) return "przed chwilą";
  if (diffMin < 60) return `${diffMin} min temu`;
  if (diffH < 24) return `${diffH}h temu`;
  if (diffDays === 1) return "wczoraj";
  if (diffDays < 7) return `${diffDays} dni temu`;
  return formatDate(date);
}

export function calcMargin(rateClient?: number, rateCandidate?: number): number | null {
  if (rateClient == null || rateCandidate == null) return null;
  return rateClient - rateCandidate;
}

/**
 * Pola stawek po polsku przyjmują przecinek dziesiętny (np. „215,60"). Natywne
 * `<input type="number">` w przeglądarce o locale z kropką dziesiętną odrzuca
 * przecinek (sanityzuje value→""), więc pola kwotowe używają
 * `type="text" inputMode="decimal"` + tych helperów (spójnie z normalizacją
 * przecinka w modalach stawek).
 */

/** Przepuszcza tylko cyfry i jeden separator dziesiętny (przecinek lub kropkę). */
export function sanitizeDecimalInput(raw: string): string {
  const cleaned = raw.replace(/[^\d.,]/g, "");
  const sepIndex = cleaned.search(/[.,]/);
  if (sepIndex === -1) return cleaned;
  // Zostaw tylko pierwszy separator; kolejne separatory w części ułamkowej usuń.
  const head = cleaned.slice(0, sepIndex + 1);
  const tail = cleaned.slice(sepIndex + 1).replace(/[.,]/g, "");
  return head + tail;
}

/** Parsuje wartość pola (przecinek lub kropka) na number; pusty/niepoprawny → null. */
export function parseDecimalInput(value: string): number | null {
  const normalized = value.trim().replace(",", ".");
  if (normalized === "") return null;
  const parsed = Number.parseFloat(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}
