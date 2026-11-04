import type { QueryClient } from "@tanstack/react-query";

import { BOARD_TASKS_QUERY_KEY } from "@/lib/api/boardTasks";
import { REQUEST_BOARD_QUERY_KEY } from "@/lib/api/requestAllocation";

/**
 * Zapytania, które pokazują obsadę rekrutacji (Rekruterów i propozycje
 * automatu) albo jej priorytet. Jedna zmiana — dodanie, zdjęcie, przejęcie,
 * decyzja o propozycji, nowy priorytet — jest widoczna na kilku ekranach naraz:
 *
 *  - rekrutacja (`["job", id]`: strona trzyma ją pod kluczem ze stringiem
 *    z `useParams`, dok i okna pod `String(jobId)`, część okien pod liczbą —
 *    stąd oba kształty),
 *  - lista rekrutacji i jej liczniki (`["jobs-v2", …]`,
 *    `["jobs-quick-counts", …]`: „Moje”, „Moja kategoria”, „Bez rekrutera”),
 *  - pulpit „Requesty i obłożenie” (`REQUEST_BOARD_QUERY_KEY`),
 *  - „Czeka na Ciebie” z propozycjami automatu (`BOARD_TASKS_QUERY_KEY`).
 *
 * Jedna funkcja zamiast listy kluczy w każdym miejscu zapisu — kopia
 * rozjeżdża się przy pierwszym nowym ekranie (ten sam wzorzec co
 * `invalidateChampionDependents` w `lib/champion-cache.ts`).
 *
 * Bez `jobId` (decyzja zbiorcza o propozycjach z wielu rekrutacji) odświeża
 * każdą wczytaną rekrutację.
 */
export function invalidateJobTeam(
  qc: QueryClient,
  jobId?: number | null,
): void {
  if (jobId == null) {
    void qc.invalidateQueries({ queryKey: ["job"] });
  } else {
    void qc.invalidateQueries({ queryKey: ["job", jobId] });
    void qc.invalidateQueries({ queryKey: ["job", String(jobId)] });
  }
  void qc.invalidateQueries({ queryKey: ["jobs-v2"] });
  void qc.invalidateQueries({ queryKey: ["jobs-quick-counts"] });
  void qc.invalidateQueries({ queryKey: REQUEST_BOARD_QUERY_KEY });
  void qc.invalidateQueries({ queryKey: BOARD_TASKS_QUERY_KEY });
}
