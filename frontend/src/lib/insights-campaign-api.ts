import api from "@/lib/api";

/**
 * Klient `/api/insights/campaigns/*` — baner kampanii rekrutacyjnej.
 *
 * Świadomie ODDZIELNY plik od `insights-api.ts`: kampania nie ma parametru
 * okresu. Jej okno jest wpisane w samą kampanię (`start_date`/`end_date`),
 * więc `PeriodPicker` na nią nie wpływa i wciągnięcie jej do wspólnego
 * klienta okresowego sugerowałoby, że wpływa.
 */

/**
 * Aktywna kampania z policzonymi liczbami.
 *
 * Trzy liczniki (`placements`, `resignations`, `net`) są LICZONE przez serwer
 * przy każdym odczycie, nigdy przechowywane — przesunięcie etapu albo
 * zakończenie kontraktu wstecz od razu zmienia baner.
 */
export interface InsightsCampaign {
  id: number;
  name: string;
  /** Ozdoba banera. `null` = kampania bez emoji, nie błąd. */
  emoji: string | null;
  start_date: string;
  end_date: string;
  target_net: number;
  is_active: boolean;
  created_at: string | null;

  /** Okno kampanii policzone przez serwer — półotwarte [start, end) w Warszawie. */
  window: {
    kind: string;
    start: string;
    end: string;
    timezone: string;
  };

  /** Dni do końca kampanii, liczone kalendarzem Europe/Warsaw. Nigdy ujemne. */
  days_remaining: number;
  has_started: boolean;

  placements: number;
  resignations: number;
  /** `placements - resignations`. Może być UJEMNE. */
  net: number;
  /**
   * `null` przy celu 0 — „nie da się policzyć" znaczy co innego niż „zero
   * postępu". NIE jest przycięte do 100: przekroczony cel jest faktem.
   */
  progress_pct: number | null;
  /** `target_net - net`. Ujemne = cel przekroczony o tyle. */
  remaining_to_target: number;

  placements_definition: string;
  placements_definition_note: string;
  resignations_definition: string;
  resignations_definition_note: string;
  net_definition_note: string;
}

/** `null` = nie ma aktywnej kampanii. Awaria kończy się kodem błędu, nie pustką. */
export type InsightsActiveCampaign = InsightsCampaign | null;

export interface InsightsCampaignWrite {
  name: string;
  emoji?: string | null;
  start_date: string;
  end_date: string;
  target_net: number;
  is_active?: boolean;
}

export interface InsightsCampaignListItem {
  id: number;
  name: string;
  emoji: string | null;
  start_date: string;
  end_date: string;
  target_net: number;
  is_active: boolean;
  created_at: string | null;
}

export const insightsCampaignQueryKeys = {
  active: () => ["insights", "campaigns", "active"] as const,
  list: () => ["insights", "campaigns", "list"] as const,
};

export const insightsCampaignApi = {
  /** Aktywna kampania albo `null`. Każda zalogowana rola (D7). */
  active: () =>
    api
      .get<InsightsActiveCampaign>("/api/insights/campaigns/active")
      .then((r) => r.data ?? null),

  /** Lista kampanii do zarządzania — wyłącznie admin (403 dla reszty). */
  list: () =>
    api
      .get<{ campaigns: InsightsCampaignListItem[] }>("/api/insights/campaigns")
      .then((r) => r.data),

  create: (payload: InsightsCampaignWrite) =>
    api
      .post<InsightsCampaign>("/api/insights/campaigns", payload)
      .then((r) => r.data),

  update: (id: number, payload: Partial<InsightsCampaignWrite>) =>
    api
      .patch<InsightsCampaign>(`/api/insights/campaigns/${id}`, payload)
      .then((r) => r.data),

  remove: (id: number) =>
    api.delete(`/api/insights/campaigns/${id}`).then(() => undefined),
};
