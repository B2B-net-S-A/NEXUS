"use client";

import { useOwnerLabels, useSalesSummary } from "@/lib/api/sales";

import type { SalesSelectOption } from "./SalesSelect";

/**
 * Opcje filtra „Opiekun”: moje, osoby prowadzące szanse (z podsumowania lejka
 * — lista dostępna każdemu z „Sprzedaż: podgląd”) i opiekunowie z Atlasa bez
 * konta w NEXUSIE (etykiety do przypisania przez admina).
 *
 * `pipelineId` to oglądany lejek inny niż domyślny: opiekun kont Fabryk IT nie
 * musi mieć szansy w lejku Sprzedaż, a bez niego nie dało się go wybrać w filtrze.
 */
export function useOwnerFilterOptions(pipelineId: number | null = null): SalesSelectOption[] {
  const summary = useSalesSummary(pipelineId, "all");
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
