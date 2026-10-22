// Zdrowie relacji (Dobrze / Uwaga / Ryzyko, decyzja 6 z 22.10.2026) — czyste
// reguły wyświetlania bez Reacta. Poziom i zdania „dlaczego” liczy serwer
// (`care/health.py`); czytający spoza kręgu D11 dostaje `health: null`
// i etykiety nie ma wcale — także „Dobrze” się nie pokazuje.

import type { Health, HealthLevel } from "@/lib/api/care";

import type { StatusDotTone } from "@/components/ds/StatusDot";

export const HEALTH_LEVELS: HealthLevel[] = ["risk", "watch", "ok"];

export const HEALTH_LABELS: Record<HealthLevel, string> = {
  ok: "Dobrze",
  watch: "Uwaga",
  risk: "Ryzyko",
};

export const HEALTH_BADGE: Record<HealthLevel, "success" | "warning" | "danger"> = {
  ok: "success",
  watch: "warning",
  risk: "danger",
};

export const HEALTH_DOT: Record<HealthLevel, StatusDotTone> = {
  ok: "success",
  watch: "warning",
  risk: "danger",
};

/** Kolor segmentu paska zdrowia w tabeli klientów (tokeny, bez surowych kolorów). */
export const HEALTH_BAR: Record<HealthLevel, string> = {
  ok: "bg-success",
  watch: "bg-warning",
  risk: "bg-destructive",
};

/** Etykieta z serwera, a bez niej — stała z poziomu. */
export function healthLabel(health: Health): string {
  return health.label?.trim() || HEALTH_LABELS[health.level];
}

/** „dlaczego” w jednym zdaniu: powody po kropce, przy „Dobrze” bez powodów — nic. */
export function healthWhy(health: Health | null | undefined): string | null {
  if (!health) return null;
  const reasons = health.reasons.map((reason) => reason.trim()).filter(Boolean);
  return reasons.length ? reasons.join(" · ") : null;
}

/** Kolejność sortowania: ryzyko, uwaga, dobrze, brak etykiety. */
export function healthRank(health: Health | null | undefined): number {
  if (!health) return 3;
  return HEALTH_LEVELS.indexOf(health.level);
}

export interface HealthTotals {
  ok: number;
  watch: number;
  risk: number;
}

/** Ile osób na każdym poziomie (wiersze bez etykiety się nie liczą). */
export function healthTotals(rows: { health?: Health | null }[]): HealthTotals {
  const totals: HealthTotals = { ok: 0, watch: 0, risk: 0 };
  for (const row of rows) {
    if (row.health) totals[row.health.level] += 1;
  }
  return totals;
}

export interface HealthSegment {
  level: HealthLevel;
  count: number;
  percent: number;
}

/**
 * Pasek zdrowia: segmenty od ryzyka do „dobrze”, procenty sumują się do 100
 * (zaokrąglenie dobiera ostatni niezerowy segment). Pusty zbiór = brak segmentów.
 */
export function healthSegments(totals: HealthTotals): HealthSegment[] {
  const sum = totals.ok + totals.watch + totals.risk;
  if (sum <= 0) return [];
  const present = HEALTH_LEVELS.filter((level) => totals[level] > 0);
  let used = 0;
  return present.map((level, index) => {
    const percent =
      index === present.length - 1 ? 100 - used : Math.round((totals[level] / sum) * 100);
    used += percent;
    return { level, count: totals[level], percent };
  });
}

/** Wymaga uwagi — „Uwaga” albo „Ryzyko” (filtr „Z sygnałem”). */
export function needsAttention(health: Health | null | undefined): boolean {
  return health?.level === "watch" || health?.level === "risk";
}
