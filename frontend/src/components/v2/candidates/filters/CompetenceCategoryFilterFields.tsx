"use client";

import { CompetenceCategoryMultiSelect } from "@/components/v2/filters/CompetenceCategoryMultiSelect";
import type { CandidateFilters } from "@/lib/url-filters";

export type CompetenceCategoryValue = Pick<CandidateFilters, "competenceCategoryIds">;

interface CompetenceCategoryFilterFieldsProps {
  value: CompetenceCategoryValue;
  /** Łatka filtrów; wołający sam zeruje stronę. */
  onPatch: (patch: Partial<CandidateFilters>) => void;
}

/**
 * Kategoria kompetencji (5 głównych obszarów, dopasowuje też poboczne) —
 * ten sam blok w szufladzie „Filtry" i w pigułce „Kategoria" nad listą.
 */
export function CompetenceCategoryFilterFields({
  value,
  onPatch,
}: CompetenceCategoryFilterFieldsProps) {
  return (
    <div className="space-y-1.5">
      <p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
        Kategoria
      </p>
      <CompetenceCategoryMultiSelect
        value={value.competenceCategoryIds}
        onChange={(ids) => onPatch({ competenceCategoryIds: ids })}
        triggerWidthClass="w-full"
      />
      <p className="text-[10px] text-muted-foreground">
        Główny obszar kandydata (dopasowuje też kategorie poboczne).
      </p>
    </div>
  );
}
