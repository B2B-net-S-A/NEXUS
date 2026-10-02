import { COLLABORATOR_ROLES } from "@/lib/job-collaborators";
import type { UserRole } from "@/store/auth";

/**
 * Minimal user DTO returned by the backend for primary_owner / collaborators /
 * directory listings. Mirrors `UserBrief` in backend/app/schemas/job.py.
 */
export interface UserBrief {
  id: number;
  name: string;
  email: string;
  role: UserRole;
  /** Role dodatkowe (lista z `/api/users`). */
  roles?: string[];
  /**
   * Tylko współpracownicy (`collaborators[]`): `manual` = dopisany ręcznie,
   * `auto_cc` = cała kategoria kompetencji. Brak = dodany ręcznie.
   */
  source?: string | null;
  /** Runda 9 (R9-V2-2): `false` = konto nieaktywne. Brak = aktywne. */
  is_active?: boolean;
}

/**
 * Kto może sam wziąć rekrutację („Biorę”) albo do niej dołączyć („Dołącz”) —
 * lustro `_OWNERSHIP_ELIGIBLE_ROLES` w `backend/app/api/jobs.py`.
 * `POST /jobs/{id}/claim` odrzuca 403 każdą inną rolę, także te z zapisem
 * w sekcji pipeline (finance, head_of_recruitment, talent_community_manager),
 * a `POST …/collaborators` odmawia im 409. Przycisk bez tego lustra =
 * gwarantowana odmowa po kliknięciu. Ten sam zbiór co role, które serwer
 * przyjmuje jako kolejną osobę przy rekrutacji.
 */
export const CLAIM_ELIGIBLE_ROLES = COLLABORATOR_ROLES;

/**
 * Pierwszy rekruter z nieaktywnym kontem to brak rekrutera (R9-V2-2):
 * rekrutację da się wtedy wziąć („Biorę”), a `POST /api/jobs/{id}/claim`
 * to przyjmuje.
 */
export function hasActiveOwner(
  owner: { is_active?: boolean | null } | null | undefined,
): boolean {
  return owner != null && owner.is_active !== false;
}
