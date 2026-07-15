"use client";

import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { competenceCategoriesApi, type CompetenceCategoryOut } from "@/lib/api";

/**
 * Coordinated 5-hue token map — one Badge variant per competence-category slug.
 * All variants are design-system tokens (no hardcoded colours), so the set
 * stays legible in light/dark/soft themes.
 */
const CC_TONE: Record<
  string,
  "info" | "soft" | "success" | "danger" | "warning"
> = {
  infrastructure_operations: "info",
  software_development: "soft",
  data_ai: "success",
  security_quality: "danger",
  management_delivery: "warning",
};

/**
 * Cached catalog of the 5 active competence categories. Shares the query key
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
    (slug ? data?.find((c) => c.slug === slug) : undefined);
  if (!cc) return null;

  const tone = CC_TONE[cc.slug] ?? "neutral";
  return (
    <Badge variant={tone} size={size} className={className} title={cc.name_pl}>
      {cc.name_pl}
    </Badge>
  );
}
