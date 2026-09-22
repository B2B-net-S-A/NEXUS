/**
 * Kto edytuje rekrutację — per rekrutacja, nie per rola (decyzja Artura
 * 22.09.2026, audyt ról U2).
 *
 * Dwa poziomy:
 *  • `full`    — admin, Delivery Lead (i TAC): wszystko, łącznie z klientem,
 *                budżetem, właścicielami, terminem i cyklem życia (publikacja,
 *                zamknięcie, „prowadzona w NEXUSIE"). Capability `job.update`.
 *  • `content` — rekruter prowadzący i współpracownicy: TREŚĆ rekrutacji
 *                (opis, ogłoszenia, Profil Championa, podpowiedzi Championa).
 *                Budżet, właściciele, klient i cykl życia zostają zamknięte.
 *
 * O `content` rozstrzyga serwer polem `can_edit` z `GET /api/jobs/{id}`
 * (liczone tą samą funkcją co bramka zapisu). Pole może jeszcze nie przyjść
 * (starszy backend) — wtedy zostaje dotychczasowa reguła z capability, bez
 * żadnego poszerzenia. Jawne `can_edit: false` wygrywa zawsze.
 */

export type JobEditScope = "full" | "content" | "none";

export interface JobEditAccessInput {
  /** `GET /api/jobs/{id}` → `can_edit` (od 22.09.2026). */
  can_edit?: boolean | null;
}

export function jobEditScope(
  job: JobEditAccessInput | null | undefined,
  {
    canWritePipeline,
    canManageJob,
  }: {
    /** Zapis w sekcji Pipeline (sufit) i brak trybu „podgląd jako". */
    canWritePipeline: boolean;
    /** Capability `job.update` — pełna edycja (TacPlus). */
    canManageJob: boolean;
  },
): JobEditScope {
  if (!canWritePipeline) return "none";
  if (job?.can_edit === false) return "none";
  if (canManageJob) return "full";
  if (job?.can_edit === true) return "content";
  return "none";
}

/**
 * Edycja Profilu Championa. `can_edit` z serwera, a gdy go jeszcze nie ma —
 * dotychczasowe lustro `PUT /champion-profile` (`fallback`, np. admin + DL).
 */
export function canEditJobContent(
  job: JobEditAccessInput | null | undefined,
  { canWritePipeline, fallback }: { canWritePipeline: boolean; fallback: boolean },
): boolean {
  if (!canWritePipeline) return false;
  if (typeof job?.can_edit === "boolean") return job.can_edit;
  return fallback;
}
