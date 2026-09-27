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
  /** Runda 9 (R9-V2-2): `false` = konto nieaktywne. Brak = aktywne. */
  is_active?: boolean;
}

/**
 * Prowadzący z nieaktywnym kontem to brak prowadzącego (R9-V2-2): rekrutację
 * da się wtedy przejąć, a `POST /api/jobs/{id}/claim` przyjmuje przejęcie.
 */
export function hasActiveOwner(
  owner: { is_active?: boolean | null } | null | undefined,
): boolean {
  return owner != null && owner.is_active !== false;
}
