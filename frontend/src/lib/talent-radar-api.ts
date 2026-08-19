/**
 * Klient `POST /api/talent-radar/search` — ranking bazy pod wklejony request.
 *
 * UWAGA na kolizję nazw: `talent_radar` funkcjonuje w tym repo od dawna jako
 * *legacy źródło importu* (`/api/admin/import-talent-radar`, `adminApi
 * .startTalentRadarImport`). Tamto źródło zostało w bazie przemianowane na
 * `tr_legacy` właśnie po to, żeby nazwa „Talent Radar" należała do TEGO modułu.
 * Nic tutaj nie ma z tamtym importem wspólnego.
 */

import { api } from "@/lib/api";

/** Warstwa punktowa scoringu — jedna z sześciu składowych wyniku. */
export interface TalentRadarLayer {
  points: number | null;
  max: number | null;
  reason: string | null;
  /**
   * Obecne tylko na warstwie wynagrodzenia. `not_applicable` znaczy, że radar
   * nie ma widełek do porównania — inaczej niż zero punktów, które znaczyłoby
   * „nie pasuje finansowo".
   */
  status?: string;
}

/** Tożsamość kandydata dołączona do wyniku — świadomie węższa niż profil. */
export interface TalentRadarCandidate {
  id: number;
  name: string | null;
  lastname: string | null;
  location: string | null;
  competence_category: string | null;
  years_it_experience: number | null;
  availability_status: string | null;
  champion: boolean;
  avatar_url: string | null;
}

export interface TalentRadarResult {
  candidate_id: number;
  total: number;
  semantic: TalentRadarLayer;
  skills: TalentRadarLayer;
  salary: TalentRadarLayer;
  location: TalentRadarLayer;
  availability: TalentRadarLayer;
  champion_fit: TalentRadarLayer;
  matching_must: string[];
  gap_must: string[];
  matching_nice: string[];
  gap_nice: string[];
  penalties: string[];
  fit_confidence: number | null;
  /** `null` tylko wtedy, gdy wiersz zniknął między rankingiem a odpowiedzią. */
  candidate: TalentRadarCandidate | null;
}

export interface TalentRadarMeta {
  /** Ilu kandydatów wróciło z wyszukiwania wektorowego. */
  pool_size: number;
  /** Ilu z nich przeszło filtr dopuszczalności (blacklisty, NDA, weto). */
  eligible_size: number;
  returned: number;
  /**
   * Retrieval padł. MUSI być pokazane jako awaria — puste `results` przy
   * `degraded` znaczą „nie wiemy", a nie „nikt nie pasuje".
   */
  degraded: boolean;
  reason: string | null;
  /** Dealbreaker-switche: liczniki ukrytych per powód (runda 3). */
  hidden?: { over_budget?: number; remote_only?: number };
}

export interface TalentRadarSearchResponse {
  results: TalentRadarResult[];
  meta: TalentRadarMeta;
}

export interface TalentRadarSearchRequest {
  /**
   * Wymagany, nie opcjonalny: filtr dopuszczalności sprawdza względem niego
   * blacklistę klienta, NDA, konflikty konkurencyjne i weto hiring managera.
   * Bez klienta lista byłaby wynikiem, w którym te kontrole cicho nie zaszły.
   */
  client_id: number;
  text?: string;
  champion_profile?: Record<string, unknown>;
  title?: string;
  location?: string;
  top_k?: number;
  min_score?: number;
  /**
   * Dealbreaker-switche. Budżet PLN/h podaje rekruter wprost (radar nie ma
   * oferty) — sama jego obecność działa jako twardy sufit, bez marginesu
   * (decyzja produktowa 19.08). Nieznana stawka/preferencja PRZECHODZI.
   */
  budget_hourly_max?: number;
  exclude_remote_only?: boolean;
}

export interface ChampionParseSummary {
  role_name: string | null;
  must_count: number;
  nice_count: number;
  rate_value: number | null;
  location: string | null;
  work_mode: string | null;
}

export interface ChampionParseResponse {
  champion_profile: Record<string, unknown>;
  summary: ChampionParseSummary;
}

export const talentRadarApi = {
  search: (
    payload: TalentRadarSearchRequest,
  ): Promise<TalentRadarSearchResponse> =>
    api
      .post<TalentRadarSearchResponse>("/api/talent-radar/search", payload)
      .then((r) => r.data),
  /** Plik profilu Championa (docx/pdf) → sparsowany profil + podsumowanie. */
  parseChampion: (file: File): Promise<ChampionParseResponse> => {
    const fd = new FormData();
    fd.append("file", file);
    return api
      .post<ChampionParseResponse>("/api/talent-radar/parse-champion", fd, {
        // Instancja `api` ma domyślne Content-Type: application/json, które
        // NIE jest podmieniane dla FormData — multipart jechał jako "json"
        // i FastAPI odpowiadał 422 `file Field required` (złapane w Chrome
        // na prodzie 19.08; curl działał, bo omija axiosa). Jawny nagłówek
        // to wzorzec pozostałych uploadów w api.ts — axios dokłada boundary.
        headers: { "Content-Type": "multipart/form-data" },
      })
      .then((r) => r.data);
  },
};
