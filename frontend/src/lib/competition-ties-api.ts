import api from "@/lib/api";

/**
 * Klient remisów w konkursach płatnych (`/api/competitions/ties`,
 * `/api/competitions/{type}/{period}/resolve-tie`). Oba endpointy są
 * wyłącznie dla admina.
 *
 * Remis, którego regulamin nie rozstrzyga (np. równe punkty w Lidze Mistrzów,
 * brak policzalnej marży w wyścigu placementów), zamyka okres ze statusem
 * `tie_pending`: miejsca objęte remisem nie mają nagrody, dopóki admin nie
 * ustali kolejności.
 */

export interface CompetitionTieEntry {
  user_id: number;
  name: string;
  metric_value: number;
  hit_ratio?: number | null;
  placements?: number;
  margin_per_hour_sum?: number | null;
  precision_pct?: number;
  [key: string]: unknown;
}

export interface CompetitionTieGroup {
  /** Miejsca podium (1..3) zablokowane przez remis. */
  positions: number[];
  /** Wszyscy remisujący — może ich być więcej niż miejsc. */
  user_ids: number[];
  reason: string;
  entries: CompetitionTieEntry[];
  /** Nagroda per miejsce, klucze to numery miejsc jako tekst. */
  prizes_pln: Record<string, number>;
}

export interface PendingCompetitionTie {
  competition_type: string;
  period: string;
  closed_at: string | null;
  tie_break_rule: string | null;
  ties: CompetitionTieGroup[];
}

export const competitionTiesQueryKeys = {
  pending: () => ["competitions", "ties", "pending"] as const,
};

export const competitionTiesApi = {
  async pending(): Promise<PendingCompetitionTie[]> {
    const { data } = await api.get<{ items: PendingCompetitionTie[] }>(
      "/api/competitions/ties",
    );
    return data.items;
  },

  /**
   * `userIds` = remisujący ze WSZYSTKICH remisów okresu, w kolejności remisów
   * z listy i — w obrębie remisu — w kolejności decyzji.
   */
  async resolve(
    competitionType: string,
    period: string,
    userIds: number[],
  ): Promise<void> {
    await api.post(
      `/api/competitions/${encodeURIComponent(competitionType)}/${encodeURIComponent(period)}/resolve-tie`,
      { user_ids: userIds },
    );
  },
};

export const COMPETITION_LABELS: Record<string, string> = {
  quarterly_champions_recruiter: "Liga Mistrzów — rekrutacja",
  quarterly_champions_dl: "Liga Mistrzów — Delivery Lead",
  monthly_placements: "Wyścig placementów",
  monthly_recommendations: "Wyścig rekomendacji",
};

/** Opis wyniku remisującej osoby — co było równe i czego zabrakło. */
export function describeTieEntry(
  competitionType: string,
  entry: CompetitionTieEntry,
): string {
  if (competitionType === "quarterly_champions_recruiter") {
    return `${entry.metric_value} pkt`;
  }
  if (competitionType === "quarterly_champions_dl") {
    const ratio =
      typeof entry.hit_ratio === "number" ? ` · hit ratio ${entry.hit_ratio}%` : "";
    return `${entry.metric_value} placementów${ratio}`;
  }
  if (competitionType === "monthly_placements") {
    const margin =
      typeof entry.margin_per_hour_sum === "number"
        ? `${entry.margin_per_hour_sum.toFixed(2)} zł/h marży`
        : "marża niepoliczalna";
    return `${entry.metric_value} placementów · ${margin}`;
  }
  return `${entry.metric_value}`;
}

/** Przesuń element listy o `delta` pozycji (niemutująco). */
export function moveItem<T>(items: readonly T[], index: number, delta: number): T[] {
  const target = index + delta;
  if (target < 0 || target >= items.length) return [...items];
  const next = [...items];
  const [item] = next.splice(index, 1);
  next.splice(target, 0, item);
  return next;
}
