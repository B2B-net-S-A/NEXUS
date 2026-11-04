"use client";

import { useOwnerLabels, useSalesSummary } from "@/lib/api/sales";

import type { SalesSelectOption } from "./SalesSelect";

/**
 * Opcje filtra „Opiekun”: moje, osoby prowadzące szanse (z podsumowania lejka
 * — lista dostępna każdemu z „Sprzedaż: podgląd”) i opiekunowie z Atlasa bez
 * konta w NEXUSIE (etykiety do przypisania przez admina).
 */
export function useOwnerFilterOptions(): SalesSelectOption[] {
  const summary = useSalesSummary(null, "all");
  const labels = useOwnerLabels();
  return [
    { value: "me", label: "Moje" },
    ...(summary.data?.by_owner ?? [])
      .filter((row) => row.owner)
      .map((row) => ({ value: `acct:${row.owner!.id}`, label: row.owner!.name })),
    ...(labels.data ?? []).map((entry) => ({
      value: `label:${entry.label}`,
      label: `${entry.label} · z Atlasa, bez konta (${entry.companies})`,
    })),
  ];
}
