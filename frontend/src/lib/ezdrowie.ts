// Centrum e-Zdrowia — jedyny klient z polem „część umowy" (ticket #3, Faza C).
//
// Bramka po client_id (decyzja Fazy B) — NIE po nazwie: Traffit nadpisuje
// Client.name, a duplikat 37721 został scalony w kanoniczny rekord 115.
// Lustrzany moduł backendu: backend/app/services/ezdrowie.py (słownik musi
// zostać w synchronizacji; cz.3 celowo nie istnieje — potwierdzone w tickecie).

export const EZDROWIE_CLIENT_ID = 115;

export type ProjectPart = "cz1" | "cz2" | "cz4" | "cz5" | "cz6";

export const PROJECT_PARTS: { value: ProjectPart; label: string }[] = [
  { value: "cz1", label: "E-zdrowie cz.1" },
  { value: "cz2", label: "E-zdrowie cz.2" },
  { value: "cz4", label: "E-zdrowie cz.4" },
  { value: "cz5", label: "E-zdrowie cz.5" },
  { value: "cz6", label: "E-zdrowie cz.6" },
];

export function isEzdrowieClient(clientId: number | null | undefined): boolean {
  return clientId === EZDROWIE_CLIENT_ID;
}

export function projectPartLabel(part: string | null | undefined): string | null {
  if (!part) return null;
  return PROJECT_PARTS.find((p) => p.value === part)?.label ?? part;
}

/**
 * Filtr sekcji „Obecni konsultanci" po części umowy. "all" = pełna lista.
 * Konsultant bez części (NULL — np. nieuzupełniony auto-draft) pokazuje się
 * TYLKO pod „Wszystkie części" — częściowy filtr nie może udawać kompletu.
 */
export function filterConsultantsByPart<T extends { project_part?: string | null }>(
  consultants: T[],
  part: ProjectPart | "all",
): T[] {
  if (part === "all") return consultants;
  return consultants.filter((c) => c.project_part === part);
}
