/**
 * Robocze wyszukiwanie Talent Radaru — snapshot formularza i wyników, żeby
 * powrót z profilu kandydata nie kasował pracy rekrutera.
 *
 * „Otwórz profil" nawiguje w TEJ SAMEJ karcie, a `/talent-radar` przy powrocie
 * montuje się od zera (App Router nie utrzymuje stanu React między stronami).
 * Bez tego snapshotu rekruter wracał na pusty formularz i układał zapytanie od
 * nowa (zgłoszenie 20.08).
 *
 * `sessionStorage`, świadomie NIE `localStorage`:
 *  - wyniki niosą dane kandydatów (nazwiska, dopasowania), więc żyją najwyżej
 *    tyle co karta przeglądarki, a wylogowanie i martwa sesja kasują je wprost
 *    (`clearSessionArtifacts` w lib/session.ts woła `clearTalentRadarSession`),
 *  - per-karta: dwie otwarte karty radaru nie nadpisują sobie nawzajem pracy.
 *
 * Klucz jest WERSJONOWANY: kształt snapshotu podąża za stanem workspace'u,
 * więc zapis sprzed deployu nowej wersji ma zostać zignorowany, nie
 * „naprawiony" — od walidacji jest `loadTalentRadarSession`, która na
 * cokolwiek niespodziewanego odpowiada `null` (świeży start), nigdy wyjątkiem.
 *
 * Importy typów są `import type` — ten moduł NIE może w runtime ciągnąć
 * `talent-radar-api` (a przez nie axiosowej instancji `api`), bo importuje go
 * lib/session.ts, który sam jest importowany przez lib/api.ts. Zwykły import
 * domknąłby cykl modułów.
 */

import type { ClientRef } from "@/lib/contract-client-filter";
import type {
  ChampionParseSummary,
  TalentRadarSearchResponse,
} from "@/lib/talent-radar-api";

export const TALENT_RADAR_SESSION_KEY = "nexus_talent_radar_session_v1";

/** Lustro pól `useState` w TalentRadarWorkspace — zapisywane i odtwarzane RAZEM. */
export interface TalentRadarSessionState {
  client: ClientRef | null;
  title: string;
  text: string;
  location: string;
  budgetMax: string;
  excludeRemoteOnly: boolean;
  championProfile: Record<string, unknown> | null;
  championSummary: ChampionParseSummary | null;
  /**
   * Wymagania z `parse-champion`. Trzymane OSOBNO od `championProfile`, bo ten
   * obiekt ich nie niesie (`build_champion_dict` ich nie kopiuje) — a bez nich
   * w snapshocie powrót z profilu kandydata gubił listy i kolejne „Szukaj"
   * leciało bez wymagań. Dziś bez skutku widocznego (flaga strukturalnych
   * wymagań jest wyłączona), ale po jej flipie łańcuch urwałby się cicho.
   */
  championSkills: { must: string[]; nice: string[] } | null;
  response: TalentRadarSearchResponse | null;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/**
 * Walidacja kształtu przed oddaniem snapshotu do `setState`. Płytka z wyboru:
 * pilnuje inwariantów, na których workspace i wyniki polegają wprost
 * (`client.id` do requestu, `response.results.map(...)`, `meta` jako obiekt);
 * pola głębiej są renderowane defensywnie (optional chaining, `?? null`).
 */
function isValidState(value: unknown): value is TalentRadarSessionState {
  if (!isRecord(value)) return false;
  if (typeof value.title !== "string") return false;
  if (typeof value.text !== "string") return false;
  // `location` i `championSkills` doszły później — snapshot sprzed tej wersji
  // nie ma ich wcale. Klucz jest wersjonowany, więc taki zapis i tak zostanie
  // odrzucony; walidacja przyjmuje `undefined` po to, żeby restore nie zależał
  // od kolejności deployu frontu i klucza w przeglądarce.
  if (value.location !== undefined && typeof value.location !== "string") {
    return false;
  }
  if (
    value.championSkills !== undefined &&
    value.championSkills !== null &&
    !isRecord(value.championSkills)
  ) {
    return false;
  }
  if (typeof value.budgetMax !== "string") return false;
  if (typeof value.excludeRemoteOnly !== "boolean") return false;

  const client = value.client;
  if (client !== null) {
    if (!isRecord(client)) return false;
    if (typeof client.id !== "number" || typeof client.name !== "string") {
      return false;
    }
  }

  if (value.championProfile !== null && !isRecord(value.championProfile)) {
    return false;
  }
  if (value.championSummary !== null && !isRecord(value.championSummary)) {
    return false;
  }

  const response = value.response;
  if (response !== null) {
    if (!isRecord(response)) return false;
    if (!Array.isArray(response.results)) return false;
    if (!isRecord(response.meta)) return false;
  }

  return true;
}

/** Odczytaj snapshot. `null` = brak zapisu, zepsuty JSON, obcy kształt lub SSR. */
export function loadTalentRadarSession(): TalentRadarSessionState | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(TALENT_RADAR_SESSION_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    return isValidState(parsed) ? parsed : null;
  } catch {
    // Storage zablokowany (tryb prywatny z twardą polityką) albo nie-JSON —
    // brak snapshotu nie może wywrócić strony.
    return null;
  }
}

/** Zapisz snapshot. Cichy no-op poza przeglądarką i przy zablokowanym storage. */
export function saveTalentRadarSession(state: TalentRadarSessionState): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(
      TALENT_RADAR_SESSION_KEY,
      JSON.stringify(state),
    );
  } catch {
    // QuotaExceeded / storage wyłączony — persystencja jest udogodnieniem,
    // wyszukiwanie musi działać bez niej.
  }
}

/** Usuń snapshot — wołane też z teardownu sesji (lib/session.ts). */
export function clearTalentRadarSession(): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(TALENT_RADAR_SESSION_KEY);
  } catch {
    /* storage wyłączony — nie ma czego kasować */
  }
}
