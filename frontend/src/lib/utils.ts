import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatCurrency(amount: number | null | undefined, currency = "PLN"): string {
  if (amount == null) return "–";
  return new Intl.NumberFormat("pl-PL", { style: "currency", currency }).format(amount);
}

export function formatDate(date: string | Date | null | undefined): string {
  if (!date) return "–";
  return new Intl.DateTimeFormat("pl-PL").format(new Date(date));
}

export function formatRelativeTime(date: string | Date | null | undefined): string {
  if (!date) return "–";
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
