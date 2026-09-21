/**
 * Optymistyczna współbieżność ruchu w pipeline (audyt Codexa, F05).
 *
 * Karta kanbanu niesie `process_state_version` — wersję procesu rekrutacji
 * pary (kandydat, rekrutacja), jaką widział serwer w chwili odczytu tablicy.
 * Ruch z UI odsyła ją jako `expected_state_version`; serwer porównuje ją pod
 * blokadą i przy rozjeździe odpowiada 409 `PIPELINE_VERSION_CONFLICT` BEZ
 * zapisu. Bez tego ruch z dawno otwartej karty nadpisywał świeższą decyzję
 * kolegi.
 *
 * Reguły, których pilnuje ten moduł:
 * - Wersję wysyłają WYŁĄCZNIE ruchy pojedyncze z karty. Ruchy zbiorcze
 *   i importy zostają bez niej (`undefined` = serwer nie sprawdza).
 * - Karta bez liczby (np. dane spoza tablicy) NIE wysyła wersji — zgadnięte
 *   0 zamieniłoby każdy ruch takiej karty w fałszywy konflikt.
 * - Konflikt NIE jest ponawiany automatycznie: użytkownik ma zobaczyć, co
 *   zrobił kolega, i zdecydować ponownie. Odświeżamy tablicę (OBA klucze —
 *   część konsumentów trzyma `jobId` jako liczbę, część jako tekst) i dane
 *   doku.
 */

import { AxiosError } from "axios";
import type { QueryClient } from "@tanstack/react-query";

export const PIPELINE_VERSION_CONFLICT_CODE = "PIPELINE_VERSION_CONFLICT";

export const PIPELINE_VERSION_CONFLICT_MESSAGE =
  "Kandydat został w międzyczasie przesunięty przez kogoś innego — odświeżyłem kartę.";

/** Wersja procesu z karty — `undefined`, gdy karta jej nie niesie. */
export function expectedStateVersionOf(
  item: { process_state_version?: number | null } | null | undefined,
): number | undefined {
  const version = item?.process_state_version;
  return typeof version === "number" && Number.isInteger(version) && version >= 0
    ? version
    : undefined;
}

/** Czy błąd to 409 `PIPELINE_VERSION_CONFLICT` z `POST /api/pipeline/move`. */
export function isPipelineVersionConflict(error: unknown): boolean {
  const response =
    error instanceof AxiosError
      ? error.response
      : (error as { response?: { status?: unknown; data?: unknown } } | null)
          ?.response;
  if (!response || response.status !== 409) return false;
  const detail = (response.data as { detail?: unknown } | null | undefined)
    ?.detail;
  return (
    !!detail &&
    typeof detail === "object" &&
    (detail as { code?: unknown }).code === PIPELINE_VERSION_CONFLICT_CODE
  );
}

/** Klucz historii etapów osoby w rekrutacji (dok kandydata, panel osoby). */
export function candidateStageHistoryKey(candidateId: number, jobId: number) {
  return ["candidate-stage-history", candidateId, jobId] as const;
}

/**
 * Po konflikcie: tablica (oba klucze) i historia etapów doku kandydata.
 * Bez automatycznego ponowienia ruchu.
 */
export function invalidateAfterPipelineVersionConflict(
  queryClient: QueryClient,
  jobId: number,
  candidateId?: number,
): void {
  void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
  void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
  if (candidateId !== undefined) {
    void queryClient.invalidateQueries({
      queryKey: candidateStageHistoryKey(candidateId, jobId),
    });
  }
}
