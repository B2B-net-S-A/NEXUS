"use client";

import { useQuery } from "@tanstack/react-query";
import {
  MultiSelectFilter,
  type MultiSelectFilterOption,
} from "@/components/v2/filters/MultiSelectFilter";
import { competenceCategoriesApi, type CompetenceCategoryOut } from "@/lib/api";

interface CompetenceCategoryMultiSelectProps {
  value: number[];
  onChange: (ids: number[]) => void;
  /** Tailwind width class for the trigger; defaults to `w-[190px]`. */
  triggerWidthClass?: string;
}

/**
 * Dropdown multi-select over the 5 NEXUS competence categories, populated from
 * `GET /api/competence-categories?active_only=true`. Mirrors the dropdown look
 * of the other jobs-list filters (status, client) rather than the chip layout
 * of `CompetenceCategoryFilter`, which is purpose-built for the sourcing brief.
 */
export function CompetenceCategoryMultiSelect({
  value,
  onChange,
  triggerWidthClass = "w-[190px]",
}: CompetenceCategoryMultiSelectProps) {
  const { data } = useQuery<CompetenceCategoryOut[]>({
    queryKey: ["competence-categories-active"],
    queryFn: () => competenceCategoriesApi.list(true),
    staleTime: 300_000,
  });

  const options: MultiSelectFilterOption<number>[] = (data ?? []).map((cc) => ({
    value: cc.id,
    label: cc.name_pl,
  }));

  return (
    <MultiSelectFilter<number>
      value={value}
      onChange={onChange}
      options={options}
      placeholder="Kategoria: dowolna"
      searchPlaceholder="Szukaj kategorii…"
      triggerWidthClass={triggerWidthClass}
      triggerLabel={(n) =>
        n === 1
          ? (options.find((o) => o.value === value[0])?.label ?? "Kategoria")
          : `Kategorie: ${n}`
      }
    />
  );
}
