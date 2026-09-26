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
  /**
   * Dorobek kont spoza ról rekrutacyjnych (admin, Finanse…) — reguła Hall of
   * Fame (24.09.2026). Nie mają wiersza osoby, ale wchodzą w „Łącznie”.
   */
  outside_scope?: TeamTableCounts;
  outside_scope_users?: number;
  outside_scope_label?: string;
  /** `attributed + outside_scope + unattributed` — zgodne z lejkiem. */
  all: TeamTableCounts;
  users: number;
  former_employees: number;
}

export interface TeamTableResponse {
  period: InsightsPeriod;
  columns: TeamTableColumn[];
  rows: TeamTableRow[];
  totals: TeamTableTotals;
  /**
   * Tylko przy `anchored_average=true`: średnia „CV wysłane" osoby z co
   * najmniej jednym CV, atrybucją verifier-anchored (jak „Mój miesiąc").
   * `recommendations: null` = w oknie nikt nic nie wysłał.
   */
  anchored_average?: {
    attribution: "verifier_anchored";
    people: number;
    recommendations: number | null;
  };
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
  /** Tabela + średnia zespołu atrybucją „Mojego miesiąca" (runda 6 audytu). */
  teamTableWithAnchoredAverage: (p: InsightsPeriodParams) =>
    api
      .get<TeamTableResponse>("/api/insights/team-table", {
        params: { ...periodQuery(p), anchored_average: true },
      })
      .then((r) => r.data),
};

export const insightsTeamQueryKeys = {
  teamTable: (p: InsightsPeriodParams) =>
    ["insights", "team", "table", p] as const,
  teamTableAnchored: (p: InsightsPeriodParams) =>
    ["insights", "team", "table", p, "anchored-average"] as const,
};

// ─────────────────────────────────────────────────────────────────────────────
// Widok Zespół (24.09.2026): `/api/insights/team/*` i rekrutacje bez ruchu.
// Za capability `view_team_kpi` — imienne wyniki cudzej pracy, bez kwot.
// Atrybucja jak w wyścigach i „Mój miesiąc" (verifier-anchored).
// ─────────────────────────────────────────────────────────────────────────────

export interface TeamPeopleRow {
  user_id: number;
  name: string;
  role: string;
  is_active: boolean;
  verifications: number;
  recommendations: number;
  interviews: number;
  placements: number;
  /** Placementy z TEGO SAMEGO odcinka poprzedniego okresu. */
  previous_placements: number;
  /** `null` = w oknie nie upłynął jeszcze żaden dzień roboczy. */
  verifications_per_workday: number | null;
  /**
   * Z par zweryfikowanych w 30 dniach — ile ma „CV wysłane” (kohorta, max
   * 100%). `null` = mniej niż 5 weryfikacji.
   */
  precision_pct: number | null;
}

export interface TeamPeopleOutsideScope {
  label: string;
  /** Ile kont miało ruch w bieżącym okresie. */
  people: number;
  verifications: number;
  recommendations: number;
  interviews: number;
  placements: number;
  previous_placements: number;
}

export interface TeamPeopleResponse {
  period: InsightsPeriod;
  rows: TeamPeopleRow[];
  /** Konta administracyjne — jeden wiersz pod tabelą (reguła Hall of Fame). */
  outside_scope?: TeamPeopleOutsideScope;
  workdays: number;
  precision_target_pct: number;
  low_precision_pct: number;
  totals: {
    verifications: number;
    recommendations: number;
    interviews: number;
    placements: number;
    precision_pct: number | null;
    people: number;
    unattributed: number;
  };
  previous_totals: {
    verifications: number;
    recommendations: number;
    interviews: number;
    placements: number;
  };
}

export type TeamAttentionKind = "stale_jobs" | "low_precision" | "weak_preps";

export interface TeamAttentionItem {
  kind: TeamAttentionKind;
  count: number;
  label: string;
  /** Raport, który pokazuje listę. `null` = sygnał wskazuje wiersze tabeli. */
  report: string | null;
  user_ids?: number[];
}

export interface StaleJob {
  job_id: number;
  title: string;
  client_id: number | null;
  client_name: string | null;
  recruiter_id: number | null;
  recruiter_name: string | null;
  last_move_at: string | null;
  days_without_move: number | null;
  people: number;
}

export const insightsTeamSignalsApi = {
  people: (p: InsightsPeriodParams) =>
    api
      .get<TeamPeopleResponse>("/api/insights/team/people", {
        params: periodQuery(p),
      })
      .then((r) => r.data),
  attention: () =>
    api
      .get<{ items: TeamAttentionItem[] }>("/api/insights/team/attention")
      .then((r) => r.data),
  staleJobs: () =>
    api
      .get<{ days: number; items: StaleJob[]; total: number }>(
        "/api/insights/recruitment/stale-jobs",
      )
      .then((r) => r.data),
};

export const insightsTeamSignalsQueryKeys = {
  people: (p: InsightsPeriodParams) =>
    ["insights", "team", "people", p] as const,
  attention: () => ["insights", "team", "attention"] as const,
  staleJobs: () => ["insights", "team", "stale-jobs"] as const,
};
