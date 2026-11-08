"use client";

/**
 * Wybór kategorii hasła słownika (etap 2, 06.11.2026). Kategoria decyduje, czy
 * hasło jest technologią (pogrubianie CV, QC, bramka must), więc nowe hasło jej
 * wymaga. Lista z serwera: kategorie słownika bez ról plus praktyki i wiedza
 * domenowa — ta sama co w propozycjach.
 */

import { useQuery } from "@tanstack/react-query";

import { skillsAdminApi } from "@/lib/api";
import { skillCategoryLabel } from "@/lib/skill-categories";

export const skillCategoriesQueryKey = ["skills-admin", "skills", "categories"] as const;

/** Kategorie do wyboru; pusta lista, dopóki serwer nie odpowie. */
export function useSkillCategories(): string[] {
  const query = useQuery({
    queryKey: skillCategoriesQueryKey,
    queryFn: () => skillsAdminApi.list({ kind: "skills", limit: 1 }),
    staleTime: 5 * 60_000,
  });
  return query.data?.categories ?? [];
}

export function SkillCategorySelect({
  value,
  onChange,
  categories,
  label = "Kategoria",
  allowEmpty = false,
  className = "",
}: {
  value: string;
  onChange: (value: string) => void;
  categories: readonly string[];
  label?: string;
  /** „Bez kategorii” tylko tam, gdzie brak kategorii jest dopuszczalny. */
  allowEmpty?: boolean;
  className?: string;
}) {
  // Bieżąca wartość spoza listy (np. kategoria roli) zostaje do wyboru.
  const options = value && !categories.includes(value) ? [value, ...categories] : categories;
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-label={label}
      className={`h-9 rounded-md border border-border bg-background px-2 text-sm text-foreground ${className}`}
    >
      <option value="">{allowEmpty ? "Bez kategorii" : "Wybierz kategorię…"}</option>
      {options.map((c) => (
        <option key={c} value={c}>
          {skillCategoryLabel(c)}
        </option>
      ))}
    </select>
  );
}
