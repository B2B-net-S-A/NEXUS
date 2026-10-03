/**
 * „Kolejne osoby” przy rekrutacji (decyzje Artura 29.09 i 02.10.2026).
 *
 * Nad rekrutacją pracuje jedna albo kilka osób w roli „Rekruter”: pierwsza
 * siedzi w `jobs.recruiter_id`, kolejne w `job_collaborators` (stąd nazwy
 * w kodzie). W oknie edycji i na `/jobs/new` pole „Kolejne osoby” pokazuje
 * WYŁĄCZNIE dopisanych ręcznie (`source: "manual"`); wiersze `auto_cc` to
 * cała kategoria kompetencji — te osoby widzą rekrutację w „Moja kategoria”,
 * ale nad nią nie pracują. Dopisuje i zdejmuje każdy, kto redaguje rekrutację —
 * lustro `ensure_job_editor` w `POST/DELETE /api/jobs/{id}/collaborators`.
 */

import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";

/** Role, które serwer przyjmuje jako osobę przy rekrutacji (`_OWNERSHIP_ELIGIBLE_ROLES`). */
export const COLLABORATOR_ROLES = [
  "admin",
  "delivery_lead",
  "recruiter",
] as const;

export interface JobCollaboratorEntry {
  id: number;
  name?: string | null;
  /** Brak pola (starsze odpowiedzi) = dodany ręcznie. */
  source?: string | null;
  /** Nieaktywne konto nie liczy się do „+N” (tak jak w filtrze „Rekruter”). */
  is_active?: boolean | null;
}

export function manualCollaborators<T extends JobCollaboratorEntry>(
  collaborators: readonly T[] | null | undefined,
): T[] {
  return (collaborators ?? []).filter((c) => c.source !== "auto_cc");
}

export function manualCollaboratorIds(
  collaborators: readonly JobCollaboratorEntry[] | null | undefined,
): number[] {
  return manualCollaborators(collaborators).map((c) => c.id);
}

export interface CollaboratorChanges {
  add: number[];
  remove: number[];
}

/**
 * Różnica między ręcznie dopisanymi osobami przed i po edycji. Pierwszy
 * rekruter (`recruiter_id`) nie jest dopisywany drugi raz (serwer odpowiada
 * wtedy 409).
 */
export function collaboratorChanges(
  before: readonly number[],
  after: readonly number[],
  primaryOwnerId?: number | null,
): CollaboratorChanges {
  const was = new Set(before);
  const next = new Set(after.filter((id) => id !== primaryOwnerId));
  return {
    add: [...next].filter((id) => !was.has(id)),
    remove: [...was].filter((id) => !next.has(id)),
  };
}

export function hasCollaboratorChanges(changes: CollaboratorChanges): boolean {
  return changes.add.length > 0 || changes.remove.length > 0;
}

/**
 * Zapisuje zmiany po kolei. Zwraca `null`, gdy wszystko się udało, albo
 * polskie zdanie z pierwszym błędem (rekrutacja już jest zapisana — wołający
 * mówi to użytkownikowi, nie cofa niczego).
 */
export async function saveCollaboratorChanges(
  jobId: number,
  changes: CollaboratorChanges,
): Promise<string | null> {
  const failures: string[] = [];
  for (const userId of changes.add) {
    try {
      await api.post(`/api/jobs/${jobId}/collaborators`, { user_id: userId });
    } catch (err) {
      failures.push(apiErrorMessage(err, "błąd zapisu"));
    }
  }
  for (const userId of changes.remove) {
    try {
      await api.delete(`/api/jobs/${jobId}/collaborators/${userId}`);
    } catch (err) {
      failures.push(apiErrorMessage(err, "błąd zapisu"));
    }
  }
  if (failures.length === 0) return null;
  const total = changes.add.length + changes.remove.length;
  return failures.length === total
    ? `nie zapisano kolejnych osób (${failures[0]})`
    : `zapisano ${total - failures.length} z ${total} zmian na liście kolejnych osób (${failures[0]})`;
}
