"use client";

import { Badge, type BadgeProps } from "@/components/ui/badge";

/**
 * Shared, purely-presentational labels + badges for the Cortex Action Layer
 * (drill-down drawer, successors, client×stack). Token-first — colors come from
 * the Badge variants (semantic tokens), never hardcoded.
 */

// ── Seniority ─────────────────────────────────────────────────────────────────

export const SENIORITY_LABELS: Record<string, string> = {
  junior: "Junior",
  mid: "Mid",
  senior: "Senior",
  unknown: "Nieznane",
};

const SENIORITY_VARIANT: Record<string, BadgeProps["variant"]> = {
  senior: "soft",
  mid: "info",
  junior: "neutral",
  unknown: "outline",
};

export function SeniorityBadge({ seniority }: { seniority: string }) {
  return (
    <Badge variant={SENIORITY_VARIANT[seniority] ?? "outline"} size="sm">
      {SENIORITY_LABELS[seniority] ?? seniority}
    </Badge>
  );
}

// ── Freshness (parity with CoverageView ramp) ────────────────────────────────

export const FRESHNESS_LABELS: Record<string, string> = {
  lt_1y: "‹ 1 rok",
  y1_3: "1–3 lata",
  gt_3y: "› 3 lata",
  unknown: "nieznana data",
};

// fresh → good (success), medium → warning, stale → danger, unknown → neutral.
const FRESHNESS_VARIANT: Record<string, BadgeProps["variant"]> = {
  lt_1y: "success",
  y1_3: "warning",
  gt_3y: "danger",
  unknown: "outline",
};

export function FreshnessBadge({ freshness }: { freshness: string }) {
  return (
    <Badge variant={FRESHNESS_VARIANT[freshness] ?? "outline"} size="sm">
      {FRESHNESS_LABELS[freshness] ?? freshness}
    </Badge>
  );
}

// ── Availability ─────────────────────────────────────────────────────────────

export const AVAILABILITY_LABELS: Record<string, string> = {
  actively_looking: "Aktywnie szuka",
  open_to_offers: "Otwarty na projekty",
  not_looking: "Nie szuka",
  unknown: "Nie wiemy",
};

const AVAILABILITY_VARIANT: Record<string, BadgeProps["variant"]> = {
  actively_looking: "success",
  open_to_offers: "info",
  not_looking: "neutral",
  unknown: "outline",
};

export function availabilityLabel(status: string | null): string {
  if (!status) return AVAILABILITY_LABELS.unknown;
  return AVAILABILITY_LABELS[status] ?? status;
}

export function AvailabilityBadge({ status }: { status: string | null }) {
  const key = status ?? "unknown";
  return (
    <Badge variant={AVAILABILITY_VARIANT[key] ?? "outline"} size="sm">
      {availabilityLabel(status)}
    </Badge>
  );
}

/** Compact confidence percentage (0–1 → 0–100%). */
export function confidencePct(confidence: number): string {
  return `${Math.round(confidence * 100)}%`;
}
