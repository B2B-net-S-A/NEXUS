import api from "@/lib/api";
import type { InsightsPeriod, InsightsPeriodParams } from "@/lib/insights-api";

/**
 * Klient `GET /api/insights/team-table` — „Performance per osoba".
 *
 * Osobny plik od `insights-api.ts` świadomie: tamten jest współdzielony przez
 * wszystkie zakładki Insights i rośnie równolegle w kilku gałęziach naraz,
 * więc dokładanie tam kolejnych typów gwarantuje konflikt scalania na pliku,
 * którego nikt nie czyta w całości. Typy okresu importujemy stamtąd — okno
 * MUSI być tym samym oknem co reszta zakładki.
 */

export interface TeamTableColumn {
  /** Klucz pola w wierszu (`verifications`, `recommendations`, …). */
  key: TeamTableMetricKey;
  label: string;
  /** Etap w `analytics_first_milestones`, z którego liczona jest kolumna. */
  stage: string;
}

export type TeamTableMetricKey =
  "verifications" | "recommendations" | "interviews" | "placements";

export interface TeamTableRow {
  user_id: number;
  /**
   * `null` = kamień jest przypisany do konta, którego już nie ma w `users`.
   * Atrybucja jest znana, tylko osoby nie potrafimy nazwać — dlatego wiersz
   * ZOSTAJE (i wchodzi w sumę kolumny), a nie znika do „nieprzypisanych".
   */
  name: string | null;
  /** Surowa wartość enuma `UserRole` — po niej kolorujemy chip. */
  role: string | null;
  /** Etykieta PL z serwera. Może być `null`, gdy konta już nie ma. */
  role_label: string | null;
  /** `false` = były pracownik. `null` = nie wiemy (brak konta). */
  is_active: boolean | null;
  verifications: number;
  recommendations: number;
  interviews: number;
  placements: number;
  total: number;
}

export type TeamTableCounts = Record<TeamTableMetricKey, number>;

export interface TeamTableTotals {
  /** Suma WIDOCZNYCH wierszy. */
  attributed: TeamTableCounts;
  /**
   * Kamienie, których nie da się przypisać nikomu — per etap, nie jednym
   * skalarem. MUSZĄ być wyrenderowane obok sumy kolumny: bez nich suma nie
   * zgadza się z lejkiem, a tabela wygląda na ZEPSUTĄ, nie na niekompletną.
   */
  unattributed: TeamTableCounts;
  /** `attributed + unattributed` — ta liczba ma się zgadzać z lejkiem. */
  all: TeamTableCounts;
  users: number;
  former_employees: number;
}

export interface TeamTableResponse {
  period: InsightsPeriod;
  columns: TeamTableColumn[];
  rows: TeamTableRow[];
  totals: TeamTableTotals;
}

/** Lokalna kopia — `periodQuery` z `insights-api.ts` nie jest eksportowane. */
function periodQuery(p: InsightsPeriodParams): Record<string, string | number> {
  const q: Record<string, string | number> = { period: p.period };
  if (p.offset !== undefined) q.offset = p.offset;
  if (p.anchor) q.anchor = p.anchor;
  if (p.date_from) q.date_from = p.date_from;
  if (p.date_to) q.date_to = p.date_to;
  return q;
}

export const insightsTeamApi = {
  teamTable: (p: InsightsPeriodParams) =>
    api
      .get<TeamTableResponse>("/api/insights/team-table", {
        params: periodQuery(p),
      })
      .then((r) => r.data),
};

export const insightsTeamQueryKeys = {
  teamTable: (p: InsightsPeriodParams) =>
    ["insights", "team", "table", p] as const,
};
