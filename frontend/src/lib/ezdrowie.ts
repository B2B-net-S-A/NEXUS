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

// ── Struktura umów wykonawczych (ticket 09.2026) ─────────────────────────────
// Dwupoziomowo: umowa ramowa = część (cz. I/II/IV/V/VI) → 0..N umów
// wykonawczych. Konsultant jest przypisany do KONKRETNEJ umowy wykonawczej;
// `project_part` jest od teraz wartością pochodną z jej umowy ramowej.

/** Cyfry rzymskie części — tak nazywa je klient w dokumentach. */
export const PART_ROMAN: Record<ProjectPart, string> = {
  cz1: "I",
  cz2: "II",
  cz4: "IV",
  cz5: "V",
  cz6: "VI",
};

/**
 * Filtr sekcji „Obecni konsultanci" po umowie wykonawczej.
 * "all" = pełna lista; "unassigned" = osoby bez przypisania (legacy, do
 * przeglądu); obiekt = jedna konkretna umowa wykonawcza.
 */
export type ConsultantAssignmentFilter =
  | "all"
  | "unassigned"
  | { executiveContractId: number };

/**
 * Konsultant bez umowy wykonawczej (NULL — wiersz sprzed wdrożenia albo
 * nieuzupełniony auto-draft) pokazuje się WYŁĄCZNIE pod „Wszystkie" i pod
 * „Nieprzypisani": filtr po konkretnej umowie nie może udawać kompletu, a
 * pustka pod „Nieprzypisani" ma znaczyć „wszyscy są przypisani", nie „nie
 * policzyliśmy".
 */
export function filterConsultantsByExecutiveContract<
  T extends { executive_contract?: { id: number } | null },
>(consultants: T[], filter: ConsultantAssignmentFilter): T[] {
  if (filter === "all") return consultants;
  if (filter === "unassigned") {
    return consultants.filter((c) => c.executive_contract == null);
  }
  return consultants.filter(
    (c) => c.executive_contract?.id === filter.executiveContractId,
  );
}

/** Porównanie dwóch filtrów — obiektowa wartość nie ma tożsamości referencyjnej. */
export function isSameAssignmentFilter(
  a: ConsultantAssignmentFilter,
  b: ConsultantAssignmentFilter,
): boolean {
  if (typeof a === "string" || typeof b === "string") return a === b;
  return a.executiveContractId === b.executiveContractId;
}
