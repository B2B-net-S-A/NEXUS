"use client";

import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { competenceCategoriesApi, type CompetenceCategoryOut } from "@/lib/api";

/**
 * Cztery kategorie kompetencji zespołu (od 24.09.2026) — jeden wariant Badge
 * na slug, same tokeny design systemu. Slugi zostały z czasów pięciu
 * kategorii: `security_quality` to dziś QA, a `infrastructure_operations`
 * obejmuje też security oraz dane i AI.
 */
const CC_TONE: Record<string, "info" | "soft" | "success" | "warning"> = {
  infrastructure_operations: "info",
  software_development: "success",
  security_quality: "warning",
  management_delivery: "soft",
};

/**
 * Wycofana kategoria „Dane i AI” należy dziś do grupy Infra. Stare pole
 * tekstowe kandydata (`competence_category`) nadal może nieść `data_ai`,
 * a katalog zwraca tylko aktywne kategorie — bez aliasu plakietka by znikła.
 */
const RETIRED_SLUG_ALIAS: Record<string, string> = {
  data_ai: "infrastructure_operations",
};

/** Wariant Badge dla kategorii — ten sam kolor na pulpicie i w plakietce. */
export function competenceTone(
  slug: string | null | undefined,
): "info" | "soft" | "success" | "warning" | "neutral" {
  const resolved = resolveSlug(slug)
  return (resolved && CC_TONE[resolved]) || "neutral"
}

function resolveSlug(slug: string | null | undefined): string | null {
  if (!slug) return null;
  return RETIRED_SLUG_ALIAS[slug] ?? slug;
}

/**
 * Cached catalog of the 4 active competence categories. Shares the query key
 * with `CompetenceCategoryMultiSelect`, so opening the filter or rendering a
 * badge warms the same cache — one request per session.
 */
export function useCompetenceCategories() {
  return useQuery<CompetenceCategoryOut[]>({
    queryKey: ["competence-categories-active"],
    queryFn: () => competenceCategoriesApi.list(true),
    staleTime: 300_000,
  });
}

interface CompetenceCategoryBadgeProps {
  /** Primary competence-category id (preferred — robust to slug drift). */
  categoryId?: number | null;
  /** Legacy slug fallback when the id isn't available on the row. */
  slug?: string | null;
  size?: "sm" | "md" | "lg";
  className?: string;
}

/**
 * Small token-tinted badge naming a candidate's primary competence category.
 * Resolves the display name (`name_pl`) + tone from the cached CC catalog.
 * Renders nothing when the candidate has no category or the catalog hasn't
 * resolved a match yet — never shows a raw slug.
 */
export function CompetenceCategoryBadge({
  categoryId,
  slug,
  size = "sm",
  className,
}: CompetenceCategoryBadgeProps) {
  const { data } = useCompetenceCategories();
  if (categoryId == null && !slug) return null;

  const cc =
    (categoryId != null
      ? data?.find((c) => c.id === categoryId)
      : undefined) ??
    (slug ? data?.find((c) => c.slug === resolveSlug(slug)) : undefined);
  if (!cc) return null;

  const tone = CC_TONE[cc.slug] ?? "neutral";
  return (
    <Badge variant={tone} size={size} className={className} title={cc.name_pl}>
      {cc.name_pl}
    </Badge>
  );
}

/**
 * Sama nazwa kategorii (bez plakietki) — dla miejsc, gdzie kategoria jest
 * zwykłym tekstem w linii metadanych. Jak plakietka: nigdy surowy klucz
 * (`software_development`), a dopóki katalog się nie wczytał — nic.
 */
export function CompetenceCategoryName({
  categoryId,
  slug,
}: {
  categoryId?: number | null;
  slug?: string | null;
}) {
  const { data } = useCompetenceCategories();
  if (categoryId == null && !slug) return null;
  const cc =
    (categoryId != null ? data?.find((c) => c.id === categoryId) : undefined) ??
    (slug ? data?.find((c) => c.slug === resolveSlug(slug)) : undefined);
  return cc ? <>{cc.name_pl}</> : null;
}
