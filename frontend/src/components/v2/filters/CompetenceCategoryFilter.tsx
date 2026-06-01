"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import {
  competenceCategoriesApi,
  type CompetenceCategoryOut,
} from "@/lib/api";
import { cn } from "@/lib/utils";

interface CompetenceCategoryFilterProps {
  /** Currently selected CC ids. */
  selected: number[];
  /** Called with the new selection on every toggle. */
  onChange: (ids: number[]) => void;
  /** ``"single"`` for radio behaviour, ``"multi"`` for checkboxes. */
  mode?: "single" | "multi";
  /** Optional facet counts ``{cc_id → count}`` rendered as a badge. */
  counts?: Record<number, number>;
  className?: string;
}

/**
 * Flagship filter for the manual candidate search – pinned in the planning
 * brief as the primary chip. Renders the 5 NEXUS competence categories
 * (Infrastructure / Development / Data & AI / Security & QA / Management)
 * fetched from `GET /api/competence-categories` so admin-facing additions or
 * renames flow through automatically.
 *
 * Lazy-loads the category list on mount; until the response arrives we render
 * a 5-tile skeleton so the chip layout doesn't pop in.
 */
export function CompetenceCategoryFilter({
  selected,
  onChange,
  mode = "multi",
  counts,
  className,
}: CompetenceCategoryFilterProps) {
  const [categories, setCategories] = useState<CompetenceCategoryOut[] | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    competenceCategoriesApi
      .list(true)
      .then((rows) => {
        if (!cancelled) setCategories(rows);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Nie udało się pobrać kategorii");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const toggle = (id: number) => {
    if (mode === "single") {
      onChange(selected.includes(id) ? [] : [id]);
      return;
    }
    onChange(
      selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id],
    );
  };

  if (error) {
    return (
      <div className={cn("text-sm text-rose-600 dark:text-rose-400", className)}>
        {error}
      </div>
    );
  }

  if (categories === null) {
    return (
      <div
        role="group"
        aria-busy="true"
        aria-label="Ładowanie kategorii kompetencji"
        className={cn("flex flex-wrap gap-2", className)}
      >
        {Array.from({ length: 5 }).map((_, i) => (
          <div
            key={i}
            className="h-8 w-32 animate-pulse rounded-md bg-zinc-100 dark:bg-zinc-800"
          />
        ))}
      </div>
    );
  }

  return (
    <div
      role={mode === "single" ? "radiogroup" : "group"}
      aria-label="Filtruj po kategorii kompetencji"
      className={cn("flex flex-wrap gap-2", className)}
    >
      {categories.map((cc) => {
        const isActive = selected.includes(cc.id);
        const count = counts?.[cc.id];
        return (
          <button
            key={cc.id}
            type="button"
            role={mode === "single" ? "radio" : "checkbox"}
            aria-checked={isActive}
            onClick={() => toggle(cc.id)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm",
              "transition-colors focus:outline-none focus-visible:ring-2",
              "focus-visible:ring-violet-500 focus-visible:ring-offset-2",
              isActive
                ? "border-violet-500 bg-violet-50 text-violet-700 dark:bg-violet-900/40 dark:text-violet-200 dark:border-violet-700"
                : "border-zinc-200 bg-white text-zinc-700 hover:bg-zinc-50 dark:bg-zinc-900 dark:text-zinc-200 dark:border-zinc-800 dark:hover:bg-zinc-800",
            )}
          >
            <span>{cc.name_pl}</span>
            {count !== undefined && (
              <Badge
                variant="neutral"
                className="ml-1 h-5 px-1.5 text-xs tabular-nums"
              >
                {count}
              </Badge>
            )}
          </button>
        );
      })}
    </div>
  );
}
