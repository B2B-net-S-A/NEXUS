import type { QueryClient } from "@tanstack/react-query";

/**
 * Zapytania, które czytają Profil Championa POŚREDNIO — nie tylko pod jego
 * własnym kluczem. Zapis profilu (`PUT …/champion-profile`), import dokumentu
 * i zastosowanie propozycji AI zmieniają trzy rzeczy naraz:
 *
 *  - sam profil (`["champion-profile", jobId]`),
 *  - zlecenie (`["job", "<id>"]` — zapis synchronizuje stack do
 *    `Job.must_skills`/`nice_skills`, a strona trzyma zlecenie pod kluczem
 *    ze stringiem z `useParams`),
 *  - werdykt bramki „Przekaż do searchu" (`["job-readiness", jobId]`):
 *    kontekst projektu i dwa pytania screeningowe to blokery gotowości.
 *    Bez unieważnienia przycisk zostawał wyszarzony (staleTime 30 s) z listą
 *    braków, które DL właśnie uzupełnił.
 *
 * Jedna funkcja zamiast trzech linijek w każdym miejscu zapisu — kopia
 * rozjeżdża się przy pierwszym nowym konsumencie.
 */
export function invalidateChampionDependents(
  qc: QueryClient,
  jobId: number,
): void {
  void qc.invalidateQueries({ queryKey: ["champion-profile", jobId] });
  void qc.invalidateQueries({ queryKey: ["job", String(jobId)] });
  void qc.invalidateQueries({ queryKey: ["job-readiness", jobId] });
}
