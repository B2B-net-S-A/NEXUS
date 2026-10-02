/**
 * Współpracownicy rekrutacji (decyzja Artura 29.09.2026).
 *
 * Rekrutację prowadzi jedna osoba (`jobs.recruiter_id`, „Rekruter
 * prowadzący”), ale pracuje nad nią kilka — współpracownicy z
 * `job_collaborators`. W oknie edycji, na `/jobs/new` i w kolumnie „Prowadzi”
 * widać WYŁĄCZNIE dodanych ręcznie (`source: "manual"`); wiersze `auto_cc` to
 * cała kategoria kompetencji, nie osoby przy tej rekrutacji (i nie liczą się
 * w „Kto pracuje”). Dopisuje i zdejmuje każdy, kto redaguje rekrutację —
 * lustro `ensure_job_editor` w `POST/DELETE /api/jobs/{id}/collaborators`.
 */

import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";

/** Role, które serwer przyjmuje jako współpracownika (`_OWNERSHIP_ELIGIBLE_ROLES`). */
export const COLLABORATOR_ROLES = [
  "admin",
  "delivery_lead",
  "tac",
  "recruiter",
  "sourcer",
] as const;

export interface JobCollaboratorEntry {
  id: number;
  name?: string | null;
  /** Brak pola (starsze odpowiedzi) = dodany ręcznie. */
  source?: string | null;
  /** Nieaktywne konto nie liczy się do „+N” (tak jak w „Kto pracuje”). */
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
 * Różnica między ręcznymi współpracownikami przed i po edycji. Prowadzący nie
 * jest dopisywany jako współpracownik (serwer odpowiada wtedy 409).
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
    ? `nie zapisano zmian współpracowników (${failures[0]})`
    : `zapisano ${total - failures.length} z ${total} zmian współpracowników (${failures[0]})`;
}

/**
 * „+N” obok prowadzącego w kolumnie „Prowadzi” i treść podpowiedzi. Liczy
 * tylko aktywne konta — ta sama reguła co filtr „Kto pracuje”, inaczej wiersz
 * mówiłby „+1” i jednocześnie „Nikt nie pracuje”.
 */
export function collaboratorsSummary(
  collaborators: readonly JobCollaboratorEntry[] | null | undefined,
): { count: number; names: string[]; tooltip: string } {
  const manual = manualCollaborators(collaborators).filter(
    (c) => c.is_active !== false,
  );
  const names = manual.map((c) => c.name?.trim() || `#${c.id}`);
  return {
    count: manual.length,
    names,
    tooltip: names.length > 0 ? `Współpracownicy: ${names.join(", ")}` : "",
  };
}
