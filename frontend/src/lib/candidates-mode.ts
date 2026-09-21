/**
 * Tryby jednego ekranu „Kandydaci" (`/candidates?mode=…`). Czysty moduł —
 * czytają go ekran, przekierowania starych adresów i rejestr nawigacji.
 */
export type CandidatesMode = "list" | "search" | "request";

export const CANDIDATES_MODE_PARAM = "mode";

const MODES: readonly CandidatesMode[] = ["list", "search", "request"];

/** Nieznana albo pusta wartość = lista (dotychczasowe `/candidates`). */
export function parseCandidatesMode(value: string | null | undefined): CandidatesMode {
  return MODES.includes(value as CandidatesMode) ? (value as CandidatesMode) : "list";
}

/**
 * Adres trybu. `extra` przenosi parametry starego adresu (np. `s` i `job`
 * z `/candidates/search`), żeby zapisany link otwierał TO SAMO wyszukiwanie.
 */
export function candidatesModeHref(
  mode: CandidatesMode,
  extra?: URLSearchParams | null,
): string {
  const params = new URLSearchParams(extra ?? undefined);
  params.delete(CANDIDATES_MODE_PARAM);
  const qs = params.toString();
  if (mode === "list") return qs ? `/candidates?${qs}` : "/candidates";
  return `/candidates?${CANDIDATES_MODE_PARAM}=${mode}${qs ? `&${qs}` : ""}`;
}
