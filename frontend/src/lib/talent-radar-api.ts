/**
 * Klient `POST /api/talent-radar/search` — ranking bazy pod wklejony request.
 *
 * UWAGA na kolizję nazw: `talent_radar` funkcjonuje w tym repo od dawna jako
 * *legacy źródło importu* (`/api/admin/import-talent-radar`, `adminApi
 * .startTalentRadarImport`). Tamto źródło zostało w bazie przemianowane na
 * `tr_legacy` właśnie po to, żeby nazwa „Talent Radar" należała do TEGO modułu.
 * Nic tutaj nie ma z tamtym importem wspólnego.
 */

import { api, type HiddenCounters } from "@/lib/api";
// Sufit czasu dla endpointów LLM/scoringowych — jedna stała dla całej
// aplikacji, nie kopia w każdym kliencie (kopie rozjeżdżają się cicho).
import { SLOW_ENDPOINT_TIMEOUT_MS } from "@/lib/http-timeouts";

/** Warstwa punktowa scoringu — jedna z sześciu składowych wyniku. */
export interface TalentRadarLayer {
  points: number | null;
  max: number | null;
  reason: string | null;
  /**
   * Obecne tylko na warstwie wynagrodzenia — dwie różne rzeczy pod jedną
   * nazwą, więc rozróżnienie jest istotne:
   * `not_applicable` — nie było czego porównać (wklejony request bez stawki
   * Championa albo kandydat bez stawki), więc warstwa nie weszła do wyniku;
   * `redacted` — weszła i realnie przesunęła `total`, ale LICZB nie
   * pokazujemy: są liniową funkcją stawki Championa, którą rekruter zna, więc
   * odsłoniłyby oczekiwania kandydata co do złotówki (ta lista celowo ich nie
   * niesie). Zero punktów znaczyłoby „nie pasuje finansowo" i nie jest tym
   * samym co żadne z powyższych.
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
  /** Dealbreaker-switche: liczniki ukrytych per powód (0278: pięć rubryk). */
  hidden?: HiddenCounters;
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
  /**
   * Rubryki 0278: dni w biurze / tydzień i miasto biura, podane WPROST przez
   * rekrutera (radar nie ma ani kolumn oferty, ani profilu Championa do
   * odpytania). `onsite_days_per_week` uzbraja dealbreakery dni/miasta TYLKO
   * gdy > 0 — 0 jest legalną, „znaną" wartością (praca wyłącznie zdalna).
   */
  onsite_days_per_week?: number;
  office_location?: string;
  /**
   * Wymagania twarde/miękkie WPROST, prosto z `parse-champion`. Bez nich
   * ranking wywodzi wymagania regexem z prozy, a plakietka „8 must · 5 nice"
   * obiecuje wiedzę, której scoring nigdy nie dostał. Puste przy wklejonym
   * tekście — wtedy działa dotychczasowy fallback.
   */
  must_skills?: string[];
  nice_skills?: string[];
  requirements_reviewed?: boolean;
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
  /**
   * Wymagania z dokumentu. MUSZĄ zostać przekazane do `search` — profil
   * (`champion_profile`) ich NIE niesie (`build_champion_dict` ich nie
   * kopiuje), więc porzucenie tej odpowiedzi gubi je bezpowrotnie i to tutaj
   * łańcuch od parsera do rankingu się urywał.
   */
  must_skills: string[];
  nice_skills: string[];
  summary: ChampionParseSummary;
}

export const talentRadarApi = {
  interpret: (body: TalentRadarSearchRequest) =>
    api.post<{ must: string[]; nice: string[]; excluded: string[]; uncertain: string[] }>("/api/talent-radar/interpret", body).then(r => r.data),
  search: (
    payload: TalentRadarSearchRequest,
  ): Promise<TalentRadarSearchResponse> =>
    api
      .post<TalentRadarSearchResponse>("/api/talent-radar/search", payload, {
        timeout: SLOW_ENDPOINT_TIMEOUT_MS,
      })
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
        timeout: SLOW_ENDPOINT_TIMEOUT_MS,
      })
      .then((r) => r.data);
  },
};
